from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.assistance.models.models import (
    AssistanceProgram,
    CitizenRequest,
    RequestDocument,
)
from apps.assistance.services.document_service import DocumentService, DocumentServiceError
from apps.assistance.services.lifecycle import is_locked_status
from apps.assistance.services.public_access_service import (
    InvalidPublicEditToken,
    get_request_for_public_mutation,
)
from apps.assistance.services.public_progress_service import build_public_progress_context
from apps.assistance.services.request_service import RequestSubmissionService


def _citizen_request_for_secure_edit(secure_edit_token: str) -> CitizenRequest:
    return get_object_or_404(
        CitizenRequest.objects.select_related("program", "citizen"),
        secure_edit_token=secure_edit_token,
        is_active=True,
    )


def _documents_locked(request_obj: CitizenRequest) -> bool:
    return request_obj.is_locked or is_locked_status(request_obj.status)


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
            **build_public_progress_context(request_obj),
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
                **build_public_progress_context(request_obj),
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
            **build_public_progress_context(request_obj),
        },
    )


def _ajax_upload_error(message: str):
    return JsonResponse({"status": "error", "message": message})


def _ajax_delete_error(message: str):
    return JsonResponse({"status": "error", "message": message})


def _ajax_upload_forbidden(message: str):
    return JsonResponse(
        {"status": "error", "message": message},
        status=403,
    )


def _ajax_delete_forbidden(message: str):
    return JsonResponse(
        {"status": "error", "message": message},
        status=403,
    )


@require_POST
def upload_document_ajax(request, secure_edit_token):
    if request.headers.get("x-requested-with") != "XMLHttpRequest":
        return _ajax_upload_error("Invalid request.")

    try:
        request_obj = get_request_for_public_mutation(
            request=request,
            edit_token=secure_edit_token,
            action="upload_document",
        )
    except InvalidPublicEditToken as exc:
        return _ajax_upload_forbidden(str(exc))

    if _documents_locked(request_obj):
        return _ajax_upload_forbidden("This request is locked.")

    doc_type = request.POST.get("document_type", "").strip()
    uploaded_file = request.FILES.get("file")

    if not doc_type or not uploaded_file:
        return _ajax_upload_error("Missing file or document type.")

    try:
        DocumentService.upload_for_citizen(
            citizen_request=request_obj,
            document_type=doc_type,
            uploaded_file=uploaded_file,
        )
    except DocumentServiceError as e:
        return _ajax_upload_error(str(e))

    return JsonResponse(
        {"status": "success", "message": "File uploaded successfully."},
    )


@require_POST
def delete_document_view(request, secure_edit_token):
    if request.headers.get("x-requested-with") != "XMLHttpRequest":
        return _ajax_delete_error("Invalid request.")

    try:
        request_obj = get_request_for_public_mutation(
            request=request,
            edit_token=secure_edit_token,
            action="delete_document",
        )
    except InvalidPublicEditToken as exc:
        return _ajax_delete_forbidden(str(exc))

    if _documents_locked(request_obj):
        return _ajax_delete_forbidden("Request is locked.")

    doc_id_raw = request.POST.get("doc_id")
    try:
        doc_id = int(doc_id_raw)
    except (TypeError, ValueError):
        return _ajax_delete_error("Document not found.")

    try:
        DocumentService.delete_for_citizen(
            citizen_request=request_obj,
            document_id=doc_id,
        )
    except DocumentServiceError as e:
        return _ajax_delete_error(str(e))

    return JsonResponse(
        {"status": "success", "message": "Document deleted."},
    )
