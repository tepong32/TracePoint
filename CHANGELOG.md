# Changelog
## [Unreleased] - v0.5 Lifecycle Engine wrap-up
### Added
- Centralized staff workflow orchestration for role-aware status transitions, document review, and fulfillment.
- Public lifecycle progress context with required-document visibility across tracking and secure edit pages.
- Staff request detail completeness summary and timeline event labeling.
- Notification adapter registry with configurable Email/SMS channels and best-effort failure logging.
- Tests for approval preconditions, fulfillment transitions, public progress, staff queue metadata, notification dispatch, and workflow error logging.

### Changed
- Staff dashboard flags now use required-document completeness instead of broad active-document checks.
- Approval is blocked until all required documents are approved.
- Public and staff views now delegate more lifecycle decisions to services.

## [0.5.0] - 2026-04-21
### ✨ Added
feat(public-ui): complete citizen request lifecycle with guided UI flow

- Aligned public-facing templates (track_request, secure_edit) for consistent UX
- Added clear step indicators (Step 1–3) and current step visibility
- Standardized status display using public_status_label across views
- Improved document upload experience with instructions and feedback messages
- Added completion feedback when request reaches under_review
- Enhanced document list with status, remarks, and replacement indicators
- Added conditional guidance for needs_attention and editable states
- Preserved AJAX upload/delete logic with improved user feedback
- Ensured end-to-end citizen flow: submit → upload → track → update

This completes the citizen-side lifecycle MVP for TracePoint.

## [0.4.1] - 2026-04-12
### ✨ Added
v0.4.1 patch: secure edit flow completion

- completed citizen secure-edit routes using secure_edit_token
- wired upload and delete endpoints to DocumentService
- added transaction-safe file cleanup after successful DB commit
- preserved legacy AJAX response contracts for frontend stability
- added locked secure-edit citizen template
- expanded public secure-edit endpoint tests
- finalized document lifecycle service adoption for v0.4 milestone

## [0.4.0] - 2026-04-12
### ✨ Added
@
TracePoint document pipeline — service layer and citizen document lifecycle

- Introduced DocumentService (upload/replace, soft-delete) with shared upload validation and RequestTimeline events for future audit/notification adapters.
- Extended RequestDocument with soft-delete fields, replacement tracking, canonical document types, and a partial unique constraint (one active document per type per request).
- Track page shows active documents and a '(replaced)' marker when replacement_count > 0; admin exposes removal/replacement columns.
- Upload limits configurable via TRACEPOINT_UPLOAD_* settings and .env.example.
- Added focused tests for replace storage deletion, soft-delete file retention, re-upload after soft-delete, and locked requests.
@

## [0.3.0] - 2026-04-12
### ✨ Added
First working citizen-facing request submission and tracking flow
- modular service layer added
- auto citizen linking via phone and email
- request timeline auto-created on submission
- public submit and tracking routes wired
- root and CKEditor URL integration fixed
- browser-tested first citizen MVP slice

## [0.2.0] - 2026-04-10
### ✨ Added
- TracePoint MVP data architecture and modular assistance models

## [0.1.1] - 2026-04-10
### ✨ Added
- clean slate baseline --- modular app structure (without code yet)

## [0.1.0] - 2026-04-09
### ✨ Added
- Initialized TracePoint Django project baseline
- Installed and configured Git version manager tooling
- Replicated environment-aware split settings architecture from LGU project
	base.py
	dev.py
	prod.py
- Established apps-based scalable project structure target
- Added initial notifications app skeleton
- Locked MVP notification baseline:
	Email (strict)
	SMS (strict)
- Planned provider-adapter architecture
	email provider
	Android SMS gateway provider
	future provider hot-swap support
- Defined long-term GovTech SaaS-ready modular direction
