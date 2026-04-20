"""Request document completeness evaluator utilities.

Pure helper functions only:
- No model writes
- No request status transitions
- No side effects
"""

from __future__ import annotations

from collections import defaultdict

from apps.assistance.models import CitizenRequest

# Temporary MVP mapping. In future iterations this can be driven per program.
REQUIRED_DOCUMENTS: dict[str, list[str]] = {
    "default": [
        "birth_cert",
        "indigency",
        "school_id",
    ]
}


def get_required_documents(request: CitizenRequest) -> list[str]:
    """Return required document types for the given request.

    For MVP all requests use a single fallback ruleset ("default").
    Returns a copy to avoid callers mutating module-level constants.
    """

    _ = request  # Reserved for future program-specific branching.
    return list(REQUIRED_DOCUMENTS.get("default", ()))


def evaluate_request_completeness(request: CitizenRequest) -> dict:
    """Evaluate request document completeness with no side effects.

    Rules:
    - Missing: required doc type has no active document.
    - Problematic: active document status is not "approved".
    - Complete: all required docs exist and are approved.
    - Has issues: any active document is not approved.
    """

    required_documents = get_required_documents(request)

    document_rows = list(
        request.documents.values(
            "document_type",
            "status",
            "remarks",
        )
    )

    # Track which required document types currently exist.
    present_required_document_types: set[str] = set()

    # Keep per-required-type status list so duplicate rows (unexpected edge case)
    # are handled safely without crashing.
    required_statuses: dict[str, list[str]] = defaultdict(list)

    problematic_documents: list[dict] = []

    for row in document_rows:
        document_type = row.get("document_type")
        status = row.get("status")
        if not document_type or not status:
            # Defensive skip: malformed/incomplete rows should not poison
            # completeness calculations.
            continue
        remarks = row.get("remarks") or ""

        if document_type in required_documents:
            present_required_document_types.add(document_type)
            required_statuses[document_type].append(status)

        if status != "approved":
            problematic_documents.append(
                {
                    "document_type": document_type,
                    "status": status,
                    "remarks": remarks,
                }
            )

    missing_documents = [
        doc_type
        for doc_type in required_documents
        if doc_type not in present_required_document_types
    ]

    all_required_approved = all(
        required_statuses.get(doc_type)
        and all(status == "approved" for status in required_statuses[doc_type])
        for doc_type in required_documents
    )

    is_complete = not missing_documents and all_required_approved
    required_problematic = [
        doc
        for doc in problematic_documents
        if doc["document_type"] in required_documents
    ]
    has_issues = bool(required_problematic)

    return {
        "is_complete": is_complete,
        "has_issues": has_issues,
        "missing_documents": missing_documents,
        "problematic_documents": problematic_documents,
    }
