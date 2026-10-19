> **Superseded 2026-10-15** by [`poc-conformance-report.md`](poc-conformance-report.md). Several findings below (unmigrated DB, mock pages, missing users router, no FORCE RLS) have since been fixed.

# LEADFLOW POC — COMPREHENSIVE REQUIREMENTS & IMPLEMENTATION AUDIT REPORT

**Audit Date:** October 12, 2026  
**Auditor Roles:** Senior Software Architect, Full-Stack Engineering Auditor, Database Architect, Security Reviewer, QA Engineer, and Technical Project Manager  
**Repository Root:** `c:\Users\Krish Fefar\Desktop\LeadFlow_v1`  
**Development Budget:** ₹0 (Absolute zero-cost local constraint)  

---

## SECTION 1: EXECUTIVE SUMMARY

### 1.1 Overall Project Condition
LeadFlow is architectured as a multi-tenant B2B lead intelligence, scoring, and outreach platform designed to bridge prospect sourcing via Apollo.io and CRM ingestion via HubSpot.

The codebase exhibits a **well-scaffolded, modern technical foundation**:
- **Backend**: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0 (Async), Alembic, and ARQ background worker. Ruff linting passes with zero errors, and existing unit tests pass cleanly.
- **Frontend**: Next.js 16.4.0 (Turbopack), React 19, TypeScript, and Tailwind CSS. The Next.js production build (`next build`), TypeScript type checking (`tsc --noEmit`), and ESLint pass with zero errors.
- **Infrastructure**: Docker Compose defining PostgreSQL 16, Redis 7, API, Worker, and Next.js containers. Both PostgreSQL (`leadflow_postgres`) and Redis (`leadflow_redis`) containers are actively running and healthy on the host machine.

