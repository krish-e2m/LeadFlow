import asyncio
import ipaddress
import json
import re
import socket
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.core.config import settings
from app.core.logging import logger
from app.providers.base import BaseProviderAdapter, ProviderStatus
from app.providers.firecrawl import FirecrawlAdapter

# SSRF Disallowed IP Ranges
DISALLOWED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

DISALLOWED_HOSTS = {
    "localhost",
    "metadata.google.internal",
    "instance-data",
}

DISALLOWED_EXTENSIONS = (
    ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
    ".mp4", ".mov", ".zip", ".tar", ".gz", ".exe", ".css", ".js"
)

# "compatible; <bot>" is the convention Googlebot/Bingbot use: still an honest bot identity, but not
# rejected by the many naive filters that block any user agent lacking "Mozilla".
CRAWLER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; LeadFlowBot/1.0; +https://leadflow.local)",
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.8",
}

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_ISO_DATE_RE = re.compile(r"\b(20\d{2}|19\d{2})-(\d{2})-(\d{2})")
_MONTH_FIRST_RE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d{2}|19\d{2})\b",
    re.I,
)
_DAY_FIRST_RE = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?,?\s+(20\d{2}|19\d{2})\b",
    re.I,
)

SOCIAL_PATTERNS = {
    "LinkedIn": re.compile(r"linkedin\.com/(?:company|in)/[\w.%-]+", re.I),
    "X/Twitter": re.compile(r"(?<![\w.-])(?:twitter|x)\.com/(?!share|intent|home|i/)[\w]{2,}", re.I),
    "Facebook": re.compile(r"(?<![\w.-])facebook\.com/(?!tr\b|sharer|plugins|dialog|share)[\w.-]{3,}", re.I),
    "YouTube": re.compile(r"youtube\.com/(?:channel/|c/|user/|@)[\w.-]+", re.I),
}
VIDEO_EMBED_MARKERS = (
    "youtube.com/embed", "youtube-nocookie.com/embed", "player.vimeo.com", "fast.wistia",
    "wistia.com/embed", "loom.com/embed", "loom.com/share",
)

# URL path sections. Matched on whole path segments, so "/newsletter" is not a news page and a
# keyword inside the host name (newsmax.com) never counts.
_BLOG_PATH = re.compile(r"(?:^|/)(?:blog|blogs|news|articles?|insights|resources)(?:/|$|[-_.])", re.I)
_PRESS_PATH = re.compile(r"(?:^|/)(?:press|newsroom|media|press-releases?|in-the-news)(?:/|$|[-_.])", re.I)
_CAREERS_PATH = re.compile(r"(?:^|/)(?:careers?|jobs?|join-us|join|work-with-us|openings|vacancies)(?:/|$|[-_.])", re.I)
_CASE_PATH = re.compile(r"(?:^|/)(?:case-stud\w*|customers?|success-stor\w*|testimonials?|portfolio|our-work|work|results)(?:/|$|[-_.])", re.I)
_ABOUT_PATH = re.compile(r"(?:^|/)(?:about|about-us|company|our-story|team|who-we-are)(?:/|$|[-_.])", re.I)
_SERVICE_PATH = re.compile(r"(?:^|/)(?:services?|solutions?|products?|features?|what-we-do)(?:/|$|[-_.])", re.I)
_CONTACT_PATH = re.compile(r"(?:^|/)(?:contact|contact-us|reach-us|support|get-in-touch)(?:/|$|[-_.])", re.I)

_BLOG_HREF = re.compile(r"href=[\"'][^\"']*/(?:blog|blogs|news|articles?|insights)(?:/|[\"'?#-])", re.I)
_PRESS_HREF = re.compile(r"href=[\"'][^\"']*/(?:press|newsroom|press-releases?)(?:/|[\"'?#-])", re.I)
_CASE_HREF = re.compile(r"href=[\"'][^\"']*/(?:case-stud\w*|customers|testimonials|success-stor\w*|portfolio)(?:/|[\"'?#-])", re.I)

# High-intent conversion phrases. A bare "Contact us" nav link is not one; it only counts when it
# is styled as a button (see _is_button_like).
STRONG_CTA_PHRASES = (
    "book a demo", "request a demo", "request demo", "schedule a demo", "get a demo", "get started",
    "start free", "start your free", "free trial", "sign up", "try now", "try it free", "talk to sales",
    "contact sales", "get a quote", "get a free quote", "request a quote", "free quote", "get pricing",
    "free consultation", "book a consultation", "schedule a consultation", "book a call", "schedule a call",
    "book an appointment", "book appointment", "request an appointment", "schedule an appointment",
    "book now", "buy now", "shop now", "order now", "call now", "call today", "get a proposal",
    "request a proposal", "get an estimate", "free estimate",
)
SOFT_CTA_PHRASES = (
    "contact us", "get in touch", "let's talk", "let’s talk", "talk to us", "work with us",
    "enquire now", "inquire now", "send us a message", "request info",
)
_BUTTON_CLASS = re.compile(r"\b(?:btn|button|cta)\b|btn-|button-|-btn|-button|-cta|cta-", re.I)

