# Changelog
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
