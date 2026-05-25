from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db.models import QuerySet
from django.shortcuts import get_object_or_404

from apps.assistance.models import CitizenRequest, RequestDocument
from apps.assistance.services.document_service import DocumentService, DocumentServiceError
from apps.assistance.services.lifecycle_rules import can_citizen_upload_documents, is_request_locked
from apps.assistance.services.public_access_service import (
    InvalidPublicEditToken,
    get_request_for_public_mutation,
)
from apps.assistance.services.public_progress_service import build_public_progress_context
from apps.assistance.services.request_service import RequestSubmissionService


class PublicMutationError(Exception):
    def __init__(self, message: str, *, forbidden: bool = False):
        super().__init__(message)
        self.message = message
        self.forbidden = forbidden


@dataclass(frozen=True)
class SecureEditState:
    request_obj: CitizenRequest
    documents: QuerySet[RequestDocument]
    progress_context: dict
    is_locked_view: bool


class PublicRequestService:
    @staticmethod
    def validate_submit_payload(*, full_name: str, email: str, phone: str) -> None:
        if not full_name or not email or not phone:
            raise ValidationError("Please complete all required fields.")

    @staticmethod
    def submit_request(*, program, full_name: str, email: str, phone: str) -> CitizenRequest:
        PublicRequestService.validate_submit_payload(
            full_name=full_name,
            email=email,
            phone=phone,
        )
        return RequestSubmissionService.submit_request(
            program=program,
            full_name=full_name,
            email=email,
            phone=phone,
        )

    @staticmethod
    def get_secure_edit_state(*, secure_edit_token: str) -> SecureEditState:
        request_obj = get_object_or_404(
            CitizenRequest.objects.select_related("program", "citizen"),
            secure_edit_token=secure_edit_token,
            is_active=True,
        )
        progress_context = build_public_progress_context(request_obj)
        documents = request_obj.documents.filter(is_removed=False).order_by("-uploaded_at")
        return SecureEditState(
            request_obj=request_obj,
            documents=documents,
            progress_context=progress_context,
            is_locked_view=(
                is_request_locked(request_obj)
                or not progress_context["can_update_documents"]
            ),
        )

    @staticmethod
    def upload_document(*, request, secure_edit_token: str) -> None:
        try:
            request_obj = get_request_for_public_mutation(
                request=request,
                edit_token=secure_edit_token,
                action="upload_document",
            )
        except InvalidPublicEditToken as exc:
            raise PublicMutationError(str(exc), forbidden=True) from exc

        if not can_citizen_upload_documents(request_obj):
            raise PublicMutationError("This request is locked.", forbidden=True)

        doc_type = request.POST.get("document_type", "").strip()
        uploaded_file = request.FILES.get("file")

        if not doc_type or not uploaded_file:
            raise PublicMutationError("Missing file or document type.")

        try:
            DocumentService.upload_for_citizen(
                citizen_request=request_obj,
                document_type=doc_type,
                uploaded_file=uploaded_file,
            )
        except DocumentServiceError as exc:
            raise PublicMutationError(str(exc)) from exc

    @staticmethod
    def delete_document(*, request, secure_edit_token: str) -> None:
        try:
            request_obj = get_request_for_public_mutation(
                request=request,
                edit_token=secure_edit_token,
                action="delete_document",
            )
        except InvalidPublicEditToken as exc:
            raise PublicMutationError(str(exc), forbidden=True) from exc

        if not can_citizen_upload_documents(request_obj):
            raise PublicMutationError("Request is locked.", forbidden=True)

        doc_id_raw = request.POST.get("doc_id")
        try:
            doc_id = int(doc_id_raw)
        except (TypeError, ValueError) as exc:
            raise PublicMutationError("Document not found.") from exc

        try:
            DocumentService.delete_for_citizen(
                citizen_request=request_obj,
                document_id=doc_id,
            )
        except DocumentServiceError as exc:
            raise PublicMutationError(str(exc)) from exc
