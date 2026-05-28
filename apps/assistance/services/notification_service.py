from __future__ import annotations

from apps.assistance.models import CitizenRequest, RequestDocument
from apps.assistance.services.notifications import (
    NotificationResult,
    dispatch_notification,
    prepare_document_review_notification,
    prepare_status_notification,
)


class NotificationService:
    @staticmethod
    def notify_request_status_change(
        *,
        citizen_request: CitizenRequest,
        status: str | None = None,
    ) -> list[NotificationResult]:
        trigger = prepare_status_notification(
            citizen_request,
            status=status,
        )
        return dispatch_notification(
            trigger,
            citizen_request=citizen_request,
        )

    @staticmethod
    def notify_document_review_result(
        *,
        document: RequestDocument,
    ) -> list[NotificationResult]:
        trigger = prepare_document_review_notification(document)
        return dispatch_notification(
            trigger,
            citizen_request=document.request,
        )
