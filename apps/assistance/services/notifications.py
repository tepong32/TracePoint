from dataclasses import dataclass

from apps.assistance.models import CitizenRequest
from apps.assistance.services.lifecycle import (
    get_public_status_label,
    requires_citizen_action,
    should_trigger_notification,
)


@dataclass(frozen=True)
class NotificationTrigger:
    """
    Backend-neutral notification payload for future Email/SMS adapters.
    """

    request_id: int
    tracking_code: str
    status: str
    public_status_label: str
    recipient_email: str
    recipient_phone: str
    requires_citizen_action: bool


def prepare_status_notification(
    citizen_request: CitizenRequest,
    *,
    status: str | None = None,
) -> NotificationTrigger | None:
    """
    Return notification trigger data for statuses that should notify citizens.
    No delivery or vendor work belongs here yet.
    """
    target_status = status or citizen_request.status
    if not should_trigger_notification(target_status):
        return None

    return NotificationTrigger(
        request_id=citizen_request.id,
        tracking_code=citizen_request.tracking_code,
        status=target_status,
        public_status_label=get_public_status_label(target_status),
        recipient_email=citizen_request.email,
        recipient_phone=citizen_request.phone,
        requires_citizen_action=requires_citizen_action(target_status),
    )
