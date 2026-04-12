# apps/assistance/services/citizen_service.py
from django.utils import timezone

from apps.assistance.models import CitizenProfile


class CitizenService:
    @staticmethod
    def get_or_create_citizen(*, full_name: str, email: str, phone: str):
        """
        Finds an existing citizen by strongest identifiers first.
        Falls back safely and updates stale fields.
        """

        citizen = (
            CitizenProfile.objects.filter(phone=phone).first()
            or CitizenProfile.objects.filter(email=email).first()
        )

        if citizen:
            updated = False

            # refresh stale values if newer data is better
            if full_name and citizen.full_name != full_name:
                citizen.full_name = full_name
                updated = True

            if email and citizen.email != email:
                citizen.email = email
                updated = True

            if phone and citizen.phone != phone:
                citizen.phone = phone
                updated = True

            if updated:
                citizen.save(update_fields=["full_name", "email", "phone", "updated_at"])

            return citizen

        return CitizenProfile.objects.create(
            full_name=full_name,
            email=email,
            phone=phone,
        )

    @staticmethod
    def update_request_stats(citizen):
        citizen.total_requests += 1
        citizen.last_request_at = timezone.now()
        citizen.save(update_fields=["total_requests", "last_request_at", "updated_at"])