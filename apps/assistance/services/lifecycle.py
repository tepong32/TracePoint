"""
TracePoint Assistance Lifecycle Service
Source-of-truth workflow policy helpers for citizen requests.
"""

REQUEST_LIFECYCLE = {
    "submitted": 1,
    "awaiting_documents": 2,
    "under_review": 3,
    "needs_attention": 4,
    "approved": 5,
    "claimable": 6,
    "claimed": 7,
    "closed": 8,
}


PUBLIC_STATUS_LABELS = {
    "submitted": "Personal Info Submitted",
    "awaiting_documents": "Waiting for Supporting Documents",
    "under_review": "Under Review",
    "needs_attention": "Action Needed",
    "approved": "Approved",
    "claimable": "Ready to Claim",
    "claimed": "Claimed",
    "closed": "Closed",
}


EDITABLE_PUBLIC_STATES = {
    "submitted",
    "awaiting_documents",
    "needs_attention",
}


NOTIFICATION_TRIGGER_STATES = {
    "needs_attention",
    "claimable",
    "closed",
}


def get_progress_step(status: str) -> int:
    """
    Return numeric progress index for citizen UI steppers.
    Unknown statuses safely fall back to step 1.
    """
    return REQUEST_LIFECYCLE.get(status, 1)


def get_public_status_label(status: str) -> str:
    """
    Citizen-friendly label for UI, SMS, and email templates.
    """
    return PUBLIC_STATUS_LABELS.get(status, "Request In Progress")


def is_public_editable(status: str) -> bool:
    """
    Whether citizen secure edit links should remain active.
    """
    return status in EDITABLE_PUBLIC_STATES


def requires_citizen_action(status: str) -> bool:
    """
    True when citizen must revisit and update request details/documents.
    """
    return status == "needs_attention"


def should_trigger_notification(status: str) -> bool:
    """
    Future-safe notification hook used by notifications.py.
    """
    return status in NOTIFICATION_TRIGGER_STATES


def next_status_after_citizen_update(current_status: str) -> str:
    """
    Once citizen responds to an action-needed request,
    send it back to staff review automatically.
    """
    if current_status == "needs_attention":
        return "under_review"
    return current_status