However, an exhaustive code and runtime audit reveals that **the application is currently a hybrid of partial implementations, UI mockups with hardcoded fallbacks, and unmigrated database infrastructure**:
1. **Unmigrated Live Database**: While an extensive Alembic migration script ([`001_initial_schema.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/alembic/versions/001_initial_schema.py)) exists, the running PostgreSQL instance has **never had migrations executed**. The `public` schema contains only an empty `alembic_version` table (0 rows) and 0 domain tables.
2. **Disconnected Frontend Features**: Key frontend pages rely on mock data or simulated browser delays instead of real API calls. For example, the Scoring Engines page ([`engines/page.tsx`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/web/src/app/(dashboard)/engines/page.tsx#L50-L58)) simulates saving versions using `setTimeout()`; the Client Portal ([`portal/page.tsx`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/web/src/app/(dashboard)/portal/page.tsx)) displays hardcoded static HTML; and the Operator Dashboard ([`dashboard/page.tsx`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/web/src/app/(dashboard)/dashboard/page.tsx#L18-L35)) renders mock metrics and mock active jobs.
3. **Scoring Engine Defects**: 21 of the 22 catalog signals have detection logic, but the 22nd signal (`hiring`) is an **orphan metric** that is never collected by any adapter. Furthermore, the scoring engine uses mismatched status enums (`HIGH`, `MEDIUM`, `LOW`, `DISQUALIFIED`, `UNSCORED`) rather than the required specification bands (`qualified`, `review`, `disqualified`, `null`), and lacks the configurable Ideal Client bonus.
4. **All External Providers Unconfigured**: Except for the internal web crawler, all 8 external provider adapters (`apollo`, `google_pagespeed`, `openrouter`, `hubspot`, `google_places`, `dataforseo`, `resend`, `supermemory`) lack API keys or tokens in the environment. While the system adheres to graceful degradation, external operations cannot execute live without credentials.

### 1.2 Confirmed Working Functionality
- **Health Probes**: `/healthz`, `/livez`, and `/readyz` in [`apps/api/app/main.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/main.py#L58-L82) respond correctly.
- **Provider Status Reporting**: [`apps/api/app/providers/manager.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/providers/manager.py) successfully checks all 9 adapters and honestly flags missing credentials without raising uncaught exceptions.
- **Web Crawler Signal Gathering**: [`apps/api/app/providers/crawler.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/providers/crawler.py) successfully fetches homepage HTML and evaluates 14 technical and marketing heuristics.
- **Normalized Scoring Logic**: [`apps/api/app/scoring/engine.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/scoring/engine.py) correctly computes weighted means over available signals and skips missing (`None`) metrics without zero-penalizing prospect scores.
- **Frontend Compilation & Routing**: Next.js builds clean static pages for all 13 application routes with valid TypeScript definitions and Lucide icon components.
- **Redis & PostgreSQL Connectivity**: Local connections to Dockerized PostgreSQL 16 and Redis 7 are functional and verified via [`test_connectivity.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/test_connectivity.py).

### 1.3 Critical Blockers
1. **Empty Database Schema**: No application tables exist in the running PostgreSQL container. Running the API or executing any database operation against tenant entities causes SQL relation errors (`relation "users" does not exist`).
2. **Missing Super Admin and User Management APIs**: There is no router for `/users` in FastAPI, no invitation flow, and no user-lifecycle management endpoints.
3. **No Frontend Authentication Protection**: Next.js lacks a `middleware.ts` file; navigation items are unauthenticated, tokens are held in insecure `localStorage`, and unauthenticated visitors can view protected routes directly.
4. **Zero-Cost External Provider Block**: External prospect discovery via Apollo, Core Web Vitals via PageSpeed, domain trust via DataForSEO, AI drafting via OpenRouter, and CRM sync via HubSpot are blocked by the ₹0 budget and lack of provider credentials.

### 1.4 Is the POC Runnable?
- **Partially Runnable**: The services can be launched locally (Docker containers for PostgreSQL and Redis are already active, Next.js builds and runs, FastAPI starts up). However, **no authenticated business workflow can execute** until database migrations are applied to the active PostgreSQL database instance.

### 1.5 Has the End-to-End Lead Workflow Been Demonstrated?
- **No**: The full lead workflow (*Apollo search → Crawl/Enrich → 22-signal Score → Human Approval → Contact Reveal → AI Draft → Draft Approval → HubSpot Sync*) has **not been demonstrated end-to-end**. The database has 0 stored leads, external APIs lack credentials, and several frontend interactions remain mockups.

---

## SECTION 2: REQUIREMENTS TRACEABILITY MATRIX

The matrix below maps every requirement from the product specification against the verified workspace implementation.

| Req ID | Specification Requirement | Status | Actual Code Evidence | Verification Performed | Gaps & Defects | Missing Prerequisite | Priority |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **REQ-01** | Multi-tenant B2B Lead Platform between Apollo & HubSpot | **PARTIAL** | [`apollo.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/providers/apollo.py), [`hubspot.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/providers/hubspot.py) | Code inspection & health status check | Adapters scaffolded, but lack credentials; Apollo & HubSpot synchronization never executed end-to-end | Provider credentials (or mock sandbox) | **P1** |
| **REQ-02** | Mandatory provider principle (real adapters, no runtime mocks, skip unconfigured) | **PASS** | [`manager.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/providers/manager.py), [`test_providers.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/test_providers.py) | Verified via `test_providers.py` execution | None in backend adapter layer; adapters honestly report `is_configured=False` | None | **P1** |
| **REQ-03** | `super_admin` Role (Org lifecycle, quotas, provider config, audit logs) | **PARTIAL** | [`admin.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/api/v1/admin.py#L21-L111) | Code inspection of `/admin` router | Missing org suspension/offboarding endpoints; missing user management router; usage metrics endpoint returns hardcoded credit counts | DB migration applied | **P1** |
| **REQ-04** | `super_admin` Context Switch via `X-Org-Context` | **NOT IMPLEMENTED** | [`rbac.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/security/rbac.py#L38-L98) | Grepped entire codebase for `X-Org-Context` (0 occurrences) | Header is neither parsed in FastAPI backend nor sent by Next.js frontend | None | **P2** |
| **REQ-05** | `org_admin` Role (Manage users, engines, searches, approvals, reveals, drafts) | **PARTIAL** | [`leads.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/api/v1/leads.py), [`drafts.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/api/v1/drafts.py), [`contacts.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/api/v1/contacts.py) | Inspected route decorators | User management inside org is missing; operator mode check (`operator_enabled`) is not evaluated | DB migration applied | **P1** |
| **REQ-06** | `client_viewer` Role (Read-only portal, no PII, no unapproved leads, no costs) | **PARTIAL** | [`leads.py:L37-L39`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/api/v1/leads.py#L37-L39), [`portal/page.tsx`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/web/src/app/(dashboard)/portal/page.tsx) | Code review of backend filters & frontend portal | Backend enforces `approved` filter for `client_viewer`, but frontend portal is 100% hardcoded mockup | DB migration applied | **P2** |
| **REQ-07** | Authentication: Email/password login, JWT tokens | **PASS** | [`auth.py:L25-L58`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/api/v1/auth.py#L25-L58) | Verified password hashing and JWT encoding functions | None in core login logic | DB migration applied | **P1** |
| **REQ-08** | Authentication: Role-aware redirect after login | **FAIL** | [`login/page.tsx:L29`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/web/src/app/(auth)/login/page.tsx#L29) | Inspected `handleSubmit` in `login/page.tsx` | Hardcodes `router.push("/dashboard")`; does not inspect role to route `client_viewer` to `/portal` or `super_admin` to `/admin` | None | **P2** |
| **REQ-09** | Forced password change (`must_reset_password=true`) | **NOT IMPLEMENTED** | [`user.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/models/user.py), [`auth.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/api/v1/auth.py) | Inspected `User` model and `auth.py` | `must_reset_password` field does not exist on model; login endpoint does not check or force reset | DB migration update | **P2** |
| **REQ-10** | Password recovery via Resend & Security Questions | **PARTIAL** | [`auth.py:L96-L128`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/api/v1/auth.py#L96-L128), [`resend.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/providers/resend.py) | Code inspection | Forgot password email dispatches token via Resend, but Resend is unconfigured; security questions flow is not implemented | Resend credentials | **P2** |
| **REQ-11** | Token Revocation & Refresh Token Rotation | **FAIL** | [`auth.py:L60-L94`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/api/v1/auth.py#L60-L94) | Inspected refresh endpoint and token handling | No token blacklisting table or Redis cache; old refresh token is not invalidated upon rotation; no `/auth/logout` endpoint | None | **P2** |
| **REQ-12** | Operator Dashboard with Real Metrics & Active Runs | **PARTIAL** | [`dashboard/page.tsx`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/web/src/app/(dashboard)/dashboard/page.tsx) | Inspected dashboard component state | All funnel counts and active ARQ jobs are hardcoded static numbers (`142`, `38`, `14`, mock run) | DB migration applied | **P2** |
| **REQ-13** | Audiences / ICP Management (Brief, OpenRouter filter proposal) | **PARTIAL** | [`audiences.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/api/v1/audiences.py), [`audiences/page.tsx`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/web/src/app/(dashboard)/audiences/page.tsx) | Inspected audience router and page | Create/list exists; OpenRouter filter proposal, document brief upload, and version update endpoints are missing | DB migration applied | **P2** |
| **REQ-14** | Search Creation (Async, returns 202, polls run ID) | **PASS** | [`searches.py:L16-L43`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/api/v1/searches.py#L16-L43), [`searches/new/page.tsx`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/web/src/app/(dashboard)/searches/new/page.tsx) | Code review of HTTP 202 response and `pollRun` loop | Implemented in code; fails at runtime because Redis job dispatch fails when schema is absent | DB migration applied | **P1** |
| **REQ-15** | Search Criteria (OR/AND match, CRM exclusion, Quota check) | **PARTIAL** | [`search_tasks.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/jobs/search_tasks.py), [`search_service.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/services/search_service.py) | Inspected query params parsing | Search takes raw domain list; OR/AND logic and CRM contact exclusion are not implemented; monthly quotas not enforced | None | **P2** |
| **REQ-16** | Lead Pipeline (Filters, approvals, rejections, archiving, bulk ops, export) | **PARTIAL** | [`leads.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/api/v1/leads.py), [`leads/page.tsx`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/web/src/app/(dashboard)/leads/page.tsx) | Inspected pipeline routes and table view | Filtering and approval/rejection implemented; soft archiving, bulk operations, and CSV/JSON exports are completely missing | DB migration applied | **P1** |
| **REQ-17** | Lead Details Screen (Score breakdown, provenance, signal count /22) | **PASS** | [`leads/[id]/page.tsx`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/web/src/app/(dashboard)/leads/[id]/page.tsx), [`SignalBreakdown.tsx`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/web/src/components/SignalBreakdown.tsx) | Inspected page layout and subscore cards | Component handles all 22 signals and displays provider provenance; falls back to mock lead when API fails | DB migration applied | **P1** |
| **REQ-18** | Contact Reveal Gate (Explicit human confirmation, credit spend audit) | **PASS** | [`contacts.py:L15-L51`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/api/v1/contacts.py#L15-L51), [`ContactRevealCard.tsx`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/web/src/components/ContactRevealCard.tsx) | Code review of approval check & audit logging | Credit remaining response is hardcoded placeholder (`credits_remaining=95`); backend gate itself is implemented | DB migration applied | **P1** |
| **REQ-19** | AI Draft Studio (Tone selection, citations, human editing, approval) | **PARTIAL** | [`drafts.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/api/v1/drafts.py), [`DraftEditor.tsx`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/web/src/components/DraftEditor.tsx) | Inspected draft generation & editor UI | Generation, citations, editing, and approval implemented; tone selection (direct/consultative/short) and bulk drafting missing | DB migration applied | **P1** |
| **REQ-20** | HubSpot Sync (After draft approval, idempotent upsert) | **PASS** | [`crm.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/api/v1/crm.py), [`crm_service.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/services/crm_service.py) | Code inspection of approval gates and HubSpot adapter | Enforces `DRAFT_APPROVED` and `LEAD_APPROVED`; HubSpot adapter handles company/contact search and note associations | HubSpot credentials | **P1** |
| **REQ-21** | Scoring Engine Config (22 signals, weights, versioning, AI proposal, rescoring) | **PARTIAL** | [`catalog.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/scoring/catalog.py), [`engines.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/api/v1/engines.py), [`engines/page.tsx`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/web/src/app/(dashboard)/engines/page.tsx) | Code inspection of engine backend & UI | Engine parameters versioned in backend, but frontend uses `setTimeout()` mock save; AI proposal and batch rescoring missing | DB migration applied | **P2** |
| **REQ-22** | Exact 22 Scoring Catalog Keys & Default Weights | **PASS** | [`catalog.py:L14-L39`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/scoring/catalog.py#L14-L39) | Tested via `test_scoring_engine.py` (5/5 tests passed) | All 22 canonical keys and default weights match specification exactly | None | **P1** |
| **REQ-23** | Collector Signal Generation for All 22 Signals | **FAIL** | [`crawler.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/providers/crawler.py), [`pagespeed.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/providers/pagespeed.py), [`places.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/providers/places.py), [`dataforseo.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/providers/dataforseo.py) | Comprehensive symbol search across all providers | The 22nd signal (`hiring`) is an **orphan metric** not emitted by any collector; crawler visits 1 page instead of 8 | None | **P1** |
| **REQ-24** | Score Bands (`review`, `qualified`, `disqualified`, `null`) | **FAIL** | [`constants.py:L23-L28`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/core/constants.py#L23-L28), [`engine.py:L128-L137`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/scoring/engine.py#L128-L137) | Inspected enum definitions | Code uses `HIGH`, `MEDIUM`, `LOW`, `DISQUALIFIED`, `UNSCORED` instead of required `review`, `qualified`, `disqualified`, `null` | None | **P2** |
| **REQ-25** | Configurable Ideal Client Bonus | **NOT IMPLEMENTED** | [`engine.py:L120-L125`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/scoring/engine.py#L120-L125) | Inspected `ScoringEngineCore.evaluate` | No ideal client bonus logic or condition evaluation implemented in engine | None | **P2** |
| **REQ-26** | Redis Enrichment Cache (7 days / 168 hours) | **NOT IMPLEMENTED** | [`enrichment_service.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/services/enrichment_service.py) | Inspected `enrich_lead` method | Enrichment service calls collectors directly without checking or storing results in Redis cache | None | **P2** |
| **REQ-27** | 14 Relational Tables in PostgreSQL 16 | **IMPLEMENTED, UNVERIFIED** | [`001_initial_schema.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/alembic/versions/001_initial_schema.py) | Database inspection (`psql \dt`) | Migration code defines all 14 tables, but migration has not been applied to the live database (0 tables exist) | Execute `alembic upgrade head` | **P0** |
| **REQ-28** | PostgreSQL RLS with `FORCE ROW LEVEL SECURITY` | **PARTIAL** | [`001_initial_schema.py:L568`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/alembic/versions/001_initial_schema.py#L568), [`session.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/db/session.py) | Inspected SQL executed in migration & session factory | Migration executes `ENABLE ROW LEVEL SECURITY`, but omits `FORCE ROW LEVEL SECURITY`; backend connects as table owner `leadflow_admin`, bypassing RLS | Non-owner connection user | **P1** |
| **REQ-29** | Monthly Quotas & LLM Spend Ceilings (Fail closed) | **PARTIAL** | [`search_service.py:L58-L68`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/services/search_service.py#L58-L68) | Inspected Redis failure handling | Redis enqueue error is caught as a warning on `run.error_details` rather than failing closed with HTTP 503 | None | **P1** |
| **REQ-30** | Scalability Target: 1,500 Concurrent Users | **FAIL** | [`run_scalability_test.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/tests/load/run_scalability_test.py), [`k6_scalability.js`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/tests/load/k6_scalability.js) | Inspected test scripts & historical logs | Tests only target `GET /healthz`. At 1,000 VUs error rate reached 16.33%; at 1,500 VUs error rate reached 58.11% with p95 > 18s | Architecture scaling | **P3** |

---

## SECTION 3: FRONTEND AUDIT

The frontend is a **Next.js 16.4.0** application utilizing the App Router, TypeScript, React 19, and Tailwind CSS.

### 3.1 Page-by-Page Audit Summary

| Route | File Path | API Connectivity | Functionality Status | State & Permission Handling |
| :--- | :--- | :--- | :--- | :--- |
| `/` | [`apps/web/src/app/page.tsx`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/web/src/app/page.tsx) | None (Marketing/Landing) | Functional | Static landing page showcasing pipeline architecture and CTAs |
| `/login` | [`apps/web/src/app/(auth)/login/page.tsx`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/web/src/app/(auth)/login/page.tsx) | Real: `POST /api/v1/auth/login` | Functional | Stores tokens in `localStorage`. **Defect**: Hardcodes `router.push('/dashboard')` with no role-based routing |
| `/forgot-password` | [`apps/web/src/app/(auth)/forgot-password/page.tsx`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/web/src/app/(auth)/forgot-password/page.tsx) | Real: `POST /api/v1/auth/forgot-password` | Functional | Sends password recovery request; toggles success card |
| `/dashboard` | [`apps/web/src/app/(dashboard)/dashboard/page.tsx`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/web/src/app/(dashboard)/dashboard/page.tsx) | None (Mocked) | **Mockup** | **Defect**: Funnel statistics (`142`, `38`, `14`, `22`) and active jobs are hardcoded static state |
| `/audiences` | [`apps/web/src/app/(dashboard)/audiences/page.tsx`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/web/src/app/(dashboard)/audiences/page.tsx) | Real: `GET/POST /api/v1/audiences` | Partially Functional | Can fetch and create audiences; falls back to mock audience on error. Missing AI proposal and brief extraction |
| `/searches/new` | [`apps/web/src/app/(dashboard)/searches/new/page.tsx`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/web/src/app/(dashboard)/searches/new/page.tsx) | Real: `POST /api/v1/searches`, `pollRun` | Functional | Submits domain list, polls run progress. Missing audience selector, scoring engine selector, and location filters |
| `/leads` | [`apps/web/src/app/(dashboard)/leads/page.tsx`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/web/src/app/(dashboard)/leads/page.tsx) | Real: `GET /api/v1/leads`, `PATCH approval` | Functional | Table view with status/band filters and approval toggles; falls back to mock leads on error. Missing exports and bulk ops |
| `/leads/[id]` | [`apps/web/src/app/(dashboard)/leads/[id]/page.tsx`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/web/src/app/(dashboard)/leads/[id]/page.tsx) | Real: `GET /leads/{id}`, `POST rescore`, `sync-crm` | Functional | Displays full signal breakdown, contact reveal card, draft editor, and rescore action. Falls back to mock lead on error |
| `/drafts` | [`apps/web/src/app/(dashboard)/drafts/page.tsx`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/web/src/app/(dashboard)/drafts/page.tsx) | None (Mocked) | **Mockup** | **Defect**: Hardcodes a single static draft (`draft-001`). No API call to fetch organization drafts |
| `/engines` | [`apps/web/src/app/(dashboard)/engines/page.tsx`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/web/src/app/(dashboard)/engines/page.tsx) | None (Simulated) | **Mockup** | **Defect**: Sliders update local state, but saving uses `setTimeout()` to increment version number instead of calling API |
| `/portal` | [`apps/web/src/app/(dashboard)/portal/page.tsx`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/web/src/app/(dashboard)/portal/page.tsx) | None (Mocked) | **Mockup** | **Defect**: Completely static presentation of approved leads with zero backend API connectivity |
| `/admin` | [`apps/web/src/app/(admin)/admin/page.tsx`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/web/src/app/(admin)/admin/page.tsx) | Real: `GET /admin/providers` | Partially Functional | Triggers live provider health check; audit logs and organization management UI are hardcoded mockups |

### 3.2 Frontend Architecture and Security Deficiencies
1. **Absence of Route Protection**: There is no Next.js `middleware.ts` in [`apps/web/src`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/web/src). Any user can navigate directly to `/dashboard`, `/admin`, or `/leads` without being redirected to `/login`.
2. **Insecure Token Storage**: Access and refresh tokens are stored in browser `localStorage` ([`api-client.ts:L20-L26`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/web/src/lib/api-client.ts#L20-L26)), violating the specification requirement for secure HTTP-only cookies.
3. **Hardcoded User Profile**: The header ([`Header.tsx:L28-L37`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/web/src/components/Header.tsx#L28-L37)) displays a hardcoded tenant name (`Acme Revenue Corp`) and role (`org_admin`) instead of inspecting decoded JWT claims.
4. **No Role-Aware Navigation**: The sidebar ([`Sidebar.tsx:L19-L28`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/web/src/components/Sidebar.tsx#L19-L28)) renders all navigation links (including `/admin` and `/portal`) to every user regardless of role.

---

## SECTION 4: BACKEND AUDIT

The backend is built with **FastAPI**, **Pydantic v2**, **SQLAlchemy 2.0 (Async)**, and an **ARQ Redis worker**.

### 4.1 Implemented Routers and Endpoints

| Router Path | Prefix | Tag | Registered Endpoints | Implementation Status |
| :--- | :--- | :--- | :--- | :--- |
| [`auth.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/api/v1/auth.py) | `/api/v1/auth` | Authentication | `POST /login`, `POST /refresh`, `POST /forgot-password`, `POST /reset-password` | Complete (Missing `/logout` & token revocation) |
| [`searches.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/api/v1/searches.py) | `/api/v1/searches` | Searches & Discovery | `POST /`, `GET /` | Complete with HTTP 202 semantics |
| [`runs.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/api/v1/runs.py) | `/api/v1/runs` | Job Runs & Polling | `GET /{run_id}` | Complete |
| [`leads.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/api/v1/leads.py) | `/api/v1/leads` | Leads & Pipeline | `GET /`, `GET /{id}`, `PATCH /{id}/approval`, `POST /{id}/rescore` | Complete (Missing bulk ops, archiving, CSV export) |
| [`audiences.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/api/v1/audiences.py) | `/api/v1/audiences` | ICP Audiences | `GET /`, `POST /`, `GET /{id}` | Complete (Missing AI filter proposal endpoint) |
| [`engines.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/api/v1/engines.py) | `/api/v1/engines` | Scoring Engines | `GET /`, `POST /`, `POST /{id}/params` | Complete (Missing AI weight proposals) |
| [`contacts.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/api/v1/contacts.py) | `/api/v1/contacts` | Contacts & Spend Gates | `POST /{id}/reveal` | Complete (Returns hardcoded quota placeholder) |
| [`drafts.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/api/v1/drafts.py) | `/api/v1` | AI Draft Studio | `POST /leads/{id}/drafts`, `GET /leads/{id}/drafts`, `PATCH /drafts/{id}`, `PATCH /drafts/{id}/approval` | Complete |
| [`crm.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/api/v1/crm.py) | `/api/v1` | CRM Synchronization | `POST /leads/{id}/sync-crm`, `GET /leads/{id}/sync-status` | Complete |
| [`admin.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/api/v1/admin.py) | `/api/v1/admin` | Administration & Health | `GET /orgs`, `POST /orgs`, `GET /providers`, `GET /audit-logs`, `GET /usage` | Partial (`/usage` returns hardcoded numbers; missing user management) |

### 4.2 Missing Backend Routes and Models
1. **User Management Router**: The API does not have `/api/v1/users` (no list users, invite user, or deactivate user routes).
2. **Organization Lifecycle Management**: Missing `PATCH /admin/orgs/{id}/suspend`, `reactivate`, `offboard`, or `toggle-operator`.
3. **Data Export**: No `/leads/export/csv` or `/leads/export/json` endpoints exist.
4. **Bulk Operations**: No bulk lead approval, bulk draft generation, or bulk rescoring endpoints exist.
5. **OpenAPI Exposure in Production**: In [`apps/api/app/main.py:L39-L41`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/main.py#L39-L41), `docs_url="/docs"` and `openapi_url="/openapi.json"` are hardcoded without checking `ENVIRONMENT != "production"`.

---

## SECTION 5: DATABASE & INFRASTRUCTURE AUDIT

### 5.1 Relational Schema & Migration Status
The original specification mandates 14 relational tables:
1. `orgs`
2. `users`
3. `audiences`
4. `engines`
5. `engine_params`
6. `searches`
7. `leads`
8. `enrichments`
9. `scores`
10. `contacts`
11. `drafts`
12. `crm_syncs`
13. `runs`
14. `audit_log`

**Alembic Migration Analysis**:
- Migration script [`001_initial_schema.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/alembic/versions/001_initial_schema.py) defines all 14 tables, complete with UUID primary keys, foreign key constraints, JSONB payload fields, indexes, and RLS policy statements.
- **Critical Live Database Finding**: Executing `psql \dt` against the live PostgreSQL 16 container (`leadflow_postgres`) shows only 1 table: `alembic_version`. The table contains **0 rows**.
- **Conclusion**: The migrations have **never been applied** to the running database instance.

### 5.2 Row-Level Security (RLS) Configuration Defect
The migration executes:
```sql
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
CREATE POLICY users_tenant_isolation_policy ON users
FOR ALL USING (
    current_setting('leadflow.is_super_admin', true) = 'true'
    OR org_id = NULLIF(current_setting('leadflow.current_org_id', true), '')::uuid
);
```
**Two Significant Defects Found**:
1. **No `FORCE ROW LEVEL SECURITY`**: When the table owner connects, PostgreSQL by default **bypasses RLS** unless `FORCE ROW LEVEL SECURITY` is set.
2. **Superuser Connection**: In `docker-compose.yml` and `.env`, the backend connects as `leadflow_admin` (the table owner and superuser), completely bypassing RLS. While `init-db.sql` created the restricted `leadflow_app` role, the backend is not configured to use it at runtime.

### 5.3 Redis & Task Queue Infrastructure
- **Redis 7 Container**: Up, healthy, and responds to `PING` with `PONG`.
- **ARQ Worker Settings**: Configured in [`apps/api/app/jobs/worker.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/jobs/worker.py) with `max_jobs=20` and `job_timeout=1800`.
- **Enrichment Cache Missing**: No Redis key-value caching is implemented for crawled domains or PageSpeed results. Every lead enrichment attempts fresh live requests.

---

## SECTION 6: THE 22-SIGNAL SCORING ENGINE AUDIT

The scoring engine catalog is defined in [`catalog.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/scoring/catalog.py) and evaluated in [`engine.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/scoring/engine.py).

### 6.1 Catalog Verification (22 Signals)

| Category | Canonical Key | Expected Weight | Catalog Weight | Provider Collector | Collector Code Verified? |
| :--- | :--- | :---: | :---: | :--- | :---: |
| **Website** | `legacy_platform` | 1.5 | 1.5 | `web_crawler` | ✅ Crawls HTML for WP4, Drupal 7, jQuery 1.x |
| **Website** | `slow_site` | 1.3 | 1.3 | `google_pagespeed` | ✅ Evaluates Lighthouse FCP/LCP & CWV |
| **Website** | `old_design` | 1.0 | 1.0 | `web_crawler` | ✅ Evaluates table layouts, archaic font tags |
| **Website** | `weak_ctas` | 1.0 | 1.0 | `web_crawler` | ✅ Scans hero for high-intent booking phrases |
| **Website** | `not_mobile_friendly` | 0.8 | 0.8 | `google_pagespeed` | ✅ Checks viewport & mobile audit |
| **Website** | `no_ssl` | 1.2 | 1.2 | `web_crawler` | ✅ Tests HTTPS redirects & certificate |
| **Website** | `thin_content` | 0.7 | 0.7 | `web_crawler` | ✅ Evaluates word count (<250 words) |
| **Website** | `no_analytics` | 0.6 | 0.6 | `web_crawler` | ✅ Checks GA4, GTM, Pixel, PostHog scripts |
| **Website** | `accessibility` | 0.6 | 0.6 | `google_pagespeed` | ✅ Reads Lighthouse accessibility audit |
| **Website** | `no_live_chat` | 0.5 | 0.5 | `web_crawler` | ✅ Checks Intercom, Drift, Crisp, HubSpot |
| **Marketing** | `poor_seo` | 1.4 | 1.4 | `dataforseo` | ✅ Queries historical rank overview |
| **Marketing** | `poor_aeo_geo` | 1.0 | 1.0 | `web_crawler` | ✅ Parses JSON-LD Schema.org blocks |
| **Marketing** | `low_domain_trust` | 0.6 | 0.6 | `dataforseo` | ✅ Checks domain authority / backlink ratio |
| **Marketing** | `stale_blog` | 1.1 | 1.1 | `web_crawler` | ✅ Analyzes blog navigation links |
| **Marketing** | `no_press` | 0.7 | 0.7 | `web_crawler` | ✅ Scans for media/press releases |
| **Marketing** | `no_case_studies` | 0.8 | 0.8 | `web_crawler` | ✅ Scans for case studies / testimonials |
| **Marketing** | `no_video` | 0.5 | 0.5 | `web_crawler` | ✅ Detects YouTube/Vimeo/Wistia embeds |
| **Marketing** | `weak_social` | 0.9 | 0.9 | `web_crawler` | ✅ Checks LinkedIn/Twitter company links |
| **Marketing** | `weak_email_capture` | 0.6 | 0.6 | `web_crawler` | ✅ Checks email input / newsletter forms |
| **Marketing** | `ppc_spend` | 1.2 | 1.2 | `dataforseo` | ✅ Checks paid ad spend proxy |
| **Marketing** | `hiring` | 1.1 | 1.1 | None (Missing) | ❌ **DEFECT**: No collector extracts `hiring` |
| **Marketing** | `low_review_rating` | 0.8 | 0.8 | `google_places` | ✅ Google Places rating < 3.8 stars |

### 6.2 Critical Scoring Defects Identified
1. **The `hiring` Orphan Signal**: Although defined in [`catalog.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/scoring/catalog.py), no collector in [`crawler.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/providers/crawler.py), [`pagespeed.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/providers/pagespeed.py), [`places.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/providers/places.py), or [`dataforseo.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/providers/dataforseo.py) emits the `"hiring"` signal key. As a result, the maximum available signals across any lead is 21 out of 22.
2. **Score Band Enum Mismatch**: The specification mandates bands: `review`, `qualified`, `disqualified`, and `null`. The implementation in [`constants.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/core/constants.py) and [`engine.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/scoring/engine.py#L128-L137) uses `HIGH`, `MEDIUM`, `LOW`, `DISQUALIFIED`, and `UNSCORED`.
3. **No Ideal-Client Bonus**: Section 8 requires: *"Apply a configurable ideal-client bonus when both prospect groups satisfy the configured conditions."* The scoring engine evaluates weighted averages only and contains zero logic for bonus adjustments.

---

## SECTION 7: SECURITY AUDIT

### 7.1 Authentication & Secrets
- **JWT Expiration**: [`config.py:L39`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/core/config.py#L39) sets `ACCESS_TOKEN_EXPIRE_MINUTES = 60`, which violates the specification's 15-minute requirement.
- **Default Production Secret**: [`config.py:L37`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/core/config.py#L37) contains an insecure hardcoded fallback string (`leadflow-insecure-dev-secret-key...`). If not overridden by `.env`, production deployments would use a known secret.
- **Token Storage**: Next.js stores tokens in client-side `localStorage`, leaving them vulnerable to XSS. HTTP-only cookies are not implemented.

### 7.2 Multi-Tenant Isolation
- **Application Context**: FastAPI correctly establishes async ContextVars for tenant isolation via [`set_current_tenant`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/security/tenant.py#L12) and sets `SET LOCAL leadflow.current_org_id` on PostgreSQL sessions.
- **Missing `X-Org-Context`**: Super admins cannot switch organizational context using the specified `X-Org-Context` header.
- **RLS Bypass Risk**: Because the backend connects as the database superuser `leadflow_admin`, PostgreSQL bypasses RLS policies entirely at runtime.

### 7.3 Action & Spend Safety Gates
- **Lead Approval Gate**: **Verified in Code**. [`drafts.py:L28`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/api/v1/drafts.py#L28) and [`crm.py:L26`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/api/v1/crm.py#L26) reject requests with HTTP 400 if the target lead is not approved.
- **Draft Approval Gate**: **Verified in Code**. CRM sync strictly requires `draft.approval_status == 'approved'`.
- **Contact Reveal Gate**: **Verified in Code**. Unmasking contact information requires explicit POST to `/contacts/{id}/reveal`.
- **Spending Quota Defect**: Quotas are not decremented in the database; [`contacts.py:L48`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/api/v1/contacts.py#L48) returns a hardcoded placeholder (`credits_remaining=95`).

---

## SECTION 8: EXTERNAL PROVIDER READINESS

Results from running [`test_providers.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/test_providers.py):

```text
--- Provider Configuration & Health Report ---
[web_crawler]       is_configured: True   is_healthy: True   Internal crawler ready and operating.
[google_pagespeed]  is_configured: False  is_healthy: False  Google PageSpeed API key not configured.
[apollo]            is_configured: False  is_healthy: False  Apollo API key not configured.
[openrouter]        is_configured: False  is_healthy: False  OpenRouter API key not configured.
[hubspot]           is_configured: False  is_healthy: False  HubSpot access token not configured.
[google_places]     is_configured: False  is_healthy: False  Google Places API credentials not configured.
[dataforseo]        is_configured: False  is_healthy: False  DataForSEO credentials not configured.
[resend]            is_configured: False  is_healthy: False  Resend transactional email unconfigured.
[supermemory]       is_configured: False  is_healthy: False  SuperMemory optional provider disabled.
```

### Detailed Adapter Status
1. **Apollo.io** ([`apollo.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/providers/apollo.py)): Implements company search, contact discovery, and credit-gated unmasking (`/people/match`). Unconfigured in `.env`.
2. **OpenRouter** ([`openrouter.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/providers/openrouter.py)): Implements cold draft generation citing technical findings. Missing audience filter proposals and scoring weight proposals. Unconfigured in `.env`.
3. **HubSpot** ([`hubspot.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/providers/hubspot.py)): Implements idempotent company search, contact creation, and engagement note logging. Unconfigured in `.env`.
4. **Google PageSpeed** ([`pagespeed.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/providers/pagespeed.py)): Queries mobile performance, LCP, and accessibility. Unconfigured in `.env`.
5. **Google Places** ([`places.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/providers/places.py)): Gracefully unconfigured; correctly returns `None` for review ratings without raising errors.
6. **DataForSEO** ([`dataforseo.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/providers/dataforseo.py)): Gracefully unconfigured; correctly returns `None` for SEO, backlink, and PPC signals without raising errors.
7. **Resend** ([`resend.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/providers/resend.py)): Implements password reset email delivery. Unconfigured in `.env`.
8. **SuperMemory** ([`supermemory.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/providers/supermemory.py)): Stub implementation only (contains no memory query/storage logic). Disabled in `.env`.
9. **Web Crawler** ([`crawler.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/providers/crawler.py)): Fully functional local crawler. **Defect**: Crawls only the single homepage URL rather than up to 8 pages per domain.

---

## SECTION 9: ZERO-COST COMPLIANCE AUDIT

The project has strictly observed the **₹0 budget constraint**:
- **No Cloud Services Provisioned**: The audit executed entirely on local processes and Docker containers.
- **Zero Paid API Invocations**: No billable requests were sent to Apollo, OpenRouter, HubSpot, DataForSEO, or Google Cloud.
- **Local Tooling Used**: PostgreSQL 16 Alpine, Redis 7 Alpine, pytest, ruff, Next.js build, and local HTTP clients.
- **Honest Absence Reporting**: No mock data was injected into the runtime provider adapters to fake external integrations.

---

## SECTION 10: SCALABILITY AUDIT (1,500 CONCURRENT USERS TARGET)

### 10.1 Review of Existing Load Test Tooling and Scripts
- **Test Scripts**: [`tests/load/k6_scalability.js`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/tests/load/k6_scalability.js) and [`tests/load/run_scalability_test.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/tests/load/run_scalability_test.py).
- **Executable**: [`tools/k6.exe`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/tools/k6.exe) (v0.56.0, 65 MB) is present in the repository.

### 10.2 Analysis of Historical Test Results
Historical benchmark results recorded in [`run_scalability_test.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/tests/load/run_scalability_test.py):

| Virtual Users (VUs) | Target Endpoint | Total Requests | Successful | Failed | Error Rate | Requests/sec | p95 Latency |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **500 VUs** | `GET /healthz` | 1,500 | 1,500 | 0 | **0.0%** | ~280 req/s | 5.3s |
| **1,000 VUs** | `GET /healthz` | 3,000 | 2,510 | 490 | **16.33%** | ~140 req/s | 12.1s |
| **1,500 VUs** | `GET /healthz` | 4,500 | 1,885 | 2,615 | **58.11%** | ~75 req/s | 18.3s |

### 10.3 Scalability Verdict: Target NOT Demonstrated
The additional target of 1,500 simultaneously active users **has NOT been demonstrated**:
1. **Trivial Endpoint Tested**: The test exclusively pounded `GET /healthz`, which returns static in-memory JSON with zero database transactions, no JWT authentication, no Redis queue operations, and no HTML crawling.
2. **High Error Rates at Scale**: Even on the trivial `/healthz` probe, the local system suffered a **16.33% error rate at 1,000 VUs** and a **58.11% error rate at 1,500 VUs**, halting the test run due to connection exhaustion.
3. **Severe Architectural Bottlenecks**:
   - **Database Connection Pool**: [`session.py:L19-L20`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/db/session.py#L19-L20) sets `pool_size=10, max_overflow=20`. A concurrency load of 1,500 users hitting database endpoints would exhaust connections within milliseconds.
   - **Single Worker Process**: The API container runs a single Uvicorn reload process with concurrency limited to 1 worker thread.
   - **Aggressive Frontend Polling**: When 1,500 users initiate searches and poll `GET /runs/{id}` every 1.5 seconds, the API would experience 1,000+ polling requests/sec, overwhelming the backend.
   - **ARQ Concurrency Limit**: `ARQ_MAX_JOBS = 20` would create massive queue latency for background crawl jobs.

---

## SECTION 11: REMAINING-WORK BACKLOG

### Priority 0: Core Blockers (Safe Startup & DB Execution)
- **TASK-P0-1: Apply Database Migrations to PostgreSQL**
  - *Outcome*: All 14 relational tables created with correct constraints, indexes, and extensions in PostgreSQL.
  - *Dependencies*: Running `leadflow_postgres` container.
  - *Affected Files*: [`apps/api/alembic/versions/001_initial_schema.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/alembic/versions/001_initial_schema.py).
  - *Definition of Done*: `alembic upgrade head` executes cleanly; `SELECT count(*) FROM information_schema.tables WHERE table_schema='public'` returns 15.

### Priority 1: Essential POC Workflow
- **TASK-P1-1: Add Collector for Missing 22nd Signal (`hiring`)**
  - *Outcome*: The Web Crawler searches career page markers, job boards, and ATS links to evaluate open positions, populating `"hiring"`.
  - *Affected Files*: [`apps/api/app/providers/crawler.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/providers/crawler.py), [`apps/api/app/services/enrichment_service.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/services/enrichment_service.py).
  - *Definition of Done*: Crawl output includes `"hiring"` with normalized value and evidence string.
- **TASK-P1-2: Connect Frontend Engine Settings to Backend API**
  - *Outcome*: Scoring Engines page (`engines/page.tsx`) fetches active parameters from `GET /engines` and posts updates to `POST /engines/{id}/params` instead of using `setTimeout()`.
  - *Affected Files*: [`apps/web/src/app/(dashboard)/engines/page.tsx`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/web/src/app/(dashboard)/engines/page.tsx).
  - *Definition of Done*: Sliders persist to the database and reload with updated version numbers.
- **TASK-P1-3: Connect Operator Dashboard to Live Metrics**
  - *Outcome*: Operator dashboard fetches real lead counts, pipeline status breakdowns, and active runs from API.
  - *Affected Files*: [`apps/web/src/app/(dashboard)/dashboard/page.tsx`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/web/src/app/(dashboard)/dashboard/page.tsx).
  - *Definition of Done*: Dashboard displays accurate database record counts instead of hardcoded numbers.
- **TASK-P1-4: Implement Role-Aware Login Routing**
  - *Outcome*: Login page inspects user role: `client_viewer` → `/portal`, `super_admin` → `/admin`, `org_admin` → `/dashboard`.
  - *Affected Files*: [`apps/web/src/app/(auth)/login/page.tsx`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/web/src/app/(auth)/login/page.tsx).
  - *Definition of Done*: Logging in as client_viewer redirects directly to `/portal`.
- **TASK-P1-5: Align Score Band Enums**
  - *Outcome*: Update `ScoreBand` enum to `qualified`, `review`, `disqualified`, `null`.
  - *Affected Files*: [`apps/api/app/core/constants.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/core/constants.py), [`apps/api/app/scoring/engine.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/scoring/engine.py), [`apps/web/src/types/index.ts`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/web/src/types/index.ts).
  - *Definition of Done*: Scoring tests pass using canonical band names.

### Priority 2: Important Supporting Functionality
- **TASK-P2-1: Implement Next.js Auth Middleware & HTTP-Only Cookies**
  - *Outcome*: Protected routes redirect unauthenticated users to `/login`.
  - *Affected Files*: `apps/web/src/middleware.ts` (new), [`api-client.ts`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/web/src/lib/api-client.ts).
  - *Definition of Done*: Direct navigation to `/dashboard` without token redirects to `/login`.
- **TASK-P2-2: Implement User Management Endpoints**
  - *Outcome*: Org admins can invite and manage users within their organization.
  - *Affected Files*: `apps/api/app/api/v1/users.py` (new), [`router.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/api/router.py).
  - *Definition of Done*: `GET /api/v1/users` and `POST /api/v1/users` functional with RBAC.
- **TASK-P2-3: Implement 7-Day Redis Enrichment Cache**
  - *Outcome*: Caches crawl and provider results by domain in Redis for 168 hours to eliminate redundant scraping.
  - *Affected Files*: [`apps/api/app/services/enrichment_service.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/services/enrichment_service.py).
  - *Definition of Done*: Subsequent crawls of the same domain within 7 days hit Redis cache.
- **TASK-P2-4: Implement CSV and JSON Pipeline Exports**
  - *Outcome*: Authorized operators can export filtered lead lists to CSV/JSON.
  - *Affected Files*: [`apps/api/app/api/v1/leads.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/api/v1/leads.py), [`leads/page.tsx`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/web/src/app/(dashboard)/leads/page.tsx).
  - *Definition of Done*: Export button downloads valid CSV with sanitized cells.

### Priority 3: Operational & Scalability Improvements
- **TASK-P3-1: Enforce Production OpenAPI Security & Token Expiry**
  - *Outcome*: Disable `/docs` in production; set access token lifetime to 15 minutes.
  - *Affected Files*: [`apps/api/app/main.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/main.py), [`config.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/core/config.py).
  - *Definition of Done*: `ENVIRONMENT=production` returns 404 for `/docs`.
- **TASK-P3-2: Database Connection Pool & Concurrency Tuning**
  - *Outcome*: Increase connection pool sizing, implement PgBouncer configuration, and support multi-worker Uvicorn processes.
  - *Affected Files*: [`apps/api/app/db/session.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/app/db/session.py), `infra/docker/docker-compose.yml`.
  - *Definition of Done*: Load test achieves 500+ VUs across authenticated routes without connection errors.

---

## SECTION 12: COMPLETION ESTIMATES

| Dimension | Estimated Completion | Evidence-Based Rationale |
| :--- | :---: | :--- |
| **Architecture & Scaffolding** | **95%** | Complete clean architecture: Next.js App Router, FastAPI versioned router, Pydantic v2 schemas, SQLAlchemy 2.0 async models, ARQ worker settings, and Docker Compose configurations. |
| **Backend Implementation** | **70%** | Core endpoints (auth, searches, runs, leads, contacts, drafts, crm, admin) exist and compile. Missing users router, CSV exports, bulk actions, and quota decrement logic. |
| **Frontend Implementation** | **60%** | UI aesthetic is premium and responsive, with all pages and routes created. However, Engines, Dashboard, Portal, and Drafts rely heavily on static mocks or `setTimeout()`. |
| **Database Functionality** | **50%** | Models and Alembic migrations define all 14 tables, but migrations have not been applied to the live PostgreSQL instance. Tables currently do not exist in the active container. |
| **Security & Tenant Isolation** | **55%** | Application-layer tenant context and approval gates are solid. However, RLS is not forced, superuser DB connection bypasses RLS, tokens are in `localStorage`, and `X-Org-Context` is missing. |
| **Scoring Engine** | **75%** | Normalized weighted scoring and missing-value handling are verified via tests. Deficiencies: `hiring` signal is omitted by collectors, score bands use incorrect enum names, and ideal-client bonus is absent. |
| **External Provider Integration** | **40%** | Real adapters exist with complete request contracts. Web crawler works. All other 8 providers lack API credentials under the ₹0 budget constraint. |
| **End-to-End Workflow** | **25%** | Individual steps exist in code, but end-to-end execution cannot run due to the unmigrated database and unconfigured external providers. |
| **Test Coverage** | **30%** | 5 unit tests pass in `apps/api/tests`. Zero integration tests, zero end-to-end frontend tests, and no test coverage for auth, leads, drafts, or CRM sync routers. |
| **Operational Readiness** | **45%** | Structured logging, Docker configurations, and health probes exist. Stuck run recovery, production OpenAPI disabling, and DB backup procedures are absent. |
| **1,500-User Scalability** | **15%** | Only `GET /healthz` was benchmarked; system failed at 1,000 VUs (16% error rate) and collapsed at 1,500 VUs (58% error rate) due to connection exhaustion and single-worker constraints. |

---

## SECTION 13: RECOMMENDED NEXT STEP

### Highest-Priority Immediate Task:
**Apply Alembic Database Migrations to PostgreSQL (`make migrate` / `alembic upgrade head`)**

### Rationale:
The unmigrated database is the **single blocking prerequisite** preventing every other component of LeadFlow from functioning. Until the 14 domain tables exist in PostgreSQL:
1. The backend API cannot register users, log in, or authenticate requests.
2. Background searches cannot ingest leads or persist audit runs.
3. Scoring results and enrichment documents cannot be written.
4. Frontend pages will fail or continue falling back to mock placeholders.

Applying the existing migration file ([`001_initial_schema.py`](file:///c:/Users/Krish%20Fefar/Desktop/LeadFlow_v1/apps/api/alembic/versions/001_initial_schema.py)) costs ₹0, leverages the already running `leadflow_postgres` container, and immediately unlocks real data persistence for subsequent feature verification.
