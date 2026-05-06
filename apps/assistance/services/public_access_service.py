import logging

from django.core.cache import cache

from apps.assistance.models import CitizenRequest

logger = logging.getLogger(__name__)


class InvalidPublicEditToken(Exception):
    """Raised when a public mutation cannot authenticate with edit token."""

    pass


def _client_ip(request) -> str:
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def record_invalid_edit_attempt(*, request, edit_token: str, action: str) -> int:
    """
    Lightweight abuse signal for public edit-token failures.

    Counts failures per action/IP/token prefix for ten minutes and logs every
    invalid mutation attempt. The full token is never written to logs.
    """
    ip = _client_ip(request)
    token_prefix = (edit_token or "")[:8] or "missing"
    cache_key = f"tracepoint:invalid_edit:{action}:{ip}:{token_prefix}"

    attempts = cache.get(cache_key, 0) + 1
    cache.set(cache_key, attempts, timeout=600)

    logger.warning(
        "Invalid public edit token attempt action=%s ip=%s token_prefix=%s attempts=%s",
        action,
        ip,
        token_prefix,
        attempts,
    )
    return attempts


def get_request_for_public_mutation(
    *,
    request,
    edit_token: str,
    action: str,
) -> CitizenRequest:
    """
    Treat the secure edit token as the public authentication credential.
    """
    if not edit_token:
        record_invalid_edit_attempt(
            request=request,
            edit_token=edit_token,
            action=action,
        )
        raise InvalidPublicEditToken("Invalid edit code.")

    request_obj = (
        CitizenRequest.objects.select_related("program", "citizen")
        .filter(
            secure_edit_token=edit_token,
            is_active=True,
        )
        .first()
    )
    if request_obj is None:
        record_invalid_edit_attempt(
            request=request,
            edit_token=edit_token,
            action=action,
        )
        raise InvalidPublicEditToken("Invalid edit code.")

    return request_obj
