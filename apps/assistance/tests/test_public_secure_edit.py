import json
import secrets
import shutil
from pathlib import Path
from unittest.mock import patch

from django.core.cache import cache
from django.db.models import Q
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse

from apps.assistance.models import (
    AssistanceProgram,
    CitizenProfile,
    CitizenRequest,
    RequestDocument,
    RequestTimeline,
)
from apps.assistance.services.document_service import DocumentService
from apps.assistance.services.lifecycle import RequestStatus
from apps.assistance.services.request_service import RequestSubmissionService

_TEST_MEDIA_ROOT = Path(__file__).resolve().parents[3] / ".test_media"
_TEST_MEDIA_ROOT.mkdir(exist_ok=True)
_TEST_MEDIA = _TEST_MEDIA_ROOT / "public_secure_edit"
_TEST_MEDIA.mkdir(exist_ok=True)


@override_settings(MEDIA_ROOT=str(_TEST_MEDIA))
class PublicSecureEditEndpointsTests(TransactionTestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_TEST_MEDIA, ignore_errors=True)

    def setUp(self):
        super().setUp()
        cache.clear()
        self.client = Client()
        self.program = AssistanceProgram.objects.create(
            name="Prog",
            slug="prog",
            description="d",
            requirements="r",
        )
        self.req = RequestSubmissionService.submit_request(
            program=self.program,
            full_name="Pat Citizen",
            email="pat@example.com",
            phone="09991234567",
        )

    def _pdf(self, name: str = "x.pdf") -> SimpleUploadedFile:
        return SimpleUploadedFile(name, b"%PDF-1.4 x", content_type="application/pdf")

    def test_secure_edit_get_ok(self):
        url = reverse(
            "assistance:secure_edit",
            kwargs={"secure_edit_token": self.req.secure_edit_token},
        )
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, self.req.tracking_code)

    def test_secure_edit_locked_template(self):
        self.req.is_locked = True
        self.req.save(update_fields=["is_locked", "updated_at"])
        url = reverse(
            "assistance:secure_edit",
            kwargs={"secure_edit_token": self.req.secure_edit_token},
        )
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "locked")

    def test_needs_attention_reopens_secure_edit_when_locked(self):
        self.req.status = RequestStatus.NEEDS_ATTENTION
        self.req.save(update_fields=["status", "updated_at"])
        url = reverse(
            "assistance:secure_edit",
            kwargs={"secure_edit_token": self.req.secure_edit_token},
        )
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Update your request")
        self.assertNotContains(r, "locked")

    def test_needs_attention_upload_returns_to_awaiting_documents_if_incomplete(self):
        self.req.status = RequestStatus.NEEDS_ATTENTION
        self.req.save(update_fields=["status", "updated_at"])
        url = reverse(
            "assistance:upload_document_ajax",
            kwargs={"secure_edit_token": self.req.secure_edit_token},
        )
        r = self.client.post(
            url,
            data={
                "document_type": "birth_cert",
                "file": self._pdf(),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        data = json.loads(r.content.decode())
        self.assertEqual(data["status"], "success")
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, RequestStatus.AWAITING_DOCUMENTS)
        self.assertTrue(
            RequestTimeline.objects.filter(
                request=self.req,
                event_type="status_change",
            )
            .filter(
                Q(
                    message__contains=(
                        f"old_status={RequestStatus.NEEDS_ATTENTION}"
                    )
                )
                & Q(
                    message__contains=(
                        f"new_status={RequestStatus.AWAITING_DOCUMENTS}"
                    )
                )
            ).exists()
        )

    def test_upload_ajax_success_shape(self):
        self.req.status = RequestStatus.AWAITING_DOCUMENTS
        self.req.save(update_fields=["status", "updated_at"])
        url = reverse(
            "assistance:upload_document_ajax",
            kwargs={"secure_edit_token": self.req.secure_edit_token},
        )
        r = self.client.post(
            url,
            data={
                "document_type": "birth_cert",
                "file": self._pdf(),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content.decode())
        self.assertEqual(data["status"], "success")
        self.assertIn("message", data)
        self.assertTrue(
            RequestDocument.objects.filter(
                request=self.req, document_type="birth_cert", is_removed=False
            ).exists()
        )
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, RequestStatus.AWAITING_DOCUMENTS)

    def test_upload_ajax_locked(self):
        self.req.is_locked = True
        self.req.save(update_fields=["is_locked", "updated_at"])
        url = reverse(
            "assistance:upload_document_ajax",
            kwargs={"secure_edit_token": self.req.secure_edit_token},
        )
        r = self.client.post(
            url,
            data={"document_type": "others", "file": self._pdf()},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        data = json.loads(r.content.decode())
        self.assertEqual(data["status"], "error")
        self.assertIn("locked", data["message"].lower())
        self.assertEqual(r.status_code, 403)

    def test_upload_ajax_invalid_edit_code_returns_403_and_logs_attempt(self):
        url = reverse(
            "assistance:upload_document_ajax",
            kwargs={"secure_edit_token": "bad-token"},
        )
        with patch(
            "apps.assistance.services.public_access_service.logger.warning"
        ) as warning_mock:
            r = self.client.post(
                url,
                data={"document_type": "others", "file": self._pdf()},
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
                REMOTE_ADDR="203.0.113.10",
            )

        data = json.loads(r.content.decode())
        self.assertEqual(r.status_code, 403)
        self.assertEqual(data["status"], "error")
        self.assertEqual(data["message"], "Invalid edit code.")
        warning_mock.assert_called_once()

    def test_upload_ajax_requires_xhr_header(self):
        url = reverse(
            "assistance:upload_document_ajax",
            kwargs={"secure_edit_token": self.req.secure_edit_token},
        )
        r = self.client.post(
            url,
            data={"document_type": "others", "file": self._pdf()},
        )
        data = json.loads(r.content.decode())
        self.assertEqual(data["status"], "error")

    def test_upload_auto_transition_failure_is_logged_without_breaking_response(self):
        self.req.status = RequestStatus.AWAITING_DOCUMENTS
        self.req.save(update_fields=["status", "updated_at"])
        url = reverse(
            "assistance:upload_document_ajax",
            kwargs={"secure_edit_token": self.req.secure_edit_token},
        )

        with patch(
            "apps.assistance.services.document_service.apply_auto_status_transition",
            side_effect=RuntimeError("boom"),
        ), patch("apps.assistance.services.document_service.logger.exception"):
            r = self.client.post(
                url,
                data={
                    "document_type": "birth_cert",
                    "file": self._pdf(),
                },
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )

        data = json.loads(r.content.decode())
        self.assertEqual(data["status"], "success")
        self.assertTrue(
            RequestTimeline.objects.filter(
                request=self.req,
                event_type="workflow_error",
                message__contains="Auto status transition failed",
            ).exists()
        )

    def test_delete_ajax_success_shape(self):
        doc = DocumentService.upload_or_replace(
            citizen_request=self.req,
            document_type="school_id",
            uploaded_file=self._pdf(),
        )
        url = reverse(
            "assistance:delete_document",
            kwargs={"secure_edit_token": self.req.secure_edit_token},
        )
        r = self.client.post(
            url,
            data={"doc_id": str(doc.id)},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content.decode())
        self.assertEqual(data["status"], "success")
        self.assertIn("message", data)
        doc.refresh_from_db()
        self.assertTrue(doc.is_removed)

    def test_delete_wrong_doc_returns_error(self):
        other_citizen = CitizenProfile.objects.create(
            full_name="Other",
            email="o@example.com",
            phone="08881234567",
        )
        other = CitizenRequest.objects.create(
            tracking_code=f"TP-x-{secrets.token_hex(4)}",
            secure_edit_token=secrets.token_urlsafe(32),
            program=self.program,
            full_name="Other",
            email="o@example.com",
            phone="08881234567",
            citizen=other_citizen,
            status=RequestStatus.SUBMITTED,
        )
        doc = DocumentService.upload_or_replace(
            citizen_request=other,
            document_type="grade_card",
            uploaded_file=self._pdf(),
        )
        url = reverse(
            "assistance:delete_document",
            kwargs={"secure_edit_token": self.req.secure_edit_token},
        )
        r = self.client.post(
            url,
            data={"doc_id": str(doc.id)},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        data = json.loads(r.content.decode())
        self.assertEqual(data["status"], "error")

    def test_delete_ajax_invalid_edit_code_returns_403_and_logs_attempt(self):
        url = reverse(
            "assistance:delete_document",
            kwargs={"secure_edit_token": "bad-token"},
        )
        with patch(
            "apps.assistance.services.public_access_service.logger.warning"
        ) as warning_mock:
            r = self.client.post(
                url,
                data={"doc_id": "1"},
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
                REMOTE_ADDR="203.0.113.10",
            )

        data = json.loads(r.content.decode())
        self.assertEqual(r.status_code, 403)
        self.assertEqual(data["status"], "error")
        self.assertEqual(data["message"], "Invalid edit code.")
        warning_mock.assert_called_once()
