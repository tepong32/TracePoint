"""Centralized lifecycle policy helpers used across views and services."""

from __future__ import annotations

from apps.assistance.models import CitizenRequest
from apps.assistance.services.lifecycle import (
    can_transition_status,
    is_locked_status,
    is_public_editable,
)


class LifecycleValidationError(Exception):
    """Raised when lifecycle validation fails."""


_VALID_STATUSES = frozenset(value for value, _ in CitizenRequest.STATUS_CHOICES)


def is_valid_status(status: str) -> bool:
    return status in _VALID_STATUSES


def validate_transition_or_raise(*, current_status: str, new_status: str) -> None:
    if not is_valid_status(new_status):
        raise LifecycleValidationError("Invalid status value.")
    if not can_transition_status(current_status, new_status):
        raise LifecycleValidationError(
            f"Invalid status transition: {current_status} to {new_status}."
        )


def is_request_locked(request_obj: CitizenRequest) -> bool:
    return bool(request_obj.is_locked or is_locked_status(request_obj.status))


def can_citizen_edit_request(request_obj: CitizenRequest) -> bool:
    return bool(not is_request_locked(request_obj) and is_public_editable(request_obj.status))


def can_citizen_upload_documents(request_obj: CitizenRequest) -> bool:
    """Mirror current public-view gate: only locked states are blocked upfront."""
    return not is_request_locked(request_obj)
