// Content for the marketing landing page only. Copy here is reviewed against what the product
// actually does (see docs/poc.md) — nothing here should assert a feature, certification or number
// that the codebase can't back up.

export const NAV_LINKS = [
  { label: "How it works", href: "#how-it-works" },
  { label: "Security", href: "#security" },
] as const;

export const PRODUCT_DROPDOWN_ITEMS = [
  {
    label: "Scoring engine",
    description: "22 website and marketing signals checked per company.",
    dotClassName: "bg-brand-500",
    href: "#how-it-works",
  },
  {
    label: "HubSpot sync",
    description: "Companies, contacts and drafts pushed to HubSpot after approval.",
    dotClassName: "bg-indigo-500",
    href: "#security",
  },
] as const;

export const STEPS = [
  {
    title: "Source",
    body: "Search by industry, location and company size, or paste a list of domains.",
    meta: "0 credits deducted",
  },
  {
    title: "Enrich",
    body: "Each website is crawled and audited for speed, SEO, content and reputation signals.",
    meta: "22 parallel signal checks",
  },
  {
    title: "Score",
    body: "22 weighted signals produce a 0–100 score. Missing data is skipped, never counted as zero.",
    meta: "Weighted algorithmic index",
  },
  {
    title: "Review and sync",
    body: "A person approves every lead before contacts are revealed, drafts are written or HubSpot is updated.",
    meta: "Human-in-the-loop guarantee",
  },
] as const;

export const STATS = [
  { value: "22", badge: null, label: "Audit signals per company" },
  { value: "3", badge: "Full control", label: "Human approvals before any credit spend" },
  { value: "Per org", badge: null, label: "Data isolated with Postgres row-level security" },
] as const;

export const SECURITY_POINTS = [
  {
    title: "Postgres row-level security (RLS)",
    body: "Every tenant's target lists, ICP models and enrichment caches are isolated per organization with Postgres row-level security.",
  },
  {
    title: "Human approval gateway",
    body: "Contacts, emails and HubSpot synchronizations are held in staging until explicitly authorized by an operator.",
  },
] as const;

export const FOOTER_PRODUCT_LINKS = [
  { label: "Scoring engine", href: "#how-it-works" },
  { label: "22-signal index", href: "#how-it-works" },
  { label: "HubSpot sync", href: "#security" },
] as const;

export const FOOTER_SECURITY_LINKS = [
  { label: "Postgres RLS", href: "#security" },
  { label: "Human approval gateway", href: "#security" },
] as const;

// No privacy/terms/subprocessor pages exist yet, so these render as plain (non-clickable) text
// in the footer rather than dead "#" links.
export const FOOTER_LEGAL_ITEMS = ["Privacy policy", "Terms of service", "Subprocessors"] as const;

export type MockSignal = { label: string; value: number; status: string; detail: string };

export type MockCompany = {
  id: "acme" | "nimbus" | "horizon";
  name: string;
  domain: string;
  meta: string;
  initials: string;
  score: number;
  tone: "high" | "mid" | "low";
  statusBadge: string;
  signals: {
    speed: MockSignal;
    seo: MockSignal;
    cadence: MockSignal;
    reputation: MockSignal;
  };
  evidence: string;
  startsApproved: boolean;
};

// Illustrative demo data only — the mockup never calls a real API. "Nimbus Stack Labs" replaces
// the Stitch export's "ScaleAI Systems", which read as a real company name.
export const MOCK_COMPANIES: MockCompany[] = [
  {
    id: "acme",
    name: "Acme Cloud Corp",
    domain: "acmecloud.io",
    meta: "Enterprise SaaS • 240 employees",
    initials: "AC",
    score: 94,
    tone: "high",
    statusBadge: "All 22 tested",
    signals: {
      speed: { label: "Speed (LCP 1.1s)", value: 98, status: "98%", detail: "TTFB 142ms • PageSpeed 99" },
      seo: { label: "SEO structure", value: 92, status: "92%", detail: "Valid JSON-LD • Clean H1 hierarchy" },
      cadence: { label: "Content cadence", value: 86, status: "86%", detail: "Changelog active • Weekly blog articles" },
      reputation: { label: "Reputation", value: 95, status: "95%", detail: "Clean SPF/DMARC records" },
    },
    evidence: "Evidence: Active sitemap, engineering blog updated 2d ago, verified MX records.",
    startsApproved: false,
  },
  {
    id: "nimbus",
    name: "Nimbus Stack Labs",
    domain: "nimbusstack.example",
    meta: "Series B • AI infrastructure",
    initials: "NS",
    score: 88,
    tone: "high",
    statusBadge: "HubSpot mapped",
    signals: {
      speed: { label: "Speed (LCP 1.4s)", value: 90, status: "90%", detail: "TTFB 180ms • PageSpeed 94" },
      seo: { label: "SEO structure", value: 87, status: "87%", detail: "Valid sitemap • Clean heading order" },
      cadence: { label: "Content cadence", value: 82, status: "82%", detail: "Release notes • Recent changelog" },
      reputation: { label: "Reputation", value: 93, status: "93%", detail: "Active DKIM key • Verified domain" },
    },
    evidence: "Evidence: Automated docs crawled, recent release notes, active DKIM key.",
    startsApproved: true,
  },
  {
    id: "horizon",
    name: "Horizon Fintech",
    domain: "horizonfintech.example",
    meta: "Seed • Outdated domain footprint",
    initials: "HF",
    score: 42,
    tone: "low",
    statusBadge: "14 failed signals",
    signals: {
      speed: { label: "Speed (LCP 3.8s)", value: 34, status: "34%", detail: "TTFB 890ms • PageSpeed 41" },
      seo: { label: "SEO structure", value: 45, status: "45%", detail: "Missing H1 • Thin homepage content" },
      cadence: { label: "Content cadence", value: 28, status: "28%", detail: "No posts found in the last 6 months" },
      reputation: { label: "Reputation", value: 61, status: "61%", detail: "Expired certificate on a subdomain" },
    },
    evidence: "Evidence: No blog activity in 180+ days, broken SSL chain on subdomains, expired cert.",
    startsApproved: false,
  },
];

export const AUDIT_STEPS = [
  "Crawling robots.txt and sitemap structure…",
  "Testing LCP, TTFB and Web Vitals speed…",
  "Verifying MX records, SPF and DMARC…",
  "Recalculating the 22-signal weighted index…",
] as const;
