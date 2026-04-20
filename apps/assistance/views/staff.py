from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from apps.assistance.models import RequestDocument
from apps.assistance.views.public import apply_auto_status_transition


def _ajax_staff_error(message: str):
    return JsonResponse({"status": "error", "message": message})


@require_POST
def mswd_update_document_ajax(request, document_id):
    if request.headers.get("x-requested-with") != "XMLHttpRequest":
        return _ajax_staff_error("Invalid request.")

    document = get_object_or_404(
        RequestDocument.objects.select_related("request"),
        id=document_id,
        is_removed=False,
    )

    new_status = request.POST.get("status", "").strip()
    if not new_status:
        return _ajax_staff_error("Missing document status.")

    document.status = new_status
    document.remarks = request.POST.get("remarks", "").strip()
    document.save(update_fields=["status", "remarks", "updated_at"])

    try:
        apply_auto_status_transition(document.request)
    except Exception:
        # Safety guard: never break existing AJAX response shape.
        pass

    return JsonResponse(
        {"status": "success", "message": "Document updated successfully."},
    )
