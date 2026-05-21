from django.shortcuts import render

from apps.assistance.models import AssistanceProgram


def home_view(request):
    programs = AssistanceProgram.objects.filter(is_active=True).order_by("name")
    return render(request, "home.html", {"programs": programs})
