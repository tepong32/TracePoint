from django.shortcuts import redirect, render

from apps.assistance.forms import TrackRequestForm
from apps.assistance.models import AssistanceProgram


def home_view(request):
    programs = AssistanceProgram.objects.filter(is_active=True).order_by("name")
    if request.method == "POST":
        tracking_form = TrackRequestForm(request.POST)
        if tracking_form.is_valid():
            return redirect(
                "assistance:track_request",
                tracking_code=tracking_form.cleaned_data["tracking_code"],
            )
    else:
        tracking_form = TrackRequestForm()

    return render(
        request,
        "home.html",
        {
            "programs": programs,
            "tracking_form": tracking_form,
        },
    )
