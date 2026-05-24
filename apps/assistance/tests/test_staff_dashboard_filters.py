from datetime import timedelta
import secrets

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.assistance.models import AssistanceProgram, CitizenProfile, CitizenRequest
from apps.assistance.services.lifecycle import RequestStatus
from apps.assistance.services.request_service import RequestSubmissionService


class StaffDashboardFilterTests(TestCase):
    def setUp(self):
        self.program_a = AssistanceProgram.objects.create(
            name="Program A",
            slug="program-a",
            description="desc",
            requirements="req",
        )
        self.program_b = AssistanceProgram.objects.create(
            name="Program B",
            slug="program-b",
            description="desc",
            requirements="req",
        )
        self.req_a = RequestSubmissionService.submit_request(
            program=self.program_a,
            full_name="Alpha Citizen",
            email="alpha@example.com",
            phone="09111111111",
        )
        self.req_a.status = RequestStatus.SUBMITTED
        self.req_a.save(update_fields=["status", "updated_at"])
        self.req_a.submitted_at = timezone.now() - timedelta(days=10)
        self.req_a.save(update_fields=["submitted_at"])

        citizen_b = CitizenProfile.objects.create(
            full_name="Beta Citizen",
            email="beta@example.com",
            phone="09222222222",
        )
        self.req_b = CitizenRequest.objects.create(
            tracking_code=f"TP-{secrets.token_hex(4)}",
            secure_edit_token=secrets.token_urlsafe(32),
            program=self.program_b,
            citizen=citizen_b,
            full_name="Beta Citizen",
            email="beta@example.com",
            phone="09222222222",
            status=RequestStatus.SUBMITTED,
        )
        self.req_b.status = RequestStatus.UNDER_REVIEW
        self.req_b.save(update_fields=["status", "updated_at"])
        self.req_b.submitted_at = timezone.now() - timedelta(days=2)
        self.req_b.save(update_fields=["submitted_at"])

        user_model = get_user_model()
        self.staff_user = user_model.objects.create_user(
            username="dashboard-staff",
            password="pass-12345",
            is_staff=True,
        )
        self.staff_user.groups.add(Group.objects.get(name="assistance_reviewer"))
        self.client.force_login(self.staff_user)

    def test_dashboard_filters_by_program_slug(self):
        response = self.client.get(
            reverse("assistance_staff:dashboard"),
            {"program": self.program_b.slug, "queue": "all"},
        )

        self.assertEqual(response.status_code, 200)
        requests = response.context["requests"]
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].id, self.req_b.id)

    def test_dashboard_filters_by_submitted_date_range(self):
        start_date = (timezone.localdate() - timedelta(days=3)).isoformat()
        end_date = timezone.localdate().isoformat()
        response = self.client.get(
            reverse("assistance_staff:dashboard"),
            {"start_date": start_date, "end_date": end_date, "queue": "all"},
        )

        self.assertEqual(response.status_code, 200)
        requests = response.context["requests"]
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].id, self.req_b.id)

    def test_dashboard_applies_queue_and_program_together(self):
        response = self.client.get(
            reverse("assistance_staff:dashboard"),
            {"queue": "review", "program": self.program_b.slug},
        )

        self.assertEqual(response.status_code, 200)
        requests = response.context["requests"]
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].id, self.req_b.id)

    def test_dashboard_ignores_invalid_date_filters(self):
        response = self.client.get(
            reverse("assistance_staff:dashboard"),
            {"queue": "all", "start_date": "not-a-date", "end_date": "2026-13-99"},
        )

        self.assertEqual(response.status_code, 200)
        requests = response.context["requests"]
        request_ids = {req.id for req in requests}
        self.assertSetEqual(request_ids, {self.req_a.id, self.req_b.id})
        self.assertEqual(response.context["filters"]["start_date"], "")
        self.assertEqual(response.context["filters"]["end_date"], "")
