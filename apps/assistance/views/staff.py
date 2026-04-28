from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.db.models import Exists, OuterRef
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.assistance.models import CitizenRequest, RequestDocument, RequestTimeline
from apps.assistance.services.lifecycle import (
    get_allowed_next_statuses,
    is_locked_status,
)
from apps.assistance.services.lifecycle_service import (
    LifecycleTransitionError,
    apply_auto_status_transition,
    transition_request_status,
)
from apps.assistance.services.notifications import (
    dispatch_notification,
    prepare_document_review_notification,
)

ASSISTANCE_STAFF_GROUPS = {
    "mswd",
    "assistance_reviewer",
    "assistance_approver",
    "assistance_fulfillment",
}
QUEUE_STATUS_MAP = {
    "intake": {"submitted", "awaiting_documents", "needs_attention"},
    "review": {"under_review", "needs_attention"},
    "approval": {"under_review"},
    "fulfillment": {"approved", "claimable", "claimed"},
    "closed": {"closed"},
    "all": set(),
}
ROLE_DEFAULT_QUEUE = {
    "assistance_reviewer": "review",
    "assistance_approver": "approval",
    "assistance_fulfillment": "fulfillment",
    "mswd": "all",
}
ROLE_TRANSITIONS = {
    "assistance_reviewer": {
        ("submitted", "awaiting_documents"),
        ("submitted", "under_review"),
        ("awaiting_documents", "under_review"),
        ("needs_attention", "under_review"),
        ("under_review", "needs_attention"),
    },
    "assistance_approver": {
        ("under_review", "approved"),
        ("under_review", "needs_attention"),
    },
    "assistance_fulfillment": {
        ("approved", "claimable"),
        ("claimable", "claimed"),
        ("claimed", "closed"),
    },
}
DOCUMENT_REVIEW_ROLES = {"assistance_reviewer", "mswd"}


def _ajax_staff_error(message: str):
    return JsonResponse({"status": "error", "message": message})


