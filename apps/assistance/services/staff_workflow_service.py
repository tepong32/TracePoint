import logging

from apps.assistance.models import CitizenRequest, RequestDocument, RequestTimeline
from apps.assistance.services.evaluator import (
    evaluate_request_completeness,
    get_required_documents,
)
from apps.assistance.services.lifecycle import (
    REQUEST_STATUS_CHOICES,
    get_allowed_next_statuses,
    is_locked_status,
)
from apps.assistance.services.lifecycle_service import (
    LifecycleTransitionError,
    apply_auto_status_transition,
    transition_request_status,
)
from apps.assistance.services.notifications import (
    dispatch_notification,
    prepare_document_review_notification,
)

logger = logging.getLogger(__name__)


ASSISTANCE_STAFF_GROUPS = {
    "mswd",
    "assistance_reviewer",
    "assistance_approver",
    "assistance_fulfillment",
}

QUEUE_STATUS_MAP = {
    "intake": {"submitted", "awaiting_documents", "needs_attention"},
    "review": {"under_review", "needs_attention"},
    "approval": {"under_review"},
    "fulfillment": {"approved", "claimable", "claimed"},
    "closed": {"closed"},
    "all": set(),
}

ROLE_DEFAULT_QUEUE = {
    "assistance_reviewer": "review",
    "assistance_approver": "approval",
    "assistance_fulfillment": "fulfillment",
    "mswd": "all",
}

ROLE_TRANSITIONS = {
    "assistance_reviewer": {
        ("submitted", "awaiting_documents"),
        ("submitted", "under_review"),
        ("awaiting_documents", "under_review"),
        ("needs_attention", "under_review"),
        ("under_review", "needs_attention"),
    },
    "assistance_approver": {
        ("under_review", "approved"),
        ("under_review", "needs_attention"),
    },
    "assistance_fulfillment": {
        ("approved", "claimable"),
        ("claimable", "claimed"),
        ("claimed", "closed"),
    },
}

DOCUMENT_REVIEW_ROLES = {"assistance_reviewer", "mswd"}

TIMELINE_EVENT_META = {
    "submitted": ("Submitted", "info"),
    "status_change": ("Status Change", "status"),
    "staff_update": ("Staff Update", "staff"),
    "document_uploaded": ("Document Uploaded", "document"),
    "document_replaced": ("Document Replaced", "document"),
    "document_removed": ("Document Removed", "document"),
    "citizen_update_received": ("Citizen Update", "citizen"),
    "notification": ("Notification", "notification"),
    "workflow_error": ("Workflow Error", "danger"),
}


class StaffWorkflowError(Exception):
    """Raised when a staff workflow action violates access or lifecycle policy."""

    pass


