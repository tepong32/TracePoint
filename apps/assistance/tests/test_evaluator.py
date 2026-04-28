import shutil
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from apps.assistance.models import AssistanceProgram, RequestDocument
from apps.assistance.services.evaluator import (
    evaluate_request_completeness,
    get_required_documents,
)
from apps.assistance.services.request_service import RequestSubmissionService

_TEST_MEDIA_ROOT = Path(__file__).resolve().parents[3] / ".test_media"
_TEST_MEDIA_ROOT.mkdir(exist_ok=True)
_TEST_MEDIA = _TEST_MEDIA_ROOT / "evaluator"
_TEST_MEDIA.mkdir(exist_ok=True)


@override_settings(MEDIA_ROOT=str(_TEST_MEDIA))
class RequestCompletenessEvaluatorTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_TEST_MEDIA, ignore_errors=True)

    def setUp(self):
        super().setUp()
        self.program = AssistanceProgram.objects.create(
            name="Evaluator Program",
            slug="evaluator-program",
            description="desc",
            requirements="req",
        )
        self.request_obj = RequestSubmissionService.submit_request(
            program=self.program,
            full_name="Jane Citizen",
            email="jane@example.com",
            phone="09123456789",
        )

    def _pdf(self, name: str) -> SimpleUploadedFile:
        return SimpleUploadedFile(name, b"%PDF-1.4 test", content_type="application/pdf")

    def _create_document(self, *, document_type: str, status: str, remarks: str = "") -> None:
        RequestDocument.objects.create(
            request=self.request_obj,
            document_type=document_type,
            file=self._pdf(f"{document_type}.pdf"),
            status=status,
            remarks=remarks,
        )

    def test_empty_request_reports_all_required_as_missing(self):
        result = evaluate_request_completeness(self.request_obj)

        self.assertFalse(result["is_complete"])
        self.assertFalse(result["has_issues"])
        self.assertEqual(result["missing_documents"], get_required_documents(self.request_obj))
        self.assertEqual(result["problematic_documents"], [])

    def test_all_required_approved_marks_request_complete(self):
        for document_type in get_required_documents(self.request_obj):
            self._create_document(document_type=document_type, status="approved")

        result = evaluate_request_completeness(self.request_obj)

        self.assertTrue(result["is_complete"])
        self.assertFalse(result["has_issues"])
        self.assertEqual(result["missing_documents"], [])
        self.assertEqual(result["problematic_documents"], [])

    def test_non_approved_document_is_reported_as_problematic(self):
        self._create_document(document_type="birth_cert", status="approved")
        self._create_document(
            document_type="indigency",
            status="clearer_copy",
            remarks="Please upload a clearer scan.",
        )

        result = evaluate_request_completeness(self.request_obj)

        self.assertFalse(result["is_complete"])
        self.assertTrue(result["has_issues"])
        self.assertEqual(result["missing_documents"], ["school_id"])
        self.assertEqual(
            result["problematic_documents"],
            [
                {
                    "document_type": "indigency",
                    "status": "clearer_copy",
                    "remarks": "Please upload a clearer scan.",
                }
            ],
        )

    def test_unknown_document_type_does_not_satisfy_required_missing_logic(self):
        self._create_document(document_type="others", status="pending")

        result = evaluate_request_completeness(self.request_obj)

        self.assertFalse(result["is_complete"])
        self.assertFalse(result["has_issues"])
        self.assertEqual(result["missing_documents"], get_required_documents(self.request_obj))
        self.assertEqual(
            result["problematic_documents"],
            [{"document_type": "others", "status": "pending", "remarks": ""}],
        )

    def test_extra_non_required_problematic_does_not_block_completion(self):
        for document_type in get_required_documents(self.request_obj):
            self._create_document(document_type=document_type, status="approved")

        self._create_document(document_type="others", status="pending")

        result = evaluate_request_completeness(self.request_obj)

        self.assertTrue(result["is_complete"])
        self.assertFalse(result["has_issues"])