def _is_staff_user(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True

    group_names = set(user.groups.values_list("name", flat=True))
    if group_names & ASSISTANCE_STAFF_GROUPS:
        return True

    employee_profile = getattr(user, "employeeprofile", None)
    assigned_department = getattr(employee_profile, "assigned_department", None)
    return getattr(assigned_department, "slug", None) == "mswd"


def _staff_role_names(user) -> set[str]:
    if getattr(user, "is_superuser", False):
        return {"mswd"}

    names = set(user.groups.values_list("name", flat=True)) & ASSISTANCE_STAFF_GROUPS
    employee_profile = getattr(user, "employeeprofile", None)
    assigned_department = getattr(employee_profile, "assigned_department", None)
    if getattr(assigned_department, "slug", None) == "mswd":
        names.add("mswd")
    return names


def _has_all_queue_access(user) -> bool:
    return getattr(user, "is_superuser", False) or "mswd" in _staff_role_names(user)


def _default_queue_for_user(user) -> str:
    roles = _staff_role_names(user)
    if _has_all_queue_access(user):
        return "all"
    for role, queue in ROLE_DEFAULT_QUEUE.items():
        if role in roles:
            return queue
    return "review"


def _allowed_transition_statuses(user, current_status: str) -> set[str]:
    next_statuses = get_allowed_next_statuses(current_status)
    if _has_all_queue_access(user):
        return next_statuses

    roles = _staff_role_names(user)
    allowed_pairs = set()
    for role in roles:
        allowed_pairs.update(ROLE_TRANSITIONS.get(role, set()))
    return {
        new_status
        for new_status in next_statuses
        if (current_status, new_status) in allowed_pairs
    }


def _can_review_documents(user) -> bool:
    return _has_all_queue_access(user) or bool(_staff_role_names(user) & DOCUMENT_REVIEW_ROLES)


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

        if not _is_staff_user(request.user):
            if is_ajax:
                return JsonResponse(
                    {"status": "error", "message": "Staff access required."},
                    status=403,
                )
            return HttpResponseForbidden("Staff access required.")

        return view_func(request, *args, **kwargs)

    return _wrapped


def _is_locked(request_obj: CitizenRequest) -> bool:
    return request_obj.is_locked or is_locked_status(request_obj.status)


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


@staff_required
def staff_dashboard_view(request):
    requests_qs = CitizenRequest.objects.select_related("program").filter(is_active=True)

    status_filter = request.GET.get("status", "").strip()
    active_queue = request.GET.get("queue", "").strip() or _default_queue_for_user(request.user)
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

    active_docs = RequestDocument.objects.filter(request=OuterRef("pk"), is_removed=False)
    requests_qs = requests_qs.annotate(
        has_missing_documents=~Exists(active_docs),
        has_doc_issues=Exists(active_docs.exclude(status="approved")),
    ).order_by("-submitted_at")

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

    requests = list(requests_qs)
    for req in requests:
        req.allowed_next_statuses = _allowed_transition_statuses(request.user, req.status)

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
    documents = request_obj.documents.filter(is_removed=False).order_by("document_type", "-uploaded_at")
    timeline_items = request_obj.timeline.select_related("created_by").order_by("-created_at")

    document_total = documents.count()
    approved_documents = documents.filter(status="approved").count()
    issue_documents = documents.exclude(status__in=("approved", "pending")).count()
    pending_documents = documents.filter(status="pending").count()
    has_needs_attention = document_total == 0 or issue_documents > 0

    allowed_next_statuses = _allowed_transition_statuses(request.user, request_obj.status)
    context = {
        "request_obj": request_obj,
        "documents": documents,
        "timeline_items": timeline_items,
        "status_choices": _request_status_choices(),
        "allowed_next_statuses": allowed_next_statuses,
        "document_status_choices": _document_status_choices(),
        "is_locked": _is_locked(request_obj),
        "can_review_documents": _can_review_documents(request.user),
        "has_needs_attention": has_needs_attention,
        "document_review_summary": {
            "total": document_total,
            "approved": approved_documents,
            "pending": pending_documents,
            "issues": issue_documents,
        },
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

    old_status = request_obj.status
    old_remarks = request_obj.remarks
    updates = ["updated_at"]

    if remarks != old_remarks:
        request_obj.remarks = remarks
        updates.append("remarks")

    status_changed = bool(new_status and new_status != request_obj.status)
    if status_changed and new_status not in _allowed_transition_statuses(request.user, request_obj.status):
        return _ajax_staff_error("Your role cannot perform this status transition.")

    if _is_locked(request_obj) and remarks != old_remarks:
        return _ajax_staff_error("Request is locked and remarks cannot be edited.")

    if status_changed:
        try:
            transition_request_status(
                request_obj,
                new_status=new_status,
                actor=request.user,
            )
        except LifecycleTransitionError as e:
            return _ajax_staff_error(str(e))

    if remarks != old_remarks:
        request_obj.save(update_fields=updates)
    elif not status_changed:
        return JsonResponse({"status": "success", "message": "No changes detected."})

    if old_status != request_obj.status:
        pass

    if remarks != old_remarks:
        _create_timeline_event(
            request_obj=request_obj,
            message="Staff remarks updated.",
            user=request.user,
        )

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

    if _is_locked(document.request):
        return _ajax_staff_error("Request is locked and document cannot be updated.")
    if not _can_review_documents(request.user):
        return _ajax_staff_error("Your role cannot review documents.")

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
    dispatch_notification(
        prepare_document_review_notification(document),
        citizen_request=document.request,
    )

    try:
        apply_auto_status_transition(document.request)
    except Exception:
        pass

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
    if new_status not in _allowed_transition_statuses(request.user, request_obj.status):
        return _ajax_staff_error("Your role cannot perform this status transition.")

    try:
        transition_request_status(
            request_obj,
            new_status=new_status,
            actor=request.user,
        )
    except LifecycleTransitionError as e:
        return _ajax_staff_error(str(e))

    return JsonResponse({"status": "success", "message": "Status updated."})