def is_staff_user(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True

    group_names = set(user.groups.values_list("name", flat=True))
    if group_names & ASSISTANCE_STAFF_GROUPS:
        return True

    employee_profile = getattr(user, "employeeprofile", None)
    assigned_department = getattr(employee_profile, "assigned_department", None)
    return getattr(assigned_department, "slug", None) == "mswd"


def staff_role_names(user) -> set[str]:
    if getattr(user, "is_superuser", False):
        return {"mswd"}

    names = set(user.groups.values_list("name", flat=True)) & ASSISTANCE_STAFF_GROUPS
    employee_profile = getattr(user, "employeeprofile", None)
    assigned_department = getattr(employee_profile, "assigned_department", None)
    if getattr(assigned_department, "slug", None) == "mswd":
        names.add("mswd")
    return names


def has_all_queue_access(user) -> bool:
    return getattr(user, "is_superuser", False) or "mswd" in staff_role_names(user)


def default_queue_for_user(user) -> str:
    roles = staff_role_names(user)
    if has_all_queue_access(user):
        return "all"
    for role, queue in ROLE_DEFAULT_QUEUE.items():
        if role in roles:
            return queue
    return "review"


def allowed_transition_statuses(user, current_status: str) -> set[str]:
    next_statuses = get_allowed_next_statuses(current_status)
    if has_all_queue_access(user):
        return next_statuses

    roles = staff_role_names(user)
    allowed_pairs = set()
    for role in roles:
        allowed_pairs.update(ROLE_TRANSITIONS.get(role, set()))
    return {
        new_status
        for new_status in next_statuses
        if (current_status, new_status) in allowed_pairs
    }


def _approval_block_reason(request_obj: CitizenRequest) -> str:
    completeness = evaluate_request_completeness(request_obj)
    if completeness["is_complete"]:
        return ""
    return "Approval requires all required documents to be approved."


def transition_options_for_request(user, request_obj: CitizenRequest) -> list[dict]:
    allowed_statuses = allowed_transition_statuses(user, request_obj.status)
    status_labels = dict(REQUEST_STATUS_CHOICES)
    options = [
        {
            "value": request_obj.status,
            "label": status_labels.get(request_obj.status, request_obj.status),
            "is_current": True,
            "disabled": False,
            "reason": "",
        }
    ]

    for status in REQUEST_STATUS_CHOICES:
        value = status[0]
        if value not in allowed_statuses:
            continue
        reason = ""
        if value == "approved":
            reason = _approval_block_reason(request_obj)
        options.append(
            {
                "value": value,
                "label": status_labels.get(value, value),
                "is_current": False,
                "disabled": bool(reason),
                "reason": reason,
            }
        )
    return options


def apply_staff_queue_metadata(requests: list[CitizenRequest], user) -> list[CitizenRequest]:
    for request_obj in requests:
        completeness = evaluate_request_completeness(request_obj)
        request_obj.has_missing_documents = bool(completeness["missing_documents"])
        request_obj.has_doc_issues = bool(completeness["has_issues"])
        request_obj.transition_options = transition_options_for_request(user, request_obj)
    return requests


def can_review_documents(user) -> bool:
    return has_all_queue_access(user) or bool(staff_role_names(user) & DOCUMENT_REVIEW_ROLES)


def is_request_locked(request_obj: CitizenRequest) -> bool:
    return request_obj.is_locked or is_locked_status(request_obj.status)


def _actor(user):
    return user if getattr(user, "is_authenticated", False) else None


def create_staff_timeline_event(*, request_obj: CitizenRequest, message: str, user) -> None:
    RequestTimeline.objects.create(
        request=request_obj,
        event_type="staff_update",
        message=message,
        created_by=_actor(user),
    )


def _document_review_summary(*, request_obj: CitizenRequest, documents) -> dict:
    completeness = evaluate_request_completeness(request_obj)
    required_types = get_required_documents(request_obj)
    labels = dict(RequestDocument.DOCUMENT_TYPE_CHOICES)
    active_by_type = {doc.document_type: doc for doc in documents}
    required_documents = []

    for doc_type in required_types:
        document = active_by_type.get(doc_type)
        required_documents.append(
            {
                "type": doc_type,
                "label": labels.get(doc_type, doc_type),
                "status": document.status if document else "missing",
                "status_label": document.get_status_display() if document else "Missing",
                "remarks": document.remarks if document else "",
                "is_missing": document is None,
                "needs_attention": bool(
                    document and document.status not in {"approved", "pending"}
                ),
            }
        )

    return {
        "total": len(documents),
        "approved": sum(1 for doc in documents if doc.status == "approved"),
        "pending": sum(1 for doc in documents if doc.status == "pending"),
        "issues": sum(1 for doc in documents if doc.status not in {"approved", "pending"}),
        "required": required_documents,
        "missing": completeness["missing_documents"],
        "problematic": completeness["problematic_documents"],
        "is_complete": completeness["is_complete"],
    }


def timeline_display_items(timeline_items) -> list[dict]:
    display_items = []
    for item in timeline_items:
        label, tone = TIMELINE_EVENT_META.get(
            item.event_type,
            (item.event_type.replace("_", " ").title(), "info"),
        )
        display_items.append(
            {
                "item": item,
                "label": label,
                "tone": tone,
            }
        )
    return display_items


def build_staff_request_detail_context(*, request_obj: CitizenRequest, user) -> dict:
    documents = list(
        request_obj.documents.filter(is_removed=False).order_by(
            "document_type",
            "-uploaded_at",
        )
    )
    timeline_items = list(
        request_obj.timeline.select_related("created_by").order_by("-created_at")
    )
    document_summary = _document_review_summary(
        request_obj=request_obj,
        documents=documents,
    )

    return {
        "documents": documents,
        "timeline_items": timeline_display_items(timeline_items),
        "allowed_next_statuses": allowed_transition_statuses(user, request_obj.status),
        "transition_options": transition_options_for_request(user, request_obj),
        "is_locked": is_request_locked(request_obj),
        "can_review_documents": can_review_documents(user),
        "has_needs_attention": bool(
            document_summary["missing"] or document_summary["problematic"]
        ),
        "document_review_summary": document_summary,
    }


def update_request_by_staff(
    *,
    request_obj: CitizenRequest,
    user,
    new_status: str = "",
    remarks: str | None = None,
) -> bool:
    old_status = request_obj.status
    old_remarks = request_obj.remarks
    incoming_remarks = old_remarks if remarks is None else remarks
    status_changed = bool(new_status and new_status != old_status)
    remarks_changed = incoming_remarks != old_remarks

    if not status_changed and not remarks_changed:
        return False

    if status_changed and new_status not in allowed_transition_statuses(user, old_status):
        raise StaffWorkflowError("Your role cannot perform this status transition.")

    if is_request_locked(request_obj) and remarks_changed:
        raise StaffWorkflowError("Request is locked and remarks cannot be edited.")

    if status_changed and new_status == "approved":
        completeness = evaluate_request_completeness(request_obj)
        if not completeness["is_complete"]:
            raise StaffWorkflowError(
                "Request cannot be approved until all required documents are approved."
            )

    if status_changed:
        try:
            transition_request_status(
                request_obj,
                new_status=new_status,
                actor=user,
            )
        except LifecycleTransitionError as exc:
            raise StaffWorkflowError(str(exc)) from exc
        request_obj.refresh_from_db(fields=["status", "is_locked", "remarks", "updated_at"])

    if remarks_changed:
        request_obj.remarks = incoming_remarks
        request_obj.save(update_fields=["remarks", "updated_at"])
        create_staff_timeline_event(
            request_obj=request_obj,
            message=(
                "Staff remarks updated; "
                f"old_remarks={old_remarks or '(blank)'}; "
                f"new_remarks={incoming_remarks or '(blank)'}"
            ),
            user=user,
        )

    return True


def review_document_by_staff(
    *,
    document: RequestDocument,
    user,
    new_status: str,
    remarks: str = "",
) -> bool:
    if is_request_locked(document.request):
        raise StaffWorkflowError("Request is locked and document cannot be updated.")
    if not can_review_documents(user):
        raise StaffWorkflowError("Your role cannot review documents.")

    old_status = document.status
    old_remarks = document.remarks
    if new_status == old_status and remarks == old_remarks:
        return False

    document.status = new_status
    document.remarks = remarks
    document.save(update_fields=["status", "remarks", "updated_at"])

    create_staff_timeline_event(
        request_obj=document.request,
        message=(
            f"Document {document.get_document_type_display()} reviewed; "
            f"old_status={old_status}; new_status={new_status}; "
            f"old_remarks={old_remarks or '(blank)'}; "
            f"new_remarks={remarks or '(blank)'}"
        ),
        user=user,
    )
    dispatch_notification(
        prepare_document_review_notification(document),
        citizen_request=document.request,
    )

    try:
        apply_auto_status_transition(document.request)
    except Exception:
        logger.exception(
            "Auto status transition failed after document review for request %s.",
            document.request_id,
        )
        RequestTimeline.objects.create(
            request=document.request,
            event_type="workflow_error",
            message="Auto status transition failed after document review.",
            created_by=_actor(user),
        )

    return True
