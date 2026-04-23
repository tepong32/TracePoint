from django.urls import path

from apps.assistance.views.staff import (
    mswd_update_document_ajax,
    staff_dashboard_view,
    staff_request_detail_view,
    staff_update_request_ajax,
    staff_update_status_inline,
)

app_name = "assistance_staff"

urlpatterns = [
    path("dashboard/", staff_dashboard_view, name="dashboard"),
    path("request/<int:request_id>/", staff_request_detail_view, name="request_detail"),
    path("request/<int:request_id>/update/ajax/", staff_update_request_ajax, name="request_update_ajax"),
    path("request/<int:request_id>/status/ajax/", staff_update_status_inline, name="request_status_inline"),
    path("document/<int:document_id>/update/ajax/", mswd_update_document_ajax, name="document_update_ajax"),
]
