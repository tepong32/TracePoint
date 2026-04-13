import shutil
from pathlib import Path

from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TransactionTestCase, override_settings

from apps.assistance.models import AssistanceProgram, RequestTimeline
from apps.assistance.services.document_service import DocumentService, DocumentServiceError
from apps.assistance.services.request_service import RequestSubmissionService

_TEST_MEDIA_ROOT = Path(__file__).resolve().parents[3] / ".test_media"
_TEST_MEDIA_ROOT.mkdir(exist_ok=True)
_TEST_MEDIA = _TEST_MEDIA_ROOT / "document_service"
_TEST_MEDIA.mkdir(exist_ok=True)


@override_settings(MEDIA_ROOT=str(_TEST_MEDIA))
class DocumentServiceTests(TransactionTestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_TEST_MEDIA, ignore_errors=True)

    def setUp(self):
        super().setUp()
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

    def _pdf(self, name: str, data: bytes = b"%PDF-1.4 test") -> SimpleUploadedFile:
        return SimpleUploadedFile(name, data, content_type="application/pdf")

    def test_first_upload_no_replaced_marker(self):
        doc = DocumentService.upload_or_replace(
            citizen_request=self.req,
            document_type="birth_cert",
            uploaded_file=self._pdf("a.pdf"),
        )
        self.assertEqual(doc.replacement_count, 0)
        self.assertFalse(doc.was_replaced_by_citizen)

    def test_replace_hard_deletes_prior_file_and_increments_count(self):
        doc = DocumentService.upload_or_replace(
            citizen_request=self.req,
            document_type="birth_cert",
            uploaded_file=self._pdf("first.pdf"),
        )
        first_key = doc.file.name
        self.assertTrue(default_storage.exists(first_key))

        doc2 = DocumentService.upload_or_replace(
            citizen_request=self.req,
            document_type="birth_cert",
            uploaded_file=self._pdf("second.pdf"),
        )
        self.assertEqual(doc2.id, doc.id)
        self.assertEqual(doc2.replacement_count, 1)
        self.assertTrue(doc2.was_replaced_by_citizen)
        self.assertFalse(default_storage.exists(first_key))
        self.assertTrue(default_storage.exists(doc2.file.name))

    def test_soft_delete_keeps_file_on_storage(self):
        doc = DocumentService.upload_or_replace(
            citizen_request=self.req,
            document_type="school_id",
            uploaded_file=self._pdf("keep.pdf"),
        )
        path = doc.file.name
        DocumentService.soft_delete_document(
            citizen_request=self.req,
            document_id=doc.id,
        )
        doc.refresh_from_db()
        self.assertTrue(doc.is_removed)
        self.assertTrue(default_storage.exists(path))

    def test_reupload_after_soft_delete_hard_deletes_soft_deleted_file(self):
        doc = DocumentService.upload_or_replace(
            citizen_request=self.req,
            document_type="grade_card",
            uploaded_file=self._pdf("old.pdf"),
        )
        old_path = doc.file.name
        DocumentService.soft_delete_document(
            citizen_request=self.req,
            document_id=doc.id,
        )
        revived = DocumentService.upload_or_replace(
            citizen_request=self.req,
            document_type="grade_card",
            uploaded_file=self._pdf("new.pdf"),
        )
        self.assertEqual(revived.id, doc.id)
        self.assertFalse(revived.is_removed)
        self.assertEqual(revived.replacement_count, 1)
        self.assertFalse(default_storage.exists(old_path))
        self.assertTrue(default_storage.exists(revived.file.name))

    def test_locked_request_blocks_upload(self):
        self.req.is_locked = True
        self.req.save(update_fields=["is_locked", "updated_at"])
        with self.assertRaises(DocumentServiceError):
            DocumentService.upload_or_replace(
                citizen_request=self.req,
                document_type="others",
                uploaded_file=self._pdf("x.pdf"),
            )

    def test_needs_attention_locked_request_accepts_upload_and_returns_to_review(self):
        self.req.status = "needs_attention"
        self.req.is_locked = True
        self.req.save(update_fields=["status", "is_locked", "updated_at"])

        DocumentService.upload_or_replace(
            citizen_request=self.req,
            document_type="others",
            uploaded_file=self._pdf("x.pdf"),
        )

        self.req.refresh_from_db()
        self.assertEqual(self.req.status, "under_review")
        self.assertTrue(self.req.is_locked)
        self.assertTrue(
            RequestTimeline.objects.filter(
                request=self.req,
                event_type="citizen_update_received",
            ).exists()
        )
