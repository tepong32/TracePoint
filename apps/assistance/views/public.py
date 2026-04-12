# apps/assistance/views/public.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages

from apps.assistance.models import AssistanceProgram
from apps.assistance.services.request_service import RequestSubmissionService


def submit_request_view(request, program_slug):
    program = get_object_or_404(
        AssistanceProgram,
        slug=program_slug,
        is_active=True
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
                {"program": program}
            )

        request_obj = RequestSubmissionService.submit_request(
            program=program,
            full_name=full_name,
            email=email,
            phone=phone,
        )

        messages.success(
            request,
            f"Request submitted successfully. Tracking Code: {request_obj.tracking_code}"
        )

        return redirect(
            "assistance:track_request",
            tracking_code=request_obj.tracking_code
        )

    return render(
        request,
        "assistance/public/submit_request.html",
        {"program": program}
    )