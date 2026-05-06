from dataclasses import dataclass
import logging
from typing import Protocol

from django.conf import settings
from django.core.mail import send_mail

from apps.assistance.models import RequestDocument, RequestTimeline
from apps.assistance.models import CitizenRequest
from apps.assistance.services.lifecycle import (
    RequestStatus,
    get_public_status_label,
    requires_citizen_action,
    should_trigger_notification,
)

logger = logging.getLogger(__name__)

DEFAULT_NOTIFICATION_CHANNELS = ("email", "sms")


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
    subject: str
    message: str


@dataclass(frozen=True)
class NotificationResult:
    channel: str
    status: str
    message: str


class NotificationAdapter(Protocol):
    channel: str

    def send(self, trigger: NotificationTrigger) -> NotificationResult:
        """Send one notification trigger through a concrete channel."""


DOCUMENT_REVIEW_NOTIFICATION_STATUSES = {
    "clearer_copy",
    "wrong_file",
    "incomplete",
    "missing_stamp",
    "expired",
}


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

    public_status_label = get_public_status_label(target_status)
    subject = f"TracePoint request update: {citizen_request.tracking_code}"
    message = (
        f"Your assistance request {citizen_request.tracking_code} is now "
        f"{public_status_label}."
    )
    if requires_citizen_action(target_status):
        message += " Please open your secure edit link and update the requested documents."

    return NotificationTrigger(
        request_id=citizen_request.id,
        tracking_code=citizen_request.tracking_code,
        status=target_status,
        public_status_label=public_status_label,
        recipient_email=citizen_request.email,
        recipient_phone=citizen_request.phone,
        requires_citizen_action=requires_citizen_action(target_status),
        subject=subject,
        message=message,
    )


def prepare_document_review_notification(
    document: RequestDocument,
) -> NotificationTrigger | None:
    """
    Return notification data for document review outcomes requiring citizen action.
    Approved/pending document states stay quiet.
    """
    if document.status not in DOCUMENT_REVIEW_NOTIFICATION_STATUSES:
        return None

    request_obj = document.request
    doc_label = document.get_document_type_display()
    status_label = dict(RequestDocument.STATUS_CHOICES).get(document.status, document.status)
    remarks = document.remarks or "No remarks provided."
    message = (
        f"Your {doc_label} for request {request_obj.tracking_code} was reviewed: "
        f"{status_label}. Remarks: {remarks}"
    )
    return NotificationTrigger(
        request_id=request_obj.id,
        tracking_code=request_obj.tracking_code,
        status=document.status,
        public_status_label=status_label,
        recipient_email=request_obj.email,
        recipient_phone=request_obj.phone,
        requires_citizen_action=True,
        subject=f"TracePoint document update: {request_obj.tracking_code}",
        message=message,
    )


class EmailNotificationAdapter:
    channel = "email"

    def send(self, trigger: NotificationTrigger) -> NotificationResult:
        if not trigger.recipient_email:
            return NotificationResult(self.channel, "skipped", "Missing email recipient.")

        sent = send_mail(
            subject=trigger.subject,
            message=trigger.message,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=[trigger.recipient_email],
            fail_silently=True,
        )
        if sent:
            return NotificationResult(self.channel, "success", "Email notification sent.")
        return NotificationResult(self.channel, "error", "Email backend did not send.")


class LoggingSmsNotificationAdapter:
    channel = "sms"

    def send(self, trigger: NotificationTrigger) -> NotificationResult:
        if not trigger.recipient_phone:
            return NotificationResult(self.channel, "skipped", "Missing SMS recipient.")

        logger.info(
            "SMS notification queued for %s: %s",
            trigger.recipient_phone,
            trigger.message,
        )
        return NotificationResult(
            self.channel,
            "success",
            "SMS notification logged by placeholder adapter.",
        )


NOTIFICATION_ADAPTERS = {
    EmailNotificationAdapter.channel: EmailNotificationAdapter,
    LoggingSmsNotificationAdapter.channel: LoggingSmsNotificationAdapter,
}


def get_enabled_notification_channels() -> tuple[str, ...]:
    """
    Return configured notification channels while preserving email + SMS as
    the baseline default required by the product contract.
    """
    channels = getattr(
        settings,
        "TRACEPOINT_NOTIFICATION_CHANNELS",
        DEFAULT_NOTIFICATION_CHANNELS,
    )
    if isinstance(channels, str):
        channels = (channels,)

    normalized = []
    for channel in channels:
        value = str(channel).strip().lower()
        if value and value not in normalized:
            normalized.append(value)
    return tuple(normalized)


def get_notification_adapters() -> tuple[NotificationAdapter, ...]:
    adapters = []
    for channel in get_enabled_notification_channels():
        adapter_cls = NOTIFICATION_ADAPTERS.get(channel)
        if adapter_cls is None:
            logger.warning("Unknown notification channel configured: %s", channel)
            continue
        adapters.append(adapter_cls())
    return tuple(adapters)


def _record_notification_result(
    *,
    citizen_request: CitizenRequest,
    result: NotificationResult,
) -> None:
    RequestTimeline.objects.create(
        request=citizen_request,
        event_type="notification",
        message=(
            f"channel={result.channel}; "
            f"status={result.status}; "
            f"message={result.message}"
        ),
    )


def dispatch_notification(
    trigger: NotificationTrigger | None,
    *,
    citizen_request: CitizenRequest,
) -> list[NotificationResult]:
    """
    Best-effort notification fanout. Failures are logged to timeline and never
    block lifecycle/document review mutations.
    """
    if trigger is None:
        return []

    results: list[NotificationResult] = []
    for adapter in get_notification_adapters():
        try:
            result = adapter.send(trigger)
        except Exception as exc:
            result = NotificationResult(
                adapter.channel,
                "error",
                f"Notification adapter failed: {exc}",
            )
            logger.exception("Notification adapter failed.")

        results.append(result)
        _record_notification_result(
            citizen_request=citizen_request,
            result=result,
        )

    return results
