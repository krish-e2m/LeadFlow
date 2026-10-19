import asyncio
import ipaddress
import re
import socket
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
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

        addr_info = socket.getaddrinfo(hostname, None)
        for _, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            ip_obj = ipaddress.ip_address(ip_str)
            for net in DISALLOWED_NETWORKS:
                if ip_obj in net:
                    return False
        return True
    except Exception:
        return False


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
        self, client: httpx.AsyncClient, url: str
    ) -> Optional[Dict[str, Any]]:
        """Attempts Firecrawl first if configured; falls back safely to internal httpx crawler."""
        if self.firecrawl.is_configured():
            try:
                fc_res = await self.firecrawl.scrape_url(url, formats=["markdown", "rawHtml", "links"])
                if fc_res.get("success") and fc_res.get("html"):
                    rendered_html = fc_res["html"]
                    soup = BeautifulSoup(rendered_html, "html.parser")
                    body_text = soup.body.get_text(separator=" ", strip=True) if soup.body else ""
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

        return await self._safe_fetch_page(client, url)

    async def _safe_fetch_page(
        self, client: httpx.AsyncClient, url: str
    ) -> Optional[Dict[str, Any]]:
        """Fetches a single page with SSRF check, redirect validation, and size capping."""
        current_url = url
        for _ in range(5):  # Max 5 redirect hops
            if not is_safe_url(current_url):
                return None

            try:
                response = await client.get(
                    current_url,
                    headers={"User-Agent": "LeadFlowBot/1.0 (+https://leadflow.local)"},
                    follow_redirects=False,
                )
                if response.is_redirect and "location" in response.headers:
                    redirect_target = urljoin(current_url, response.headers["location"])
                    current_url = redirect_target
                    continue

                if response.status_code != 200:
                    return None

                # Check Content-Type & length
                content_type = response.headers.get("content-type", "").lower()
                if "text/html" not in content_type and "application/xhtml" not in content_type:
                    return None

                content_bytes = response.content[: self.MAX_RESPONSE_BYTES]
                html_text = content_bytes.decode(errors="replace")
                soup = BeautifulSoup(html_text, "html.parser")
                body_text = soup.body.get_text(separator=" ", strip=True) if soup.body else ""

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
        """Discovers up to 7 distinct relevant internal pages prioritized by business intent."""
        clean_domain = domain.lower()

        candidate_links: Set[str] = set()
        for a_tag in homepage_soup.find_all("a", href=True):
            href = a_tag["href"].strip()
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue

            resolved = urljoin(base_url, href)
            parsed_res = urlparse(resolved)

            # Check domain match (same domain or subdomain)
            res_host = (parsed_res.hostname or "").lower()
            if res_host != clean_domain and not res_host.endswith(f".{clean_domain}"):
                continue

            if parsed_res.path.lower().endswith(DISALLOWED_EXTENSIONS):
                continue

            clean_url = f"{parsed_res.scheme}://{parsed_res.netloc}{parsed_res.path}"
            if clean_url != base_url and clean_url != f"{base_url}/":
                candidate_links.add(clean_url)

        # Prioritize relevant buckets
        buckets: Dict[str, List[str]] = {
            "careers": [],
            "case_studies": [],
            "about": [],
            "services": [],
            "blog": [],
            "contact": [],
            "other": [],
        }

        career_patterns = re.compile(r"(careers?|jobs?|join|work-with-us|openings)", re.I)
        case_study_patterns = re.compile(r"(case-stud|customers?|success|testimonials?|results)", re.I)
        about_patterns = re.compile(r"(about|company|our-story|team)", re.I)
        service_patterns = re.compile(r"(services?|solutions?|products?|features?)", re.I)
        blog_patterns = re.compile(r"(blog|news|articles?|insights?|press)", re.I)
        contact_patterns = re.compile(r"(contact|reach-us|support)", re.I)

        for link in candidate_links:
            path = urlparse(link).path
            if career_patterns.search(path):
                buckets["careers"].append(link)
            elif case_study_patterns.search(path):
                buckets["case_studies"].append(link)
            elif about_patterns.search(path):
                buckets["about"].append(link)
            elif service_patterns.search(path):
                buckets["services"].append(link)
            elif blog_patterns.search(path):
                buckets["blog"].append(link)
            elif contact_patterns.search(path):
                buckets["contact"].append(link)
            else:
                buckets["other"].append(link)

        selected: List[str] = []
        for bucket in ["careers", "case_studies", "about", "services", "blog", "contact", "other"]:
            for u in buckets[bucket]:
                if u not in selected:
                    selected.append(u)
                if len(selected) >= (self.MAX_PAGES - 1):
                    break
            if len(selected) >= (self.MAX_PAGES - 1):
                break

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

        extracted_signals: Dict[str, Any] = {}

        if not is_safe_url(target_url):
            err_msg = f"Security block: {target_url} resolves to internal or restricted IP."
            provenance["error"] = err_msg
            return self._build_failed_payload(err_msg, provenance)

        crawled_pages: List[Dict[str, Any]] = []
        visited_urls: Set[str] = set()

        try:
            start_time = time.time()
            async with httpx.AsyncClient(timeout=self.TIMEOUT_SECONDS, verify=True) as client:
                # 1. Fetch Homepage
                homepage_data = await self._fetch_with_firecrawl_or_fallback(client, target_url)
                if not homepage_data and target_url.startswith("https://"):
                    # Fallback to HTTP if HTTPS fails
                    http_target = f"http://{base_domain}"
                    if is_safe_url(http_target):
                        homepage_data = await self._fetch_with_firecrawl_or_fallback(client, http_target)

                if not homepage_data:
                    err_msg = f"Unable to reach domain {base_domain} within {self.TIMEOUT_SECONDS}s."
                    provenance["error"] = err_msg
                    return self._build_failed_payload(err_msg, provenance)

                crawled_pages.append(homepage_data)
                visited_urls.add(target_url)
                visited_urls.add(homepage_data["url"])

                provenance["status_code"] = homepage_data["status_code"]
                provenance["ssl_valid"] = homepage_data["url"].startswith("https://")
                provenance["engine"] = homepage_data.get("scraped_by", "httpx")
                if homepage_data.get("markdown"):
                    provenance["markdown"] = homepage_data["markdown"]
                provenance["crawled_urls"].append(homepage_data["url"])

                # 2. Discover Relevant Internal Pages
                discovered_links = self._discover_relevant_links(
                    homepage_data["soup"], homepage_data["url"], base_domain
                )

                # 3. Fetch Discovered Pages concurrently with bounded Firecrawl usage
                # Configurable max subpages to attempt via Firecrawl (prioritizes high-value pages like careers)
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
                    if isinstance(res, dict) and res is not None:
                        crawled_pages.append(res)
                        provenance["crawled_urls"].append(res["url"])

                elapsed_ms = int((time.time() - start_time) * 1000)
                provenance["response_time_ms"] = elapsed_ms
                provenance["pages_crawled_count"] = len(crawled_pages)
                provenance["pages_scraped_by"] = {
                    p["url"]: p.get("scraped_by", "httpx") for p in crawled_pages
                }
                provenance["firecrawl_pages_count"] = sum(
                    1 for p in crawled_pages if p.get("scraped_by") == "firecrawl"
                )

                # 4. Extract Technical & Marketing Signals across all crawled pages
                extracted_signals = self._evaluate_signals_across_pages(
                    crawled_pages, provenance["ssl_valid"], base_domain
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

        combined_html = " ".join(p.get("html", "").lower() for p in pages)
        combined_markdown = " ".join(p.get("markdown", "").lower() for p in pages)
        all_buttons: List[str] = []
        for p in pages:
            if p.get("soup"):
                for b in p["soup"].find_all(["button", "a"]):
                    text = b.get_text().strip().lower()
                    if text:
                        all_buttons.append(text)

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

        # 2. legacy_platform (1.5)
        legacy_detected = False
        legacy_evidence = f"Modern framework detected across {total_pages} crawled pages"
        legacy_source = home_url
        legacy_markers = ["wordpress 4", "wordpress 3", "drupal 7", "joomla", "magento 1", "typo3 4"]

        for p in pages:
            if p.get("soup"):
                generator = p["soup"].find("meta", attrs={"name": "generator"})
                if generator and "content" in generator.attrs:
                    gen_content = generator["content"].lower()
                    if any(m in gen_content for m in legacy_markers):
                        legacy_detected = True
                        legacy_evidence = f"Legacy CMS generator '{generator['content']}' detected"
                        legacy_source = p["url"]
                        break
            if "jquery/1." in p["html"].lower() or "jquery-1." in p["html"].lower():
                legacy_detected = True
                legacy_evidence = "Archaic jQuery 1.x library detected in page source"
                legacy_source = p["url"]
                break

        signals["legacy_platform"] = {
            "value": 1.0 if legacy_detected else 0.0,
            "evidence": legacy_evidence,
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

        # 4. weak_ctas (1.0)
        cta_keywords = [
            "book a demo", "get started", "schedule", "contact us", "free trial",
            "request demo", "talk to sales", "start free", "sign up", "try now"
        ]
        found_cta = None
        cta_source = home_url
        for p in pages:
            if p.get("soup"):
                for b in p["soup"].find_all(["button", "a"]):
                    txt = b.get_text().strip().lower()
                    for kw in cta_keywords:
                        if kw in txt:
                            found_cta = txt
                            cta_source = p["url"]
                            break
                    if found_cta:
                        break
            if found_cta:
                break

        # If not found in DOM elements, inspect clean Markdown action links / callout text across pages
        if not found_cta:
            for p in pages:
                p_md = p.get("markdown", "").lower()
                if p_md:
                    for kw in cta_keywords:
                        if kw in p_md:
                            found_cta = kw
                            cta_source = p["url"]
                            break
                    if found_cta:
                        break

        signals["weak_ctas"] = {
            "value": 0.0 if found_cta else 1.0,
            "evidence": f"High-intent conversion CTA found: '{found_cta}' at {cta_source}"
            if found_cta
            else f"No prominent conversion CTA identified across {total_pages} crawled pages",
            "provider": self.name,
            "source_url": cta_source,
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

        # 6. thin_content (0.7)
        # Use clean Markdown if provided by Firecrawl, falling back to body_text from HTML
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
        analytics_patterns = ["googletagmanager.com", "google-analytics.com", "gtag(", "fbevents.js", "posthog", "segment.com", "heap.js"]
        found_analytics = None
        analytics_source = home_url
        for p in pages:
            for pat in analytics_patterns:
                if pat in p["html"].lower():
                    found_analytics = pat
                    analytics_source = p["url"]
                    break
            if found_analytics:
                break

        signals["no_analytics"] = {
            "value": 0.0 if found_analytics else 1.0,
            "evidence": f"Web analytics script detected ({found_analytics}) at {analytics_source}"
            if found_analytics
            else f"Missing analytics or tag manager scripts across {total_pages} crawled pages",
            "provider": self.name,
            "source_url": analytics_source,
        }

        # 8. accessibility (0.6)
        total_imgs = sum(len(p["soup"].find_all("img")) for p in pages)
        missing_alt = sum(len([img for img in p["soup"].find_all("img") if not img.get("alt")]) for p in pages)
        has_lang = bool(home_soup.find("html", attrs={"lang": True}))
        is_accessible = (missing_alt == 0 or (total_imgs > 0 and (missing_alt / total_imgs) < 0.35)) and has_lang

        signals["accessibility"] = {
            "value": 0.0 if is_accessible else 1.0,
            "evidence": f"Accessibility checks passed: HTML lang present, {total_imgs - missing_alt}/{total_imgs} images have alt tags"
            if is_accessible
            else f"Accessibility issues: {missing_alt}/{total_imgs} images lack alt tags, HTML lang: {has_lang} at {home_url}",
            "provider": self.name,
            "source_url": home_url,
        }

        # 9. no_live_chat (0.5)
        chat_patterns = ["intercom", "drift.com", "crisp.chat", "hubspot-messages", "zendesk", "livechat", "tidio"]
        found_chat = None
        chat_source = home_url
        for p in pages:
            for pat in chat_patterns:
                if pat in p["html"].lower():
                    found_chat = pat
                    chat_source = p["url"]
                    break
            if found_chat:
                break

        signals["no_live_chat"] = {
            "value": 0.0 if found_chat else 1.0,
            "evidence": f"Live chat widget detected ({found_chat}) at {chat_source}"
            if found_chat
            else f"No conversational live chat widget found across {total_pages} crawled pages",
            "provider": self.name,
            "source_url": chat_source,
        }

        # 10. poor_seo (1.4)
        title_tag = home_soup.find("title")
        meta_desc = home_soup.find("meta", attrs={"name": "description"})
        h1_tags = home_soup.find_all("h1")
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

        # 11. poor_aeo_geo (1.0)
        json_ld = home_soup.find_all("script", attrs={"type": "application/ld+json"})
        og_tags = home_soup.find_all("meta", attrs={"property": re.compile(r"^og:")})
        has_schema = len(json_ld) > 0 or len(og_tags) >= 2
        signals["poor_aeo_geo"] = {
            "value": 0.0 if has_schema else 1.0,
            "evidence": f"Structured Schema / OpenGraph data found ({len(json_ld)} JSON-LD blocks, {len(og_tags)} OG tags) at {home_url}"
            if has_schema
            else f"Missing Schema.org JSON-LD microdata at {home_url}",
            "provider": self.name,
            "source_url": home_url,
        }

        # 12. stale_blog (1.1): none, or newest post older than 6 months, is stale
        now_utc = datetime.now(timezone.utc)
        blog_page = next((p for p in pages if re.search(r"(blog|news|articles|insights)", _url_path(p))), None)
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
            has_blog_link = any(kw in combined_html or kw in combined_markdown for kw in ["/blog", "/news", "/articles"])
            signals["stale_blog"] = {
                "value": 0.0 if has_blog_link else 1.0,
                "evidence": "Blog hub link detected on site"
                if has_blog_link
                else f"No active blog or resource hub detected across {total_pages} crawled pages",
                "provider": self.name,
                "source_url": home_url,
            }

        # 13. no_press (0.7): none, or newest release older than 1 year, is flagged
        press_page = next((p for p in pages if re.search(r"(press|newsroom|media)", _url_path(p))), None)
        has_press = bool(press_page or any(kw in combined_html or kw in combined_markdown for kw in ["/press", "/newsroom", "press release"]))
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
        case_page = next((p for p in pages if re.search(r"(case-stud|customers|success|testimonial)", _url_path(p))), None)
        has_cases = bool(case_page or any(kw in combined_html or kw in combined_markdown for kw in ["/case-studies", "/customers", "/testimonials"]))
        signals["no_case_studies"] = {
            "value": 0.0 if has_cases else 1.0,
            "evidence": f"Customer case studies detected at {case_page['url'] if case_page else home_url}"
            if has_cases
            else f"No case studies or customer stories found across {total_pages} crawled pages",
            "provider": self.name,
            "source_url": case_page["url"] if case_page else home_url,
        }

        # 15. no_video (0.5)
        has_video = False
        video_source = home_url
        # Only real embeds count; a footer link to a YouTube channel is not marketing video.
        for p in pages:
            if p.get("soup") and (p["soup"].find_all("video") or any(v in p.get("html", "").lower() for v in VIDEO_EMBED_MARKERS)):
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
        has_email = any(p.get("soup") and p["soup"].find("input", attrs={"type": "email"}) for p in pages) or (
            "newsletter" in combined_html and "subscribe" in combined_html
        )
        signals["weak_email_capture"] = {
            "value": 0.0 if has_email else 1.0,
            "evidence": "Email capture or newsletter form present on site"
            if has_email
            else f"No email capture or lead magnet form found across {total_pages} crawled pages",
            "provider": self.name,
            "source_url": home_url,
        }

        # 18. hiring (1.1)
        # Canonical rule: If careers page found with job listings -> 1.0 (hiring).
        # If careers page found but no listings -> 0.0 (not hiring).
        # If no careers page found -> None (unavailable; do NOT claim company is not hiring).
        careers_page = next((p for p in pages if re.search(r"(careers?|jobs?|openings)", _url_path(p))), None)
        if careers_page:
            c_body = (careers_page.get("body_text") or "").lower()
            c_md = (careers_page.get("markdown") or "").lower()
            c_text = f"{c_body} {c_md}"
            no_jobs_indicators = ["no current openings", "no open positions", "no job openings", "not currently hiring", "no vacancies", "0 open positions"]
            is_explicitly_not_hiring = any(neg in c_text for neg in no_jobs_indicators)

            if is_explicitly_not_hiring:
                has_openings = False
            else:
                job_keywords = ["apply now", "open positions", "current openings", "view jobs", "we are hiring", "job description", "open roles"]
                has_openings = any(kw in c_text for kw in job_keywords) or (
                    bool(careers_page.get("soup")) and len(careers_page["soup"].find_all("a", href=re.compile(r"/jobs?/"))) > 0
                )

            signals["hiring"] = {
                "value": 1.0 if has_openings else 0.0,
                "evidence": f"Active hiring detected: open job listings verified at {careers_page['url']}"
                if has_openings
                else f"Careers page verified at {careers_page['url']}, but no active job openings found",
                "provider": self.name,
                "source_url": careers_page["url"],
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
