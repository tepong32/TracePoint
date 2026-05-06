from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.assistance.models import AssistanceProgram, RequestDocument
from apps.assistance.services.lifecycle import RequestStatus
from apps.assistance.services.public_progress_service import build_public_progress_context
from apps.assistance.services.request_service import RequestSubmissionService


class PublicProgressServiceTests(TestCase):
    def setUp(self):
        self.program = AssistanceProgram.objects.create(
            name="Progress Program",
            slug="progress-program",
            description="desc",
            requirements="req",
        )
        self.request_obj = RequestSubmissionService.submit_request(
            program=self.program,
            full_name="Pia Progress",
            email="pia@example.com",
            phone="09123456789",
        )

    def _pdf(self, name: str) -> SimpleUploadedFile:
        return SimpleUploadedFile(name, b"%PDF-1.4 test", content_type="application/pdf")

    def test_submitted_progress_exposes_required_missing_documents(self):
        context = build_public_progress_context(self.request_obj)

        self.assertEqual(context["public_status_label"], "Personal Info Submitted")
        self.assertTrue(context["can_update_documents"])
        self.assertFalse(context["is_document_complete"])
        self.assertEqual(
            [item["type"] for item in context["required_documents"]],
            ["birth_cert", "indigency", "school_id"],
        )
        self.assertTrue(all(item["is_missing"] for item in context["required_documents"]))

    def test_needs_attention_marks_problem_document_for_citizen(self):
        self.request_obj.status = RequestStatus.NEEDS_ATTENTION
        self.request_obj.save(update_fields=["status", "updated_at"])
        RequestDocument.objects.create(
            request=self.request_obj,
            document_type="birth_cert",
            file=self._pdf("birth.pdf"),
            status="clearer_copy",
            remarks="Please upload a clearer copy.",
        )

        context = build_public_progress_context(self.request_obj)
        birth_cert = context["required_documents"][0]

        self.assertEqual(context["action_callout"]["tone"], "warning")
        self.assertTrue(birth_cert["needs_attention"])
        self.assertEqual(birth_cert["status_label"], "Needs Clearer Copy")
        self.assertIn("birth_cert", [doc["document_type"] for doc in context["problematic_documents"]])

    def test_locked_progress_disables_document_updates(self):
        self.request_obj.status = RequestStatus.CLAIMABLE
        self.request_obj.is_locked = True
        self.request_obj.save(update_fields=["status", "is_locked", "updated_at"])

        context = build_public_progress_context(self.request_obj)

        self.assertFalse(context["can_update_documents"])
        self.assertEqual(context["action_callout"]["tone"], "locked")
        self.assertIn(
            (RequestStatus.CLAIMABLE, "current"),
            [(step.key, step.state) for step in context["progress_steps"]],
        )
