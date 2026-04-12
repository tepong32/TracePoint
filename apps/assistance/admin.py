from django.contrib import admin

from .models.models import AssistanceProgram, CitizenProfile, CitizenRequest, RequestDocument, RequestTimeline

admin.site.register(AssistanceProgram)
admin.site.register(CitizenProfile)
admin.site.register(CitizenRequest)
admin.site.register(RequestDocument)
admin.site.register(RequestTimeline)
