# apps/assistance/services/request_service.py
import secrets
from django.utils import timezone

from apps.assistance.models import (
    CitizenRequest,
    RequestTimeline,
)
from apps.assistance.services.citizen_service import CitizenService


class RequestSubmissionService:
    @staticmethod
    def generate_tracking_code():
        timestamp = timezone.now().strftime("%Y%m%d%H%M%S")
        return f"TP-{timestamp}"

    @staticmethod
    def generate_secure_token():
        return secrets.token_urlsafe(32)

    @classmethod
    def submit_request(cls, *, program, full_name, email, phone):
        citizen = CitizenService.get_or_create_citizen(
            full_name=full_name,
            email=email,
            phone=phone,
        )

        request_obj = CitizenRequest.objects.create(
            tracking_code=cls.generate_tracking_code(),
            secure_edit_token=cls.generate_secure_token(),
            program=program,
            full_name=full_name,
            email=email,
            phone=phone,
            citizen=citizen,
            status="submitted",
        )

        CitizenService.update_request_stats(citizen)

        RequestTimeline.objects.create(
            request=request_obj,
            event_type="submitted",
            message="Citizen request submitted successfully.",
        )

        return request_obj