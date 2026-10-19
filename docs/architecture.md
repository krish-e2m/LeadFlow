# LeadFlow System Architecture

## 1. Architectural Philosophy and Component Boundaries

LeadFlow is built on clean architectural separation of concerns, strict multi-tenancy boundaries, and spend safety gates. The platform coordinates distributed data sourcing, web crawling, metric scoring, and AI drafting across distinct lifecycle phases.

```text
+-----------------------------------------------------------------------------------+
|                                Next.js 16 (React 19)                              |
|   App Router / Typed Client / Polling Hooks / Draft Studio / Operator Dashboard   |
+-----------------------------------------------------------------------------------+
                                      | HTTP/REST (JWT Bearer + Tenant Context)
                                      v
+-----------------------------------------------------------------------------------+
|                               FastAPI REST Layer                                  |
|   - Authentication & RBAC (super_admin, org_admin, client_viewer)                 |
|   - Pydantic v2 Request/Response Validation                                       |
|   - Tenant Context Injection (`leadflow.current_org_id`)                           |
|   - 202 Accepted Job Dispatcher & Progress Polling Endpoints                      |
+-----------------------------------------------------------------------------------+
       |                                               |
       | Query / Mutate                                | Enqueue Job
       v                                               v
+-----------------------------+               +-------------------------------------+
|    PostgreSQL 16 Engine     |               |          Redis 7 & ARQ Worker       |
| - Row-Level Security (RLS)  |               | - Async Search & Lead Scraping      |
| - 14 Core Domain Tables     |<--------------| - Multi-Collector Enrichment        |
| - JSONB Enrichment Storage  |  Write State  | - 22-Signal Scoring Engine Batch    |
| - Audit Logs & History      |  & Progress   | - CRM Synchronization Tasks         |
+-----------------------------+               +-------------------------------------+
                                                               |
                                            Isolate via Adapters
                                                               v
                                              +-------------------------------------+
                                              |       External Provider Adapters    |
                                              | - Apollo.io (Sourcing/Reveal)       |
                                              | - Google PageSpeed API (Auditing)   |
                                              | - Web Crawler (Tech & Content)      |
                                              | - OpenRouter (AI Reasoning & Draft) |
                                              | - HubSpot API v3 (CRM Sync)         |
                                              | - Resend (Transactional Email)      |
                                              | - Google Places / DataForSEO        |
                                              +-------------------------------------+
```

---

## 2. Asynchronous Job Processing & HTTP 202 Semantics

Heavy discovery and enrichment tasks must never block the client HTTP request thread. The platform follows an asynchronous job pattern:

1. **Job Dispatch**: When a user or automated schedule triggers a search (`POST /api/v1/searches`), the API:
   - Validates the query parameters against tenant quotas and active audience filters.
   - Creates a `Run` record with status `PENDING` and a unique UUID.
   - Enqueues the task in Redis via ARQ (`enqueue_job('run_search_pipeline', run_id=run.id)`).
   - Immediately returns **HTTP 202 Accepted** with payload:
     ```json
     {
       "run_id": "c1f7b8d0-...",
       "status": "pending",
       "message": "Search job accepted and queued for execution.",
       "poll_url": "/api/v1/runs/c1f7b8d0-..."
     }
     ```
2. **Execution**: The ARQ worker executes the job in stages (Discovery -> Enrichment -> Scoring), periodically updating the `Run` record's `progress_pct` (0 to 100) and step status.
3. **Polling**: The frontend polls `GET /api/v1/runs/{run_id}` until the run status reaches `COMPLETED` or `FAILED`.

---

## 3. The 8-Stage Pipeline & Spend Safety

LeadFlow enforces an explicit 8-stage pipeline with mandatory human approval gates:

1. **Source Discovery**: Ingestion of target domains and organization metadata from Apollo.io or domain uploads.
2. **Enrichment**: Multi-source collector crawls domain homepage, checks meta-tags, inspects robots/sitemap, tests SSL, triggers PageSpeed Insights, and aggregates provider data into an immutable JSONB document.
3. **Scoring**: The 22-signal engine processes the enrichment document and produces a normalized score (0–100) with detailed signal breakdowns and explanations.
4. **Human Approval Gate (`ApprovalStatus`)**: An operator reviews the scored lead. A lead **cannot** be drafted, revealed, or exported to CRM unless explicitly marked as `APPROVED`.
5. **Contact Reveal Gate**: Executive contacts (decision-makers) are kept masked (`j***@acme.com`). Unmasking contacts consumes credits and requires explicit operator confirmation (`POST /api/v1/contacts/{id}/reveal`).
6. **AI Draft Generation**: OpenRouter (Claude 3.5 Sonnet / GPT-4o-mini) generates hyper-personalized outreach proposals citing verified audit signals (e.g. "Your site takes 4.2s to load and lacks mobile viewport optimization").
7. **Draft Approval Gate (`DraftApprovalStatus`)**: Outreach messages must be reviewed, edited if necessary, and approved by a human operator before any CRM or email export is allowed.
8. **HubSpot CRM Synchronization**: Only approved drafts and approved leads are pushed to HubSpot. Upserts are idempotent to prevent duplicate contact creation.

---

## 4. Provider Adapter Layer Design

All external third-party communications are encapsulated within the `app.providers` package under a unified interface (`BaseProviderAdapter`).

### Graceful Degradation for Unconfigured Providers
Google Places and DataForSEO credentials may not be configured in every environment. The provider manager checks configuration flags (`is_configured()`). When a provider is unconfigured:
- The system **never crashes** or blocks other collectors.
- The provider honestly reports its status as `unconfigured`.
- The enrichment document records the corresponding signal keys as `None`.
- The scoring engine skips `None` values rather than treating them as 0 or failure, preventing distortion of lead quality scores.
