from django.db.models import Exists, OuterRef
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.assistance.models import CitizenRequest, RequestDocument, RequestTimeline
from apps.assistance.views.public import apply_auto_status_transition

LOCKED_STATUSES = {"approved", "claimable", "claimed", "closed"}


def _ajax_staff_error(message: str):
    return JsonResponse({"status": "error", "message": message})


def _is_locked(request_obj: CitizenRequest) -> bool:
    return request_obj.is_locked or request_obj.status in LOCKED_STATUSES


def _create_timeline_event(*, request_obj: CitizenRequest, message: str, user):
    RequestTimeline.objects.create(
        request=request_obj,
        event_type="staff_update",
        message=message,
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )


def _request_status_choices():
    return list(CitizenRequest.STATUS_CHOICES)


def _document_status_choices():
    return list(RequestDocument.STATUS_CHOICES)


def staff_dashboard_view(request):
    requests_qs = CitizenRequest.objects.select_related("program").filter(is_active=True)

    status_filter = request.GET.get("status", "").strip()
    program_filter = request.GET.get("program", "").strip()
    start_date = request.GET.get("start_date", "").strip()
    end_date = request.GET.get("end_date", "").strip()

    if status_filter:
        requests_qs = requests_qs.filter(status=status_filter)
    if program_filter:
        requests_qs = requests_qs.filter(program__slug=program_filter)
    if start_date:
        requests_qs = requests_qs.filter(submitted_at__date__gte=start_date)
    if end_date:
        requests_qs = requests_qs.filter(submitted_at__date__lte=end_date)

    active_docs = RequestDocument.objects.filter(request=OuterRef("pk"), is_removed=False)
    requests_qs = requests_qs.annotate(
        has_missing_documents=~Exists(active_docs),
        has_doc_issues=Exists(active_docs.exclude(status="approved")),
    ).order_by("-submitted_at")

    today = timezone.localdate()
    base_stats = CitizenRequest.objects.filter(is_active=True)
    summary_stats = {
        "pending_total": base_stats.filter(status="pending").count(),
        "under_review_total": base_stats.filter(status="under_review").count(),
        "approved_today": base_stats.filter(status="approved", updated_at__date=today).count(),
    }

    assistance_types = (
        CitizenRequest.objects.filter(is_active=True)
        .values_list("program__slug", "program__name")
        .distinct()
        .order_by("program__name")
    )

    context = {
        "requests": requests_qs,
        "status_choices": _request_status_choices(),
        "assistance_types": assistance_types,
        "filters": {
            "status": status_filter,
            "program": program_filter,
            "start_date": start_date,
            "end_date": end_date,
        },
        "summary_stats": summary_stats,
    }
    return render(request, "assistance/staff/dashboard.html", context)


def staff_request_detail_view(request, request_id):
    request_obj = get_object_or_404(
        CitizenRequest.objects.select_related("program"),
        id=request_id,
        is_active=True,
    )
    documents = request_obj.documents.filter(is_removed=False).order_by("document_type", "-uploaded_at")
    timeline_items = request_obj.timeline.select_related("created_by").order_by("-created_at")

    has_needs_attention = documents.exclude(status="approved").exists() if documents else True

    context = {
        "request_obj": request_obj,
        "documents": documents,
        "timeline_items": timeline_items,
        "status_choices": _request_status_choices(),
        "document_status_choices": _document_status_choices(),
        "is_locked": _is_locked(request_obj),
        "has_needs_attention": has_needs_attention,
    }
    return render(request, "assistance/staff/request_detail.html", context)


@require_POST
def staff_update_request_ajax(request, request_id):
    if request.headers.get("x-requested-with") != "XMLHttpRequest":
        return _ajax_staff_error("Invalid request.")

    request_obj = get_object_or_404(CitizenRequest, id=request_id, is_active=True)

    if _is_locked(request_obj):
        return _ajax_staff_error("Request is locked and cannot be edited.")

    new_status = request.POST.get("status", "").strip()
    remarks = request.POST.get("remarks", "").strip()

    if new_status and new_status not in {value for value, _ in _request_status_choices()}:
        return _ajax_staff_error("Invalid status value.")

    old_status = request_obj.status
    old_remarks = request_obj.remarks
    updates = ["updated_at"]

    if new_status and new_status != request_obj.status:
        request_obj.status = new_status
        updates.append("status")

    if remarks != old_remarks:
        request_obj.remarks = remarks
        updates.append("remarks")

    if len(updates) > 1:
        request_obj.save(update_fields=updates)
    else:
        return JsonResponse({"status": "success", "message": "No changes detected."})

    if old_status != request_obj.status:
        _create_timeline_event(
            request_obj=request_obj,
            message=f"Status changed from {old_status} to {request_obj.status}.",
            user=request.user,
        )

    if remarks != old_remarks:
        _create_timeline_event(
            request_obj=request_obj,
            message="Staff remarks updated.",
            user=request.user,
        )

    return JsonResponse({"status": "success", "message": "Request updated successfully."})


@require_POST
def mswd_update_document_ajax(request, document_id):
    if request.headers.get("x-requested-with") != "XMLHttpRequest":
        return _ajax_staff_error("Invalid request.")

    document = get_object_or_404(
        RequestDocument.objects.select_related("request"),
        id=document_id,
        is_removed=False,
    )

    if _is_locked(document.request):
        return _ajax_staff_error("Request is locked and document cannot be updated.")

    new_status = request.POST.get("status", "").strip()
    if not new_status:
        return _ajax_staff_error("Missing document status.")

    if new_status not in {value for value, _ in _document_status_choices()}:
        return _ajax_staff_error("Invalid document status.")

    incoming_remarks = request.POST.get("remarks", "").strip()
    if new_status == document.status and incoming_remarks == document.remarks:
        return JsonResponse({"status": "success", "message": "No changes detected."})

    document.status = new_status
    document.remarks = incoming_remarks
    document.save(update_fields=["status", "remarks", "updated_at"])

    _create_timeline_event(
        request_obj=document.request,
        message=f"Document {document.get_document_type_display()} marked as {document.status}.",
        user=request.user,
    )

    try:
        apply_auto_status_transition(document.request)
    except Exception:
        pass

    return JsonResponse(
        {"status": "success", "message": "Document updated successfully."},
    )


@require_POST
def staff_update_status_inline(request, request_id):
    if request.headers.get("x-requested-with") != "XMLHttpRequest":
        return _ajax_staff_error("Invalid request.")

    request_obj = get_object_or_404(CitizenRequest, id=request_id, is_active=True)

    if _is_locked(request_obj):
        return _ajax_staff_error("Request is locked and cannot be edited.")

    new_status = request.POST.get("status", "").strip()
    if new_status not in {value for value, _ in _request_status_choices()}:
        return _ajax_staff_error("Invalid status value.")

    if request_obj.status == new_status:
        return JsonResponse({"status": "success", "message": "No changes detected."})

    old_status = request_obj.status
    request_obj.status = new_status
    request_obj.save(update_fields=["status", "updated_at"])
    _create_timeline_event(
        request_obj=request_obj,
        message=f"Status changed from {old_status} to {new_status}.",
        user=request.user,
    )

    return JsonResponse({"status": "success", "message": "Status updated."})
