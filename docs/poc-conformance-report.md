# LeadFlow – Conformance Report against `docs/poc.md`

**Date:** 2026-10-15 · **Scope:** whole repo (`apps/api`, `apps/web`, `infra`, `docs`)
**Supersedes:** `docs/poc-audit-report.md` (2026-10-12), whose "unmigrated database / mock pages / no users router / no FORCE RLS" findings no longer apply.

## 1. How this was tested

| Check | Result |
|---|---|
| Backend test suite (`pytest`) | **170 passed** (146 before this audit; 24 regression tests added) |
| `ruff` on `app/` + `scripts/` | clean (was 29 findings) |
| Frontend `tsc --noEmit` + `eslint` | clean |
| Live provider smoke tests (Hunter, PageSpeed, SerpApi, Firecrawl, OpenRouter) | all reachable; bugs found and fixed (§2) |
| **Live end-to-end run**, 1 real domain (`slikk.club`) through the real worker pipeline in a throw-away org | Hunter → crawl/PageSpeed/SerpApi/Firecrawl → 22-signal score → band; org deleted afterwards |
| Route smoke test (all read routes + create flows, org_admin and super_admin) | no 5xx |

Not exercised live: contact reveal spend, AI draft generation, HubSpot sync (no HubSpot token), DataForSEO / Google Places / Resend / SuperMemory (keys empty).

## 2. Bugs found and fixed

| # | Defect | Fix |
|---|---|---|
| 1 | **`POST /engines` and `POST /engines/{id}/params` returned 500** – `commit()` then `refresh()` ran outside the transaction-local RLS context | flush inside the request transaction (`engines.py`) |
| 2 | **Firecrawl `html` format strips `<head>`** → `poor_seo`, `poor_aeo_geo`, `not_mobile_friendly`, generator/OG/analytics detection were wrong whenever Firecrawl was used (slikk.club was scored "no title, no viewport, no schema") | request/prefer `rawHtml`; enrichment cache key versioned (`v2`) so poisoned cached payloads are not reused |
| 3 | Hunter `/companies/find` parser assumed an imagined shape (live payload is camelCase, `location` is a string) → crash on every call, firmographics (industry, headcount, city, country) never filled | new `_parse_company_find` handling the real shape (old shape still accepted); unit tests mocked the wrong shape, so a live-shape test was added |
| 4 | **OpenRouter default model `anthropic/claude-3.5-sonnet` no longer exists** → every draft would fail | default is now `anthropic/claude-sonnet-5.5` (code, `.env`, `.env.example`); verified with a live 5-token call |
| 5 | Provider health checks spent credits on every refresh (Firecrawl scrape; Hunter `domain-search` probe) | Firecrawl uses free `/team/credit-usage`; Hunter probe cached 1 h |
| 6 | Hunter reveal fell back to `emails[0]` when the requested first name didn't match → could unmask (and bill) the wrong person; also crashed on `first_name: null` | no arbitrary fallback when a person was requested; null-safe |
| 7 | Contacts from the same company with the same masked email (`j***@acme.com`) were de-duplicated away (lost "John Collison" next to "Jane Underwood") | de-duplicate on identity, not on masked email |
| 8 | Crawler: keyword matches ran on the whole URL incl. host (`newsmax-…` = "blog"); `wix.com/`, Facebook tracking pixel and a YouTube *channel link* counted as social profile / embedded video | path-only matching, anchored social regexes, real embed markers |
| 9 | PageSpeed 45 s timeout hit intermittently (live runs take 26–44 s) and reported an empty error | 90 s timeout, error text always populated |
| 10 | `SERPAPI_ENABLED` flag was ignored | honoured like the other providers |
| 11 | Admin UI user activate/deactivate called a non-existent `POST /users/{id}/activate` | now `PATCH /users/{id} {is_active}` |
| 12 | `check_*.py` scripts crashed on Windows (cp1252) printing `★`/`—` | UTF-8 stdout |
| 13 | Duplicate `HunterAdapter.get_usage`, `ProviderStatus.last_checked` default evaluated once at import, misc lint | cleaned |

## 3. Conformance matrix

Legend: ✅ conforms · ⚠️ partial / deviates · ❌ missing · 🔧 fixed during this audit

