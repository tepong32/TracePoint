# TracePoint Agent Guide

This guide is for Codex, Gar, and any future collaborator working in this repo.
It reflects what is currently visible in the repository, plus a short set of
human-context fields for the project owners to fill in.

## Project Purpose

TracePoint is a GovTech SaaS-ready Django platform for citizen assistance
request workflows.

Current MVP focus:

- No-login citizen assistance request submission.
- Secure citizen continuation links using `secure_edit_token`.
- Citizen document upload, replacement, soft-delete, and tracking.
- Staff-facing review/audit concepts for MSWD-style assistance workflows.
- A future multi-tenant LGU workflow platform direction.

Current version observed in `VERSION`: `0.4.1`.

## Stack

- Python: `3.13.2` in the local `env` virtual environment.
- Django: `6.0.4`.
- Database: SQLite via `db.sqlite3` for local development.
- Settings layout: split settings in `src/settings/base.py`, `dev.py`, and `prod.py`.
- Forms/templates: Django templates under app template directories.
- Rich text: `django-ckeditor-5`.
- API readiness: `djangorestframework` is installed, but public DRF APIs do not
  appear to be implemented yet.
- Notifications: `apps.notifications` exists as a skeleton for future work.

## Repository Layout

- `manage.py`: Django management entrypoint. It chooses `src.settings.dev` unless
  `DJANGO_ENV=production`, then uses `src.settings.prod`.
- `src/`: Django project config, root URLs, ASGI/WSGI, settings.
- `apps/assistance/`: Main product app for programs, citizen requests,
  documents, timelines, public views, services, and tests.
- `apps/notifications/`: Placeholder notification app for future Email/SMS
  adapter work.
- `apps/assistance/services/`: Business rule layer. Prefer adding workflow logic
  here rather than burying it in views.
- `apps/assistance/models/models.py`: Current assistance models live here.
  Neighbor files such as `request.py`, `document.py`, and `logs.py` currently
  appear empty, likely reserved for a future model split.
- `apps/assistance/views/public.py`: Current citizen/public request and secure
  edit endpoints live here.
- `apps/assistance/urls/public.py`: Current public assistance routes.
- `apps/assistance/views/ajax.py`, `views/staff.py`, `urls/ajax.py`, and
  `urls/staff.py`: Currently placeholder/empty split points.

## Local Setup

Observed local virtualenv path:

```powershell
.\env\Scripts\Activate.ps1
```

Install dependencies:

```powershell
.\env\Scripts\pip.exe install -r requirements.txt
```

If creating the environment from scratch:

