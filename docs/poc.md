LeadFlow Platform Handbook
==========================

> **Purpose:** Single reference for product, engineering, and operations — how LeadFlow works, what it costs, and how much volume it supports.

1\. Executive summary
---------------------

LeadFlow is a **multi-tenant B2B lead qualification and outreach platform**. It sits between [Apollo.io](http://Apollo.io) (lead source) and HubSpot (CRM):

Plain textANTLR4BashCC#CSSCoffeeScriptCMakeDartDjangoDockerEJSErlangGitGoGraphQLGroovyHTMLJavaJavaScriptJSONJSXKotlinLaTeXLessLuaMakefileMarkdownMATLABMarkupObjective-CPerlPHPPowerShell.propertiesProtocol BuffersPythonRRubySass (Sass)Sass (Scss)SchemeSQLShellSwiftSVGTSXTypeScriptWebAssemblyYAMLXML`   Apollo search → Enrich (website + SEO + content + social + growth) → Score (22-signal engine)  → Human approve → Reveal contact → AI draft (OpenRouter) → HubSpot sync   `

**Core value:** Turn large unqualified lists into a short, evidence-backed, ranked funnel with personalized outreach copy — before manual research.

**Live-only principle:** Every external dependency uses a live provider adapter. There is no mock/offline mode. Contract tests skip providers until credentials exist.

**One-line pitch:** _From thousands of Apollo contacts to a ranked Review → Qualified funnel with a personalized email for each._

2\. Product overview
--------------------

### 2.1 What each org gets

Every tenant organization receives:

CapabilityDescription**Audience (ICP)**Versioned Apollo filter catalog; AI can propose filters from a brief or uploaded document**Qualification engine**Configurable weights/thresholds over a fixed **22-signal catalog** (10 website + 12 marketing)**Search & pipeline**Background jobs: source → enrich → score → approve → draft → CRM sync**Client portal**Read-only view of qualified leads + ICP/engine summary (when not in operator mode)**Usage & quotas**Monthly lead allotment, daily reveal/draft caps, concurrent run limits

### 2.2 Operator elevation

Orgs carry operator\_enabled (default false for client orgs):

ModeClient experience**Operator off**Client portal only — summary + qualified leads, no mutations**Operator on**Full pipeline capability within their own org\_id (searches, engines, approve, draft, export, sync)

Super Admin toggles this per org.

### 2.3 Primary user journeys

**J1 — Operator lead gen (primary)**

1.  Log in → Dashboard (usage + funnel)
    
2.  Optional: Audience — brief/doc → AI propose filters → edit → save ICP
    
3.  Optional: Engine — AI propose weights → edit toggles/thresholds → save
    
4.  New Search — pick audience/engine, estimate pool, run
    
5.  Pipeline: Sourced → Enriched → Scored; bands **Review** and **Qualified**
        
6.  Approve → Reveal contact (credit confirm) → Generate draft → Edit → Approve draft → Sync to HubSpot
    

**J2 — Client portal (default client mode)**

1.  Dashboard + ICP & Engine summary
    
2.  Latest search criteria + engine config (thresholds + signal weights)
    
3.  Browse qualified leads, scores, rationales, drafts — read-only
    

**J3 — Super Admin onboarding**

1.  Create org → invite users
    
2.  Set **monthly lead quota** and optionally **Operator enabled**
    
3.  Clone engine template; run or delegate pilot search
    

**J4 — Tune scoring**

1.  Engine Config → enable/weight signals; set Review / Qualified thresholds
    
2.  Re-score existing search → band count diff (Review / Qualified / Disqualified)
    

**J5 — Forgot password**

1.  From login → Forgot password → enter email
    
2.  Recover via **security question** (if set) or **email reset link** (Resend)
    
3.  Set new password → sign in
    

### 2.4 Client visibility contract

client\_viewer sees qualified / approved / drafted / synced leads, scores, drafts, and ICP/engine summary. They do not see costs, usage dollars, audit, admin providers, export, disqualified lists, other orgs, raw Apollo payloads, or unrevealed PII.

org\_admin with operator off: portal + Users in own org. org\_admin with operator on: full own-org pipeline and costs. super\_admin: all orgs via X-Org-Context.

API and UI enforce the same gates. Deep-links to operator routes return 403 for viewers and non-operator client admins.

### 2.5 Production onboarding checklist

1.  Super Admin creates org (kind=client, status=active)
    
2.  Set monthly\_lead\_quota and monthly LLM spend ceiling
    
3.  Decide operator\_enabled (default off — portal only)
    
4.  Invite users — temp password shown once in Admin UI; delivered out-of-band. User completes /setup (new password + security question)
    
5.  Confirm HubSpot token ownership and Apollo seat ownership
    
6.  Clone engine template; optionally save Audience from brief
    
7.  Run a pilot search (50–100 leads)
    
8.  Walk client through portal vs operator mode, credit gates, and 40–60 synced/mo goal
    

3\. Functional rules & screens
------------------------------

### 3.1 Functional rules (FDD)

These rules govern pipeline behavior regardless of UI path:

#Rule1Credit-spending actions (contact reveal; live LLM generate) require **explicit human action** — never silent auto-batch spend. Bulk draft still requires an operator click.2A lead **cannot be drafted before approval**; **cannot be synced before draft approval**.3Disqualified / rejected leads **keep score + evidence** — nothing hard-deleted for learning.4**Archived** leads leave the default pipeline; optional on export only (include\_archived=true).5Default client users **never see**: costs, other orgs, raw Apollo dumps, **disqualified lists**, or export controls. They **do** see search + engine **summary** (weights/thresholds) on the portal.6Operator-elevated client orgs follow **operator rules within their own org only**.7**Re-scoring never mutates history**: new scores row per engine version; latest displayed. Re-score is compute-only (no re-enrichment).8Location/vertical multi-select defaults to **OR** (widen pool). **AND** and exclude lists are explicit opt-ins.9**Monthly lead quota** blocks further ingest when exhausted (Super Admin can raise it).

### 3.2 Screens & features (summary)

ScreenKey behavior**Login & recovery**Email + password; role-aware redirect; no signup; forgot-password (security Q and/or Resend link); forced change when must\_reset\_password**Dashboard**Operator: sourced/review/qualified/drafted/synced, cost/usage, allotment progress, funnel **Review → Qualified → Approved → Drafted → In HubSpot**. Client: qualified pipeline + ICP/engine link only; **no cost cardsAudiences (ICP)**Brief and/or document upload → AI propose filters; full manual edit before save; shared filter catalog**New Search**Engine + optional audience; pool estimate; respects monthly quota; OR/AND/exclude on verticals & locations**Lead Pipeline**Filter by pipeline\_status + score\_band; archived hidden by default; bulk approve/reject/archive/draft; export CSV/JSON**Lead Detail**Score dial, Website vs Marketing breakdown, ideal-client badge; gated Approve/Reject/Reveal/Draft/Sync; PII masked until reveal**Draft Studio**Findings-based subject/body; edit; regenerate with tone (direct / consultative / short); cost readout for operators; approve → sync**Engine Config**Templates; AI suggest from brief; toggles, weights, thresholds, ideal-client bonus; re-score with band diff**Client portal summary**Latest search criteria, engine thresholds/weights, audience brief — read-only**Admin (Super Admin)**Org lifecycle (activate/suspend/reactivate/offboard); operator toggle; monthly quota; users; provider status; cost/usage/audit**Audit trail**Approvals, reveals, drafts, syncs, exports, org setting changes — who / what / when

4\. Users, roles & tenancy
--------------------------

### 4.1 Roles

RoleScopeCapabilitiessuper\_adminAll orgsCreate/suspend orgs, set operator\_enabled + monthly\_lead\_quota, manage users, cross-org via X-Org-Context, view costs & providersorg\_adminOwn orgFull pipeline when operator-enabled (or org kind=internal): audiences, engines, searches, approve/draft/sync, exportclient\_viewerOwn orgRead-only portal: qualified pipeline, scores, drafts; ICP & Engine summary. No mutations, costs, or export

### 4.2 Multi-tenancy model

*   Shared database, shared schema
    
*   org\_id on every tenant-owned row
    
*   Application layer: every tenant query filters by org\_id from the JWT (or X-Org-Context for super\_admin)
    
*   Database layer: Postgres RLS with FORCE ROW LEVEL SECURITY; runtime app role is non-superuser; Alembic uses a privileged role separately
    
*   Worker jobs resolve search.org\_id, then set tenant context for the rest of the job
    
*   Ownership checks: contacts, drafts, and related entities must belong to the same lead and org
    
*   Org lifecycle: suspended and offboarded orgs cannot authenticate or call tenant APIs
    

### 4.3 Auth

Access token: JWT, 15 min — signed with a production JWT\_SECRET (no default secret outside local).

Refresh token: JWT, 7 days, rotating; blacklisted on logout and password reset.

Forced password change: when must\_reset\_password is true, API access is limited to auth/change-password until the user sets a new password; the web app routes them to settings.

User administration: org admins manage users in their org only; they cannot rotate, activate, or deactivate super\_admin accounts.

Password recovery: security question and/or Resend email reset link; reset tokens are never returned in API responses outside local development.

Rate limits: per-user API limits; auth limits use the real client IP behind Railway (X-Forwarded-For / proxy headers).

Explicit exclusions: no payment gateway, no client self-onboarding / public signup.

### 4.4 Account lifecycle

Provision: Super Admin creates org; users invited with temp password. Setup: /setup before pipeline or portal data access. Active: JWT + RBAC; Super Admin X-Org-Context switch is marked in the audit log.

Suspend: immediate auth + refresh block; data retained. Offboard: deleted\_at set; auth blocked; Super Admin may export then erase per DPA.

Kill switches: suspend org, disable operator\_enabled, or disable a provider globally.

Sessions: httpOnly Secure SameSite cookies; web logout calls POST /v1/auth/logout; password reset revokes all refresh tokens.

5\. End-to-end pipeline
-----------------------

### 5.1 Run stages

A **Run** = orchestrated background job:

Plain textANTLR4BashCC#CSSCoffeeScriptCMakeDartDjangoDockerEJSErlangGitGoGraphQLGroovyHTMLJavaJavaScriptJSONJSXKotlinLaTeXLessLuaMakefileMarkdownMATLABMarkupObjective-CPerlPHPPowerShell.propertiesProtocol BuffersPythonRRubySass (Sass)Sass (Scss)SchemeSQLShellSwiftSVGTSXTypeScriptWebAssemblyYAMLXML`   Source → Enrich → Score → (human approve) → Draft → (human approve draft) → CRM Sync   `

*   ARQ jobs on Redis; stages idempotent/resumable via lead pipeline\_status
    
*   Failures per lead → error + reason; run continues
    
*   Cost/tokens logged on runs and drafts
    

### 5.2 Lead state fields (orthogonal — do not overload)

**Pipeline status** (pipeline\_status):

Plain textANTLR4BashCC#CSSCoffeeScriptCMakeDartDjangoDockerEJSErlangGitGoGraphQLGroovyHTMLJavaJavaScriptJSONJSXKotlinLaTeXLessLuaMakefileMarkdownMATLABMarkupObjective-CPerlPHPPowerShell.propertiesProtocol BuffersPythonRRubySass (Sass)Sass (Scss)SchemeSQLShellSwiftSVGTSXTypeScriptWebAssemblyYAMLXML`   sourced → enriched → scored → approved → drafted → synced  (any stage) → error  scored | approved → rejected   `

**Score band** (score\_band):

BandConditionreviewscore ≥ review\_threshold and < qualified\_thresholdqualifiedscore ≥ qualified\_thresholddisqualifiedbelow review\_thresholdnullnot yet scored

### 5.3 Product funnel order (UI / reporting)

Plain textANTLR4BashCC#CSSCoffeeScriptCMakeDartDjangoDockerEJSErlangGitGoGraphQLGroovyHTMLJavaJavaScriptJSONJSXKotlinLaTeXLessLuaMakefileMarkdownMATLABMarkupObjective-CPerlPHPPowerShell.propertiesProtocol BuffersPythonRRubySass (Sass)Sass (Scss)SchemeSQLShellSwiftSVGTSXTypeScriptWebAssemblyYAMLXML`   Review → Qualified → Approved → Drafted → In HubSpot (synced)   `

### 5.4 Credit-safety gates

ActionWhen credits/API spend occurApollo search (list)No reveal credits on list viewApollo org enrich1 credit per company (if APOLLO\_ENRICH\_ON\_PIPELINE=true)Contact reveal1 Apollo credit — **human confirm only**LLM draft/insightOpenRouter — **explicit generate action only**HubSpot syncNo marginal per-lead API fee (existing seat)

### 5.5 Bulk actions

*   Approve, reject, archive, unarchive
    
*   Bulk draft (advance selected Approved → Drafted)
    
*   Export CSV/JSON (org-admin+, audit-logged, PII masked until revealed)
    

6\. Architecture & tech stack
-----------------------------

### 6.1 High-level diagram

Multi-tenant SaaS: shared Postgres schema with org\_id on every tenant row, JWT + RBAC, live provider adapters selected by env (no mock mode).

*   Request path: Browser → Next.js → POST /v1/... (JSON + JWT) → FastAPI. Heavy search work returns 202 and runs in an ARQ worker; the UI polls /v1/runs/{id} for progress.
    
*   Automated pipeline (worker): Source (Apollo) → Enrich (5 collectors in parallel: crawl, PageSpeed, Apollo org, DataForSEO, Places; Redis cache ~7 days) → Score (22-signal qualification engine). Per-lead failures do not abort the run.
    
*   Human gates (sync API, after scored): Approve → Draft (OpenRouter) → Sync (HubSpot). Contact reveal is credit-gated. Draft/CRM are not part of the ARQ search job.
    

Plain textANTLR4BashCC#CSSCoffeeScriptCMakeDartDjangoDockerEJSErlangGitGoGraphQLGroovyHTMLJavaJavaScriptJSONJSXKotlinLaTeXLessLuaMakefileMarkdownMATLABMarkupObjective-CPerlPHPPowerShell.propertiesProtocol BuffersPythonRRubySass (Sass)Sass (Scss)SchemeSQLShellSwiftSVGTSXTypeScriptWebAssemblyYAMLXML`   ┌─────────────────────────────────────────────────────────────┐  │              Next.js 16 App Router (React + TS)              │  │  Auth · Dashboard · Audiences · Engines · Pipeline · Portal │  └───────────────────────────┬─────────────────────────────────┘                              │ REST /v1 (JSON) + JWT  ┌───────────────────────────▼─────────────────────────────────┐  │                      FastAPI Backend                         │  │  ┌──────────┐ ┌──────────────┐ ┌───────────┐ ┌───────────┐  │  │  │ Auth/RBAC│ │ Pipeline Svc │ │ Qual.     │ │ Draft Svc │  │  │  │ + quotas │ │ (orchestr.)  │ │ Engine    │ │ (LLM)     │  │  │  └──────────┘ └──────┬───────┘ └───────────┘ └───────────┘  │  │                      │ enqueue run_search_job                 │  │  ┌───────────────────▼──────────────────────────────────┐  │  │  │ ARQ worker (same image): Source → Enrich → Score      │  │  │  └───────────────────┬──────────────────────────────────┘  │  │                      │  Provider Adapter Layer (live)        │  │   ┌────────┬─────────┼──────────┬────────────┬───────────┐  │  │   │ Apollo │ Crawl + │ PageSpeed│ DataForSEO │ Google    │  │  │   │        │ Apollo  │          │            │ Places    │  │  │   └────────┴─────────┼──────────┴────────────┴───────────┘  │  │                      │ HubSpot · OpenRouter · Resend         │  └───────────────────────────┬─────────────────────────────────┘                              │                ┌─────────────▼──────────────┐                │  PostgreSQL (multi-tenant) │                │  + Redis (ARQ/cache/quota) │                └────────────────────────────┘   `

### 6.2 Monorepo layout

PathPurposeapps/apiFastAPI, SQLAlchemy 2.0, Alembic, ARQ workerapps/webNext.js 16, React 19, TypeScript, Tailwindinfra/dockerdocker-compose (Postgres, Redis, api, worker, web)docs/TDD, FDD, plan, this handbook

### 6.3 Tech stack

LayerChoiceBackendPython 3.12, FastAPI, Pydantic v2ORMSQLAlchemy 2.0 + AlembicDatabasePostgreSQL 16 (JSONB enrichment payloads)JobsARQ (Redis)FrontendNext.js 16 App Router, React 19, TypeScriptUITailwind CSSAuthJWT + bcrypt, RBACLLM**OpenRouter** (model set via OPENROUTER\_MODEL env)EmailResendCRMHubSpot (private app token)Lead source[Apollo.io](http://Apollo.io) (B2B only)

### 6.4 Provider selection (env)

Plain textANTLR4BashCC#CSSCoffeeScriptCMakeDartDjangoDockerEJSErlangGitGoGraphQLGroovyHTMLJavaJavaScriptJSONJSXKotlinLaTeXLessLuaMakefileMarkdownMATLABMarkupObjective-CPerlPHPPowerShell.propertiesProtocol BuffersPythonRRubySass (Sass)Sass (Scss)SchemeSQLShellSwiftSVGTSXTypeScriptWebAssemblyYAMLXML`   LEAD_SOURCE_PROVIDER=apollo  ENRICHMENT_PROVIDER=live  CRM_PROVIDER=hubspot  LLM_PROVIDER=openrouter  EMAIL_PROVIDER=resend   `

7\. Data model
--------------

Core schema (shared DB, org\_id on every tenant row). Two orthogonal lead fields — **do not** overload one enum (pipeline\_status vs score\_band).

Plain textANTLR4BashCC#CSSCoffeeScriptCMakeDartDjangoDockerEJSErlangGitGoGraphQLGroovyHTMLJavaJavaScriptJSONJSXKotlinLaTeXLessLuaMakefileMarkdownMATLABMarkupObjective-CPerlPHPPowerShell.propertiesProtocol BuffersPythonRRubySass (Sass)Sass (Scss)SchemeSQLShellSwiftSVGTSXTypeScriptWebAssemblyYAMLXML`   orgs            (id, name, slug, kind, status, operator_enabled, monthly_lead_quota, ...)  users           (id, org_id, email, password_hash, role, must_reset_password, security_*)  audiences       (id, org_id, name, brief_text, filters_json, ai_rationale, source, ...)  engines         (id, org_id, name, vertical, version, llm_model,                   qualified_threshold, review_threshold, ideal_client_bonus, ...)  engine_params   (id, engine_id, engine_version, param_key, weight, enabled, threshold_json)  searches        (id, org_id, engine_id, engine_version, audience_id?, criteria_json,                   status, pool_estimate, total_ingested, created_by)  leads           (id, org_id, search_id, company_name, domain, ..., raw_json,                   pipeline_status, score_band, error_reason, archived_at)                   -- pipeline_status: sourced → enriched → scored → approved → drafted → synced                   --                  any → error; scored|approved → rejected                   -- score_band:      qualified | review | disqualified | null  enrichments     (id, lead_id, org_id, category, payload_json, fetched_at, provider)  scores          (id, lead_id, org_id, engine_id, engine_version, total_score,                   breakdown_json, rationale_text, persona_text, scored_at)  contacts        (id, lead_id, org_id, name, title, email, phone, linkedin_url,                   revealed, revealed_at)   -- PII masked until reveal  drafts          (id, lead_id, contact_id, subject, body, angle, model,                   tokens_in, tokens_out, cost_usd, status, edited_body, ...)  crm_syncs       (id, lead_id, provider, external_ref, idempotency_key, status, synced_at)  runs            (id, org_id, kind, status, progress_json, cost_usd, error_reason, ...)  audit_log       (id, org_id, user_id, action, entity, entity_id, detail, created_at)   `

**Notes:**

*   Soft archive: archived\_at hides leads from default pipeline; export may include via include\_archived=true
    
*   filters\_json / criteria\_json store versioned Apollo filter catalog snapshot (incl. match modes, excludes)
    
*   Re-score creates a **new** scores row per engine version; history preserved
    

8\. Audiences, filters & suggestion engine
------------------------------------------

### 8.1 Apollo filter catalog

Versioned catalog (filter\_catalog.py) is the single source of truth for UI, AI propose, and Apollo payload mapping.

FieldBehaviorverticals + vertical\_matchor (default) = any vertical → **wider** pool; and = all requiredlocations + location\_matchor (default) = any city → **more** companies; and narrowsexclude\_locations / exclude\_verticals / exclude\_domainsDrop matches from the poolexclude\_existing\_crmPrefer skipping contacts already in HubSpot

**Example:** Arlington + Alexandria + Washington with **OR** → larger pool, not smaller.

### 8.2 Suggestion engine (ICP from client documents)

**Audiences path:**

1.  Strategist pastes a brief and/or uploads a client document (text extracted, e.g. via SuperMemory)
    
2.  POST /v1/audiences/ai-propose → OpenRouter proposes filters\_json + rationale (**no Apollo spend**)
    
3.  Human **edits**: add/remove filters, flip AND/OR/exclude, then save Audience
    
4.  Saved audience reused as New Search starting point
    

**Engines path (parallel):**

1.  Ideal-client brief → POST /v1/engines/ai-propose
    
2.  OpenRouter suggests param toggles/weights
    
3.  Strategist sets weights/thresholds before save/version bump
    

> **AI never auto-runs searches or spends Apollo credits.**

9\. Qualification engine (22 signals)
-------------------------------------

### 9.1 Design principles

*   Fixed **22-parameter catalog** seeded from the Leads Strategy criteria doc
    
*   Split into **Website Prospect** and **Marketing Prospect** groups
    
*   **Ideal client** = both groups score strongly (bonus applied)
    
*   Scoring: weighted mean over enabled non-null params + ideal\_client\_bonus, normalized **0–100**
    
*   Each param → {score, evidence, source} in scores.breakdown\_json
    
*   LLM (OpenRouter) produces rationale\_text, persona, and outreach angle on demand
    

> _“The ideal client is one that asks us to build a new website AND provide marketing.”_

### 9.2 Engine configuration (per org)

SettingPurposequalified\_thresholdMinimum score for **Qualified** bandreview\_thresholdMinimum score for **Review** bandideal\_client\_bonusExtra points when both website + marketing groups fireengine\_params\[\]Per signal: param\_key, weight, enabledllm\_modelOpenRouter model slug per engine (falls back to env OPENROUTER\_MODEL)

### 9.3 Website signals (10)

KeyLabelCategoryDefault weightlegacy\_platformLegacy CMS platformWebsite1.5slow\_siteSlow websiteWebsite1.3old\_designDated designWebsite1.0weak\_ctasWeak CTAsWebsite1.0not\_mobile\_friendlyNot mobile friendlyWebsite0.8no\_sslNo valid SSLWebsite1.2thin\_contentThin homepage contentWebsite0.7no\_analyticsNo analytics installedWebsite0.6accessibilityAccessibility issuesWebsite0.6no\_live\_chatNo live chat / conversion widgetWebsite0.5

### 9.4 Marketing signals (12)

KeyLabelCategoryDefault weightpoor\_seoPoor SEOSEO1.4poor\_aeo\_geoPoor AEO/GEOSEO1.0low\_domain\_trustBacklink spam riskSEO0.6stale\_blogNo/stale blogContent1.1no\_pressNo recent pressContent0.7no\_case\_studiesNo case studiesContent0.8no\_videoNo video contentContent0.5weak\_socialWeak social presenceSocial0.9weak\_email\_captureWeak email captureSocial0.6ppc\_spendPPC spend > $1k/moGrowth1.2hiringHiring (5+ roles)Growth1.1low\_review\_ratingLow review ratingGrowth0.8

### 9.5 Scoring behavior when data is missing

*   If enrichment does not produce a field → signal returns **None**
    
*   Missing signal is **skipped** (not scored as zero)
    
*   Score breakdown shows _“X of 22 signals available”_
    
*   Higher weight on enabled signals that _do_ have data
    

10\. How each signal is checked
-------------------------------

Enrichment runs **five collectors in parallel**, merges into a payload, then each catalog scorer reads that payload.

**Collectors:** crawl · PageSpeed · Apollo org · DataForSEO · Google Places

### 10.1 Website signals

SignalData sourceDetection methodlegacy\_platformCrawl HTML + Apollo techFingerprint markers (ColdFusion, Joomla, Drupal 7, WP version, Squarespace, Webflow, modern JS). Apollo /organizations/enrich fills gapsslow\_sitePageSpeed InsightsMobile performance score + LCP load secondsold\_designCrawl heuristicCopyright year, WP major version, Last-Modified, Bootstrap 3 / jQuery 1.x markersweak\_ctasCrawl homepageCount CTA phrases / primary buttons in first ~80KB of HTMLnot\_mobile\_friendlyCrawl + PageSpeedViewport meta tag; refined by PageSpeed viewport auditno\_sslCrawlFinal URL starts with httpsthin\_contentCrawl homepageVisible word count on homepageno\_analyticsCrawl HTMLGA, GTM, Segment, etc. script markersaccessibilityPageSpeed InsightsLighthouse accessibility score (0–100)no\_live\_chatCrawl HTMLIntercom, Drift, HubSpot chat, etc. widget markers

### 10.2 Marketing signals

SignalData sourceDetection methodpoor\_seoDataForSEOOrganic keyword count → synthesized domain authority proxy (0–90 scale)poor\_aeo\_geoOn-page crawlJSON-LD types (FAQ, HowTo, Organization…), meta description, location pages, NAP-ish phone/addressppc\_spendDataForSEOPaid ETV as monthly spend proxy; >$1k/mo = strong buying signalstale\_blogCrawl/blog etc. paths; parse post dates; flag if none or >6 monthsno\_pressCrawlPress/news paths; flag if none or >1 yearweak\_socialCrawl + Apollo LinkedInSocial profile link discovery; **presence heuristic** for posts/followers (no live social API)hiringCrawl careers pagesJob link count; Greenhouse/Lever/Workday markers; **5+ = growth mode**no\_case\_studiesCrawlCase study / portfolio path detectionno\_videoCrawlYouTube/Vimeo//Wistia embedslow\_domain\_trustDataForSEOBacklinks bulk spam scoreweak\_email\_signupCrawlNewsletter/subscribe copy or email form fieldslow\_review\_ratingGoogle PlacesFind Place + Details → rating + review count

### 10.3 Signal reliability tiers

TierSignalsNotes**High**SSL, blog/press presence, video, case studies, PageSpeed perfDirect observation**Medium**Platform fingerprint, CTAs, AEO/GEO, jobs, email captureHeuristic but auditable**Provider-dependent**SEO/DA, spam, PPC, reviewsRequires API keys; skipped if absent**Weakest today**old\_design, weak\_socialHeuristic only; evidence string still shown

11\. Enrichment system
----------------------

### 11.1 Orchestrator flow

Plain textANTLR4BashCC#CSSCoffeeScriptCMakeDartDjangoDockerEJSErlangGitGoGraphQLGroovyHTMLJavaJavaScriptJSONJSXKotlinLaTeXLessLuaMakefileMarkdownMATLABMarkupObjective-CPerlPHPPowerShell.propertiesProtocol BuffersPythonRRubySass (Sass)Sass (Scss)SchemeSQLShellSwiftSVGTSXTypeScriptWebAssemblyYAMLXML`   domain + company_name + location      │      ├─► Crawl (up to 8 pages, 12s timeout)      ├─► PageSpeed Insights (mobile perf + a11y)      ├─► Apollo org enrich (tech stack, LinkedIn) — optional, 1 credit      ├─► DataForSEO (DA proxy, keywords, spam, paid ETV)      └─► Google Places (rating + review count)      │      ▼  merge_slices → cache (TTL 7 days) → enrichment payload      │      ▼  22-signal scorers → breakdown_json + total_score   `

### 11.2 Cache

SettingDefaultEffectENRICHMENT\_CACHE\_TTL\_HOURS168 (7 days)Same domain within org skips re-fetchENRICHMENT\_MAX\_PAGES\_PER\_DOMAIN8Crawl depth capENRICHMENT\_HTTP\_TIMEOUT\_SECONDS12Per-request timeoutENRICHMENT\_COLLECTOR\_CONCURRENCY4Parallel page fetches

### 11.3 Enrichment payload shape

Plain textANTLR4BashCC#CSSCoffeeScriptCMakeDartDjangoDockerEJSErlangGitGoGraphQLGroovyHTMLJavaJavaScriptJSONJSXKotlinLaTeXLessLuaMakefileMarkdownMATLABMarkupObjective-CPerlPHPPowerShell.propertiesProtocol BuffersPythonRRubySass (Sass)Sass (Scss)SchemeSQLShellSwiftSVGTSXTypeScriptWebAssemblyYAMLXML`   {    "website": { "platform", "pagespeed_score", "ssl_valid", "cta_count_above_fold", ... },    "seo": { "domain_authority", "organic_keywords", "spam_score", "aeo_geo_score" },    "content": { "has_blog", "days_since_last_post", "has_press_releases", "has_case_studies", "has_video" },    "social": { "posts_last_30_days", "follower_count", "has_email_signup", "social_profiles" },    "growth": { "open_job_postings", "monthly_ppc_spend_usd", "avg_review_rating", "review_count" }  }   `

### 11.4 Failure behavior

*   Each collector wrapped in \_safe() — one failure never kills the run
    
*   Partial enrichment still scores available signals
    
*   fetch\_error on website block if domain unreachable
    

12\. Subscriptions & API keys
-----------------------------

### 12.1 Required for full 22-signal coverage

ServiceEnv varsPowers**Google PageSpeed Insights API**PAGESPEED\_API\_KEYslow\_site, accessibility, refines not\_mobile\_friendly**DataForSEO**DATAFORSEO\_LOGIN, DATAFORSEO\_PASSWORDpoor\_seo, ppc\_spend, low\_domain\_trust**Google Places API**GOOGLE\_PLACES\_API\_KEYlow\_review\_rating[**Apollo.io**](http://Apollo.io) (optional enrich)APOLLO\_API\_KEYHelps legacy\_platform via org tech stack

### 12.2 No subscription (built-in)

Homepage + linked-page crawl covers the remaining ~15 signals at **$0 marginal API cost**.

Without PageSpeed / DataForSEO / Places → those fields stay empty and those signals **do not contribute** to the score.

### 12.3 Full platform stack

ServiceEnv varUsed for[Apollo.io](http://Apollo.io)APOLLO\_API\_KEYLead search + contact reveal + optional org enrichHubSpotHUBSPOT\_PRIVATE\_APP\_TOKENCRM contact upsert + draft note**OpenRouter**OPENROUTER\_API\_KEY, OPENROUTER\_MODELDrafts, insight, AI propose — **model is your env choice**ResendRESEND\_API\_KEY, EMAIL\_FROMPassword-reset emailSuperMemorySUPERMEMORY\_API\_KEYOptional PDF/DOCX brief extractionPostgres + RedisDATABASE\_URL, REDIS\_URLApp DB + background jobs

### 12.4 Not wired

ServiceStatusSpyFuNot integrated — PPC uses DataForSEO paid ETV proxy

### 12.5 Minimum viable enrichment

TierSignals activeSubs neededCrawl only~15/22None (beyond hosting)Full coverage22/22PageSpeed + DataForSEO + Places (+ Apollo for enrich)

13\. Cost model (OpenRouter)
----------------------------

> **Assumptions:** Apollo credit mid **~$0.04** (plan-dependent, $0.03–$0.05). Enrichment vendor list prices Aug 2026. **OpenRouter LLM cost depends on which model you set in OPENROUTER\_MODEL** — this section uses **pricing tiers**, not a fixed model name. Verify live rates on [openrouter.ai/models](https://openrouter.ai/models) before budgeting.

### 13.1 OpenRouter pricing tiers (estimate)

Typical pay-as-you-go bands on OpenRouter (varies by model slug):

TierInput ($ / 1M tokens)Output ($ / 1M tokens)Use case**Economy**$0.10 – $0.80$0.20 – $2.00Short drafts, high volume**Standard**$1.00 – $5.00$3.00 – $15.00Balanced outreach quality (common choice)**Premium**$8.00 – $20.00+$25.00 – $75.00+Highest copy quality

**LeadFlow LLM usage per drafted lead (typical):**

ActionCallsEst. tokens / callInsight (rationale + persona)2~1,200 in · ~500 out eachOutreach draft1~1,200 in · ~500 outAI propose (audience/engine)occasional~800–2,000 in · ~400–1,000 out

**Formula per completion:**

Plain textANTLR4BashCC#CSSCoffeeScriptCMakeDartDjangoDockerEJSErlangGitGoGraphQLGroovyHTMLJavaJavaScriptJSONJSXKotlinLaTeXLessLuaMakefileMarkdownMATLABMarkupObjective-CPerlPHPPowerShell.propertiesProtocol BuffersPythonRRubySass (Sass)Sass (Scss)SchemeSQLShellSwiftSVGTSXTypeScriptWebAssemblyYAMLXML`   cost ≈ (prompt_tokens / 1e6 × input_rate) + (completion_tokens / 1e6 × output_rate)   `

**Est. LLM cost per lead (insight + draft = 3 completions):**

TierPer completionInsight + draft / leadEconomy~$0.001 – $0.003**~$0.003 – $0.009**Standard~$0.006 – $0.015**~$0.02 – $0.05**Premium~$0.03 – $0.08**~$0.10 – $0.25**

> Regenerating a draft or running AI propose adds cost on top. Product target (TDD): **$0.20–$0.60 visibility per full run** — achievable on **Standard** tier when enrichment dominates.

### 13.2 Non-LLM variable cost by stage

StageComponentUnit costWhen it runsSourceApollo people search$0 (list view)Every searchEnrichApollo org enrich~$0.04Every new domain (if enabled; cache 7d)EnrichDataForSEO (rank + spam)~$0.036Every new domainEnrichGoogle Places~$0.03Every new domainEnrichPageSpeed + crawl$0Every new domainScoreLocal engine$0Every leadRevealApollo contact reveal~$0.04Human confirm onlySyncHubSpot$0 marginalDraft approved → CRM

**Enrich + score only:** **~$0.11 / lead** (fixed regardless of OpenRouter tier).

### 13.3 Full-path per-lead totals (enrich + insight + draft + reveal)

OpenRouter tierLLM portion**Total / lead**Economy~$0.005**~$0.12 – $0.15**Standard~$0.035**~$0.15 – $0.20**Premium~$0.15**~$0.26 – $0.35**

### 13.4 Monthly variable API estimate

Assumes ~5:1 sourced→synced funnel; enrich all sourced; insight/draft/reveal on approved path only.

**Non-LLM base (50 synced / mo):** ~250 enriched × $0.11 ≈ **$28** + ~50 reveals × $0.04 ≈ **$2** → **~$30**

Synced / moSourcedDraftedEconomy LLM addStandard LLM addPremium LLM add**Total (Standard)**5025060+$0.50+$3+$15**~$33**6030075+$0.60+$4+$19**~$38**100500120+$1+$6+$30**~$64**

**Fully loaded / synced (Standard tier):** ~**$0.55 – $0.65** (enrichment waste spread across funnel).

### 13.5 Fixed monthly (not in per-lead)

ItemEst. rangeApollo (API-capable plan)~$99–149+/seatHubSpotExisting seatHosting (API + worker + web + DB + Redis)~$40–120DataForSEO$50 min deposit (pay-as-you-go)OpenRouterPay-as-you-go (tier-dependent)ResendFree tier / lowGoogle Cloud (PSI + Places)PAYG; PSI free within quota

**All-in rough cut (50 synced/mo, Standard LLM):** ~$33 variable + ~$150–300 fixed ≈ **$180–330/mo**.

### 13.6 Cost levers

LeverSavingsChoose Economy-tier model on OpenRouterLower LLM $ (watch draft quality)Disable APOLLO\_ENRICH\_ON\_PIPELINE−1 Apollo credit / lead (~$0.04)7-day enrichment cacheSkip re-fetch on re-scores / duplicate domainsGate reveal to human approveSecond Apollo credit only when neededSkip insight if draft-only−2 OpenRouter calls per leadRegenerate draft sparinglyEach retry = +1 LLM call

### 13.7 In-app cost tracking

What is loggedWhereLLM cost\_usd, tokensdrafts, runs (draft/insight actions) — uses rates in code; update when model changesApollo credits usedruns.meta\_json.credits\_used on revealEnrichment API spend**Not yet** rolled into Run.cost\_usd — track via vendor dashboards

> Set LLM\_PROVIDER=openrouter, OPENROUTER\_API\_KEY, and OPENROUTER\_MODEL=. Pick any model on OpenRouter; cost scales with its published input/output rates.

14\. Capacity, quotas & pacing
------------------------------

### 14.1 Hard SaaS ceilings (per org)

Monthly lead quota (default 100), max 500 leads per search, 2 concurrent runs, 100 reveals/day, 200 drafts/day, plus a per-org monthly LLM spend ceiling checked before llm.complete.

Spend-related quotas (reveal, draft, LLM ceiling) fail closed if Redis is unavailable (503). Auth rate limits may fail open to preserve login availability; spend caps do not.

### 14.2 Business goals (soft targets)

Synced to CRM / org / month: 40–60. Synced volume is operator throughput; monthly allotment caps sourced ingest.

### 14.3 Search sizing & job budget

*   Interactive searches: 50–150 leads per search
    
*   Hard ceiling: 500 leads / search
    
*   Concurrent searches: 2 running per org; enqueue reserves concurrency
    
*   Search jobs do not re-spend providers on automatic retry loops
    
*   Stuck-run reaper prevents permanent 409 lockouts
    

### 14.4 Day-wise pacing

At 100/mo allotment over 22 work days: ~5 sourced/day average. Mon–Tue search-heavy; Wed–Thu score/approve; Fri draft/reveal.

15\. Configuration & Railway
----------------------------

ENVIRONMENT must be local | staging | demo | production. Boot fails closed if JWT\_SECRET is missing/default outside local.

Railway services: web (Next.js), api (Uvicorn), worker (ARQ), Postgres 16, Redis 7. Web API base is configured per environment. Uvicorn uses proxy headers so auth rate limits see the real client IP.

16\. API surface (summary)
--------------------------

All tenant routes require a valid JWT. Usage, audit, and admin providers are org-admin / super\_admin only — not client\_viewer. OpenAPI (/docs) is disabled in production.

17\. Security & compliance
--------------------------

### Access control

*   bcrypt; JWT expiry, refresh rotation, blacklist on logout and password reset
    
*   Role checks + org\_id scoping; Postgres RLS on non-superuser app role
    
*   Contact/draft ownership checks; org admins cannot alter super\_admin accounts
    
*   must\_reset\_password blocks business API until password change
    
*   Suspended and offboarded orgs cannot authenticate
    
*   Audit log on mutations, exports, and cross-org super\_admin actions
    

### Network & application hardening

*   Secrets via env; production rejects default JWT\_SECRET
    
*   CORS locked; security headers (CSP, HSTS, framing, content-type, referrer)
    
*   Non-root containers; CSV formula escaping; PII masked until reveal
    
*   Per-user API rate limits; auth limits on real client IP
    
*   Dependency scanning in CI
    

### Data protection

*   PII stored for pipeline use; reveal is credit-gated and human-confirmed
    
*   Offboarding suspends access; retention/erasure follow Ironistic DPA
    
*   Subject-access / erasure via Super Admin ops process
    
*   No public signup; no payment card data in LeadFlow
    

### Environments

local · staging · demo · production. Production: AUTO\_SEED off, OpenAPI off, JWT default rejected.

### Sessions & browser

*   Access + refresh in httpOnly, Secure, SameSite cookies
    
*   Web logout calls POST /v1/auth/logout
    
*   CSP, HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy
    

### Subprocessors

Railway (hosting), [Apollo.io](http://Apollo.io), HubSpot, OpenRouter, Resend, DataForSEO, Google (PageSpeed + Places), SuperMemory (optional document extract).

### Retention & erasure

Leads, enrichments, scores, drafts, contacts: life of the org + DPA period after offboard. Audit log: minimum 12 months. Redis is ephemeral.

SAR: Super Admin exports the org’s leads, contacts, drafts, scores, and audit rows. Erasure: offboard then documented delete path.

local · staging · demo · production — staging mirrors production for rollback drills; production has OpenAPI off and fail-closed secrets.

18\. Non-functional targets
---------------------------

*   Async search UX; recommended 50–150 leads per interactive search
    
*   Draft < 15 s under Standard OpenRouter tier
    
*   Health/readyz with worker heartbeat; structured logs with request id; error tracking
    
*   Alerts: 5xx rate, worker heartbeat, stuck runs
    
*   Deploy on Railway; CI on every PR to the default branch
    

19\. Operations, incident response & continuity
-----------------------------------------------

### 19.1 Day-to-day

Operators use Dashboard + Usage; Super Admin manages orgs and quotas; [RUNBOOK.md](http://RUNBOOK.md) covers provider outage, Redis, stuck run, and auth lockout.

### 19.2 Monitoring

API health/readyz, structured logs (request\_id, org\_id), error tracking, alerts on 5xx / worker heartbeat / stuck runs.

### 19.3 Incident response

1.  Detect via alert or operator report
    
2.  Triage with request id / run id
    
3.  Mitigate (disable provider, pause searches, raise quota, fail stuck runs)
    
4.  Follow runbook playbooks
    
5.  Post-incident notes
    

### 19.4 Backup & recovery

Postgres via Railway snapshots; Redis ephemeral; restore rehearsed in staging; RPO/RTO agreed with Ironistic ops.

### 19.5 Release process

PR + CI → staging smoke → production. Forward-fix migrations preferred. Rollback = previous image (± DB snapshot if required).

### 19.6 Support model

Channel: named account contact + email (hours in SOW). Response: P0 same day; P1 next business day; P2 planned. Kill switches: suspend org, disable provider, pause searches.

RPO ≤ 24 hours; RTO ≤ 8 hours. Restore rehearsed in staging at least quarterly.

20\. Success criteria & KPIs
----------------------------

Roles and operator elevation; full live pipeline; AI propose without auto-spend; quotas and LLM ceilings; cost visibility for operators; cross-tenant isolation at app + RLS; health and error tracking for API and worker.

21\. Risks & mitigations
------------------------

Provider drift (contract tests); credit burn (gates + quotas); OpenRouter variance (ceilings + logging); cross-tenant access (filters + RLS + ownership); stuck jobs (reaper + concurrency); Redis outage (spend quotas fail closed).

22\. Out of scope & future
--------------------------

Out of scope: payments, public signup, B2C, email sending from LeadFlow, SpyFu. Future: ClientHub/Fathom, feedback loop, PDF export, full Apollo mapping for revenue/departments/CRM exclusion.

24\. Glossaryc
--------------

Audience/ICP, Engine, Signal, Score band, Pipeline status, Reveal, Run, Operator enabled, Monthly allotment, RLS, ARQ, OpenRouter — see handbook markdown for full definitions.