ANALYTICS_MARKERS = (
    "googletagmanager.com", "google-analytics.com", "gtag(", "analytics.js", "fbevents.js",
    "connect.facebook.net", "posthog", "segment.com", "segment.io", "heap.js", "heapanalytics",
    "plausible.io", "matomo", "piwik", "_paq.push", "hotjar", "clarity.ms", "mixpanel",
    "js.hs-scripts.com", "js.hs-analytics.net", "usefathom.com", "cdn.usefathom", "umami",
    "snap.licdn.com", "static.ads-twitter.com", "amplitude.com", "fullstory", "mouseflow",
    "statcounter", "cloudflareinsights.com", "simpleanalytics",
)
LIVE_CHAT_MARKERS = (
    "intercom", "drift.com", "driftt.com", "crisp.chat", "hubspot-messages", "js.usemessages.com",
    "zendesk", "zopim", "livechat", "tidio", "tawk.to", "olark", "freshchat", "wchat.freshchat",
    "chatra", "smartsupp", "userlike", "purechat", "podium.com", "birdeye", "gorgias", "helpscout",
    "beacon-v2", "kommunicate", "ada.support", "qualified.com", "liveperson", "lpsnmedia",
    "manychat", "botpress", "chatwoot", "re:amaze", "reamaze", "landbot", "comm100", "jivosite",
    "chat-widget", "chatbot",
)
EMAIL_CAPTURE_MARKERS = (
    "list-manage.com", "mailchimp", "klaviyo", "convertkit", "hbspt.forms", "mailerlite",
    "sendinblue", "brevo", "constantcontact", "substack.com/embed", "beehiiv", "aweber", "getresponse",
)
ATS_MARKERS = (
    "boards.greenhouse.io", "greenhouse.io/embed", "jobs.lever.co", "apply.workable.com", "workable.com",
    "jobs.ashbyhq.com", "bamboohr.com/jobs", "recruitee.com", "smartrecruiters.com", "jobvite.com",
    "breezy.hr", "myworkdayjobs.com", "teamtailor.com", "jazzhr", "applytojob.com", "personio",
)
_LEGACY_GENERATORS = (
    (re.compile(r"wordpress\s+[1-4]\.", re.I), "end-of-life WordPress major version"),
    (re.compile(r"drupal\s+[5-7]\b", re.I), "end-of-life Drupal version"),
    (re.compile(r"joomla", re.I), "Joomla CMS"),
    (re.compile(r"magento\s+1\b", re.I), "end-of-life Magento 1"),
    (re.compile(r"typo3\s+[1-6]\b", re.I), "end-of-life TYPO3 version"),
    (re.compile(r"frontpage|dreamweaver|iweb|golive|netobjects|homestead", re.I), "legacy site builder"),
)
_LEGACY_SOURCE_MARKERS = (
    (re.compile(r"jquery(?:[/-]|(?:\.min)?\.js\?ver=)1\.\d", re.I), "Archaic jQuery 1.x library detected in page source"),
    (re.compile(r"href=[\"'][^\"']+\.cfm(?:[\"'?#])", re.I), "ColdFusion (.cfm) pages detected"),
    (re.compile(r"href=[\"'][^\"']+\.asp(?:[\"'?#])", re.I), "Classic ASP (.asp) pages detected"),
    (re.compile(r"\.swf[\"'?]|shockwave-flash", re.I), "Adobe Flash content detected"),
)

_MICRODATA = re.compile(r"itemtype=[\"']https?://schema\.org/", re.I)

_DNS_CACHE: Dict[str, Tuple[float, bool]] = {}
_DNS_CACHE_TTL_SECONDS = 300.0


def _safe_date(year: int, month: int, day: int) -> Optional[datetime]:
    try:
        return datetime(year, month, day, tzinfo=timezone.utc)
    except ValueError:
        return None


def extract_dates(text: str) -> List[datetime]:
    """Extracts plausible calendar dates (ISO, 'March 3, 2024', '3 March 2024') from free text."""
    found: List[datetime] = []
    for y, m, d in _ISO_DATE_RE.findall(text):
        dt = _safe_date(int(y), int(m), int(d))
        if dt:
            found.append(dt)
    for mon, d, y in _MONTH_FIRST_RE.findall(text):
        dt = _safe_date(int(y), MONTHS[mon[:3].lower()], int(d))
        if dt:
            found.append(dt)
    for d, mon, y in _DAY_FIRST_RE.findall(text):
        dt = _safe_date(int(y), MONTHS[mon[:3].lower()], int(d))
        if dt:
            found.append(dt)
    return found


def latest_content_date(page: Dict[str, Any]) -> Optional[datetime]:
    """Returns the newest non-future publication date discoverable on a page, if any."""
    soup = page.get("soup")
    chunks: List[str] = []
    if soup is not None:
        for t in soup.find_all("time"):
            chunks.append(t.get("datetime") or t.get_text())
        for m in soup.find_all("meta", attrs={"property": re.compile(r"article:(published|modified)_time", re.I)}):
            chunks.append(m.get("content", ""))
    html = page.get("html", "")
    chunks.extend(re.findall(r'"date(?:Published|Modified)"\s*:\s*"([^"]+)"', html))
    chunks.append(page.get("body_text", "") or "")
    chunks.append(page.get("markdown", "") or "")

    now = datetime.now(timezone.utc)
    dates = [d for d in extract_dates(" ".join(chunks)) if d <= now and d.year >= 2000]
    return max(dates) if dates else None


def _url_path(page: Dict[str, Any]) -> str:
    """Path component only, so keywords in the host name (e.g. newsmax.com) never match."""
    return urlparse(page.get("url", "")).path.lower()


