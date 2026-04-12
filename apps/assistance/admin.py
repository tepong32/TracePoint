from django.contrib import admin

from .models.models import AssistanceProgram, CitizenProfile, CitizenRequest, RequestDocument, RequestTimeline


@admin.register(RequestDocument)
class RequestDocumentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "request",
        "document_type",
        "is_removed",
        "replacement_count",
        "uploaded_at",
    )
    list_filter = ("is_removed", "document_type")


admin.site.register(AssistanceProgram)
admin.site.register(CitizenProfile)
admin.site.register(CitizenRequest)
admin.site.register(RequestTimeline)
