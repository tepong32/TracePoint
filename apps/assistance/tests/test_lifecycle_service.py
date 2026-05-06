from django.core import mail
from django.test import TestCase, override_settings

from apps.assistance.models import AssistanceProgram, RequestTimeline
from apps.assistance.services.lifecycle import RequestStatus
from apps.assistance.services.lifecycle_service import (
    LifecycleTransitionError,
    transition_request_status,
)
from apps.assistance.services.request_service import RequestSubmissionService


class LifecycleServiceTests(TestCase):
    def setUp(self):
        self.program = AssistanceProgram.objects.create(
            name="Lifecycle Program",
            slug="lifecycle-program",
            description="desc",
            requirements="req",
        )
        self.request_obj = RequestSubmissionService.submit_request(
            program=self.program,
            full_name="Lina Lifecycle",
            email="lina@example.com",
            phone="09123456789",
        )

    def test_valid_forward_transition_is_logged(self):
        transition_request_status(
            self.request_obj,
            new_status=RequestStatus.AWAITING_DOCUMENTS,
        )

        self.request_obj.refresh_from_db()
        self.assertEqual(self.request_obj.status, RequestStatus.AWAITING_DOCUMENTS)
        self.assertFalse(self.request_obj.is_locked)
        self.assertTrue(
            RequestTimeline.objects.filter(
                request=self.request_obj,
                event_type="status_change",
                message__contains=f"old_status={RequestStatus.SUBMITTED}",
            ).exists()
        )

    def test_invalid_transition_is_rejected(self):
        with self.assertRaises(LifecycleTransitionError):
            transition_request_status(
                self.request_obj,
                new_status=RequestStatus.CLAIMED,
            )

        self.request_obj.refresh_from_db()
        self.assertEqual(self.request_obj.status, RequestStatus.SUBMITTED)

    def test_approved_status_locks_request(self):
        self.request_obj.status = RequestStatus.UNDER_REVIEW
        self.request_obj.save(update_fields=["status", "updated_at"])

        transition_request_status(
            self.request_obj,
            new_status=RequestStatus.APPROVED,
        )

        self.request_obj.refresh_from_db()
        self.assertEqual(self.request_obj.status, RequestStatus.APPROVED)
        self.assertTrue(self.request_obj.is_locked)

    def test_fulfillment_transition_can_advance_locked_lifecycle_status(self):
        self.request_obj.status = RequestStatus.APPROVED
        self.request_obj.is_locked = True
        self.request_obj.save(update_fields=["status", "is_locked", "updated_at"])

        transition_request_status(
            self.request_obj,
            new_status=RequestStatus.CLAIMABLE,
        )

        self.request_obj.refresh_from_db()
        self.assertEqual(self.request_obj.status, RequestStatus.CLAIMABLE)
        self.assertTrue(self.request_obj.is_locked)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="tracepoint@example.test",
    )
    def test_notification_is_dispatched_for_claimable_transition(self):
        self.request_obj.status = RequestStatus.APPROVED
        self.request_obj.is_locked = True
        self.request_obj.save(update_fields=["status", "is_locked", "updated_at"])

        transition_request_status(
            self.request_obj,
            new_status=RequestStatus.CLAIMABLE,
        )

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.request_obj.tracking_code, mail.outbox[0].subject)
        self.assertTrue(
            RequestTimeline.objects.filter(
                request=self.request_obj,
                event_type="notification",
                message__contains="channel=email",
            ).exists()
        )
        self.assertTrue(
            RequestTimeline.objects.filter(
                request=self.request_obj,
                event_type="notification",
                message__contains="channel=sms",
            ).exists()
        )
