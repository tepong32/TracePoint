from django.urls import path

from apps.assistance.views.public import (
    delete_document_view,
    secure_edit_view,
    submit_request_view,
    track_request_view,
    upload_document_ajax,
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
    path(
        "edit/<str:secure_edit_token>/",
        secure_edit_view,
        name="secure_edit",
    ),
    path(
        "edit/<str:secure_edit_token>/upload/ajax/",
        upload_document_ajax,
        name="upload_document_ajax",
    ),
    path(
        "edit/<str:secure_edit_token>/delete-document/",
        delete_document_view,
        name="delete_document",
    ),
]