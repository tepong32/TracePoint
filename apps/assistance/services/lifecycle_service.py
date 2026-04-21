from apps.assistance.models.models import CitizenRequest, RequestTimeline
from apps.assistance.services.evaluator import evaluate_request_completeness


def _create_status_change_log(
    *,
    request_obj: CitizenRequest,
    old_status: str,
    new_status: str,
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
    )


def apply_auto_status_transition(request_obj: CitizenRequest) -> None:
    """Auto-transition request status based on current document completeness."""
    allowed_current_statuses = {"pending", "under_review", "needs_attention"}
    if request_obj.status not in allowed_current_statuses:
        return

    result = evaluate_request_completeness(request_obj)
    old_status = request_obj.status

    if result["missing_documents"]:
        new_status = "pending"
    elif result["has_issues"]:
        new_status = "needs_attention"
    else:
        new_status = "under_review"

    if new_status == old_status:
        return

    request_obj.status = new_status
    request_obj.save(update_fields=["status", "updated_at"])
    _create_status_change_log(
        request_obj=request_obj,
        old_status=old_status,
        new_status=new_status,
    )
