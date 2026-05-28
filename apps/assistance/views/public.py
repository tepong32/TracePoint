from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.assistance.models.models import AssistanceProgram, CitizenRequest, RequestDocument
from apps.assistance.services.public_progress_service import build_public_progress_context
from apps.assistance.services.public_request_service import (
    PublicMutationError,
    PublicRequestService,
)
from apps.assistance.services.mutation_guard import MutationGuardError, require_ajax


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

        try:
            request_obj = PublicRequestService.submit_request(
                program=program,
                full_name=full_name,
                email=email,
                phone=phone,
            )
        except ValidationError as exc:
            messages.error(request, str(exc))
            return render(
                request,
                "assistance/public/submit_request.html",
                {"program": program},
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

    documents = request_obj.documents.filter(is_removed=False).order_by("-uploaded_at")

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
    secure_edit_state = PublicRequestService.get_secure_edit_state(
        secure_edit_token=secure_edit_token,
    )

    if secure_edit_state.is_locked_view:
        return render(
            request,
            "assistance/public/secure_edit_locked.html",
            {
                "request_obj": secure_edit_state.request_obj,
                "documents": secure_edit_state.documents,
                **secure_edit_state.progress_context,
            },
        )

    return render(
        request,
        "assistance/public/secure_edit.html",
        {
            "request_obj": secure_edit_state.request_obj,
            "documents": secure_edit_state.documents,
            "document_type_choices": RequestDocument.DOCUMENT_TYPE_CHOICES,
            **secure_edit_state.progress_context,
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
    try:
        require_ajax(request)
    except MutationGuardError as exc:
        return _ajax_upload_error(exc.message)

    try:
        PublicRequestService.upload_document(
            request=request,
            secure_edit_token=secure_edit_token,
        )
    except PublicMutationError as exc:
        if exc.forbidden:
            return _ajax_upload_forbidden(exc.message)
        return _ajax_upload_error(exc.message)

    return JsonResponse(
        {"status": "success", "message": "File uploaded successfully."},
    )


@require_POST
def delete_document_view(request, secure_edit_token):
    try:
        require_ajax(request)
    except MutationGuardError as exc:
        return _ajax_delete_error(exc.message)

    try:
        PublicRequestService.delete_document(
            request=request,
            secure_edit_token=secure_edit_token,
        )
    except PublicMutationError as exc:
        if exc.forbidden:
            return _ajax_delete_forbidden(exc.message)
        return _ajax_delete_error(exc.message)

    return JsonResponse(
        {"status": "success", "message": "Document deleted."},
    )
