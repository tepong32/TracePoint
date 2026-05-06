from unittest.mock import patch

from django.core import mail
from django.test import TestCase, override_settings

from apps.assistance.models import AssistanceProgram, RequestTimeline
from apps.assistance.services.lifecycle import RequestStatus
from apps.assistance.services.notifications import (
    NotificationResult,
    dispatch_notification,
    get_enabled_notification_channels,
    get_notification_adapters,
    prepare_status_notification,
)
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
        trigger = prepare_status_notification(
            self.req,
            status=RequestStatus.NEEDS_ATTENTION,
        )

        self.assertIsNotNone(trigger)
        self.assertEqual(trigger.tracking_code, self.req.tracking_code)
        self.assertEqual(trigger.status, RequestStatus.NEEDS_ATTENTION)
        self.assertEqual(trigger.public_status_label, "Action Needed")
        self.assertEqual(trigger.recipient_email, "jane@example.com")
        self.assertEqual(trigger.recipient_phone, "09123456789")
        self.assertTrue(trigger.requires_citizen_action)

    def test_submitted_does_not_prepare_notification(self):
        self.assertIsNone(
            prepare_status_notification(self.req, status=RequestStatus.SUBMITTED)
        )

    def test_default_channels_include_email_and_sms(self):
        self.assertEqual(get_enabled_notification_channels(), ("email", "sms"))
        self.assertEqual(
            [adapter.channel for adapter in get_notification_adapters()],
            ["email", "sms"],
        )

    @override_settings(TRACEPOINT_NOTIFICATION_CHANNELS=("sms", "email", "sms"))
    def test_configured_channels_are_normalized_and_deduplicated(self):
        self.assertEqual(get_enabled_notification_channels(), ("sms", "email"))

    @override_settings(TRACEPOINT_NOTIFICATION_CHANNELS=("unknown", "sms"))
    def test_unknown_channels_are_skipped(self):
        with patch("apps.assistance.services.notifications.logger.warning"):
            self.assertEqual(
                [adapter.channel for adapter in get_notification_adapters()],
                ["sms"],
            )

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="tracepoint@example.test",
        TRACEPOINT_NOTIFICATION_CHANNELS=("email",),
    )
    def test_dispatch_uses_configured_adapters_and_records_timeline(self):
        trigger = prepare_status_notification(
            self.req,
            status=RequestStatus.CLAIMABLE,
        )

        results = dispatch_notification(trigger, citizen_request=self.req)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].channel, "email")
        self.assertEqual(results[0].status, "success")
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(
            RequestTimeline.objects.filter(
                request=self.req,
                event_type="notification",
                message__contains="channel=email",
            ).exists()
        )

    @override_settings(TRACEPOINT_NOTIFICATION_CHANNELS=("email", "sms"))
    def test_dispatch_adapter_failure_is_recorded_without_blocking(self):
        class ExplodingAdapter:
            channel = "email"

            def send(self, trigger):
                raise RuntimeError("adapter unavailable")

        class PassingAdapter:
            channel = "sms"

            def send(self, trigger):
                return NotificationResult("sms", "success", "SMS queued.")

        trigger = prepare_status_notification(
            self.req,
            status=RequestStatus.CLAIMABLE,
        )

        from apps.assistance.services import notifications

        original_adapters = notifications.NOTIFICATION_ADAPTERS
        notifications.NOTIFICATION_ADAPTERS = {
            "email": ExplodingAdapter,
            "sms": PassingAdapter,
        }
        with patch("apps.assistance.services.notifications.logger.exception"):
            try:
                results = dispatch_notification(trigger, citizen_request=self.req)
            finally:
                notifications.NOTIFICATION_ADAPTERS = original_adapters

        self.assertEqual([result.status for result in results], ["error", "success"])
        self.assertTrue(
            RequestTimeline.objects.filter(
                request=self.req,
                event_type="notification",
                message__contains="Notification adapter failed",
            ).exists()
        )