```powershell
python -m venv env
.\env\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Environment file:

- Use `.env` locally.
- `.env.example` currently documents `DJANGO_ENV`, `DJANGO_SECRET_KEY`,
  `DJANGO_ALLOWED_HOSTS`, `TRACEPOINT_UPLOAD_MAX_SIZE_MB`, and
  `TRACEPOINT_UPLOAD_ALLOWED_EXTENSIONS`.
- Do not commit real secrets.

## Common Commands

Run development server:

```powershell
.\env\Scripts\python.exe manage.py runserver
```

Run migrations:

```powershell
.\env\Scripts\python.exe manage.py migrate
```

Create migrations:

```powershell
.\env\Scripts\python.exe manage.py makemigrations
```

Run focused assistance tests:

```powershell
.\env\Scripts\python.exe manage.py test apps.assistance.tests
```

Run all Django tests:

```powershell
.\env\Scripts\python.exe manage.py test
```

Version helper:

```powershell
.\env\Scripts\python.exe version_manager.py --help
```

In Git Bash, the project owner uses this alias from `.bashrc`:

```bash
alias vm="python version_manager.py"
```

When bumping versions, prefer the project workflow through `version_manager.py`
instead of hand-editing `VERSION` and `CHANGELOG.md` separately.

## Current Local Test Note

The command below was verified as the intended focused test entrypoint:

```powershell
.\env\Scripts\python.exe manage.py test apps.assistance.tests
```

On this machine, the current run found 12 tests and failed 7 with
`PermissionError: [WinError 5] Access is denied` while Django tried to create
uploaded-file test directories under `AppData\Local\Temp`. This appears related
to local temp/media permissions or test media-root location, not a syntax or
import failure.

Suggested follow-up for Gar/project owners:

- Decide whether tests should write temporary media inside the repo workspace
  during local Windows runs, for example under `.test_media/`.
- If yes, update the test media fixture pattern so agents can verify document
  upload behavior without depending on OS temp permissions.

## Architecture Conventions

- Keep business rules in services under `apps/assistance/services/`.
- Views should orchestrate requests/responses and call services for workflow
  behavior.
- Preserve auditability by recording important request/document lifecycle events
  in `RequestTimeline`.
- Keep citizen request continuation no-login and token-based unless explicitly
  changing the product direction.
- Preserve the existing AJAX response shape for citizen upload/delete endpoints
  unless the frontend is updated at the same time:
  `{"status": "success"|"error", "message": "..."}`
- For document changes, preserve current semantics unless intentionally
  refactoring:
  - One active document per `(request, document_type)`.
  - Replacing an active document hard-deletes the superseded file after DB commit.
  - Soft-deleting a document hides the row from active lists but keeps the file.
  - Re-uploading after soft-delete revives the row and hard-deletes the old file
    after DB commit.
  - Locked or inactive requests should block document changes.
- Prefer focused tests close to the behavior being changed.

## Product Concepts

Observed models:

- `AssistanceProgram`: program metadata, slug, description, requirements,
  active flag.
- `CitizenProfile`: citizen identity/contact aggregation, request stats, future
  risk classification.
- `CitizenRequest`: tracking code, secure edit token, program, citizen/contact
  fields, status, remarks, summary, lock/active flags.
- `RequestDocument`: typed uploaded document with status, remarks, soft-delete,
  replacement tracking, and active unique constraint.
- `RequestTimeline`: request lifecycle/audit messages with optional actor.

Observed public routes:

- `/assistance/submit/<program_slug>/`
- `/assistance/track/<tracking_code>/`
- `/assistance/edit/<secure_edit_token>/`
- `/assistance/edit/<secure_edit_token>/upload/ajax/`
- `/assistance/edit/<secure_edit_token>/delete-document/`

## Safety Notes

- Do not commit `.env` or real secrets.
- Be careful with `db.sqlite3`; it is present in the repo workspace and may
  contain local development data.
- Do not delete uploaded media or test artifacts unless the task explicitly
  requires cleanup.
- Do not flatten service-layer boundaries into views just because it is quicker.
- Ask before making broad schema or workflow changes that affect audit behavior,
  document retention, tenant boundaries, or citizen identity matching.

## Known Gaps And Fill-Ins

These need you and Gar because they are product/team decisions, not facts Codex
can safely infer from the repo.

### Project Ownership

- Primary product owner: Cristino "tEppy" Agapito Jr.
- Primary engineering owner: Cristino "tEppy" Agapito Jr.
- Gar's role and decision authority: Architecture partner, workflow policy reviewer, service-layer design guidance, and release/milestone advisory
- Codex should ask before: schema migrations, authentication changes, production settings, public route contract changes, workflow status additions/removals, or anything affecting audit retention
- Codex can act without asking on: focused tests, service-layer refactors that preserve behavior, docs updates, timeline logging additions, lifecycle helper extensions, and low-risk Windows test environment fixes

Suggested fill:

- "Ask before schema migrations, auth changes, production settings, or workflow
  status changes."
- "Act without asking on focused tests, small service-layer bug fixes, docs, and
  low-risk refactors that preserve behavior."

### Current Milestone

- Current milestone after `v0.4.1`: v0.5 lifecycle engine branch in active development
- Target outcome for `v0.5`: citizen-facing lifecycle orchestration with progress tracking, action-needed recovery loop, claimable fulfillment path, and notification adapter preparation
- Highest priority feature: document completeness and first-upload auto-transition logic
- Highest risk area: status transition duplication outside lifecycle service

Suggested fill:

- "v0.5: lifecycle orchestration engine, claim/fulfillment workflow,
  notification adapter layer, and status transition rules."

### Domain Rules

- Official list of request statuses: submitted, awaiting_documents, under_review, needs_attention, approved, claimable, claimed, closed
- Which statuses lock citizen editing: approved, claimable, claimed, closed
- Required documents per assistance program: program-specific and must be configurable through `AssistanceProgram` requirements in future iterations
- Whether email or phone is the stronger citizen identifier: phone first, then email fallback (current confirmed service behavior)
- Whether staff can override uploaded document status: yes, with timeline preservation and future staff audit notes
- Retention rule for removed/replaced documents: replaced files are hard-deleted after DB commit; citizen soft-deletes hide rows but preserve storage until superseded

Suggested fill:

- "Submitted requests are editable until a staff-controlled lock/status is set."
- "Phone is currently used before email in `CitizenService`, but product owners
  should confirm if that is correct for real LGU workflows."

### Notifications

- Email provider: adapter-based, provider undecided
- SMS provider: adapter-based, must support self-hosted Android SMS gateway compatibility
- Whether notifications are strict/blocking or best-effort: best-effort with timeline-safe fallback
- Events that should trigger notifications: needs_attention, claimable, closed, and future approval confirmation milestones

Suggested fill:

- "Keep notifications behind provider/adapters; do not call vendor APIs directly
  from views or models."

### Multi-Tenancy

- Target tenant model:
- Whether tenant is subdomain, path, database, or row-level scope:
- Models that must become tenant-scoped:
- Tenant migration priority:

Suggested fill:

- "Do not retrofit tenancy ad hoc. Create an explicit tenant boundary design
  before adding tenant IDs to core models."

### Staff Workflow

- Staff roles: reviewer, approver, release/fulfillment officer, future supervisor/escalation roles
- Staff dashboard expectations: aging queues, action-needed backlog, claimable requests, SLA visibility, and citizen compliance visibility
- Approval/rejection lifecycle: under_review → needs_attention | approved → claimable → claimed → closed
- Printable document requirements: request summary, citizen details, timeline snapshot, and uploaded document listing
- Audit timeline requirements: append-only timeline for citizen, staff, lifecycle, and fulfillment transitions

Suggested fill:

- "Staff workflow should preserve an append-only timeline for important state
  transitions."

### Code Style

- Formatter:
- Linter:
- Type checker:
- Test naming convention:
- Preferred import style:

Suggested fill:

- "Adopt Ruff for lint/format when the project is ready, but do not introduce it
  in the middle of an unrelated feature."

## Collaboration Preference Draft

Unless a task says otherwise:

- Make small, reviewable changes.
- Preserve existing service boundaries and public response contracts.
- Add or update tests for behavior changes.
- Report test commands and results, including local environment failures.
- Avoid large rewrites without first naming the tradeoff.
- Leave placeholders only when they are clearly marked and useful to Gar or the
  project owner.
