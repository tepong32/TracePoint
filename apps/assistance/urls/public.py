from django.urls import path

from apps.assistance.views.public import (
    submit_request_view,
    track_request_view,
)

app_name = "assistance"

urlpatterns = [
    path(
        "submit/<slug:program_slug>/",
        submit_request_view,
        name="submit_request",
    ),
    path(
        "track/<str:tracking_code>/",
        track_request_view,
        name="track_request",
    ),
]