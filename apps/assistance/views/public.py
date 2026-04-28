# apps/assistance/views/public.py
import logging

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.assistance.models.models import AssistanceProgram, CitizenRequest, RequestDocument
from apps.assistance.services.document_service import DocumentService, DocumentServiceError
from apps.assistance.services.request_service import RequestSubmissionService
from apps.assistance.services.lifecycle import (
    get_progress_step,
    get_public_status_label,
    is_locked_status,
    is_public_editable,
    requires_citizen_action,
)
from apps.assistance.services.lifecycle_service import apply_auto_status_transition

logger = logging.getLogger(__name__)


def _citizen_request_for_secure_edit(secure_edit_token: str) -> CitizenRequest:
    return get_object_or_404(
        CitizenRequest.objects.select_related("program", "citizen"),
        secure_edit_token=secure_edit_token,
        is_active=True,
    )


def _documents_locked(request_obj: CitizenRequest) -> bool:
    return request_obj.is_locked or is_locked_status(request_obj.status)


def _public_request_context(request_obj: CitizenRequest) -> dict:
    progress_step = get_progress_step(request_obj.status)
    can_update_documents = is_public_editable(request_obj.status) and not request_obj.is_locked

    action_callout = None
    if requires_citizen_action(request_obj.status):
        action_callout = {
            "tone": "warning",
            "title": "Update your request",
            "message": "Some documents need attention. Upload a replacement or add the requested correction so staff can continue the review.",
        }
    elif can_update_documents:
        action_callout = {
            "tone": "info",
            "title": "Documents can still be updated",
            "message": "Upload missing supporting documents or replace a file before staff completes the review.",
        }
    elif request_obj.is_locked:
        action_callout = {
            "tone": "locked",
            "title": "Request locked",
            "message": "This request has moved past document editing. You can still review the current status and documents on file.",
        }

    return {
        "progress_step": progress_step,
        "public_status_label": get_public_status_label(request_obj.status),
        "can_update_documents": can_update_documents,
        "action_callout": action_callout,
    }


def submit_request_view(request, program_slug):
    program = get_object_or_404(
        AssistanceProgram,
        slug=program_slug,
        is_active=True,
    )

    if request.method == "POST":
        full_name = request.POST.get("full_name", "").strip()
        email = request.POST.get("email", "").strip()
        phone = request.POST.get("phone", "").strip()

        # beginner-friendly safety validation first
        if not full_name or not email or not phone:
            messages.error(request, "Please complete all required fields.")
            return render(
                request,
                "assistance/public/submit_request.html",
                {"program": program},
            )

        request_obj = RequestSubmissionService.submit_request(
            program=program,
            full_name=full_name,
            email=email,
            phone=phone,
        )

        messages.success(
            request,
            f"Request submitted successfully. Tracking Code: {request_obj.tracking_code}",
        )

        return redirect(
            "assistance:track_request",
            tracking_code=request_obj.tracking_code,
        )

    return render(
        request,
        "assistance/public/submit_request.html",
        {"program": program},
    )


def track_request_view(request, tracking_code):
    request_obj = get_object_or_404(
        CitizenRequest.objects.select_related("program", "citizen"),
        tracking_code=tracking_code,
        is_active=True,
    )

    documents = (
        request_obj.documents.filter(is_removed=False).order_by("-uploaded_at")
    )

    return render(
        request,
        "assistance/public/track_request.html",
        {
            "request_obj": request_obj,
            "documents": documents,
            **_public_request_context(request_obj),
        },
    )


def secure_edit_view(request, secure_edit_token):
    request_obj = _citizen_request_for_secure_edit(secure_edit_token)

    if _documents_locked(request_obj):
        documents = request_obj.documents.filter(is_removed=False).order_by(
            "-uploaded_at"
        )
        return render(
            request,
            "assistance/public/secure_edit_locked.html",
            {
                "request_obj": request_obj,
                "documents": documents,
                **_public_request_context(request_obj),
            },
        )

    documents = request_obj.documents.filter(is_removed=False).order_by(
        "-uploaded_at"
    )
    return render(
        request,
        "assistance/public/secure_edit.html",
        {
            "request_obj": request_obj,
            "documents": documents,
            "document_type_choices": RequestDocument.DOCUMENT_TYPE_CHOICES,
            **_public_request_context(request_obj),
        },
    )


def _ajax_upload_error(message: str):
    return JsonResponse({"status": "error", "message": message})


def _ajax_delete_error(message: str):
    return JsonResponse({"status": "error", "message": message})


@require_POST
def upload_document_ajax(request, secure_edit_token):
    if request.headers.get("x-requested-with") != "XMLHttpRequest":
        return _ajax_upload_error("Invalid request.")

    request_obj = _citizen_request_for_secure_edit(secure_edit_token)

    if _documents_locked(request_obj):
        return _ajax_upload_error("This request is locked.")

    doc_type = request.POST.get("document_type", "").strip()
    uploaded_file = request.FILES.get("file")

    if not doc_type or not uploaded_file:
        return _ajax_upload_error("Missing file or document type.")

    status_before_upload = request_obj.status

    try:
        DocumentService.upload_or_replace(
            citizen_request=request_obj,
            document_type=doc_type,
            uploaded_file=uploaded_file,
        )
    except DocumentServiceError as e:
        return _ajax_upload_error(str(e))
    except ValidationError as e:
        return _ajax_upload_error(str(e))

    try:
        apply_auto_status_transition(
            request_obj,
            previous_status_for_audit=status_before_upload,
        )
    except Exception:
        # Safety guard: never break existing upload response shape.
        pass

    return JsonResponse(
        {"status": "success", "message": "File uploaded successfully."},
    )


@require_POST
def delete_document_view(request, secure_edit_token):
    if request.headers.get("x-requested-with") != "XMLHttpRequest":
        return _ajax_delete_error("Invalid request.")

    request_obj = _citizen_request_for_secure_edit(secure_edit_token)

    if _documents_locked(request_obj):
        return _ajax_delete_error("Request is locked.")

    doc_id_raw = request.POST.get("doc_id")
    try:
        doc_id = int(doc_id_raw)
    except (TypeError, ValueError):
        return _ajax_delete_error("Document not found.")

    try:
        DocumentService.soft_delete_document(
            citizen_request=request_obj,
            document_id=doc_id,
        )
    except DocumentServiceError as e:
        return _ajax_delete_error(str(e))

    return JsonResponse(
        {"status": "success", "message": "Document deleted."},
    )
