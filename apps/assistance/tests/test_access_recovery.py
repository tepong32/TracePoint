import secrets
from unittest.mock import patch

from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.assistance.models import (
    AssistanceProgram,
    CitizenProfile,
    CitizenRequest,
    RequestTimeline,
)
from apps.assistance.services.access_recovery_service import (
    GENERIC_RECOVERY_MESSAGE,
)
from apps.assistance.services.lifecycle import RequestStatus


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="tracepoint@example.test",
    TRACEPOINT_RECOVERY_WINDOW_SECONDS=900,
    TRACEPOINT_RECOVERY_EMAIL_LIMIT=3,
    TRACEPOINT_RECOVERY_IP_LIMIT=10,
)
class PublicAccessRecoveryTests(TestCase):
    def setUp(self):
        cache.clear()
        self.program = AssistanceProgram.objects.create(
            name="Recovery Program",
            slug="recovery-program",
            description="desc",
            requirements="req",
        )
        self.recovery_url = reverse("assistance:recover_access")

    def _request(self, *, email: str, active: bool = True, name: str = "Citizen"):
        citizen = CitizenProfile.objects.create(
            full_name=name,
            email=email,
            phone=f"09{secrets.randbelow(10**9):09d}",
        )
        return CitizenRequest.objects.create(
            tracking_code=f"TP-R-{secrets.token_hex(5)}",
            secure_edit_token=secrets.token_urlsafe(32),
            program=self.program,
            full_name=name,
            email=email,
            phone=citizen.phone,
            citizen=citizen,
            status=RequestStatus.SUBMITTED,
            is_active=active,
        )

    def test_recovery_page_renders_and_home_links_to_it(self):
        response = self.client.get(self.recovery_url)
        home_response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Recover request access")
        self.assertContains(home_response, self.recovery_url)

    def test_one_digest_contains_all_active_requests(self):
        first = self._request(email="citizen@example.com", name="First")
        second = self._request(email="citizen@example.com", name="Second")

        response = self.client.post(
            self.recovery_url,
            {"email": "citizen@example.com"},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, GENERIC_RECOVERY_MESSAGE)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0].body
        for request_obj in (first, second):
            self.assertIn(request_obj.tracking_code, message)
            self.assertIn(request_obj.secure_edit_token, message)
            self.assertIn(
                reverse(
                    "assistance:track_request",
                    kwargs={"tracking_code": request_obj.tracking_code},
                ),
                message,
            )
            self.assertIn(
                reverse(
                    "assistance:secure_edit",
                    kwargs={"secure_edit_token": request_obj.secure_edit_token},
                ),
                message,
            )

    def test_lookup_is_case_insensitive_and_excludes_inactive_requests(self):
        active = self._request(email="MixedCase@Example.com")
        inactive = self._request(email="mixedcase@example.com", active=False)

        self.client.post(
            self.recovery_url,
            {"email": "MIXEDCASE@example.COM"},
        )

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(active.tracking_code, mail.outbox[0].body)
        self.assertNotIn(inactive.tracking_code, mail.outbox[0].body)

    def test_known_and_unknown_email_receive_same_public_confirmation(self):
        request_obj = self._request(email="known@example.com")

        known_response = self.client.post(
            self.recovery_url,
            {"email": "known@example.com"},
            follow=True,
        )
        unknown_response = self.client.post(
            self.recovery_url,
            {"email": "unknown@example.com"},
            follow=True,
        )

        for response in (known_response, unknown_response):
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, GENERIC_RECOVERY_MESSAGE)
            self.assertNotContains(response, request_obj.tracking_code)
            self.assertNotContains(response, request_obj.secure_edit_token)

    @override_settings(TRACEPOINT_RECOVERY_EMAIL_LIMIT=1)
    def test_email_throttle_suppresses_repeat_delivery(self):
        self._request(email="limited@example.com")

        self.client.post(self.recovery_url, {"email": "limited@example.com"})
        response = self.client.post(
            self.recovery_url,
            {"email": "limited@example.com"},
            follow=True,
        )

        self.assertEqual(len(mail.outbox), 1)
        self.assertContains(response, GENERIC_RECOVERY_MESSAGE)

    @override_settings(
        TRACEPOINT_RECOVERY_EMAIL_LIMIT=10,
        TRACEPOINT_RECOVERY_IP_LIMIT=1,
    )
    def test_ip_throttle_applies_across_email_addresses(self):
        self._request(email="first@example.com")
        self._request(email="second@example.com")

        self.client.post(
            self.recovery_url,
            {"email": "first@example.com"},
            REMOTE_ADDR="203.0.113.10",
        )
        self.client.post(
            self.recovery_url,
            {"email": "second@example.com"},
            REMOTE_ADDR="203.0.113.10",
        )

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("first@example.com", mail.outbox[0].to)

    def test_each_matched_request_gets_secret_free_audit_event(self):
        first = self._request(email="audit@example.com")
        second = self._request(email="audit@example.com")

        self.client.post(self.recovery_url, {"email": "audit@example.com"})

        events = list(
            RequestTimeline.objects.filter(
                request__in=(first, second),
                event_type="access_recovery",
            )
        )
        self.assertEqual(len(events), 2)
        for event in events:
            self.assertIn("channel=email", event.message)
            self.assertIn("status=success", event.message)
            self.assertNotIn("audit@example.com", event.message)
            self.assertNotIn(first.secure_edit_token, event.message)
            self.assertNotIn(second.secure_edit_token, event.message)

    def test_email_failure_is_non_blocking_and_audited(self):
        request_obj = self._request(email="failure@example.com")

        with patch(
            "apps.assistance.services.notifications.EmailNotificationAdapter.send",
            side_effect=RuntimeError("mail unavailable"),
        ), patch("apps.assistance.services.notifications.logger.exception"):
            response = self.client.post(
                self.recovery_url,
                {"email": "failure@example.com"},
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, GENERIC_RECOVERY_MESSAGE)
        event = RequestTimeline.objects.get(
            request=request_obj,
            event_type="access_recovery",
        )
        self.assertIn("status=error", event.message)
        self.assertNotIn("mail unavailable", event.message)

    def test_cache_keys_and_security_logs_do_not_contain_email_or_token(self):
        request_obj = self._request(email="private@example.com")

        from apps.assistance.services import access_recovery_service

        with patch(
            "apps.assistance.services.access_recovery_service._increment_attempt",
            wraps=access_recovery_service._increment_attempt,
        ) as increment_mock, patch(
            "apps.assistance.services.access_recovery_service.logger.info"
        ) as info_mock:
            self.client.post(
                self.recovery_url,
                {"email": "unknown-private@example.com"},
                REMOTE_ADDR="203.0.113.11",
            )

        cache_keys = [call.args[0] for call in increment_mock.call_args_list]
        joined_keys = " ".join(cache_keys)
        self.assertNotIn("unknown-private@example.com", joined_keys)
        self.assertNotIn(request_obj.secure_edit_token, joined_keys)

        log_values = " ".join(
            str(value)
            for call in info_mock.call_args_list
            for value in call.args
        )
        self.assertNotIn("unknown-private@example.com", log_values)
        self.assertNotIn(request_obj.secure_edit_token, log_values)
