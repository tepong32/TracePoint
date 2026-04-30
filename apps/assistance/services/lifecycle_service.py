from apps.assistance.models.models import CitizenRequest, RequestTimeline
from apps.assistance.services.evaluator import evaluate_request_completeness
from apps.assistance.services.lifecycle import (
    can_transition_status,
    is_locked_status,
)
from apps.assistance.services.notifications import (
    dispatch_notification,
    prepare_status_notification,
)


class LifecycleTransitionError(Exception):
    """Raised when a request lifecycle transition violates v0.5 policy."""

    pass


def _create_status_change_log(
    *,
    request_obj: CitizenRequest,
    old_status: str,
    new_status: str,
    actor=None,
) -> None:
    """Record status transition details for auditability."""
    try:
        from apps.assistance.models.logs import RequestLog  # type: ignore
    except (ImportError, AttributeError):
        RequestLog = None  # type: ignore

    if RequestLog is not None:
        try:
            RequestLog.objects.create(
                request=request_obj,
                old_status=old_status,
                new_status=new_status,
                action_type="status_change",
            )
            return
        except Exception:
            pass

    RequestTimeline.objects.create(
        request=request_obj,
        event_type="status_change",
        message=(
            "action_type=status_change; "
            f"old_status={old_status}; "
            f"new_status={new_status}"
        ),
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )


def transition_request_status(
    request_obj: CitizenRequest,
    *,
    new_status: str,
    actor=None,
    message: str | None = None,
) -> None:
    """Transition a request status through the central lifecycle policy."""
    old_status = request_obj.status
    if old_status == new_status:
        return

    if not can_transition_status(old_status, new_status):
        raise LifecycleTransitionError(
            f"Invalid status transition: {old_status} to {new_status}."
        )

    request_obj.status = new_status
    request_obj.is_locked = is_locked_status(new_status)
    request_obj.save(update_fields=["status", "is_locked", "updated_at"])
    if message:
        RequestTimeline.objects.create(
            request=request_obj,
            event_type="status_change",
            message=message,
            created_by=actor if getattr(actor, "is_authenticated", False) else None,
        )
    else:
        _create_status_change_log(
            request_obj=request_obj,
            old_status=old_status,
            new_status=new_status,
            actor=actor,
        )

    dispatch_notification(
        prepare_status_notification(request_obj, status=new_status),
        citizen_request=request_obj,
    )


def apply_auto_status_transition(
    request_obj: CitizenRequest,
    *,
    previous_status_for_audit: str | None = None,
) -> None:
    """Auto-transition request status based on current document completeness."""
    allowed_current_statuses = {
        "submitted",
        "awaiting_documents",
        "under_review",
        "needs_attention",
    }
    if request_obj.status not in allowed_current_statuses:
        return

    result = evaluate_request_completeness(request_obj)
    old_status = previous_status_for_audit or request_obj.status

    if result["missing_documents"]:
        new_status = "awaiting_documents"
    elif result["has_issues"]:
        new_status = "needs_attention"
    else:
        new_status = "under_review"

    if new_status == request_obj.status and new_status == old_status:
        return

    request_obj.status = new_status
    request_obj.is_locked = is_locked_status(new_status)
    request_obj.save(update_fields=["status", "is_locked", "updated_at"])
    _create_status_change_log(
        request_obj=request_obj,
        old_status=old_status,
        new_status=new_status,
    )
    dispatch_notification(
        prepare_status_notification(request_obj, status=new_status),
        citizen_request=request_obj,
    )
