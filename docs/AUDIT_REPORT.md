# LeadFlow POC audit — 19 October 2026

Full pass over the codebase against `docs/poc.md`: find logic errors and misunderstandings, fix
them, improve the scoring engine, make the POC faster and smoother. Things that need your accounts,
money or a product decision were **not** changed; they are listed in section 6.

**Result:** 25 bugs fixed (section 2), 5 scoring-engine improvements, 7 speed/UX improvements.
**Tests:** all 231 backend tests pass, run with every provider key blanked (0 credits spent).
**Nothing committed or pushed.** One new database migration (`010`) must be run on Render after you
deploy (section 7).

---

## 1. Credit savings (biggest practical win)

Hunter's free plan is 50 credits/month. Per Hunter's docs, Discover is free, Domain Search costs
~1 credit per domain and Company Enrichment ~0.2. The search pipeline was spending credits
automatically on every company it found — against poc.md §3.1 rule 1 ("credit-spending actions
require explicit human action — never silent auto-batch spend").

| What was happening | Now |
|---|---|
| Contact lookup (Hunter Domain Search, ~1 credit) ran for **every** sourced lead, including disqualified ones, and again on every re-run of the same search | Only for leads that land in **Review or Qualified**, and only if the lead has no contacts yet |
| Company lookup fell back to Domain Search (1 credit) whenever Company Enrichment (0.2) found nothing | Fallback disabled inside the pipeline; lookup skipped when industry, size and country are already known |
| SerpApi, Google Places, DataForSEO and Hunter were called for domains that don't exist | Paid collectors run only after the free crawl confirms the site answers |
| A failed crawl was cached for 7 days, pinning "unreachable" on a site that was only briefly down | Only real audits are cached |
| Re-running a search re-collected leads that were already audited | A lead audited in the last 7 days is re-scored from saved evidence; approved / rejected / drafted / synced leads are skipped entirely |

Rough illustration for a 25-company search where about a third score Review/Qualified:
**before ≈ 30–50 Hunter credits** (most of the month), **after ≈ 13** (25 × 0.2 + ~8 × 1).
Dead domains now cost nothing beyond the free crawl.

## 2. Bugs fixed

**Pipeline / data integrity**
1. **A new search reset leads people had already acted on.** If a search found a domain that was
   already approved, drafted or synced, enrichment overwrote its stage back to "scored". Those leads
   are now skipped (`app/core/constants.py` `POST_REVIEW_STATUSES`, `app/jobs/search_tasks.py`,
   `app/services/enrichment_service.py`).
2. **Failed leads silently disappeared.** A per-lead failure rolled back the whole lead, so an
   unreachable site never showed up anywhere. poc.md §5.2 defines an `error` stage with
   `error_reason`; it now exists (migration `010_lead_error_reason.py`) and the UI shows the reason.
3. **Runs killed by the job timeout stayed "running" forever.** That kept the org's concurrent-run
   slot and part of its monthly quota reserved until the worker restarted. Interrupted runs are now
   marked failed.
4. **Searches over ~40–50 leads could never finish.** Leads were processed one at a time
   (~30–40 s each, mostly waiting on PageSpeed), so they hit the 30-minute job limit. Now 4 in
   parallel (`SEARCH_LEAD_CONCURRENCY`).
5. **The GitHub Actions burst worker was killed after 10 minutes** while a search may legitimately
   run 30. Raised to 35 minutes, with pip caching (`.github/workflows/worker-burst.yml`).
6. **Hunter headcount "11-50" would crash the insert** into the integer `employee_count` column,
   and long industry text could overflow its column. Values are now coerced and clipped.
7. **"Match all verticals" (AND) dropped every Hunter Discover result.** Discover returns no
   industry data, so nothing could match. Companies Hunter already filtered by industry are kept.
8. **Typed-in domains got industry "Direct Input"**, which stopped Hunter from filling the real
   industry and made audience vertical filters drop them.
9. **SerpApi took the first Google Maps result even if it was another business**, so a lead could
   inherit someone else's rating. The listing must now match the website (or the name when the
   listing has no website); review counts like "1,234" now parse (`app/providers/serpapi.py`).
10. **Quota rejected a 25-lead search when 20 leads were left.** It now runs with the 20 and says
    so; it only refuses when the month is used up (poc.md §3.1 rule 9).
11. **Archived leads could never be restored** (the list hid them, so nothing could be selected).
    New Archived tab with Restore; export supports `include_archived` (poc.md §3.1 rule 4).
12. **Re-scoring a lead with no audit data returned a 500.** Now a clear 409 message, and
    re-scoring an error-stage lead no longer flips it to "scored" with no score.

**Signal accuracy (crawler, `app/providers/crawler.py`)** — these false readings inflated scores:

