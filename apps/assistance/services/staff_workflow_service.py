import logging

from apps.assistance.models import CitizenRequest, RequestDocument, RequestTimeline
from apps.assistance.services.evaluator import evaluate_request_completeness
from apps.assistance.services.lifecycle import (
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
