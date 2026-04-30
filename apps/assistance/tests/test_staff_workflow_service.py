from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.assistance.models import AssistanceProgram, RequestDocument, RequestTimeline
from apps.assistance.services.request_service import RequestSubmissionService
from apps.assistance.services.staff_workflow_service import (
    StaffWorkflowError,
    review_document_by_staff,
    update_request_by_staff,
)


class StaffWorkflowServiceTests(TestCase):
    def setUp(self):
        self.program = AssistanceProgram.objects.create(
            name="Staff Workflow Program",
            slug="staff-workflow-program",
            description="desc",
            requirements="req",
        )
        self.request_obj = RequestSubmissionService.submit_request(
            program=self.program,
            full_name="Willa Workflow",
            email="willa@example.com",
            phone="09123456789",
        )

        user_model = get_user_model()
        self.reviewer = user_model.objects.create_user(
            username="workflow-reviewer",
            password="pass-12345",
            is_staff=True,
        )
        self.reviewer.groups.add(Group.objects.get(name="assistance_reviewer"))

        self.approver = user_model.objects.create_user(
            username="workflow-approver",
            password="pass-12345",
            is_staff=True,
        )
        self.approver.groups.add(Group.objects.get(name="assistance_approver"))

    def _pdf(self, name: str) -> SimpleUploadedFile:
        return SimpleUploadedFile(name, b"%PDF-1.4 test", content_type="application/pdf")

    def _document(self, *, document_type: str, status: str) -> RequestDocument:
        return RequestDocument.objects.create(
            request=self.request_obj,
            document_type=document_type,
            file=self._pdf(f"{document_type}.pdf"),
            status=status,
        )

    def test_reviewer_document_issue_moves_request_to_needs_attention(self):
        self.request_obj.status = "under_review"
        self.request_obj.save(update_fields=["status", "updated_at"])
        self._document(document_type="birth_cert", status="approved")
        self._document(document_type="indigency", status="approved")
        doc = self._document(document_type="school_id", status="pending")

        changed = review_document_by_staff(
            document=doc,
            user=self.reviewer,
            new_status="clearer_copy",
            remarks="Photo is blurry.",
        )

        self.assertTrue(changed)
        self.request_obj.refresh_from_db()
        self.assertEqual(self.request_obj.status, "needs_attention")
        self.assertTrue(
            RequestTimeline.objects.filter(
                request=self.request_obj,
                event_type="staff_update",
                message__contains="old_status=pending; new_status=clearer_copy",
                created_by=self.reviewer,
            ).exists()
        )

    def test_reviewer_approving_last_required_document_moves_request_to_under_review(self):
        self.request_obj.status = "awaiting_documents"
        self.request_obj.save(update_fields=["status", "updated_at"])
        self._document(document_type="birth_cert", status="approved")
        self._document(document_type="indigency", status="approved")
        doc = self._document(document_type="school_id", status="pending")

        review_document_by_staff(
            document=doc,
            user=self.reviewer,
            new_status="approved",
        )

        self.request_obj.refresh_from_db()
        self.assertEqual(self.request_obj.status, "under_review")

    def test_approver_cannot_review_documents(self):
        doc = self._document(document_type="birth_cert", status="pending")

        with self.assertRaises(StaffWorkflowError):
            review_document_by_staff(
                document=doc,
                user=self.approver,
                new_status="approved",
            )

    def test_request_remarks_audit_records_old_and_new_values(self):
        self.request_obj.status = "under_review"
        self.request_obj.remarks = "Initial note"
        self.request_obj.save(update_fields=["status", "remarks", "updated_at"])

        changed = update_request_by_staff(
            request_obj=self.request_obj,
            user=self.approver,
            remarks="Updated note",
        )

        self.assertTrue(changed)
        self.assertTrue(
            RequestTimeline.objects.filter(
                request=self.request_obj,
                event_type="staff_update",
                message__contains="old_remarks=Initial note",
            )
            .filter(message__contains="new_remarks=Updated note")
            .exists()
        )

    def test_request_status_audit_records_staff_actor(self):
        update_request_by_staff(
            request_obj=self.request_obj,
            user=self.reviewer,
            new_status="under_review",
        )

        self.assertTrue(
            RequestTimeline.objects.filter(
                request=self.request_obj,
                event_type="status_change",
                message__contains="old_status=submitted",
                created_by=self.reviewer,
            ).exists()
        )
