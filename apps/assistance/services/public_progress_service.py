from dataclasses import dataclass

from apps.assistance.models import CitizenRequest, RequestDocument
from apps.assistance.services.evaluator import (
    evaluate_request_completeness,
    get_required_documents,
)
from apps.assistance.services.lifecycle import (
    REQUEST_LIFECYCLE,
    RequestStatus,
    get_progress_step,
    get_public_status_label,
    is_public_editable,
    requires_citizen_action,
)


@dataclass(frozen=True)
class ProgressStep:
    key: str
    label: str
    state: str


PUBLIC_PROGRESS_STEPS = (
    (RequestStatus.SUBMITTED, "Request submitted"),
    (RequestStatus.AWAITING_DOCUMENTS, "Supporting documents"),
    (RequestStatus.UNDER_REVIEW, "Staff review"),
    (RequestStatus.NEEDS_ATTENTION, "Updates needed"),
    (RequestStatus.APPROVED, "Approved"),
    (RequestStatus.CLAIMABLE, "Ready to claim"),
    (RequestStatus.CLAIMED, "Claimed"),
    (RequestStatus.CLOSED, "Closed"),
)


def _step_state(*, current_status: str, step_status: str) -> str:
    current_order = REQUEST_LIFECYCLE.get(current_status, 1)
    step_order = REQUEST_LIFECYCLE.get(step_status, 1)
    if current_status == step_status:
        return "current"
    if step_order < current_order:
        return "complete"
    return "upcoming"


def build_public_progress_context(request_obj: CitizenRequest) -> dict:
    completeness = evaluate_request_completeness(request_obj)
    required_document_types = get_required_documents(request_obj)
    active_documents = {
        doc.document_type: doc
        for doc in request_obj.documents.filter(is_removed=False).order_by("-uploaded_at")
    }
    document_type_labels = dict(RequestDocument.DOCUMENT_TYPE_CHOICES)

    required_documents = []
    for document_type in required_document_types:
        document = active_documents.get(document_type)
        required_documents.append(
            {
                "type": document_type,
                "label": document_type_labels.get(document_type, document_type),
                "status": document.status if document else "missing",
                "status_label": (
                    document.get_status_display() if document else "Missing"
                ),
                "remarks": document.remarks if document else "",
                "is_missing": document is None,
                "needs_attention": bool(
                    document
                    and document.status
                    not in {
                        "approved",
                        "pending",
                    }
                ),
            }
        )

    can_update_documents = (
        is_public_editable(request_obj.status)
        and not request_obj.is_locked
    )

    action_callout = None
    if requires_citizen_action(request_obj.status):
        action_callout = {
            "tone": "warning",
            "title": "Update your request",
            "message": "Some documents need attention. Upload a replacement or add the requested correction so staff can continue the review.",
        }
    elif can_update_documents and completeness["missing_documents"]:
        action_callout = {
            "tone": "info",
            "title": "Documents needed",
            "message": "Upload the missing supporting documents so staff can begin the review.",
        }
    elif can_update_documents:
        action_callout = {
            "tone": "info",
            "title": "Documents can still be updated",
            "message": "Upload missing supporting documents or replace a file before staff completes the review.",
        }
    elif not request_obj.is_locked:
        action_callout = {
            "tone": "info",
            "title": "Documents under review",
            "message": "Staff is currently reviewing your request. Document editing is unavailable unless staff asks for updates.",
        }
    elif request_obj.is_locked:
        action_callout = {
            "tone": "locked",
            "title": "Request locked",
            "message": "This request has moved past document editing. You can still review the current status and documents on file.",
        }

    return {
        "progress_step": get_progress_step(request_obj.status),
        "progress_steps": [
            ProgressStep(
                key=status,
                label=label,
                state=_step_state(
                    current_status=request_obj.status,
                    step_status=status,
                ),
            )
            for status, label in PUBLIC_PROGRESS_STEPS
        ],
        "public_status_label": get_public_status_label(request_obj.status),
        "can_update_documents": can_update_documents,
        "action_callout": action_callout,
        "required_documents": required_documents,
        "missing_documents": completeness["missing_documents"],
        "problematic_documents": completeness["problematic_documents"],
        "is_document_complete": completeness["is_complete"],
    }
