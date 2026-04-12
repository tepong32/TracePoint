# apps/assistance/services/document_service.py
import os

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from apps.assistance.models import CitizenRequest, RequestDocument, RequestTimeline


class DocumentServiceError(Exception):
    """Business rule violation for document operations (map to HTTP in views)."""

    pass


def validate_uploaded_file(uploaded_file) -> None:
    """Raises django.core.exceptions.ValidationError on invalid uploads."""
    allowed = getattr(
        settings,
        "TRACEPOINT_UPLOAD_ALLOWED_EXTENSIONS",
        (".pdf",),
    )
    max_mb = int(getattr(settings, "TRACEPOINT_UPLOAD_MAX_SIZE_MB", 5))

    ext = os.path.splitext(getattr(uploaded_file, "name", "") or "")[1].lower()
    if ext not in allowed:
        raise ValidationError(f"Unsupported file type: {ext or '(none)'}")

    size = getattr(uploaded_file, "size", None)
    if size is not None and size > max_mb * 1024 * 1024:
        raise ValidationError(f"File size exceeds {max_mb}MB.")


def _allowed_document_types() -> frozenset[str]:
    return frozenset(k for k, _ in RequestDocument.DOCUMENT_TYPE_CHOICES)


def _assert_request_allows_document_changes(citizen_request: CitizenRequest) -> None:
    if not citizen_request.is_active:
        raise DocumentServiceError("This request is no longer active.")
    if citizen_request.is_locked:
        raise DocumentServiceError("This request is locked and cannot be changed.")


def _timeline_event(
    *,
    citizen_request: CitizenRequest,
    event_type: str,
    message: str,
    created_by=None,
) -> None:
    RequestTimeline.objects.create(
        request=citizen_request,
        event_type=event_type,
        message=message,
        created_by=created_by,
    )


def _delete_stored_file_by_name(name: str | None) -> None:
    if not name:
        return
    try:
        default_storage.delete(name)
    except OSError:
        pass


class DocumentService:
    @classmethod
    def upload_or_replace(
        cls,
        *,
        citizen_request: CitizenRequest,
        document_type: str,
        uploaded_file,
        created_by=None,
    ) -> RequestDocument:
        """
        Last write wins per (request, document_type):
        - Replacing an active file increments replacement_count, shows citizen
          "replaced" state, and hard-deletes the prior file from storage.
        - After a citizen soft-delete, the file stays on disk until a new upload
          supersedes it; then the prior file is hard-deleted.
        """
        if document_type not in _allowed_document_types():
            raise DocumentServiceError("Invalid document type.")

        validate_uploaded_file(uploaded_file)
        _assert_request_allows_document_changes(citizen_request)

        superseded_names: list[str] = []
        doc: RequestDocument | None = None

        with transaction.atomic():
            active = (
                RequestDocument.objects.select_for_update()
                .filter(
                    request=citizen_request,
                    document_type=document_type,
                    is_removed=False,
                )
                .first()
            )

            if active:
                old_name = active.file.name if active.file else None
                active.file = uploaded_file
                if old_name:
                    active.replacement_count += 1
                    superseded_names.append(old_name)
                active.status = "pending"
                active.save()
                _timeline_event(
                    citizen_request=citizen_request,
                    event_type="document_replaced" if old_name else "document_uploaded",
                    message=(
                        f"Supporting document ({document_type}) replaced."
                        if old_name
                        else f"Supporting document ({document_type}) uploaded."
                    ),
                    created_by=created_by,
                )
                doc = active
            else:
                removed = (
                    RequestDocument.objects.select_for_update()
                    .filter(
                        request=citizen_request,
                        document_type=document_type,
                        is_removed=True,
                    )
                    .order_by("-removed_at", "-id")
                    .first()
                )
                if removed:
                    old_name = removed.file.name if removed.file else None
                    removed.file = uploaded_file
                    removed.is_removed = False
                    removed.removed_at = None
                    removed.status = "pending"
                    if old_name:
                        removed.replacement_count += 1
                        superseded_names.append(old_name)
                    removed.save()
                    _timeline_event(
                        citizen_request=citizen_request,
                        event_type="document_replaced" if old_name else "document_uploaded",
                        message=(
                            f"Supporting document ({document_type}) re-uploaded after removal."
                            if old_name
                            else f"Supporting document ({document_type}) uploaded."
                        ),
                        created_by=created_by,
                    )
                    doc = removed
                else:
                    doc = RequestDocument.objects.create(
                        request=citizen_request,
                        document_type=document_type,
                        file=uploaded_file,
                        status="pending",
                    )
                    _timeline_event(
                        citizen_request=citizen_request,
                        event_type="document_uploaded",
                        message=f"Supporting document ({document_type}) uploaded.",
                        created_by=created_by,
                    )

        assert doc is not None
        for name in tuple(superseded_names):
            if name:
                transaction.on_commit(
                    lambda n=name: _delete_stored_file_by_name(n),
                )
        return doc

    @classmethod
    def soft_delete_document(
        cls,
        *,
        citizen_request: CitizenRequest,
        document_id: int,
        created_by=None,
    ) -> None:
        """Citizen removal: row hidden from active lists; file remains in storage."""
        _assert_request_allows_document_changes(citizen_request)

        with transaction.atomic():
            doc = (
                RequestDocument.objects.select_for_update()
                .filter(
                    id=document_id,
                    request=citizen_request,
                    is_removed=False,
                )
                .first()
            )
            if not doc:
                raise DocumentServiceError("Document not found.")

            doc.is_removed = True
            doc.removed_at = timezone.now()
            doc.save(update_fields=["is_removed", "removed_at", "updated_at"])
            _timeline_event(
                citizen_request=citizen_request,
                event_type="document_removed",
                message=f"Supporting document ({doc.document_type}) removed by requester.",
                created_by=created_by,
            )