### Product & pipeline
| poc.md | Status | Evidence / note |
|---|---|---|
| §5 Source → Enrich → Score in ARQ worker, 202 + polling, per-lead fault isolation | ✅ | live E2E: 1/1 succeeded, 18–19 of 22 signals populated |
| Lead source = **Apollo.io** (§1, §6.3, §12) | ⚠️ | project deliberately uses **Hunter.io** (Apollo adapter is a disabled stub). Handbook still says Apollo |
| 5 enrichment collectors in parallel (crawl, PageSpeed, Apollo org, DataForSEO, Places) | ⚠️ | crawl ✅ PageSpeed ✅ DataForSEO/Places off (no keys); Hunter replaces Apollo org; **SerpApi + Firecrawl added** (not in poc) |
| 7-day Redis enrichment cache, 8 pages, 12 s timeout, concurrency 4 | ✅ | crawler constants; cache key now versioned |
| Human gates: approve → reveal → draft → draft-approve → sync | ✅ (code) | gates enforced in routes + tests; reveal/draft/sync not run live |
| Lead state: `pipeline_status` ⟂ `score_band`, band `null` until scored | 🔧 | new leads were stored as `unscored`; now `NULL`. Extra statuses (`enriching`, `scoring`, `drafting`, `disqualified`) exist; no `error`/`rejected` status – rejection uses `approval_status` + `disqualified` |
| Failures keep reason (`error_reason`) | ⚠️ | per-lead failure only logged and counted; no `error_reason` column |

### Scoring engine (§9, §10)
| poc.md | Status | Note |
|---|---|---|
| Exactly 22 signals, names, weights, 10 website + 12 marketing | ✅ | `scoring/catalog.py` + tests |
| Weighted mean over available signals, `None` skipped, "X of 22 available" | ✅ | `available_signals_ratio` |
| Bands `qualified` / `review` / `disqualified` / null | ✅ | legacy `high/medium/low/unscored` enum members remain but are unused |
| Re-score never mutates history (new score row) | ✅ | |
| **Ideal-client bonus** when both groups fire, configurable per engine | 🔧 | was dead code (never passed from DB) and unconditional; now migration `007`, per-engine-version setting (0–100), applied only if website **and** marketing subscores ≥ 50 |
| Engine: `qualified_threshold`/`review_threshold`, `llm_model`, per-signal `enabled`, `vertical` | ⚠️ | thresholds exist as `threshold_high/medium` (+ unused `threshold_low`); weights stored as JSON (weight 0 = off); **no per-engine `llm_model`, `vertical`, or enable flags** |
| Signal methods (§10) | ⚠️ | `stale_blog` / `no_press` now parse post dates (6 mo / 1 yr rule) 🔧. Still simplified vs poc: `old_design` (tables/`<font>` only; no copyright-year/WP-version/Bootstrap3), `poor_seo` (on-page only; poc uses DataForSEO authority), `poor_aeo_geo` (JSON-LD or OG; no location-page/NAP), `hiring` (boolean; poc: ≥5 roles) |
| Weakest-tier honesty (evidence strings shown) | ✅ | |

### Roles, tenancy, auth (§2.2–2.4, §4)
| poc.md | Status | Note |
|---|---|---|
| Roles `super_admin` / `org_admin` / `client_viewer`, RBAC on routes | ✅ | |
| Postgres RLS with **FORCE**, non-superuser runtime role | ✅ | migrations + `test_tenant_security` |
| `X-Org-Context` for super_admin | 🔧 | code used `X-Organization-Id`; poc header now accepted (old one kept). **Web app never sends it** – no org switcher in UI |
| **Operator elevation** (`operator_enabled`; off ⇒ portal only) | ❌ | flag stored as `settings.operator_access` but **enforced nowhere**: every org_admin has the full pipeline. Toggle is now super-admin-only 🔧 (an org admin could elevate itself) |
| Org fields `kind`, `status`, `operator_enabled`, `monthly_lead_quota` | ⚠️ | no columns; `is_active` + `deleted_at`; **quota is a global setting (100), not per-org** |
| Suspend / reactivate / offboard, kill-switch via Redis | ✅ | |
| JWT 15 min / refresh 7 d rotating + blacklist, httpOnly cookies, CSRF | ✅ | |
| Forced password change | ✅ | |
| Forgot password via **security question or Resend link** | ⚠️ | link flow only; no security-question fields; Resend key empty |
| "No public signup" | ⚠️ | project has `/auth/signup` + access-request approval flow (deliberate product change) |
| Login role-aware redirect, route protection middleware | ✅ | viewer → `/portal`; middleware guards routes |
| Client visibility: viewer sees only approved+ leads, no export | ✅ | covered by existing tests |

