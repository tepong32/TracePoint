from dataclasses import dataclass
import hashlib
import logging

from django.conf import settings
from django.core.cache import cache
from django.urls import reverse

from apps.assistance.models import CitizenRequest
from apps.assistance.services.notifications import (
    AccessRecoveryTrigger,
    NotificationResult,
    dispatch_group_notification,
)

logger = logging.getLogger(__name__)

GENERIC_RECOVERY_MESSAGE = (
    "If matching active requests exist, delivery will be attempted."
)


@dataclass(frozen=True)
class RecoveryOutcome:
    matched_count: int
    throttled: bool
    notification_results: tuple[NotificationResult, ...]


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _client_ip(request) -> str:
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def _increment_attempt(key: str, *, timeout: int) -> int:
    if cache.add(key, 1, timeout=timeout):
        return 1
    try:
        return cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=timeout)
        return 1


def _build_digest_message(request, requests: list[CitizenRequest]) -> str:
    lines = [
        "Here are your active TracePoint assistance requests:",
        "",
    ]
    for request_obj in requests:
        track_url = request.build_absolute_uri(
            reverse(
                "assistance:track_request",
                kwargs={"tracking_code": request_obj.tracking_code},
            )
        )
        edit_url = request.build_absolute_uri(
            reverse(
                "assistance:secure_edit",
                kwargs={"secure_edit_token": request_obj.secure_edit_token},
            )
        )
        lines.extend(
            [
                f"Program: {request_obj.program.name}",
                f"Tracking code: {request_obj.tracking_code}",
                f"Submitted: {request_obj.submitted_at:%Y-%m-%d}",
                f"Track request: {track_url}",
                f"Continue request: {edit_url}",
                "",
            ]
        )
    lines.append(
        "If you did not request these links, you can ignore this message."
    )
    return "\n".join(lines)


class PublicAccessRecoveryService:
    @classmethod
    def request_recovery(cls, *, request, email: str) -> RecoveryOutcome:
        normalized_email = email.strip().lower()
        email_hash = _stable_hash(normalized_email)
        ip = _client_ip(request)
        ip_hash = _stable_hash(ip)

        window_seconds = getattr(
            settings,
            "TRACEPOINT_RECOVERY_WINDOW_SECONDS",
            900,
        )
        email_limit = getattr(settings, "TRACEPOINT_RECOVERY_EMAIL_LIMIT", 3)
        ip_limit = getattr(settings, "TRACEPOINT_RECOVERY_IP_LIMIT", 10)

        email_attempts = _increment_attempt(
            f"tracepoint:recovery:email:{email_hash}",
            timeout=window_seconds,
        )
        ip_attempts = _increment_attempt(
            f"tracepoint:recovery:ip:{ip_hash}",
            timeout=window_seconds,
        )
        if email_attempts > email_limit or ip_attempts > ip_limit:
            logger.warning(
                "Public access recovery throttled ip=%s email_hash=%s",
                ip,
                email_hash[:12],
            )
            return RecoveryOutcome(0, True, ())

        matching_requests = list(
            CitizenRequest.objects.select_related("program")
            .filter(email__iexact=normalized_email, is_active=True)
            .order_by("-submitted_at")
        )
        if not matching_requests:
            logger.info(
                "Public access recovery unmatched ip=%s email_hash=%s",
                ip,
                email_hash[:12],
            )
            return RecoveryOutcome(0, False, ())

        trigger = AccessRecoveryTrigger(
            recipient_email=normalized_email,
            recipient_phone="",
            subject="Your TracePoint request access links",
            message=_build_digest_message(request, matching_requests),
        )
        results = dispatch_group_notification(
            trigger,
            citizen_requests=matching_requests,
            channels=("email",),
        )
        return RecoveryOutcome(
            len(matching_requests),
            False,
            tuple(results),
        )
