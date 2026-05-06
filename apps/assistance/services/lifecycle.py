"""
TracePoint Assistance Lifecycle Service
Source-of-truth workflow policy helpers for citizen requests.
"""

class RequestStatus:
    SUBMITTED = "submitted"
    AWAITING_DOCUMENTS = "awaiting_documents"
    UNDER_REVIEW = "under_review"
    NEEDS_ATTENTION = "needs_attention"
    APPROVED = "approved"
    CLAIMABLE = "claimable"
    CLAIMED = "claimed"
    CLOSED = "closed"


REQUEST_LIFECYCLE = {
    RequestStatus.SUBMITTED: 1,
    RequestStatus.AWAITING_DOCUMENTS: 2,
    RequestStatus.UNDER_REVIEW: 3,
    RequestStatus.NEEDS_ATTENTION: 4,
    RequestStatus.APPROVED: 5,
    RequestStatus.CLAIMABLE: 6,
    RequestStatus.CLAIMED: 7,
    RequestStatus.CLOSED: 8,
}


REQUEST_STATUS_CHOICES = [
    (RequestStatus.SUBMITTED, "Submitted"),
    (RequestStatus.AWAITING_DOCUMENTS, "Awaiting Documents"),
    (RequestStatus.UNDER_REVIEW, "Under Review"),
    (RequestStatus.NEEDS_ATTENTION, "Needs Attention"),
    (RequestStatus.APPROVED, "Approved"),
    (RequestStatus.CLAIMABLE, "Ready to Claim"),
    (RequestStatus.CLAIMED, "Claimed"),
    (RequestStatus.CLOSED, "Closed"),
]


LOCKED_REQUEST_STATUSES = {
    RequestStatus.APPROVED,
    RequestStatus.CLAIMABLE,
    RequestStatus.CLAIMED,
    RequestStatus.CLOSED,
}


REQUEST_TRANSITIONS = {
    RequestStatus.SUBMITTED: {
        RequestStatus.AWAITING_DOCUMENTS,
        RequestStatus.UNDER_REVIEW,
    },
    RequestStatus.AWAITING_DOCUMENTS: {RequestStatus.UNDER_REVIEW},
    RequestStatus.UNDER_REVIEW: {
        RequestStatus.NEEDS_ATTENTION,
        RequestStatus.APPROVED,
    },
    RequestStatus.NEEDS_ATTENTION: {
        RequestStatus.UNDER_REVIEW,
        RequestStatus.AWAITING_DOCUMENTS,
    },
    RequestStatus.APPROVED: {RequestStatus.CLAIMABLE},
    RequestStatus.CLAIMABLE: {RequestStatus.CLAIMED},
    RequestStatus.CLAIMED: {RequestStatus.CLOSED},
    RequestStatus.CLOSED: set(),
}


PUBLIC_STATUS_LABELS = {
    RequestStatus.SUBMITTED: "Personal Info Submitted",
    RequestStatus.AWAITING_DOCUMENTS: "Waiting for Supporting Documents",
    RequestStatus.UNDER_REVIEW: "Under Review",
    RequestStatus.NEEDS_ATTENTION: "Action Needed",
    RequestStatus.APPROVED: "Approved",
    RequestStatus.CLAIMABLE: "Ready to Claim",
    RequestStatus.CLAIMED: "Claimed",
    RequestStatus.CLOSED: "Closed",
}


EDITABLE_PUBLIC_STATES = {
    RequestStatus.SUBMITTED,
    RequestStatus.AWAITING_DOCUMENTS,
    RequestStatus.NEEDS_ATTENTION,
}
# Important: under_review is intentionally excluded. Citizens may still open
# their secure continuation URL during review, but only in a read-only state
# unless staff sends the request back for updates.


NOTIFICATION_TRIGGER_STATES = {
    RequestStatus.NEEDS_ATTENTION,
    RequestStatus.CLAIMABLE,
    RequestStatus.CLOSED,
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


def is_locked_status(status: str) -> bool:
    """
    Approved and later lifecycle states block document changes and edits.
    """
    return status in LOCKED_REQUEST_STATUSES


def can_transition_status(current_status: str, new_status: str) -> bool:
    """
    Return whether a request status transition is permitted by v0.5 policy.
    Same-state updates are allowed as no-op saves by callers.
    """
    if current_status == new_status:
        return True
    return new_status in REQUEST_TRANSITIONS.get(current_status, set())


def get_allowed_next_statuses(current_status: str) -> set[str]:
    """
    Allowed next statuses for staff controls and service validation.
    """
    return set(REQUEST_TRANSITIONS.get(current_status, set()))


def requires_citizen_action(status: str) -> bool:
    """
    True when citizen must revisit and update request details/documents.
    """
    return status == RequestStatus.NEEDS_ATTENTION


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
    if current_status == RequestStatus.NEEDS_ATTENTION:
        return RequestStatus.UNDER_REVIEW
    return current_status
