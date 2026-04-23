# TracePoint Agent Guide

This guide is for Codex, Gar, and any future collaborator working in
this repo. It reflects what is currently visible in the repository and
defines the non-negotiable system contracts that must not be broken.

------------------------------------------------------------------------

## Project Purpose

TracePoint is a GovTech SaaS-ready Django platform for citizen
assistance request workflows.

Current MVP focus:

-   No-login citizen assistance request submission
-   Secure continuation via `secure_edit_token`
-   Citizen document upload, replacement, soft-delete, and tracking
-   Staff-facing review and audit workflows
-   Future multi-tenant LGU platform direction

Current version observed in `VERSION`: `0.4.1`

------------------------------------------------------------------------

## 🔒 System Contracts (Non-Negotiable)

### Security Contract

-   All staff endpoints MUST require authentication and role/department
    checks
-   Public users MUST NEVER access staff routes or mutate internal data
-   All mutations MUST validate access scope or ownership
-   AJAX endpoints MUST reject non-AJAX requests where applicable
-   Never trust client-provided identifiers without validation

### Request Lifecycle Contract

Valid statuses (v0.5 lifecycle model): - submitted -
awaiting_documents - under_review - needs_attention - approved -
claimable - claimed - closed

Rules: - Requests MUST start at `submitted` - Status progression MUST
follow defined lifecycle flow - Status regression is NOT allowed -
Approved, claimable, claimed, and closed requests are LOCKED - Locked
requests MUST block document uploads and edits - Lifecycle logic MUST be
centralized in services, not duplicated in views

### Document Review Contract

Each RequestDocument has an independent review state: - pending -
approved - clearer_copy - wrong_file - incomplete - missing_stamp -
expired

Rules: - Only ONE active document per `(request, document_type)` -
Re-upload replaces the existing document - Soft-delete hides document
but preserves storage - Re-upload after soft-delete revives the document
entry - Locked requests MUST block document changes

### Audit Logging Contract

-   Request updates MUST create RequestTimeline entries
-   Document updates MUST create timeline/log entries
-   Logs MUST include previous value, new value, actor, timestamp
-   No silent mutations allowed

### Data Integrity Contract

-   Duplicate active requests MUST NOT be allowed
-   Respect all model constraints
-   Reuse validation from forms/models

### Response Contract

AJAX responses MUST follow: { "status": "success \| error \| danger",
"message": "..." }

### Rules:

-   Do NOT introduce alternative response formats (e.g., {success: true})
-   Errors MUST be explicit and meaningful
-   All edge cases MUST be handled (missing data, invalid input, locked state)

### Stack

Python: 3.13.2
Django: 6.0.4
Database: SQLite (local dev)
Settings: split (base.py, dev.py, prod.py)
Rich text: django-ckeditor-5
DRF installed but not yet active
Notifications app scaffolded

### Repository Layout

manage.py: entrypoint (dev/prod switch via DJANGO_ENV)
src/: project config
apps/assistance/: core domain app
apps/notifications/: future notification adapters
services/: REQUIRED location for business logic
views/public.py: citizen flows
views/staff.py: staff workflows (must remain protected)
urls/public.py, urls/staff.py, urls/ajax.py: route separation

### Architecture Conventions

-   Business logic MUST live in services/
-   Views orchestrate only (no heavy logic)
-   Lifecycle rules MUST NOT be duplicated across views
-   Preserve auditability via timeline/logging
-   Citizen flows remain no-login + token-based
-   Respect document lifecycle semantics:
    -   one active document per type
    -   replacement behavior must remain consistent
    -   locked requests block changes

###     Product Concepts

Core models:
-   AssistanceProgram
-   CitizenProfile
-   CitizenRequest
-   RequestDocument
-   RequestTimeline

Public routes:

-   /assistance/submit/<program_slug>/
-   /assistance/track/<tracking_code>/
-   /assistance/edit/<secure_edit_token>/
-   /assistance/edit/<secure_edit_token>/upload/ajax/
-   /assistance/edit/<secure_edit_token>/delete-document/

### Safety Notes

-   Never commit .env or secrets
-   Do not delete media without explicit instruction
-   Do not bypass service-layer rules
-   Do not introduce schema or workflow changes without approval
-   Preserve audit and lifecycle integrity at all times

### Collaboration Rules

Codex MUST ask before:
-   Schema changes or migrations
-   Authentication or authorization changes
-   Lifecycle/status modifications
-   Public API/route contract changes
-   Audit/logging behavior changes
Codex MAY act without asking:
-   Service-layer refactors that preserve behavior
-   Adding or improving tests
-   Fixing bugs within existing contracts
-   Documentation improvements
-   Logging enhancements

### Current Milestone (v0.5 Lifecycle Engine)

Target:
-   Full lifecycle orchestration engine
-   Citizen progress tracking UI
-   Needs-attention recovery loop
-   Claimable → claimed fulfillment flow
-   Notification adapter preparation

Key Risks:
-   Status logic duplication outside services
-   Lifecycle inconsistencies across views
-   Unauthorized access to staff endpoints

Notifications:
-   Email + SMS are required baseline channels
-   Must use adapter-based architecture
-   No direct provider coupling in views/models
-   Notifications are best-effort (non-blocking)

Multi-Tenancy (Future):
-   Do NOT introduce tenant logic ad hoc
-   Tenant architecture must be explicitly designed first
-   No premature tenant fields in core models

Staff Workflow:
-   Roles: reviewer, approver, fulfillment officer (expandable)
-   Must support:
    -   queue management
    -   document review
    -   lifecycle transitions
    -   audit visibility
-   Timeline MUST remain append-only

Code Style (Deferred Standardization):
-   Prefer clean, modular Django patterns
-   Avoid duplication across layers
-   Introduce linting/formatting tools only when planned
------------------------------------------------------------------------

## Final Rule

If a change violates ANY contract above, it MUST NOT be implemented
without explicit approval.

This document is the single source of truth for system behavior.