def _resolves_to_public_ips(hostname: str) -> bool:
    now = time.monotonic()
    cached = _DNS_CACHE.get(hostname)
    if cached and cached[0] > now:
        return cached[1]
    try:
        addr_info = socket.getaddrinfo(hostname, None)
    except Exception:
        return False
    safe = bool(addr_info)
    for _, _, _, _, sockaddr in addr_info:
        ip_obj = ipaddress.ip_address(sockaddr[0])
        if any(ip_obj in net for net in DISALLOWED_NETWORKS):
            safe = False
            break
    _DNS_CACHE[hostname] = (now + _DNS_CACHE_TTL_SECONDS, safe)
    return safe


def is_safe_url(url: str) -> bool:
    """Validates URL against SSRF, internal IPs, and metadata services."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        hostname = hostname.lower()
        if hostname in DISALLOWED_HOSTS or hostname.endswith((".local", ".internal", ".lan")):
            return False
        return _resolves_to_public_ips(hostname)
    except Exception:
        return False


async def _check_url(url: str) -> bool:
    """is_safe_url resolves DNS with a blocking call; run it off the event loop."""
    return await asyncio.to_thread(is_safe_url, url)


def _parse_html(html_text: str) -> Tuple[BeautifulSoup, str]:
    soup = BeautifulSoup(html_text, "html.parser")
    body_text = soup.body.get_text(separator=" ", strip=True) if soup.body else ""
    return soup, body_text


def _is_button_like(tag: Any) -> bool:
    if tag.name == "button":
        return True
    if tag.name == "input" and (tag.get("type") or "").lower() in ("submit", "button"):
        return True
    classes = " ".join(tag.get("class") or []) if isinstance(tag.get("class"), list) else str(tag.get("class") or "")
    attrs = f"{classes} {tag.get('role') or ''} {tag.get('id') or ''}"
    return bool(_BUTTON_CLASS.search(attrs))


def _jsonld_types(soup: Optional[BeautifulSoup]) -> List[str]:
    if soup is None:
        return []
    types: List[str] = []
    for block in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = block.string or block.get_text() or ""
        try:
            data = json.loads(raw)
        except Exception:
            types.append("unparsed")
            continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                t = node.get("@type")
                if isinstance(t, str):
                    types.append(t)
                elif isinstance(t, list):
                    types.extend(str(x) for x in t)
                if isinstance(node.get("@graph"), list):
                    stack.extend(node["@graph"])
    return types


class WebCrawlerAdapter(BaseProviderAdapter):
    """
    Multi-page technical and marketing crawler.
    - Crawls up to 8 relevant pages per domain.
    - 12-second request timeout.
    - 4-worker concurrency limit.
    - Strict SSRF and redirect destination validation.
    - Evidence extraction with source URL tracking.
    """

    MAX_PAGES = 8
    TIMEOUT_SECONDS = 12.0
    CONCURRENCY_LIMIT = 4
    MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5MB

    def __init__(self):
        super().__init__("web_crawler")
        self.firecrawl = FirecrawlAdapter()

    def is_configured(self) -> bool:
        return True

    async def check_health(self) -> ProviderStatus:
        return ProviderStatus(
            name=self.name,
            is_configured=True,
            is_healthy=True,
            status_message="Multi-page internal crawler operational (concurrency 4, timeout 12s, max 8 pages).",
            last_checked=datetime.now(timezone.utc),
        )

    async def _fetch_with_firecrawl_or_fallback(
        self, client: httpx.AsyncClient, url: str, meta: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """Attempts Firecrawl first if configured; falls back safely to internal httpx crawler."""
        if self.firecrawl.is_configured():
            try:
                fc_res = await self.firecrawl.scrape_url(url, formats=["markdown", "rawHtml", "links"])
                if fc_res.get("success") and fc_res.get("html"):
                    rendered_html = fc_res["html"]
                    soup, body_text = await asyncio.to_thread(_parse_html, rendered_html)
                    if meta is not None:
                        meta["status_code"] = fc_res.get("status_code", 200)
                    return {
                        "url": fc_res.get("url") or url,
                        "status_code": fc_res.get("status_code", 200),
                        "html": rendered_html,
                        "soup": soup,
                        "body_text": body_text,
                        "words": len(body_text.split()),
                        "markdown": fc_res.get("markdown", ""),
                        "metadata": fc_res.get("metadata", {}),
                        "links": fc_res.get("links", []),
                        "scraped_by": "firecrawl",
                    }
                else:
                    logger.info(
                        f"Firecrawl scrape unavailing for {url}, falling back to httpx: {fc_res.get('error')}"
                    )
            except Exception as e:
                logger.warning(f"Firecrawl scrape exception for {url}, falling back to httpx: {str(e)}")

        return await self._safe_fetch_page(client, url, meta)

    async def _safe_fetch_page(
        self, client: httpx.AsyncClient, url: str, meta: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Fetches a single page with SSRF check, redirect validation, and size capping. `meta`, when
        given, records the last HTTP status seen so a blocked site can be told apart from a dead one.
        """
        current_url = url
        for _ in range(5):  # Max 5 redirect hops
            if not await _check_url(current_url):
                return None

            try:
                response = await client.get(current_url, headers=CRAWLER_HEADERS, follow_redirects=False)
                if meta is not None:
                    meta["status_code"] = response.status_code
                if response.is_redirect and "location" in response.headers:
                    current_url = urljoin(current_url, response.headers["location"])
                    continue

                if response.status_code != 200:
                    return None

                content_type = response.headers.get("content-type", "").lower()
                if "text/html" not in content_type and "application/xhtml" not in content_type:
                    return None

                html_text = response.content[: self.MAX_RESPONSE_BYTES].decode(errors="replace")
                soup, body_text = await asyncio.to_thread(_parse_html, html_text)
                return {
                    "url": str(response.url),
                    "status_code": response.status_code,
                    "html": html_text,
                    "soup": soup,
                    "body_text": body_text,
                    "words": len(body_text.split()),
                }
            except Exception:
                return None

        return None

    def _discover_relevant_links(
        self, homepage_soup: BeautifulSoup, base_url: str, domain: str
    ) -> List[str]:
        """
        Picks up to 7 internal pages, taking one from each evidence bucket in turn (careers, blog,
        case studies, press, ...) so a site with many About/Service links still gets its blog and
        careers pages audited. Shallow hub pages (/blog) are preferred over individual posts.
        """
        clean_domain = domain.lower()
        bare_domain = clean_domain[4:] if clean_domain.startswith("www.") else clean_domain

        candidate_links: Set[str] = set()
        for a_tag in homepage_soup.find_all("a", href=True):
            href = a_tag["href"].strip()
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue

            resolved = urljoin(base_url, href)
            parsed_res = urlparse(resolved)
            res_host = (parsed_res.hostname or "").lower()
            if res_host not in (clean_domain, bare_domain) and not res_host.endswith(f".{bare_domain}"):
                continue
            if parsed_res.path.lower().endswith(DISALLOWED_EXTENSIONS):
                continue

            clean_url = f"{parsed_res.scheme}://{parsed_res.netloc}{parsed_res.path}"
            if clean_url.rstrip("/") != base_url.rstrip("/"):
                candidate_links.add(clean_url)

        bucket_patterns = [
            ("careers", _CAREERS_PATH),
            ("blog", _BLOG_PATH),
            ("case_studies", _CASE_PATH),
            ("press", _PRESS_PATH),
            ("about", _ABOUT_PATH),
            ("services", _SERVICE_PATH),
            ("contact", _CONTACT_PATH),
        ]
        buckets: Dict[str, List[str]] = {name: [] for name, _ in bucket_patterns}
        buckets["other"] = []
        for link in sorted(candidate_links, key=lambda u: (urlparse(u).path.count("/"), len(u), u)):
            path = urlparse(link).path
            for name, pattern in bucket_patterns:
                if pattern.search(path):
                    buckets[name].append(link)
                    break
            else:
                buckets["other"].append(link)

        selected: List[str] = []
        order = [name for name, _ in bucket_patterns] + ["other"]
        while len(selected) < self.MAX_PAGES - 1 and any(buckets[name] for name in order):
            for name in order:
                if buckets[name] and len(selected) < self.MAX_PAGES - 1:
                    link = buckets[name].pop(0)
                    if link not in selected:
                        selected.append(link)
        return selected

    async def crawl_domain(self, domain: str) -> Dict[str, Any]:
        """
        Crawls a target domain (up to 8 relevant pages) and extracts 18 canonical signals.
        """
        clean_domain = domain.strip().lower()
        if clean_domain.startswith("https://") or clean_domain.startswith("http://"):
            parsed_d = urlparse(clean_domain)
            base_domain = parsed_d.hostname or clean_domain
            target_url = clean_domain
        else:
            base_domain = clean_domain
            target_url = f"https://{clean_domain}"

        provenance: Dict[str, Any] = {
            "crawled_url": target_url,
            "domain": base_domain,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status_code": None,
            "ssl_valid": False,
            "pages_crawled_count": 0,
            "crawled_urls": [],
        }

        if not await _check_url(target_url):
            err_msg = f"Security block: {target_url} does not resolve to a public address."
            provenance["error"] = err_msg
            provenance["reachable"] = False
            return self._build_failed_payload(err_msg, provenance)

        crawled_pages: List[Dict[str, Any]] = []
        visited_urls: Set[str] = set()

        try:
            start_time = time.time()
            async with httpx.AsyncClient(timeout=self.TIMEOUT_SECONDS, verify=True) as client:
                # 1. Fetch Homepage
                fetch_meta: Dict[str, Any] = {}
                homepage_data = await self._fetch_with_firecrawl_or_fallback(client, target_url, fetch_meta)
                if not homepage_data and target_url.startswith("https://"):
                    http_target = f"http://{base_domain}"
                    if await _check_url(http_target):
                        homepage_data = await self._fetch_with_firecrawl_or_fallback(client, http_target, fetch_meta)

                if not homepage_data:
                    http_status = fetch_meta.get("status_code")
                    if http_status:
                        err_msg = (
                            f"{base_domain} answered HTTP {http_status} and did not serve its homepage "
                            "(it may block automated audits)."
                        )
                    else:
                        err_msg = f"Unable to reach domain {base_domain} within {self.TIMEOUT_SECONDS}s."
                    provenance["error"] = err_msg
                    provenance["http_status"] = http_status
                    provenance["reachable"] = bool(http_status)
                    return self._build_failed_payload(err_msg, provenance)

                crawled_pages.append(homepage_data)
                visited_urls.add(target_url)
                visited_urls.add(homepage_data["url"])

                provenance["status_code"] = homepage_data["status_code"]
                provenance["ssl_valid"] = homepage_data["url"].startswith("https://")
                provenance["reachable"] = True
                provenance["engine"] = homepage_data.get("scraped_by", "httpx")
                if homepage_data.get("markdown"):
                    provenance["homepage_markdown_chars"] = len(homepage_data["markdown"])
                provenance["crawled_urls"].append(homepage_data["url"])

                # 2. Discover Relevant Internal Pages
                # Follow the site where it actually lives (acme.com may redirect to acmecorp.com).
                site_host = urlparse(homepage_data["url"]).hostname or base_domain
                discovered_links = self._discover_relevant_links(
                    homepage_data["soup"], homepage_data["url"], site_host
                )

                # 3. Fetch discovered pages concurrently; Firecrawl only for the first few (credits)
                max_fc_subpages = getattr(settings, "FIRECRAWL_MAX_SUBPAGES", 2)
                sem = asyncio.Semaphore(self.CONCURRENCY_LIMIT)

                async def fetch_subpage_task(u: str, allow_fc: bool) -> Optional[Dict[str, Any]]:
                    async with sem:
                        if allow_fc and self.firecrawl.is_configured():
                            return await self._fetch_with_firecrawl_or_fallback(client, u)
                        return await self._safe_fetch_page(client, u)

                subpage_tasks = []
                for idx, link in enumerate(discovered_links):
                    if link in visited_urls:
                        continue
                    visited_urls.add(link)
                    use_fc = (idx < max_fc_subpages) and self.firecrawl.is_configured()
                    subpage_tasks.append(fetch_subpage_task(link, allow_fc=use_fc))

                subpage_results = await asyncio.gather(*subpage_tasks, return_exceptions=True)

                for res in subpage_results:
                    if isinstance(res, dict):
                        crawled_pages.append(res)
                        provenance["crawled_urls"].append(res["url"])

                provenance["response_time_ms"] = int((time.time() - start_time) * 1000)
                provenance["pages_crawled_count"] = len(crawled_pages)
                provenance["pages_scraped_by"] = {
                    p["url"]: p.get("scraped_by", "httpx") for p in crawled_pages
                }
                provenance["firecrawl_pages_count"] = sum(
                    1 for p in crawled_pages if p.get("scraped_by") == "firecrawl"
                )

            # 4. Signal extraction is CPU-bound HTML work; keep it off the event loop so parallel
            # lead processing isn't stalled behind one large page.
            extracted_signals = await asyncio.to_thread(
                self._evaluate_signals_across_pages, crawled_pages, provenance["ssl_valid"], base_domain
            )

        except Exception as e:
            provenance["error"] = str(e)
            return self._build_failed_payload(str(e), provenance)

        return {
            "signals": extracted_signals,
            "provenance": provenance,
        }

    def _build_failed_payload(self, error: str, provenance: Dict[str, Any]) -> Dict[str, Any]:
        """Returns honest unavailable representation for all 22 signals when crawl fails."""
        from app.scoring.catalog import DEFAULT_SIGNAL_WEIGHTS
        signals: Dict[str, Any] = {}
        for k in DEFAULT_SIGNAL_WEIGHTS.keys():
            signals[k] = {
                "value": None,
                "evidence": f"Crawl failed: {error}",
                "provider": self.name,
                "source_url": None,
            }
        return {"signals": signals, "provenance": provenance}

    def _evaluate_signals_across_pages(
        self, pages: List[Dict[str, Any]], ssl_valid: bool, domain: str
    ) -> Dict[str, Any]:
        """Evaluates 18 canonical crawler signals against multi-page evidence."""
        homepage = pages[0]
        home_soup = homepage["soup"]
        home_url = homepage["url"]
        total_pages = len(pages)

        # Lower-case each page once; every marker check below reuses these.
        lowered = [p.get("html", "").lower() for p in pages]
        combined_html = " ".join(lowered)
        combined_markdown = " ".join(p.get("markdown", "").lower() for p in pages)

        signals: Dict[str, Any] = {}

        # 1. no_ssl (1.2)
        signals["no_ssl"] = {
            "value": 0.0 if ssl_valid else 1.0,
            "evidence": f"HTTPS verified and enforced at {home_url}"
            if ssl_valid
            else f"Missing or insecure SSL/TLS certificate at {home_url}",
            "provider": self.name,
            "source_url": home_url,
        }

        # 2. legacy_platform (1.5): end-of-life CMS generators, legacy server tech, archaic libraries
        legacy_evidence: Optional[str] = None
        legacy_source = home_url
        for p, p_lower in zip(pages, lowered):
            soup = p.get("soup")
            generator = soup.find("meta", attrs={"name": "generator"}) if soup is not None else None
            gen_content = generator.get("content", "") if generator else ""
            if gen_content:
                for pattern, label in _LEGACY_GENERATORS:
                    if pattern.search(gen_content):
                        legacy_evidence = f"Legacy CMS generator '{gen_content}' detected ({label})"
                        legacy_source = p["url"]
                        break
            if not legacy_evidence:
                for pattern, label in _LEGACY_SOURCE_MARKERS:
                    if pattern.search(p_lower):
                        legacy_evidence = label
                        legacy_source = p["url"]
                        break
            if legacy_evidence:
                break

        signals["legacy_platform"] = {
            "value": 1.0 if legacy_evidence else 0.0,
            "evidence": legacy_evidence
            or f"No end-of-life CMS or outdated framework markers across {total_pages} crawled pages",
            "provider": self.name,
            "source_url": legacy_source,
        }

        # 3. old_design (1.0)
        has_old_design = False
        old_evidence = f"Modern semantic layout verified across {total_pages} crawled pages"
        old_source = home_url
        for p in pages:
            if p.get("soup"):
                table_count = len(p["soup"].find_all("table"))
                font_count = len(p["soup"].find_all("font"))
                marquee_count = len(p["soup"].find_all("marquee"))
                if table_count > 6 or font_count > 0 or marquee_count > 0:
                    has_old_design = True
                    old_evidence = f"Archaic design markers found: {table_count} tables, {font_count} <font> tags, {marquee_count} <marquee> tags"
                    old_source = p["url"]
                    break

        signals["old_design"] = {
            "value": 1.0 if has_old_design else 0.0,
            "evidence": old_evidence,
            "provider": self.name,
            "source_url": old_source,
        }

        # 4. weak_ctas (1.0): the homepage is the conversion page, so judge it on its own.
        strong_ctas: List[str] = []
        soft_cta: Optional[str] = None
        if home_soup is not None:
            for el in home_soup.find_all(["a", "button", "input"]):
                txt = (el.get("value") if el.name == "input" else el.get_text(" ", strip=True)) or ""
                txt = txt.strip().lower()
                if not txt or len(txt) > 80:
                    continue
                strong = next((kw for kw in STRONG_CTA_PHRASES if kw in txt), None)
                if strong:
                    if strong not in strong_ctas:
                        strong_ctas.append(strong)
                elif not soft_cta and _is_button_like(el) and any(kw in txt for kw in SOFT_CTA_PHRASES):
                    soft_cta = txt
        home_markdown_lower = homepage.get("markdown", "").lower()
        if not strong_ctas and home_markdown_lower:
            strong_ctas = [kw for kw in STRONG_CTA_PHRASES if kw in home_markdown_lower][:3]

        if strong_ctas:
            cta_value = 0.0
            cta_evidence = f"High-intent conversion CTA found: '{strong_ctas[0]}' at {home_url}"
            if len(strong_ctas) > 1:
                cta_evidence += f" ({len(strong_ctas)} distinct CTAs)"
        elif soft_cta:
            cta_value = 0.0
            cta_evidence = f"Conversion button found: '{soft_cta}' at {home_url} (no high-intent offer such as a demo, quote or trial)"
        else:
            cta_value = 1.0
            cta_evidence = (
                f"No prominent conversion CTA on the homepage {home_url}: no demo, quote, trial or booking "
                "button, and no styled contact button"
            )
        signals["weak_ctas"] = {
            "value": cta_value,
            "evidence": cta_evidence,
            "provider": self.name,
            "source_url": home_url,
        }

        # 5. not_mobile_friendly (0.8)
        viewport_tag = home_soup.find("meta", attrs={"name": "viewport"}) if home_soup else None
        has_responsive_meta = bool(viewport_tag and "width=device-width" in viewport_tag.get("content", "").lower())
        signals["not_mobile_friendly"] = {
            "value": 0.0 if has_responsive_meta else 1.0,
            "evidence": f"Mobile viewport configuration verified at {home_url}"
            if has_responsive_meta
            else f"Missing responsive viewport meta tag at {home_url}",
            "provider": self.name,
            "source_url": home_url,
        }

        # 6. thin_content (0.7): rendered Markdown word count when Firecrawl supplied it
        home_markdown = homepage.get("markdown", "").strip()
        if home_markdown:
            home_words = len(re.findall(r"\b[\w'-]+\b", home_markdown))
            content_format = "rendered Markdown"
        else:
            home_words = homepage.get("words", 0)
            content_format = "HTML body text"

        is_thin = home_words < 250
        signals["thin_content"] = {
            "value": 1.0 if is_thin else 0.0,
            "evidence": f"Thin content: Homepage contains {home_words} words via {content_format} (<250 threshold) at {home_url}"
            if is_thin
            else f"Substantial content verified: {home_words} words via {content_format} on homepage at {home_url}",
            "provider": self.name,
            "source_url": home_url,
        }

        # 7. no_analytics (0.6)
        found_analytics = None
        analytics_source = home_url
        for p, p_lower in zip(pages, lowered):
            found_analytics = next((m for m in ANALYTICS_MARKERS if m in p_lower), None)
            if found_analytics:
                analytics_source = p["url"]
                break

        signals["no_analytics"] = {
            "value": 0.0 if found_analytics else 1.0,
            "evidence": f"Web analytics script detected ({found_analytics}) at {analytics_source}"
            if found_analytics
            else f"Missing analytics or tag manager scripts across {total_pages} crawled pages",
            "provider": self.name,
            "source_url": analytics_source,
        }

        # 8. accessibility (0.6). alt="" is valid for decorative images (WCAG); only a missing
        # alt attribute counts against the page.
        total_imgs = 0
        missing_alt = 0
        for p in pages:
            if p.get("soup") is None:
                continue
            imgs = p["soup"].find_all("img")
            total_imgs += len(imgs)
            missing_alt += sum(1 for img in imgs if img.get("alt") is None)
        has_lang = bool(home_soup.find("html", attrs={"lang": True})) if home_soup is not None else False
        is_accessible = (missing_alt == 0 or (total_imgs > 0 and (missing_alt / total_imgs) < 0.35)) and has_lang

        signals["accessibility"] = {
            "value": 0.0 if is_accessible else 1.0,
            "evidence": f"Accessibility checks passed: HTML lang present, {total_imgs - missing_alt}/{total_imgs} images have alt attributes"
            if is_accessible
            else f"Accessibility issues: {missing_alt}/{total_imgs} images lack alt attributes, HTML lang: {has_lang} at {home_url}",
            "provider": self.name,
            "source_url": home_url,
        }

        # 9. no_live_chat (0.5)
        found_chat = None
        chat_source = home_url
        for p, p_lower in zip(pages, lowered):
            found_chat = next((m for m in LIVE_CHAT_MARKERS if m in p_lower), None)
            if found_chat:
                chat_source = p["url"]
                break

        signals["no_live_chat"] = {
            "value": 0.0 if found_chat else 1.0,
            "evidence": f"Live chat widget detected ({found_chat}) at {chat_source}"
            if found_chat
            else f"No conversational live chat widget found across {total_pages} crawled pages",
            "provider": self.name,
            "source_url": chat_source,
        }

        # 10. poor_seo (1.4): on-page basics (DataForSEO's organic data replaces this when configured)
        title_tag = home_soup.find("title") if home_soup is not None else None
        meta_desc = home_soup.find("meta", attrs={"name": "description"}) if home_soup is not None else None
        h1_tags = home_soup.find_all("h1") if home_soup is not None else []
        seo_issues = []
        if not title_tag or len(title_tag.get_text().strip()) < 15:
            seo_issues.append("short or missing title tag")
        if not meta_desc or len(meta_desc.get("content", "").strip()) < 25:
            seo_issues.append("missing meta description")
        if len(h1_tags) == 0:
            seo_issues.append("missing H1 tag")

        signals["poor_seo"] = {
            "value": 1.0 if seo_issues else 0.0,
            "evidence": f"SEO deficiencies identified: {', '.join(seo_issues)} at {home_url}"
            if seo_issues
            else f"On-page SEO verified (title, meta description, H1 present) at {home_url}",
            "provider": self.name,
            "source_url": home_url,
        }

        # 11. poor_aeo_geo (1.0): structured data answer/generative engines can read. OpenGraph
        # tags are for social previews and don't count.
        schema_types: List[str] = []
        schema_source = home_url
        for p in pages:
            found_types = _jsonld_types(p.get("soup"))
            if found_types:
                schema_types = found_types
                schema_source = p["url"]
                break
        if not schema_types and _MICRODATA.search(combined_html):
            schema_types = ["microdata"]
        has_schema = bool(schema_types)
        shown_types = ", ".join(dict.fromkeys(t for t in schema_types if t != "unparsed")) or "structured data"
        signals["poor_aeo_geo"] = {
            "value": 0.0 if has_schema else 1.0,
            "evidence": f"Schema.org structured data found ({shown_types}) at {schema_source}"
            if has_schema
            else f"No Schema.org JSON-LD or microdata across {total_pages} crawled pages",
            "provider": self.name,
            "source_url": schema_source,
        }

        # 12. stale_blog (1.1): none, or newest post older than 6 months, is stale
        now_utc = datetime.now(timezone.utc)
        blog_page = next((p for p in pages[1:] if _BLOG_PATH.search(_url_path(p))), None)
        if blog_page:
            newest = latest_content_date(blog_page)
            if newest is None:
                signals["stale_blog"] = {
                    "value": 0.0,
                    "evidence": f"Blog/articles section detected at {blog_page['url']} (post dates not detectable)",
                    "provider": self.name,
                    "source_url": blog_page["url"],
                }
            else:
                age_days = (now_utc - newest).days
                is_stale = age_days > 183
                signals["stale_blog"] = {
                    "value": 1.0 if is_stale else 0.0,
                    "evidence": (
                        f"Stale blog: newest post dated {newest.date().isoformat()} ({age_days} days ago, >6 months) at {blog_page['url']}"
                        if is_stale
                        else f"Active blog: newest post dated {newest.date().isoformat()} ({age_days} days ago) at {blog_page['url']}"
                    ),
                    "provider": self.name,
                    "source_url": blog_page["url"],
                }
        else:
            has_blog_link = bool(_BLOG_HREF.search(combined_html)) or any(
                kw in combined_markdown for kw in ("/blog)", "/blog/", "/news)", "/news/", "/articles")
            )
            signals["stale_blog"] = {
                "value": 0.0 if has_blog_link else 1.0,
                "evidence": "Blog hub link detected on site (post dates not checked)"
                if has_blog_link
                else f"No active blog or resource hub detected across {total_pages} crawled pages",
                "provider": self.name,
                "source_url": home_url,
            }

        # 13. no_press (0.7): none, or newest release older than 1 year, is flagged
        press_page = next((p for p in pages[1:] if _PRESS_PATH.search(_url_path(p))), None)
        has_press = bool(press_page or _PRESS_HREF.search(combined_html) or "press release" in combined_html or "press release" in combined_markdown)
        press_value = 0.0 if has_press else 1.0
        press_evidence = (
            f"Press/media section detected at {press_page['url'] if press_page else home_url}"
            if has_press
            else f"No press or media releases detected across {total_pages} crawled pages"
        )
        if press_page:
            newest_press = latest_content_date(press_page)
            if newest_press is not None:
                press_age = (now_utc - newest_press).days
                if press_age > 365:
                    press_value = 1.0
                    press_evidence = (
                        f"No recent press: newest release dated {newest_press.date().isoformat()} "
                        f"({press_age} days ago, >1 year) at {press_page['url']}"
                    )
        signals["no_press"] = {
            "value": press_value,
            "evidence": press_evidence,
            "provider": self.name,
            "source_url": press_page["url"] if press_page else home_url,
        }

        # 14. no_case_studies (0.8)
        case_page = next((p for p in pages[1:] if _CASE_PATH.search(_url_path(p))), None)
        has_cases = bool(case_page or _CASE_HREF.search(combined_html) or "case stud" in combined_markdown)
        signals["no_case_studies"] = {
            "value": 0.0 if has_cases else 1.0,
            "evidence": f"Customer case studies detected at {case_page['url'] if case_page else home_url}"
            if has_cases
            else f"No case studies or customer stories found across {total_pages} crawled pages",
            "provider": self.name,
            "source_url": case_page["url"] if case_page else home_url,
        }

        # 15. no_video (0.5). Only real embeds count; a footer link to a channel is not marketing video.
        has_video = False
        video_source = home_url
        for p, p_lower in zip(pages, lowered):
            if (p.get("soup") is not None and p["soup"].find("video")) or any(v in p_lower for v in VIDEO_EMBED_MARKERS):
                has_video = True
                video_source = p["url"]
                break

        signals["no_video"] = {
            "value": 0.0 if has_video else 1.0,
            "evidence": f"Embedded marketing/explainer video found at {video_source}"
            if has_video
            else f"No embedded product or marketing video detected across {total_pages} crawled pages",
            "provider": self.name,
            "source_url": video_source,
        }

        # 16. weak_social (0.9)
        social_profiles = [name for name, pat in SOCIAL_PATTERNS.items() if pat.search(combined_html)]
        has_social = len(social_profiles) > 0
        signals["weak_social"] = {
            "value": 0.0 if has_social else 1.0,
            "evidence": f"Active social profiles detected ({', '.join(social_profiles)}) on site"
            if has_social
            else f"No corporate social media profiles detected across {total_pages} crawled pages",
            "provider": self.name,
            "source_url": home_url,
        }

        # 17. weak_email_capture (0.6)
        email_marker = next((m for m in EMAIL_CAPTURE_MARKERS if m in combined_html), None)
        has_email = (
            any(p.get("soup") is not None and p["soup"].find("input", attrs={"type": "email"}) for p in pages)
            or ("newsletter" in combined_html and "subscribe" in combined_html)
            or bool(email_marker)
        )
        signals["weak_email_capture"] = {
            "value": 0.0 if has_email else 1.0,
            "evidence": (
                f"Email capture form present on site ({email_marker})"
                if email_marker
                else "Email capture or newsletter form present on site"
            )
            if has_email
            else f"No email capture or lead magnet form found across {total_pages} crawled pages",
            "provider": self.name,
            "source_url": home_url,
        }

        # 18. hiring (1.1)
        # Careers page (or a job-board embed) with listings -> 1.0; careers page without listings ->
        # 0.0; no careers page at all -> None (unavailable; never claim a company is not hiring).
        careers_idx = next((i for i, p in enumerate(pages) if i > 0 and _CAREERS_PATH.search(_url_path(p))), None)
        ats_marker = next((m for m in ATS_MARKERS if m in combined_html), None)
        if careers_idx is not None:
            careers_page = pages[careers_idx]
            c_body = (careers_page.get("body_text") or "").lower()
            c_md = (careers_page.get("markdown") or "").lower()
            c_text = f"{c_body} {c_md}"
            no_jobs_indicators = ["no current openings", "no open positions", "no job openings", "not currently hiring", "no vacancies", "0 open positions"]
            is_explicitly_not_hiring = any(neg in c_text for neg in no_jobs_indicators)

            job_links = 0
            if careers_page.get("soup") is not None:
                job_links = len(careers_page["soup"].find_all("a", href=re.compile(r"/(?:jobs?|positions?|openings?)/[\w-]+", re.I)))
            if is_explicitly_not_hiring:
                has_openings = False
            else:
                job_keywords = ["apply now", "open positions", "current openings", "view jobs", "we are hiring", "we're hiring", "job description", "open roles"]
                has_openings = (
                    any(kw in c_text for kw in job_keywords)
                    or job_links > 0
                    or any(m in lowered[careers_idx] for m in ATS_MARKERS)
                )

            evidence = (
                f"Active hiring detected: open job listings verified at {careers_page['url']}"
                + (f" ({job_links} job links)" if job_links else "")
                if has_openings
                else f"Careers page verified at {careers_page['url']}, but no active job openings found"
            )
            signals["hiring"] = {
                "value": 1.0 if has_openings else 0.0,
                "evidence": evidence,
                "provider": self.name,
                "source_url": careers_page["url"],
            }
        elif ats_marker:
            signals["hiring"] = {
                "value": 1.0,
                "evidence": f"Active hiring detected: job board embed ({ats_marker}) found on site",
                "provider": self.name,
                "source_url": home_url,
            }
        else:
            signals["hiring"] = {
                "value": None,
                "evidence": f"No careers page detected across {total_pages} crawled pages; hiring status unverified on domain",
                "provider": self.name,
                "source_url": None,
            }

        # Unconfigured external signals: returned as None (unavailable) from crawler
        for k, prov in [
            ("slow_site", "google_pagespeed"),
            ("low_domain_trust", "dataforseo"),
            ("ppc_spend", "dataforseo"),
            ("low_review_rating", "google_places"),
        ]:
            signals[k] = {
                "value": None,
                "evidence": f"Requires external provider ({prov})",
                "provider": prov,
                "source_url": None,
            }

        return signals
