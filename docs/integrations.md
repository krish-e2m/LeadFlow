# LeadFlow External Integrations & Provider Adapters

## 1. Provider Adapter Architecture

All third-party interactions are strictly isolated behind the `BaseProviderAdapter` interface in `app/providers/base.py`. This ensures:
1. Business logic depends on unified internal schemas, never proprietary third-party schemas.
2. Unconfigured providers fail gracefully without blocking the pipeline.
3. Every external call is logged with provider provenance (timestamp, endpoint, response status, duration).
4. No runtime mocks are used in production code; live adapters report `is_configured = False` when credentials are absent.

---

## 2. Integration Matrix

| Provider | Purpose | Authentication | Missing Credentials Behavior |
| :--- | :--- | :--- | :--- |
| **Apollo.io** | Sourcing company leads & discovering contacts | `APOLLO_API_KEY` header | Fails search explicitly if used as primary source; reveals blocked |
| **Web Crawler** | Direct HTML, SSL, meta-tag, & technology inspection | None (HTTP/HTTPS client) | Always available (internal HTTP client) |
| **Google PageSpeed** | Page speed, performance score, Core Web Vitals | `PAGESPEED_API_KEY` query param | Skips metrics (`None`); marks signal unavailable |
| **Google Places** | Local presence, reviews, ratings, physical address | `GOOGLE_PLACES_API_KEY` | **Gracefully unconfigured**: Sets review signals to `None` |
| **DataForSEO** | Domain trust, organic keywords, backlink strength | Basic Auth (`DATAFORSEO_LOGIN`, `PASSWORD`) | **Gracefully unconfigured**: Sets domain trust/SEO to `None` |
| **OpenRouter** | AI reasoning, audit interpretation, draft generation | Bearer `OPENROUTER_API_KEY` | Draft generation disabled until configured |
| **HubSpot** | Contact upsert, company creation, draft note logging | Bearer `HUBSPOT_ACCESS_TOKEN` | CRM sync disabled until configured |
| **Resend** | Transactional emails (password reset, alerts) | Bearer `RESEND_API_KEY` | Skips email dispatch; logs warning |
| **SuperMemory** | Long-term organizational memory / past context | `SUPERMEMORY_API_KEY` | Optional feature disabled |

---

## 3. The 22-Signal Catalog & Provider Mapping

The scoring engine aggregates 22 signals categorized into Website and Marketing. Missing data from unconfigured providers is captured as `None` and omitted from the denominator during normalized scoring.

### Website Signals (10 Signals)
| Signal Key | Weight | Primary Provider | Description & Rule |
| :--- | :--- | :--- | :--- |
| `legacy_platform` | 1.5 | Web Crawler | WordPress <5.0, Drupal 7, Magento 1, outdated CMS detected |
| `slow_site` | 1.3 | Google PageSpeed | PageSpeed score < 50 or First Contentful Paint > 3.0s |
| `old_design` | 1.0 | Web Crawler | Non-responsive layout, deprecated HTML4 tags, table layouts |
| `weak_ctas` | 1.0 | Web Crawler | No distinct booking/demo/call-to-action buttons in hero |
| `not_mobile_friendly`| 0.8 | Google PageSpeed | Missing viewport meta tag, mobile friendliness audit failed |
| `no_ssl` | 1.2 | Web Crawler | Site redirects to HTTP or lacks valid TLS certificate |
| `thin_content` | 0.7 | Web Crawler | Word count under 250 words on homepage or missing value prop |
| `no_analytics` | 0.6 | Web Crawler | Absence of GA4, GTM, Meta Pixel, PostHog, or Segment scripts |
| `accessibility` | 0.6 | Google PageSpeed | Lighthouse accessibility score below 60 |
| `no_live_chat` | 0.5 | Web Crawler | Absence of Intercom, Drift, HubSpot Chat, Crisp widget |

### Marketing Signals (12 Signals)
| Signal Key | Weight | Primary Provider | Description & Rule |
| :--- | :--- | :--- | :--- |
| `poor_seo` | 1.4 | DataForSEO / Crawler| Missing meta description, missing canonical, low rank |
| `poor_aeo_geo` | 1.0 | Crawler / DataForSEO| Missing schema.org structured JSON-LD data |
| `low_domain_trust` | 0.6 | DataForSEO | Low domain authority or toxic backlink ratio |
| `stale_blog` | 1.1 | Web Crawler | Most recent blog post published > 12 months ago |
| `no_press` | 0.7 | Web Crawler | No news, press releases, or media mentions section |
| `no_case_studies` | 0.8 | Web Crawler | No customer proof, testimonials, or case study links |
| `no_video` | 0.5 | Web Crawler | Absence of embedded video content (Wistia, YouTube, Loom) |
| `weak_social` | 0.9 | Web Crawler | No LinkedIn, Twitter/X, or active social links detected |
| `weak_email_capture`| 0.6 | Web Crawler | No newsletter, lead magnet, or newsletter signup form |
| `ppc_spend` | 1.2 | DataForSEO / Apollo | Active ad spend detected (high intent prospect) |
| `hiring` | 1.1 | Apollo / Crawler | Open job positions detected on careers page |
| `low_review_rating` | 0.8 | Google Places | Google review rating below 3.8 stars (indicates operational pain) |

---

## 4. HubSpot (free CRM plan)

LeadFlow uses only what the free HubSpot CRM includes: a Private App token, standard **companies**,
**contacts** and **notes**, and the CRM search API. No custom properties, custom objects, deals,
workflows or sequences are used, so nothing needs a paid tier.

**Setup**: create a Private App with scopes `crm.objects.contacts.read/write` and
`crm.objects.companies.read/write`; set `HUBSPOT_ACCESS_TOKEN`, `HUBSPOT_PORTAL_ID` and
`HUBSPOT_ENABLED=true`.

**Gates (poc.md)**: the lead must be approved, a draft must be supplied and approved, and only a
*revealed* contact email is ever sent. Without a revealed contact, the company and the note are still synced.

**Sync flow** (about 6 requests; free private apps allow 100 requests per 10 s and 250,000 per day,
and a 429 is retried once after `Retry-After`):
1. **Company**: search by normalized domain (`www.` and scheme stripped). Create it if missing; if it exists,
   fill only *empty* properties (name, city, country, employee count). Existing CRM data is never overwritten.
2. **Contact**: search by email, create or fill empty properties (first name, last name, job title); a 409 on create re-uses the record that appeared meanwhile.
3. **Associate** the contact to the company (default v4 association).
4. **Note**: log the approved draft, with the LeadFlow score and top findings, as a note on the company and contact. All text is HTML-escaped.
5. **Record**: `crm_syncs` stores the HubSpot ids and an `idempotency_key` (`hubspot:<lead>:<draft>`).

**Idempotency**: syncing the same lead and draft again returns the stored record (`already_synced: true`) and
does not call HubSpot, so no second note is created. A failed attempt is saved with its error and retry count.

**Existing CRM check**: when an audience sets `exclude_existing_crm`, sourced domains that already exist as
HubSpot companies are skipped (one search request per 100 domains).
