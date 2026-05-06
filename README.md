# TracePoint

TracePoint is a **GovTech SaaS-ready Django platform** for citizen assistance request workflows.

The MVP is built around a **no-login citizen continuation flow**, allowing applicants to:
- submit assistance requests
- continue through secure edit links
- upload, replace, and remove supporting documents
- track progress using reference codes
- receive best-effort Email/SMS updates

The long-term goal is to evolve TracePoint into a **multi-tenant public service workflow platform for LGUs**, starting with assistance-first use cases.

---

## Current Milestone
**v0.5 - Lifecycle Engine**

### Highlights
- centralized request lifecycle policy and staff workflow services
- role-aware staff queues, transitions, document review, and fulfillment
- citizen progress tracking across submitted, document, review, approval, claim, and closure states
- approval blocked until all required documents are approved
- soft-delete document lifecycle with history preservation
- best-effort Email/SMS notification adapter registry
- audit-friendly timeline entries for status, document, citizen, notification, and workflow events
- focused lifecycle, security, document, notification, and public-flow tests

---

## Current MVP Features
### Citizen
- no-login request submission
- secure continuation links
- request tracking
- document upload, replacement, and soft-delete
- needs-attention recovery loop
- locked request view after approval and fulfillment states

### Staff
- role-aware review dashboard
- request lifecycle transitions
- approval and fulfillment workflow
- request status and remarks updates
- document review with independent document states
- request and document audit timeline
- timeline labels for lifecycle, document, citizen, notification, and workflow events

### Platform
- service-layer architecture
- environment-based upload settings
- soft-delete lifecycle model
- DRF-ready structure
- configurable Email + SMS adapter baseline

---

## Developer Notes
### Public Continuation Security
- `secure_edit_token` is the citizen mutation credential for public upload/delete endpoints.
- The public secure-edit page may render in read-only mode for non-editable states such as `under_review`.
- Public mutation endpoints must authenticate through the token-validation service and return the standard JSON contract on failure.
- Invalid public edit-token attempts are logged centrally for lightweight abuse visibility.

### Request Lifecycle Vocabulary
- Request statuses are centralized in `apps.assistance.services.lifecycle.RequestStatus`.
- Current v0.5 request lifecycle: `submitted`, `awaiting_documents`, `under_review`, `needs_attention`, `approved`, `claimable`, `claimed`, `closed`.
- Do not reintroduce legacy request states such as `pending`, `review`, or `denied` into request-level logic.
- Document review statuses are separate from request statuses and still use values like `pending`, `approved`, `clearer_copy`, and `wrong_file`.

---

## Product Direction
TracePoint is being designed as a **reusable GovTech workflow engine** with:
- service-oriented Django architecture
- audit-friendly lifecycle logging
- future DRF/mobile compatibility
- multi-department expansion
- multi-tenant LGU deployment support

---

## Roadmap
### v0.5 Wrap-Up
- browser smoke test public and staff lifecycle flows
- refine staff UI copy and operational affordances
- prepare branch for review and release notes

### Future Platform Milestones
- DRF public APIs
- department workflow templates
- analytics dashboards
- multi-tenant LGU onboarding
- reusable public service modules

---

## Vision
TracePoint aims to become a **secure, reusable, SaaS-grade citizen service workflow platform** that reduces account friction while preserving auditability and operational control for LGUs.
