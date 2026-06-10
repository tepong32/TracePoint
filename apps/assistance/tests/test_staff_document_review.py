import json
import shutil
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TransactionTestCase, override_settings

from apps.assistance.models import AssistanceProgram, RequestDocument, RequestTimeline
from apps.assistance.services.request_service import RequestSubmissionService
from apps.assistance.views.staff import mswd_update_document_ajax

_TEST_MEDIA_ROOT = Path(__file__).resolve().parents[3] / ".test_media"
_TEST_MEDIA_ROOT.mkdir(exist_ok=True)
_TEST_MEDIA = _TEST_MEDIA_ROOT / "staff_document_review"
_TEST_MEDIA.mkdir(exist_ok=True)


@override_settings(MEDIA_ROOT=str(_TEST_MEDIA))
class StaffDocumentReviewTests(TransactionTestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_TEST_MEDIA, ignore_errors=True)

    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()
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
        self.document = RequestDocument.objects.create(
            request=self.req,
            document_type="birth_cert",
            file=SimpleUploadedFile(
                "birth.pdf",
                b"%PDF-1.4 test",
                content_type="application/pdf",
            ),
            status="pending",
            remarks="Original remarks",
        )
        self.User = get_user_model()

    def _post(self, *, user, status="approved", remarks="Reviewed"):
        request = self.factory.post(
            f"/staff/documents/{self.document.id}/update/",
            data={"status": status, "remarks": remarks},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        request.user = user
        return mswd_update_document_ajax(request, self.document.id)

    def _staff_reviewer(self):
        user = self.User.objects.create_user(
            username="reviewer",
            password="password",
            is_staff=True,
        )
        group = Group.objects.create(name="Document Reviewers")
        user.groups.add(group)
        return user

    def test_unauthenticated_access_redirects_to_login(self):
        from django.contrib.auth.models import AnonymousUser

        response = self._post(user=AnonymousUser())

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_unauthorized_staff_access_returns_ajax_danger(self):
        user = self.User.objects.create_user(
            username="staff-no-role",
            password="password",
            is_staff=True,
        )

        response = self._post(user=user)
        data = json.loads(response.content.decode())

        self.assertEqual(response.status_code, 403)
        self.assertEqual(data["status"], "danger")
        self.assertIn("permission", data["message"].lower())

    def test_successful_update_changes_document_and_returns_success(self):
        response = self._post(
            user=self._staff_reviewer(),
            status="approved",
            remarks="Valid document.",
        )
        data = json.loads(response.content.decode())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["status"], "success")
        self.document.refresh_from_db()
        self.assertEqual(self.document.status, "approved")
        self.assertEqual(self.document.remarks, "Valid document.")

    def test_invalid_status_is_rejected_server_side(self):
        response = self._post(
            user=self._staff_reviewer(),
            status="arbitrary-posted-value",
            remarks="Should not save.",
        )
        data = json.loads(response.content.decode())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["status"], "error")
        self.assertIn("invalid document status", data["message"].lower())
        self.document.refresh_from_db()
        self.assertEqual(self.document.status, "pending")
        self.assertEqual(self.document.remarks, "Original remarks")

    def test_staff_document_update_creates_audit_timeline(self):
        user = self._staff_reviewer()

        self._post(user=user, status="clearer_copy", remarks="Upload a clearer copy.")

        timeline = RequestTimeline.objects.get(
            request=self.req,
            event_type="staff_document_review_updated",
        )
        self.assertEqual(timeline.created_by, user)
        self.assertIn("status_before=pending", timeline.message)
        self.assertIn("status_after=clearer_copy", timeline.message)
        self.assertIn("remarks_before=Original remarks", timeline.message)
        self.assertIn("remarks_after=Upload a clearer copy.", timeline.message)
