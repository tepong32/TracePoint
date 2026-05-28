from __future__ import annotations

from django.http import HttpRequest

from apps.assistance.models import CitizenRequest, RequestDocument
from apps.assistance.services.lifecycle_rules import can_citizen_upload_documents
from apps.assistance.services.staff_workflow_service import (
    StaffWorkflowError,
    can_review_documents,
    can_change_request_status,
    is_request_locked,
)


class MutationGuardError(Exception):
    def __init__(self, message: str, *, forbidden: bool = False):
        super().__init__(message)
        self.message = message
        self.forbidden = forbidden


def require_ajax(request: HttpRequest) -> None:
    if request.headers.get("x-requested-with") != "XMLHttpRequest":
        raise MutationGuardError("Invalid request.")


def parse_int_or_error(raw_value, *, message: str) -> int:
    try:
        return int(raw_value)
    except (TypeError, ValueError) as exc:
        raise MutationGuardError(message) from exc


def ensure_public_request_mutable(request_obj: CitizenRequest) -> None:
    if not can_citizen_upload_documents(request_obj):
        raise MutationGuardError("This request is locked.", forbidden=True)


def ensure_staff_can_access_request_mutations(*, request_obj: CitizenRequest, user) -> None:
    if is_request_locked(request_obj) and not getattr(user, "is_superuser", False):
        raise StaffWorkflowError("Request is locked and cannot be modified.")
    if not can_change_request_status(user, request_obj) and is_request_locked(request_obj):
        raise StaffWorkflowError("No editable request actions are available.")


def ensure_staff_can_review_document(*, document: RequestDocument, user) -> None:
    if document.is_removed:
        raise StaffWorkflowError("Document not found.")
    if is_request_locked(document.request):
        raise StaffWorkflowError("Request is locked and document cannot be updated.")
    if not can_review_documents(user):
        raise StaffWorkflowError("Your role cannot review documents.")