### Screens & features (§3)
| poc.md | Status |
|---|---|
| Login, Dashboard, Audiences (AI propose), New Search, Pipeline, Lead Detail, Draft Studio, Engine Config, Portal, Admin | ✅ pages exist, all call real APIs (no mocks left) |
| Audience AI-propose from brief (no Apollo spend) | ✅ OpenRouter live-capable. **Document upload / SuperMemory extraction** ❌ (adapter is a stub) |
| Engine **AI propose**, templates/clone, **re-score with band diff** | ❌ (single-lead and bulk re-score only) |
| New Search: pool estimate, engine/audience picker, OR/AND/exclude | ⚠️ filters + exclude + OR/AND implemented in worker; **no pool-estimate endpoint** |
| Bulk approve / reject / archive / unarchive / rescore, CSV+JSON export with formula escaping | ✅ (archive reuses `deleted_at`; no `archived_at`/`include_archived`). **Bulk draft** ❌ |
| Draft Studio: tone (direct / consultative / short), regenerate | ❌ no tone parameter |
| Portal: latest search criteria + engine thresholds/weights summary | ❌ portal lists approved leads only |
| Audit trail | ✅ |

### Quotas, cost, ops (§13, §14, §17–19)
| poc.md | Status | Note |
|---|---|---|
| 500 leads/search, 2 concurrent runs, 100 reveals/day, 200 drafts/day, monthly lead quota | ✅ | `quota_service` + tests |
| Spend quotas fail closed (503) when Redis is down | ✅ | |
| **Per-org monthly LLM spend ceiling checked before each LLM call** | ❌ | usage endpoint only echoes the ceiling (`remaining = ceiling`); nothing is measured |
| tokens / `cost_usd` on drafts and runs; credits used on reveal | ❌ | no such columns |
| Stuck-run reaper, run-slot release | ✅ | worker startup recovery |
| `/readyz` with worker heartbeat | 🔧 | now checks DB + Redis and reports ARQ heartbeat (`health_check_interval=30`) |
| OpenAPI off in production, HSTS/CSP/Referrer-Policy | 🔧 | API side done for `production`; Next.js response headers not configured |
| CI on every PR, dependency scanning, `RUNBOOK.md`, error tracking, alerts | ❌ | no `.github/`, no runbook, no Sentry |
| Env names (`JWT_SECRET`, `OPENROUTER_MODEL`, `LEAD_SOURCE_PROVIDER`, env values `local/staging/demo/production`) | ⚠️ | code uses `JWT_SECRET_KEY`, `OPENROUTER_DEFAULT_MODEL`, no provider-switch vars, `development` |
| 1,500-user scalability | ❌ not demonstrated (only `/healthz` ever load-tested) |

## 4. Verdict

* **Core pipeline works and is faithful to the poc** (source → enrich → 22-signal score → human gates), and now produces more *accurate* signals than before the audit.
* **Not poc-complete.** The largest gaps are (1) operator-mode gating / per-org quotas, (2) LLM cost tracking + spend ceiling, (3) draft tone & cost fields, (4) engine AI-propose / templates / re-score diff, pool estimate, portal summary, (5) security-question recovery, (6) CI / runbook / monitoring.
* Several deviations are **deliberate product changes** (Hunter instead of Apollo, SerpApi + Firecrawl added, self-signup with approval). `poc.md` should be updated to match, or the code reverted – that is your call.

## 5. Provider status after this audit

| Provider | Key | Live result |
|---|---|---|
| Hunter.io | set | account OK (Free plan, **7/50 searches used**); company enrichment, contact discovery working |
| OpenRouter | set (`is_free_tier: true`) | `gpt-4o-mini` and `claude-sonnet-5.5` respond; add credits before heavy draft use |
| Google PageSpeed | set | works; 26–44 s per audit |
| Firecrawl | set | works; 1,315 credits remaining |
| SerpApi | set | works; 209 searches left on the free plan |
| Web crawler | – | works |
| HubSpot, Google Places, DataForSEO, Resend, SuperMemory | empty | skipped gracefully; `low_domain_trust`, `ppc_spend` (and Places fallback) stay unavailable |
