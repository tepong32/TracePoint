import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client, TestCase
from django.urls import reverse

from apps.assistance.models import AssistanceProgram
from apps.assistance.services.request_service import RequestSubmissionService


class StaffViewSecurityTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.program = AssistanceProgram.objects.create(
            name="Staff Security Program",
            slug="staff-security-program",
            description="desc",
            requirements="req",
        )
        self.request_obj = RequestSubmissionService.submit_request(
            program=self.program,
            full_name="Sam Staffcheck",
            email="sam@example.com",
            phone="09123456789",
        )
        user_model = get_user_model()
        self.regular_user = user_model.objects.create_user(
            username="regular",
            password="pass-12345",
        )
        self.staff_user = user_model.objects.create_user(
            username="staff",
            password="pass-12345",
            is_staff=True,
        )
        self.assistance_group = Group.objects.get(name="assistance_reviewer")
        self.staff_user.groups.add(self.assistance_group)
        self.fulfillment_user = user_model.objects.create_user(
            username="fulfillment",
            password="pass-12345",
            is_staff=True,
        )
        self.fulfillment_user.groups.add(Group.objects.get(name="assistance_fulfillment"))

    def test_staff_flag_without_assistance_role_is_rejected(self):
        user_model = get_user_model()
        staff_without_role = user_model.objects.create_user(
            username="staff-no-role",
            password="pass-12345",
            is_staff=True,
        )
        self.client.force_login(staff_without_role)

        response = self.client.get(reverse("assistance_staff:dashboard"))

        self.assertEqual(response.status_code, 403)

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("assistance_staff:dashboard"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_dashboard_rejects_non_staff_user(self):
        self.client.force_login(self.regular_user)

        response = self.client.get(reverse("assistance_staff:dashboard"))

        self.assertEqual(response.status_code, 403)

    def test_dashboard_allows_staff_user(self):
        self.client.force_login(self.staff_user)

        response = self.client.get(reverse("assistance_staff:dashboard"))

        self.assertEqual(response.status_code, 200)

    def test_staff_ajax_requires_login_with_contract_shape(self):
        response = self.client.post(
            reverse(
                "assistance_staff:request_status_inline",
                kwargs={"request_id": self.request_obj.id},
            ),
            data={"status": "under_review"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 403)
        data = json.loads(response.content.decode())
        self.assertEqual(data["status"], "error")
        self.assertIn("Authentication", data["message"])

    def test_staff_ajax_rejects_non_staff_user_with_contract_shape(self):
        self.client.force_login(self.regular_user)

        response = self.client.post(
            reverse(
                "assistance_staff:request_status_inline",
                kwargs={"request_id": self.request_obj.id},
            ),
            data={"status": "under_review"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 403)
        data = json.loads(response.content.decode())
        self.assertEqual(data["status"], "error")
        self.assertIn("Staff access", data["message"])

    def test_reviewer_cannot_approve_request(self):
        self.client.force_login(self.staff_user)

        response = self.client.post(
            reverse(
                "assistance_staff:request_status_inline",
                kwargs={"request_id": self.request_obj.id},
            ),
            data={"status": "approved"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        data = json.loads(response.content.decode())
        self.assertEqual(data["status"], "error")
        self.assertIn("role", data["message"].lower())

    def test_fulfillment_role_can_mark_approved_request_claimable(self):
        self.request_obj.status = "approved"
        self.request_obj.is_locked = True
        self.request_obj.save(update_fields=["status", "is_locked", "updated_at"])
        self.client.force_login(self.fulfillment_user)

        response = self.client.post(
            reverse(
                "assistance_staff:request_status_inline",
                kwargs={"request_id": self.request_obj.id},
            ),
            data={"status": "claimable"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        data = json.loads(response.content.decode())
        self.assertEqual(data["status"], "success")
        self.request_obj.refresh_from_db()
        self.assertEqual(self.request_obj.status, "claimable")
