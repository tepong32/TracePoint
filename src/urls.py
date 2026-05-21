"""
URL configuration for src project.
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from src.views import home_view

urlpatterns = [
    path("", home_view, name="home"),
    path("admin/", admin.site.urls),
    path("assistance/", include("apps.assistance.urls.public")),
    path("assistance/staff/", include("apps.assistance.urls.staff")),
    path("ckeditor5/", include("django_ckeditor_5.urls")),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
