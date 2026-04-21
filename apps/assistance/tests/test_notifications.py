from django.test import TestCase

from apps.assistance.models import AssistanceProgram
from apps.assistance.services.notifications import prepare_status_notification
from apps.assistance.services.request_service import RequestSubmissionService


class NotificationPrepTests(TestCase):
    def setUp(self):
        self.program = AssistanceProgram.objects.create(
            name="Test Program",
            slug="test-program",
            description="d",
            requirements="r",
        )
        self.req = RequestSubmissionService.submit_request(
            program=self.program,
            full_name="Jane Citizen",
            email="jane@example.com",
            phone="09123456789",
        )

    def test_needs_attention_prepares_citizen_action_notification(self):
        trigger = prepare_status_notification(self.req, status="needs_attention")

        self.assertIsNotNone(trigger)
        self.assertEqual(trigger.tracking_code, self.req.tracking_code)
        self.assertEqual(trigger.status, "needs_attention")
        self.assertEqual(trigger.public_status_label, "Action Needed")
        self.assertEqual(trigger.recipient_email, "jane@example.com")
        self.assertEqual(trigger.recipient_phone, "09123456789")
        self.assertTrue(trigger.requires_citizen_action)

    def test_submitted_does_not_prepare_notification(self):
        self.assertIsNone(prepare_status_notification(self.req, status="submitted"))