13. `/newsletter` links counted as a blog/news section; blog, press, careers and case-study paths now
    match whole path segments.
14. A plain "Contact us" nav link counted as a strong conversion CTA. CTAs are now judged on the
    homepage: demo/quote/trial/booking phrases (including local-business ones like "free
    consultation", "book an appointment") or a contact link styled as a button.
15. Decorative images with `alt=""` (valid per WCAG) counted as missing alt text.
16. OpenGraph tags counted as AEO/GEO structured data; now only Schema.org JSON-LD/microdata counts,
    and the detected types are shown as evidence.
17. Short vendor lists made "no analytics" / "no live chat" fire on sites using Hotjar, Clarity,
    Matomo, HubSpot tracking, Tawk.to, Freshchat, Podium, etc. Both lists expanded; email-capture
    and job-board (Greenhouse, Lever, Workable…) embeds also recognized.
18. The 7 sub-page slots filled up with About/Service links, so blog, press and careers pages were
    often never crawled (making stale-blog / press / hiring guesses). Pages are now picked one per
    category in turn. Page discovery also follows a redirect to another domain.
19. The bot user agent `LeadFlowBot/1.0` is blocked by many simple filters. It now uses the
    Googlebot-style form `Mozilla/5.0 (compatible; LeadFlowBot/1.0; …)` — still honestly a bot.
    Legacy-platform detection gained ColdFusion, classic ASP, Flash, old WordPress/Drupal/TYPO3
    versions and old site builders.

**Other**
- **The frontend's `src/lib` folder was never in git.** The Python build pattern `lib/` in
  `.gitignore` also matched `apps/web/src/lib/`, so the API client, auth context and helpers were
  missing from the repo on GitHub and a Vercel build would fail with "module not found". The rule
  now excludes that folder and the files are committed.
- `ruff check app` (the CI lint step) had 9 errors, so CI would fail on its first run; fixed.
- Unexpected Google OAuth errors were swallowed with no log line; they are now logged.
- The lead list labelled bands "Qualified (75+)" etc., but thresholds are configurable per engine;
  labels are now plain.
- The AI draft prompt cited the first 4 detected signals in catalog order (and could cite a
  disabled one); it now cites the strongest pain points first.
- DataForSEO parsing read the wrong level of the response (likely "poor SEO" for everyone) and
  judged PPC by keyword count instead of poc.md's ">$1k/month" rule. Fixed to accept the documented
  shape — **not verified live** (DataForSEO isn't configured on your account).

## 3. Scoring engine improvements (`app/scoring/engine.py`)

1. **Always the full 22-signal catalog.** Engines saved with partial or stray weights (older data)
   are normalized, so "X of 22" can never shrink.
2. **Weight 0 switches a signal off** (poc.md J4 "enable/weight signals"). Disabled signals are
   excluded from the score, the counts, the pain points and the drafts, and show "Disabled" in the
   breakdown. The Engines slider now goes down to 0 ("Off") and up to 5, matching the API.
3. **Thin evidence can't auto-qualify.** A Qualified-level score built on fewer than 6 signals with
   data is held in **Review** with an explanation (`SCORING_MIN_SIGNALS_FOR_QUALIFIED`). The score
   number itself is unchanged; normal crawls produce 15+ signals, so this only catches near-empty
   audits.
4. **Pain points ranked by impact** (weight × value), used in the explanation and the AI draft.
5. **Re-score with band diff** (poc.md J4): a "Re-score leads" button on the Engines page applies
   the published version to the latest 100 leads using saved evidence (no credits) and shows the
   shift, e.g. "Qualified 4 → 5, Disqualified 6 → 5". Bulk re-score on the Leads page shows the same.

## 4. Speed and smoothness

- **~3–4× faster searches** (estimate): 4 leads in parallel, so PageSpeed's 20–40 s wait per lead
  overlaps instead of adding up. Paid collectors run while PageSpeed is still working.
- Dead domains no longer wait for PageSpeed (it is cancelled).
- DNS lookups and HTML parsing moved off the event loop, and DNS results are cached per host for
  5 minutes, so parallel leads don't stall each other.
- Lead detail returns only the newest enrichment (older versions and full homepage Markdown were
  sent on every open and never shown); homepage Markdown is no longer stored at all.
- **Leads are ranked by score** — the "ranked funnel" poc.md promises — with a Score column and a
  "Highest score / Newest" sort.
- New Search warns when the monthly quota trimmed the search.
- Error-stage leads show why ("Unable to reach domain…") in the table tooltip and the lead sheet,
  and can't be quick-approved by accident.

## 5. How this was tested (0 credits)

- Every test ran through a wrapper that **blanks all provider keys** and points Redis at a separate
  database (index 15). The second part matters: your local `leadflow_worker` container runs with
  your real keys, so a test that queued a real job on the normal queue could have spent credits.
- New tests: `tests/test_pipeline_improvements.py` (approved lead not reset, unreachable site →
  error stage with no paid calls, contacts only for Review/Qualified, parallel processing and
  de-duplication, interrupted run marked failed, SerpApi matching, headcount parsing) and five
  engine tests in `tests/test_scoring_engine.py`, all with mocked providers.
- Four existing tests were updated because they encoded the old behaviour on purpose: three
  expected a 2-signal lead to be Qualified (now held in Review — the tests now switch the guard off
  where they test something else), and one expected a 429 for a partially used quota (now trimmed;
  the test also checks the exhausted case still returns 429).
- Results: all 231 backend tests pass; `ruff check app` clean; frontend `tsc --noEmit` and
  `eslint` clean.
- **Browser check** on a throwaway local org (created for the check and removed afterwards):
  score ranking, error-stage lead and its message, archive → Archived tab → Restore, weight slider
  "Off", publish a version, "Re-score leads" (13 leads, Qualified 4 → 5). No search was run and no
  lead approved in the browser, since both would spend real credits through the dev worker.
- **Not verified live:** real provider responses for the changed SerpApi matching and DataForSEO
  parsing (unit-tested with fixtures only), and `next build` (skipped so the dev server you have
  running on port 3000 wasn't disturbed; typecheck and lint pass).

## 6. Needs your decision or contribution (not changed)

| Item | Why it's yours |
|---|---|
| **Rotate the exposed API keys**, plus the Neon admin password pasted in chat | Only you can do it in each provider's dashboard |
| **Operator on/off is saved but never enforced** (poc.md §2.2) | Enforcing it would instantly lock every existing org admin out of the pipeline (all orgs default to off). Needs a decision on defaults first |
| Self-serve signup, Google auto-provisioning and sending outreach email from LeadFlow | poc.md §22 lists all three as out of scope; keep or remove is a product call |
| LLM monthly spend ceiling is displayed but not enforced; dashboard "credits limit 500" is a placeholder | Needs OpenRouter cost tracking (a feature, not a fix) and a real limit from you |
| DataForSEO and Google Places not configured (2 signals unavailable) | Paid accounts |
| Firecrawl uses up to 3 credits per new domain (homepage + 2 sub-pages) | Set `FIRECRAWL_MAX_SUBPAGES=0` to cut it to 1 if credits run short |
| New Search has no engine picker (poc.md J1 step 4); searches use the org's first engine | Feature work; fine while each org has one engine |
| Still missing from poc.md: draft tone options, pool estimate, security-question recovery, RUNBOOK.md, monitoring/backups | Feature work, listed in `docs/DEPLOYMENT.md` §6 |

## 7. Deploying these changes

1. Review the diff, then commit and push when you're ready (nothing has been committed).
2. Render rebuilds the API automatically on push. Then, in the Render **Shell** tab, run:
   ```bash
   cd /app && PYTHONPATH=/app alembic upgrade head
   ```
   This adds `leads.error_reason` (migration `010`). Skipping it breaks every lead query.
3. The GitHub Actions worker checks out the repo on each run, so it picks up the new pipeline by
   itself.
4. The enrichment cache version moved to `v3` because the crawler's signals changed. Domains
   cached in the last 7 days will be audited once more the next time a search finds them (the crawl
   is free; paid collectors run once more for those domains).
5. Optional new settings (defaults are fine): `SEARCH_LEAD_CONCURRENCY=4`,
   `SCORING_MIN_SIGNALS_FOR_QUALIFIED=6` — documented in `.env.example`.

## 8. Files changed

**Backend** — `app/scoring/engine.py`, `app/services/{scoring_service, enrichment_service,
quota_service, search_service, google_auth_service}.py`, `app/jobs/search_tasks.py`,
`app/providers/{crawler, serpapi, dataforseo, hunter, openrouter}.py`,
`app/api/v1/{leads, searches, auth, drafts, engines}.py`, `app/repositories/lead_repo.py`,
`app/schemas/lead.py`, `app/models/lead.py`, `app/core/{config, constants}.py`,
new `alembic/versions/010_lead_error_reason.py`.

**Frontend** — `app/(dashboard)/leads/page.tsx`, `leads/[id]/page.tsx`, `engines/page.tsx`,
`searches/new/page.tsx`, `components/{LeadSheet, SignalBreakdown}.tsx`, `lib/utils.ts`,
`types/index.ts`.

**Tests** — new `tests/test_pipeline_improvements.py`; updated `test_scoring_engine.py`,
`test_enrichment_collectors.py`, `test_business_workflows.py`, `test_tenant_security.py`.

**Config** — `.github/workflows/worker-burst.yml`, `.env.example`, `.gitignore` (and the previously untracked `apps/web/src/lib/`).
