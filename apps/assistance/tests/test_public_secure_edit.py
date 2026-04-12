import json
import secrets
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse

from apps.assistance.models import (
    AssistanceProgram,
    CitizenProfile,
    CitizenRequest,
    RequestDocument,
)
from apps.assistance.services.document_service import DocumentService
from apps.assistance.services.request_service import RequestSubmissionService

_TEST_MEDIA = tempfile.mkdtemp(prefix="tracepoint_public_tests_")


@override_settings(MEDIA_ROOT=_TEST_MEDIA)
class PublicSecureEditEndpointsTests(TransactionTestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_TEST_MEDIA, ignore_errors=True)

    def setUp(self):
        super().setUp()
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

    def test_upload_ajax_success_shape(self):
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
            status="submitted",
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
