from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.assistance.models import AssistanceProgram, RequestDocument, RequestTimeline
from apps.assistance.services.request_service import RequestSubmissionService
from apps.assistance.services.staff_workflow_service import (
    StaffWorkflowError,
    apply_staff_queue_metadata,
    build_staff_request_detail_context,
    review_document_by_staff,
    timeline_display_items,
    transition_options_for_request,
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

        self.fulfillment = user_model.objects.create_user(
            username="workflow-fulfillment",
            password="pass-12345",
            is_staff=True,
        )
        self.fulfillment.groups.add(Group.objects.get(name="assistance_fulfillment"))

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

    def test_approval_requires_all_required_documents_approved(self):
        self.request_obj.status = "under_review"
        self.request_obj.save(update_fields=["status", "updated_at"])
        self._document(document_type="birth_cert", status="approved")

        with self.assertRaises(StaffWorkflowError):
            update_request_by_staff(
                request_obj=self.request_obj,
                user=self.approver,
                new_status="approved",
            )

        self.request_obj.refresh_from_db()
        self.assertEqual(self.request_obj.status, "under_review")

    def test_transition_options_explain_blocked_approval(self):
        self.request_obj.status = "under_review"
        self.request_obj.save(update_fields=["status", "updated_at"])

        options = transition_options_for_request(self.approver, self.request_obj)
        approved_option = next(option for option in options if option["value"] == "approved")

        self.assertTrue(approved_option["disabled"])
        self.assertIn("required documents", approved_option["reason"])

    def test_approver_can_approve_when_required_documents_are_approved(self):
        self.request_obj.status = "under_review"
        self.request_obj.save(update_fields=["status", "updated_at"])
        self._document(document_type="birth_cert", status="approved")
        self._document(document_type="indigency", status="approved")
        self._document(document_type="school_id", status="approved")

        update_request_by_staff(
            request_obj=self.request_obj,
            user=self.approver,
            new_status="approved",
        )

        self.request_obj.refresh_from_db()
        self.assertEqual(self.request_obj.status, "approved")
        self.assertTrue(self.request_obj.is_locked)

    def test_fulfillment_role_advances_locked_claim_lifecycle(self):
        self.request_obj.status = "approved"
        self.request_obj.is_locked = True
        self.request_obj.save(update_fields=["status", "is_locked", "updated_at"])

        update_request_by_staff(
            request_obj=self.request_obj,
            user=self.fulfillment,
            new_status="claimable",
        )
        self.request_obj.refresh_from_db()
        self.assertEqual(self.request_obj.status, "claimable")
        self.assertTrue(self.request_obj.is_locked)

        update_request_by_staff(
            request_obj=self.request_obj,
            user=self.fulfillment,
            new_status="claimed",
        )
        self.request_obj.refresh_from_db()
        self.assertEqual(self.request_obj.status, "claimed")
        self.assertTrue(self.request_obj.is_locked)

        update_request_by_staff(
            request_obj=self.request_obj,
            user=self.fulfillment,
            new_status="closed",
        )
        self.request_obj.refresh_from_db()
        self.assertEqual(self.request_obj.status, "closed")
        self.assertTrue(self.request_obj.is_locked)

    def test_staff_detail_context_summarizes_required_documents(self):
        self._document(document_type="birth_cert", status="approved")

        context = build_staff_request_detail_context(
            request_obj=self.request_obj,
            user=self.reviewer,
        )

        self.assertFalse(context["document_review_summary"]["is_complete"])
        self.assertIn("indigency", context["document_review_summary"]["missing"])
        self.assertTrue(context["has_needs_attention"])

    def test_queue_metadata_uses_required_document_completeness(self):
        self._document(document_type="birth_cert", status="approved")

        requests = apply_staff_queue_metadata([self.request_obj], self.reviewer)

        self.assertTrue(requests[0].has_missing_documents)
        self.assertFalse(requests[0].has_doc_issues)
        self.assertTrue(requests[0].transition_options)

    def test_timeline_display_items_labels_audit_event_types(self):
        RequestTimeline.objects.create(
            request=self.request_obj,
            event_type="workflow_error",
            message="Something failed.",
        )

        entries = timeline_display_items(self.request_obj.timeline.order_by("-created_at"))

        self.assertEqual(entries[0]["label"], "Workflow Error")
        self.assertEqual(entries[0]["tone"], "danger")
