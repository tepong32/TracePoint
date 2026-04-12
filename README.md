# TracePoint

TracePoint is a **GovTech SaaS-ready Django platform** for citizen assistance request workflows.

The MVP is built around a **no-login citizen continuation flow**, allowing applicants to:
- submit requests
- continue through secure edit links
- upload and replace documents
- track progress using reference codes
- receive future Email/SMS updates

The long-term goal is to evolve TracePoint into a **multi-tenant public service workflow platform for LGUs**, starting with assistance-first use cases.

---

## 🚀 Current Milestone
**v0.4.1 — Secure Edit + Document Lifecycle Service Layer**

### Highlights
- secure citizen edit routes via `secure_edit_token`
- service-based upload / replace / delete flow
- soft-delete document lifecycle with history preservation
- transaction-safe storage cleanup
- locked read-only citizen continuation page
- public secure-edit endpoint tests
- SaaS-ready service boundaries

---

## ✨ Current MVP Features
### Citizen
- no-login request submission
- secure continuation links
- request tracking
- document upload / replace / delete
- locked request view after approval

### Staff
- MSWD review dashboard
- request status + remarks updates
- request and document audit timeline
- printable request pages

### Platform
- service-layer architecture
- environment-based upload settings
- soft-delete lifecycle model
- DRF-ready structure
- future Email + SMS adapter support

---

## 🏗️ Product Direction
TracePoint is being designed as a **reusable GovTech workflow engine** with:
- service-oriented Django architecture
- audit-friendly lifecycle logging
- future DRF/mobile compatibility
- multi-department expansion
- multi-tenant LGU deployment support

---

## 🛣️ Roadmap
### v0.5+
- lifecycle orchestration engine
- claim and fulfillment workflow
- notification adapter layer
- status transition rules

### future platform milestones
- DRF public APIs
- department workflow templates
- analytics dashboards
- multi-tenant LGU onboarding
- reusable public service modules

---

## 📌 Vision
TracePoint aims to become a **secure, reusable, SaaS-grade citizen service workflow platform** that reduces account friction while preserving auditability and operational control for LGUs.
