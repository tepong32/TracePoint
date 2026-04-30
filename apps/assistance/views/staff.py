from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.assistance.models import CitizenRequest, RequestDocument
from apps.assistance.services.staff_workflow_service import (
    QUEUE_STATUS_MAP,
    StaffWorkflowError,
    apply_staff_queue_metadata,
    build_staff_request_detail_context,
    default_queue_for_user,
    is_staff_user,
    review_document_by_staff,
    update_request_by_staff,
)


def _ajax_staff_error(message: str):
    return JsonResponse({"status": "error", "message": message})


def _queue_tabs(active_queue: str) -> list[dict]:
    return [
        {"key": "intake", "label": "Intake", "active": active_queue == "intake"},
        {"key": "review", "label": "Review", "active": active_queue == "review"},
        {"key": "approval", "label": "Approval", "active": active_queue == "approval"},
        {"key": "fulfillment", "label": "Fulfillment", "active": active_queue == "fulfillment"},
        {"key": "closed", "label": "Closed", "active": active_queue == "closed"},
        {"key": "all", "label": "All", "active": active_queue == "all"},
    ]


def staff_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"

        if not getattr(request.user, "is_authenticated", False):
            if is_ajax:
                return JsonResponse(
                    {"status": "error", "message": "Authentication required."},
                    status=403,
                )
            return redirect_to_login(request.get_full_path())

        if not is_staff_user(request.user):
            if is_ajax:
                return JsonResponse(
                    {"status": "error", "message": "Staff access required."},
                    status=403,
                )
            return HttpResponseForbidden("Staff access required.")

        return view_func(request, *args, **kwargs)

    return _wrapped


def _request_status_choices():
    return list(CitizenRequest.STATUS_CHOICES)


def _document_status_choices():
    return list(RequestDocument.STATUS_CHOICES)


@staff_required
def staff_dashboard_view(request):
    requests_qs = CitizenRequest.objects.select_related("program").filter(is_active=True)

    status_filter = request.GET.get("status", "").strip()
    active_queue = request.GET.get("queue", "").strip() or default_queue_for_user(request.user)
    program_filter = request.GET.get("program", "").strip()
    start_date = request.GET.get("start_date", "").strip()
    end_date = request.GET.get("end_date", "").strip()

    if status_filter:
        requests_qs = requests_qs.filter(status=status_filter)
    elif active_queue in QUEUE_STATUS_MAP and QUEUE_STATUS_MAP[active_queue]:
        requests_qs = requests_qs.filter(status__in=QUEUE_STATUS_MAP[active_queue])
    if program_filter:
        requests_qs = requests_qs.filter(program__slug=program_filter)
    if start_date:
        requests_qs = requests_qs.filter(submitted_at__date__gte=start_date)
    if end_date:
        requests_qs = requests_qs.filter(submitted_at__date__lte=end_date)

    requests_qs = requests_qs.order_by("-submitted_at")

    today = timezone.localdate()
    base_stats = CitizenRequest.objects.filter(is_active=True)
    summary_stats = {
        "awaiting_documents_total": base_stats.filter(status="awaiting_documents").count(),
        "under_review_total": base_stats.filter(status="under_review").count(),
        "claimable_total": base_stats.filter(status="claimable").count(),
        "approved_today": base_stats.filter(
            status__in=("approved", "claimable", "claimed"),
            updated_at__date=today,
        ).count(),
    }

    assistance_types = (
        CitizenRequest.objects.filter(is_active=True)
        .values_list("program__slug", "program__name")
        .distinct()
        .order_by("program__name")
    )

    requests = apply_staff_queue_metadata(list(requests_qs), request.user)

    context = {
        "requests": requests,
        "status_choices": _request_status_choices(),
        "queue_tabs": _queue_tabs(active_queue),
        "assistance_types": assistance_types,
        "filters": {
            "status": status_filter,
            "queue": active_queue,
            "program": program_filter,
            "start_date": start_date,
            "end_date": end_date,
        },
        "summary_stats": summary_stats,
    }
    return render(request, "assistance/staff/dashboard.html", context)


@staff_required
def staff_request_detail_view(request, request_id):
    request_obj = get_object_or_404(
        CitizenRequest.objects.select_related("program"),
        id=request_id,
        is_active=True,
    )
    workflow_context = build_staff_request_detail_context(
        request_obj=request_obj,
        user=request.user,
    )
    context = {
        "request_obj": request_obj,
        "status_choices": _request_status_choices(),
        "document_status_choices": _document_status_choices(),
        **workflow_context,
    }
    return render(request, "assistance/staff/request_detail.html", context)


@require_POST
@staff_required
def staff_update_request_ajax(request, request_id):
    if request.headers.get("x-requested-with") != "XMLHttpRequest":
        return _ajax_staff_error("Invalid request.")

    request_obj = get_object_or_404(CitizenRequest, id=request_id, is_active=True)

    new_status = request.POST.get("status", "").strip()
    remarks = request.POST.get("remarks", "").strip()

    if new_status and new_status not in {value for value, _ in _request_status_choices()}:
        return _ajax_staff_error("Invalid status value.")

    try:
        changed = update_request_by_staff(
            request_obj=request_obj,
            user=request.user,
            new_status=new_status,
            remarks=remarks,
        )
    except StaffWorkflowError as e:
        return _ajax_staff_error(str(e))

    if not changed:
        return JsonResponse({"status": "success", "message": "No changes detected."})

    return JsonResponse({"status": "success", "message": "Request updated successfully."})


@require_POST
@staff_required
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

    if new_status not in {value for value, _ in _document_status_choices()}:
        return _ajax_staff_error("Invalid document status.")

    incoming_remarks = request.POST.get("remarks", "").strip()
    try:
        changed = review_document_by_staff(
            document=document,
            user=request.user,
            new_status=new_status,
            remarks=incoming_remarks,
        )
    except StaffWorkflowError as e:
        return _ajax_staff_error(str(e))

    if not changed:
        return JsonResponse({"status": "success", "message": "No changes detected."})

    return JsonResponse(
        {"status": "success", "message": "Document updated successfully."},
    )


@require_POST
@staff_required
def staff_update_status_inline(request, request_id):
    if request.headers.get("x-requested-with") != "XMLHttpRequest":
        return _ajax_staff_error("Invalid request.")

    request_obj = get_object_or_404(CitizenRequest, id=request_id, is_active=True)

    new_status = request.POST.get("status", "").strip()
    if new_status not in {value for value, _ in _request_status_choices()}:
        return _ajax_staff_error("Invalid status value.")

    if request_obj.status == new_status:
        return JsonResponse({"status": "success", "message": "No changes detected."})
    try:
        update_request_by_staff(
            request_obj=request_obj,
            user=request.user,
            new_status=new_status,
        )
    except StaffWorkflowError as e:
        return _ajax_staff_error(str(e))

    return JsonResponse({"status": "success", "message": "Status updated."})
