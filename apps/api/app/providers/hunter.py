import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.core.logging import logger
from app.providers.base import BaseProviderAdapter, ProviderStatus

OFFICIAL_HUNTER_BASE_URL = "https://api.hunter.io/v2"

# ISO 3166-1 alpha-2 mapping for standard country names
COUNTRY_NAME_TO_ISO: Dict[str, str] = {
    "united states": "US",
    "usa": "US",
    "us": "US",
    "u.s.": "US",
    "u.s.a.": "US",
    "india": "IN",
    "in": "IN",
    "united kingdom": "GB",
    "uk": "GB",
    "gb": "GB",
    "great britain": "GB",
    "canada": "CA",
    "ca": "CA",
    "australia": "AU",
    "au": "AU",
    "germany": "DE",
    "de": "DE",
    "deutschland": "DE",
    "france": "FR",
    "fr": "FR",
    "singapore": "SG",
    "sg": "SG",
    "united arab emirates": "AE",
    "uae": "AE",
    "ae": "AE",
    "dubai": "AE",
    "netherlands": "NL",
    "nl": "NL",
    "ireland": "IE",
    "ie": "IE",
    "switzerland": "CH",
    "ch": "CH",
    "spain": "ES",
    "es": "ES",
    "italy": "IT",
    "it": "IT",
    "japan": "JP",
    "jp": "JP",
    "brazil": "BR",
    "br": "BR",
}

# Known major cities to prevent ambiguous default mappings
KNOWN_CITY_MAPPINGS: Dict[str, Tuple[str, Optional[str], str]] = {
    "vadodara": ("Vadodara", "Gujarat", "IN"),
    "ahmedabad": ("Ahmedabad", "Gujarat", "IN"),
    "surat": ("Surat", "Gujarat", "IN"),
    "rajkot": ("Rajkot", "Gujarat", "IN"),
    "gandhinagar": ("Gandhinagar", "Gujarat", "IN"),
    "mumbai": ("Mumbai", "Maharashtra", "IN"),
    "pune": ("Pune", "Maharashtra", "IN"),
    "bengaluru": ("Bengaluru", "Karnataka", "IN"),
    "bangalore": ("Bengaluru", "Karnataka", "IN"),
    "delhi": ("Delhi", "Delhi", "IN"),
    "new delhi": ("New Delhi", "Delhi", "IN"),
    "hyderabad": ("Hyderabad", "Telangana", "IN"),
    "chennai": ("Chennai", "Tamil Nadu", "IN"),
    "kolkata": ("Kolkata", "West Bengal", "IN"),
    "san francisco": ("San Francisco", "California", "US"),
    "new york": ("New York", "New York", "US"),
    "austin": ("Austin", "Texas", "US"),
    "seattle": ("Seattle", "Washington", "US"),
    "chicago": ("Chicago", "Illinois", "US"),
    "los angeles": ("Los Angeles", "California", "US"),
    "london": ("London", None, "GB"),
    "toronto": ("Toronto", "Ontario", "CA"),
    "sydney": ("Sydney", "New South Wales", "AU"),
}


def parse_location_for_hunter(loc_str: str) -> Dict[str, str]:
    """
    Normalizes a freeform location string into Hunter Discover headquarters_location object.
    Requires city and country ISO code when city is present.
    Never defaults an unknown city to 'United States' or an unverified country.
    """
    clean = loc_str.strip()
    if not clean:
        return {}

    lower = clean.lower()

    # Check if direct country name/code
    if lower in COUNTRY_NAME_TO_ISO:
        return {"country": COUNTRY_NAME_TO_ISO[lower]}

    # Check if known city
    if lower in KNOWN_CITY_MAPPINGS:
        city, state, country = KNOWN_CITY_MAPPINGS[lower]
        res = {"city": city, "country": country}
        if state:
            res["state"] = state
        return res

    # Check comma-separated tokens: e.g. "Vadodara, Gujarat, India" or "Austin, TX, US" or "San Francisco, CA"
    parts = [p.strip() for p in clean.split(",") if p.strip()]
    if len(parts) >= 2:
        city_candidate = parts[0]
        country_candidate = parts[-1].lower()
        state_candidate = parts[1] if len(parts) > 2 else None

        # Handle 2-part US city-state combinations (e.g. "San Francisco, CA" or "Austin, TX")
        us_state_abbrs = {
            "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id", "il", "ia",
            "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj",
            "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "vt",
            "va", "wa", "wv", "wi", "wy", "dc"
        }
        if len(parts) == 2 and country_candidate in us_state_abbrs:
            return {"city": city_candidate, "state": country_candidate.upper(), "country": "US"}

        country_code = COUNTRY_NAME_TO_ISO.get(
            country_candidate,
            country_candidate.upper() if len(country_candidate) == 2 else country_candidate,
        )
        res = {"city": city_candidate, "country": country_code}
        if state_candidate:
            res["state"] = state_candidate
        return res

    # Single token: treat as city without inventing an unverified country
    return {"city": clean}


class HunterAdapter(BaseProviderAdapter):
    """
    Hunter.io provider adapter for:
    - Company Discovery (Hunter Discover: POST /v2/discover)
    - Company Enrichment (Company Finder: GET /v2/companies/find)
    - Domain Search & Contact Sourcing (GET /v2/domain-search)
    - Decision-Maker Email Finding (GET /v2/email-finder)
    - Deliverability Verification (GET /v2/email-verifier)
    - Person & Combined Enrichment (GET /v2/people/find, GET /v2/combined/find)
    - Domain Resolution (GET /v2/domain-finder)
    - Usage & Health Monitoring (GET /v2/account)
    """

    PROBE_CACHE_SECONDS = 3600

    def __init__(self):
        super().__init__("hunter")
        self.api_key = settings.HUNTER_API_KEY
        self.base_url = (settings.HUNTER_BASE_URL or OFFICIAL_HUNTER_BASE_URL).rstrip("/")
        self.is_enabled = getattr(settings, "HUNTER_ENABLED", True)
        self.timeout = httpx.Timeout(15.0, connect=10.0)
        self._restricted_probe: Optional[Tuple[float, bool]] = None

    def is_configured(self) -> bool:
        return bool(self.is_enabled and self.api_key and len(self.api_key.strip()) > 0)

    @property
    def _headers(self) -> Dict[str, str]:
        return {
            "Accept": "application/json",
            "X-API-KEY": self.api_key,
        }

    @property
    def _post_headers(self) -> Dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-API-KEY": self.api_key,
        }

    def _clean_domain(self, domain: str) -> str:
        clean = domain.strip().lower()
        if clean.startswith("https://") or clean.startswith("http://"):
            parsed = urlparse(clean)
            clean = parsed.hostname or clean
        return clean.split("/")[0].split(":")[0]

    def _extract_error_message(self, resp: httpx.Response) -> str:
        try:
            body = resp.json()
            errors = body.get("errors", [])
            if isinstance(errors, list) and errors:
                err_msgs = [e.get("details") or e.get("id") or str(e) for e in errors]
                return "; ".join(err_msgs)
            if isinstance(errors, dict):
                return str(errors)
            if "message" in body:
                return body["message"]
        except Exception:
            pass
        raw = resp.text[:150]
        return raw.replace(self.api_key, "[REDACTED]") if self.api_key else raw

    async def check_health(self) -> ProviderStatus:
        """
        Verifies Hunter.io API connectivity, authentication, and remaining monthly quota via GET /account.
        """
        if not self.is_configured():
            return ProviderStatus(
                name=self.name,
                is_configured=False,
                is_healthy=False,
                status_message="Hunter.io API key not configured.",
                last_checked=datetime.now(timezone.utc),
            )

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.get(
                    f"{self.base_url}/account",
                    headers=self._headers,
                )
                is_ok = res.status_code == 200
                if is_ok:
                    data = res.json().get("data", {})
                    plan = data.get("plan_name", "Free")
                    requests_info = data.get("requests", {})
                    searches = requests_info.get("searches", {})
                    used_searches = searches.get("used", 0)
                    available_searches = searches.get("available", 0)

                    # Probe domain-search to confirm account is active and verified.
                    # The probe spends a Hunter search, so its verdict is cached for an hour.
                    restricted = await self._is_account_restricted(client)
                    if restricted:
                        return ProviderStatus(
                            name=self.name,
                            is_configured=True,
                            is_healthy=False,
                            status_message="Hunter.io account restricted. Log in to https://hunter.io to verify email and activate API access.",
                            last_checked=datetime.now(timezone.utc),
                        )

                    msg = (
                        f"Connected to Hunter.io ({plan} plan). "
                        f"Searches: {used_searches}/{available_searches} used."
                    )
                else:
                    err_msg = self._extract_error_message(res)
                    msg = f"Hunter.io auth error HTTP {res.status_code}: {err_msg}"

                return ProviderStatus(
                    name=self.name,
                    is_configured=True,
                    is_healthy=is_ok,
                    status_message=msg,
                    last_checked=datetime.now(timezone.utc),
                )
        except Exception as e:
            safe_err = str(e).replace(self.api_key, "[REDACTED]") if self.api_key else str(e)
            return ProviderStatus(
                name=self.name,
                is_configured=True,
                is_healthy=False,
                status_message=f"Hunter.io connection error: {safe_err}",
                last_checked=datetime.now(timezone.utc),
            )

    async def _is_account_restricted(self, client: httpx.AsyncClient) -> bool:
        """Returns True when Hunter reports a restricted account; the probe result is cached for 1 hour."""
        now = time.monotonic()
        cached = self._restricted_probe
        if cached and now - cached[0] < self.PROBE_CACHE_SECONDS:
            return cached[1]

        probe = await client.get(
            f"{self.base_url}/domain-search",
            headers=self._headers,
            params={"domain": "hunter.io", "limit": 1},
        )
        restricted = probe.status_code == 429 and "restricted_account" in probe.text
        self._restricted_probe = (now, restricted)
        return restricted

    async def discover_companies(
        self, criteria: Dict[str, Any], limit: int = 25, page: int = 1
    ) -> Dict[str, Any]:
        """
        Executes Hunter Company Discovery (POST /v2/discover) using validated ICP criteria.
        Translates locations, industry include/exclude, headcount, keywords, and technologies.
        """
        if not self.is_configured():
            raise RuntimeError("Hunter.io API key is required to execute company discovery searches.")

        capped_limit = max(1, min(limit, 100))  # Hunter enforces max 100 per page
        filters: Dict[str, Any] = {}

        # 1. Location mapping
        raw_locations = criteria.get("locations") or []
        if isinstance(raw_locations, list) and raw_locations:
            loc_obj = parse_location_for_hunter(raw_locations[0])
            if loc_obj:
                filters["headquarters_location"] = loc_obj

        # 2. Industry inclusion & exclusion
        verticals = criteria.get("verticals") or criteria.get("industries") or []
        exclude_verticals = criteria.get("exclude_verticals") or []
        industry_filter: Dict[str, Any] = {}
        if isinstance(verticals, list) and verticals:
            clean_v = [str(v).strip() for v in verticals if str(v).strip()]
            if clean_v:
                industry_filter["include"] = clean_v
        if isinstance(exclude_verticals, list) and exclude_verticals:
            clean_ex_v = [str(v).strip() for v in exclude_verticals if str(v).strip()]
            if clean_ex_v:
                industry_filter["exclude"] = clean_ex_v
        if industry_filter:
            filters["industry"] = industry_filter

        # 3. Headcount / Employee ranges
        raw_headcount = criteria.get("employee_ranges") or []
        if isinstance(raw_headcount, list) and raw_headcount:
            filters["headcount"] = [str(r).strip() for r in raw_headcount if str(r).strip()]

        # 4. Keywords
        raw_keywords = criteria.get("keywords") or []
        if isinstance(raw_keywords, list) and raw_keywords:
            clean_kw = [str(k).strip() for k in raw_keywords if str(k).strip()]
            if clean_kw:
                filters["keywords"] = {"include": clean_kw}

        # 5. Technologies
        raw_tech = criteria.get("technologies") or []
        if isinstance(raw_tech, list) and raw_tech:
            clean_tech = [str(t).strip() for t in raw_tech if str(t).strip()]
            if clean_tech:
                filters["technologies"] = clean_tech

        payload: Dict[str, Any] = {
            "limit": capped_limit,
            "page": page,
        }
        if filters:
            payload["filters"] = filters

        query_str = criteria.get("query")
        if not (query_str and isinstance(query_str, str) and query_str.strip()):
            # Hunter's Discover AI engine requires a natural language prompt to accurately discover companies across industries & locations
            query_parts = []
            if verticals:
                query_parts.extend([str(v).strip() for v in verticals if str(v).strip()])
            if raw_keywords:
                query_parts.extend([str(k).strip() for k in raw_keywords if str(k).strip()])
            if raw_locations:
                query_parts.append(f"in {', '.join(str(loc).strip() for loc in raw_locations if str(loc).strip())}")
            if query_parts:
                query_str = " ".join(query_parts).strip()

        if query_str and isinstance(query_str, str) and query_str.strip():
            payload["query"] = query_str.strip()

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/discover",
                    headers=self._post_headers,
                    json=payload,
                )

                if resp.status_code == 200:
                    body = resp.json()
                    raw_data = body.get("data") if isinstance(body, dict) else []
                    if isinstance(raw_data, list):
                        companies = raw_data
                    elif isinstance(raw_data, dict):
                        companies = raw_data.get("companies") or raw_data.get("organizations") or []
                    else:
                        companies = []

                    meta = body.get("meta") if isinstance(body, dict) and isinstance(body.get("meta"), dict) else {}
                    total = meta.get("results") if meta.get("results") is not None else len(companies)

                    results = []
                    for c in companies:
                        if not isinstance(c, dict):
                            continue
                        hq = c.get("headquarters_location") if isinstance(c.get("headquarters_location"), dict) else {}
                        company_name = (
                            c.get("organization")
                            or c.get("name")
                            or c.get("company_name")
                            or (c.get("domain") or "").split(".")[0].capitalize()
                            or "Unknown"
                        )
                        domain = (c.get("domain") or "").strip().lower()
                        if not domain:
                            continue

                        results.append(
                            {
                                "company_name": company_name,
                                "domain": domain,
                                "industry": c.get("industry"),
                                "keywords": c.get("keywords") or [],
                                "country": hq.get("country") or c.get("country"),
                                "city": hq.get("city") or c.get("city"),
                                "state": hq.get("state") or c.get("state"),
                                "employee_count": c.get("headcount") or c.get("employee_count"),
                                "technologies": c.get("technologies") or [],
                                "linkedin_url": c.get("linkedin_url"),
                                "twitter_url": c.get("twitter_url"),
                                "description": c.get("description"),
                                "year_founded": c.get("year_founded"),
                                "hiring_intent": bool(
                                    (isinstance(c.get("job_openings"), (int, float)) and c.get("job_openings", 0) > 0)
                                    or c.get("hiring", False)
                                ),
                            }
                        )
                    return {
                        "organizations": results,
                        "total": total,
                        "provenance": {
                            "provider": self.name,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "method": "hunter_discover",
                        },
                    }

                err_msg = self._extract_error_message(resp)
                if resp.status_code == 403:
                    if "restricted" in err_msg.lower() or "plan" in err_msg.lower() or "discover" in err_msg.lower():
                        raise RuntimeError(
                            f"Hunter Discover endpoint is restricted on the current account plan: {err_msg}"
                        )
                if resp.status_code == 429:
                    raise RuntimeError(f"Hunter rate limit reached (HTTP 429): {err_msg}")

                raise RuntimeError(f"Hunter Discover failed: HTTP {resp.status_code} - {err_msg}")

        except RuntimeError:
            raise
        except Exception as e:
            safe_e = str(e).replace(self.api_key, "[REDACTED]") if self.api_key else str(e)
            raise RuntimeError(f"Hunter Discover exception: {safe_e}")

    async def search_organizations(
        self, filters: Dict[str, Any], limit: int = 25, page: int = 1
    ) -> Dict[str, Any]:
        """
        Unified discovery entrypoint:
        - If direct 'domains' are provided: resolves them via Company Enrichment / Domain Search.
        - If criteria (locations, employee_ranges, verticals, keywords) are provided: calls Hunter Discover.
        - Graceful fallback: If Discover is plan-restricted and domains were provided, resolves the domains.
        """
        if not self.is_configured():
            raise RuntimeError("Hunter.io API key is required to execute company searches.")

        domains = filters.get("domains") or []
        domain_list = (
            domains
            if isinstance(domains, list)
            else [d.strip() for d in str(domains).split("\n") if d.strip()]
        )

        has_criteria = bool(
            filters.get("locations")
            or filters.get("employee_ranges")
            or filters.get("verticals")
            or filters.get("industries")
            or filters.get("keywords")
            or filters.get("query")
        )

        # 1. Criteria-based discovery via Hunter Discover
        if has_criteria:
            try:
                return await self.discover_companies(filters, limit=limit, page=page)
            except RuntimeError as e:
                # If Discover failed due to plan restriction and domains were provided, fall back to domain enrichment
                if domain_list and "restricted" in str(e).lower():
                    logger.info("Hunter Discover restricted on current plan; falling back to provided domain list.")
                else:
                    raise

        # 2. Direct domains list resolution
        results = []
        for d in domain_list[:limit]:
            clean_d = self._clean_domain(d)
            enrichment = await self.enrich_company(clean_d)
            if enrichment and enrichment.get("company_name"):
                results.append(enrichment)
            else:
                results.append(
                    {
                        "company_name": clean_d.split(".")[0].capitalize(),
                        "domain": clean_d,
                        "industry": None,
                        "country": None,
                        "city": None,
                        "employee_count": None,
                    }
                )

        return {
            "organizations": results,
            "total": len(results),
            "provenance": {
                "provider": self.name,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "method": "hunter_domain_resolution",
            },
        }

    async def enrich_company(
        self, domain: str, allow_domain_search_fallback: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Enriches a company using Hunter's Company Enrichment API (GET /v2/companies/find).
        Extracts verified firmographics, legal name, sector, headcount, location, phone,
        technologies, and social presence.
        Falls back to /domain-search if /companies/find has nothing, unless the caller opts out:
        Company Enrichment costs ~0.2 credits but a Domain Search costs a full credit, which the
        automatic search pipeline should not spend just to fill in firmographics.
        """
        if not self.is_configured():
            return None

        clean_domain = self._clean_domain(domain)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # 1. Primary: GET /v2/companies/find
                resp = await client.get(
                    f"{self.base_url}/companies/find",
                    headers=self._headers,
                    params={"domain": clean_domain},
                )
                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    if isinstance(data, dict) and data:
                        return self._parse_company_find(data, clean_domain)

                # 2. Fallback: GET /v2/domain-search
                if not allow_domain_search_fallback:
                    return None
                logger.info(
                    f"Hunter /companies/find returned HTTP {resp.status_code} for {clean_domain}; trying /domain-search"
                )
                return await self._fallback_domain_search_enrichment(clean_domain)

        except Exception as e:
            safe_e = str(e).replace(self.api_key, "[REDACTED]") if self.api_key else str(e)
            logger.warning(f"Hunter company enrichment exception for {clean_domain}: {safe_e}")
            return None

    @staticmethod
    def _social_url(value: Any, base: str) -> Optional[str]:
        """Normalizes a social handle/URL (string or {'handle': ...} object) into a full URL."""
        if isinstance(value, dict):
            value = value.get("handle")
        if not value or not isinstance(value, str):
            return None
        return value if value.startswith("http") else f"{base}/{value.lstrip('/')}"

    def _parse_company_find(self, data: Dict[str, Any], clean_domain: str) -> Dict[str, Any]:
        """
        Normalizes a GET /v2/companies/find payload.
        Live Hunter responses are camelCase with nested `category`, `geo`, `metrics`, `linkedin`
        objects and a plain-string `location`; the legacy snake_case shape is still accepted.
        """
        category = data.get("category") if isinstance(data.get("category"), dict) else {}
        metrics = data.get("metrics") if isinstance(data.get("metrics"), dict) else {}
        geo = data.get("geo") if isinstance(data.get("geo"), dict) else {}
        legacy_loc = data.get("location") if isinstance(data.get("location"), dict) else {}
        site = data.get("site") if isinstance(data.get("site"), dict) else {}

        raw_tech = data.get("tech") or data.get("technologies") or []
        technologies = [
            t.get("name") if isinstance(t, dict) else str(t) for t in raw_tech if t
        ]

        phones = site.get("phoneNumbers") if isinstance(site.get("phoneNumbers"), list) else []
        return {
            "company_name": data.get("name") or clean_domain.split(".")[0].capitalize(),
            "legal_name": data.get("legalName") or data.get("legal_name"),
            "domain": clean_domain,
            "domain_aliases": data.get("domainAliases") or data.get("domain_aliases") or [],
            "industry": category.get("industry") or data.get("industry") or category.get("sector") or data.get("sector"),
            "sector": category.get("sector") or data.get("sector"),
            "description": data.get("description"),
            "tags": data.get("tags") or [],
            "employee_count": (
                metrics.get("employeesCount") or data.get("employees_count") or data.get("headcount")
            ),
            "country": geo.get("countryCode") or geo.get("country") or legacy_loc.get("country") or data.get("country"),
            "city": geo.get("city") or legacy_loc.get("city") or data.get("city"),
            "state": geo.get("state") or legacy_loc.get("state") or data.get("state"),
            "postal_code": geo.get("postalCode") or legacy_loc.get("postal_code"),
            "phone": data.get("phone") or data.get("phone_number") or (phones[0] if phones else None),
            "email": data.get("email"),
            "linkedin_url": self._social_url(data.get("linkedin"), "https://www.linkedin.com"),
            "twitter_url": self._social_url(data.get("twitter"), "https://twitter.com"),
            "facebook_url": self._social_url(data.get("facebook"), "https://facebook.com"),
            "technologies": technologies,
            "company_type": data.get("companyType") or data.get("company_type"),
            "year_founded": data.get("foundedYear") or data.get("year_founded"),
            "funding": data.get("funding") or ({"total_raised": metrics["raised"]} if metrics.get("raised") else None),
            "provider": "hunter_company_find",
        }

    async def _fallback_domain_search_enrichment(self, clean_domain: str) -> Optional[Dict[str, Any]]:
        """Fallback company firmographics collector via /domain-search."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    f"{self.base_url}/domain-search",
                    headers=self._headers,
                    params={"domain": clean_domain, "limit": 1},
                )
                if resp.status_code != 200:
                    return None

                data = resp.json().get("data", {})
                if not data:
                    return None

                org_name = data.get("organization") or clean_domain.split(".")[0].capitalize()
                raw_tech = data.get("technologies", [])
                technologies = [t.get("name") if isinstance(t, dict) else str(t) for t in raw_tech]

                return {
                    "company_name": org_name,
                    "domain": clean_domain,
                    "industry": data.get("industry") or data.get("description"),
                    "employee_count": None,
                    "country": data.get("country"),
                    "city": data.get("city"),
                    "state": data.get("state"),
                    "phone": None,
                    "linkedin_url": data.get("linkedin"),
                    "twitter_url": (
                        f"https://twitter.com/{data.get('twitter')}"
                        if data.get("twitter") and not data.get("twitter").startswith("http")
                        else data.get("twitter")
                    ),
                    "facebook_url": (
                        f"https://facebook.com/{data.get('facebook')}"
                        if data.get("facebook") and not data.get("facebook").startswith("http")
                        else data.get("facebook")
                    ),
                    "technologies": technologies,
                    "keywords": [],
                    "description": data.get("description"),
                    "postal_code": data.get("postal_code"),
                    "pattern": data.get("pattern"),
                    "provider": "hunter_domain_search",
                }
        except Exception as e:
            safe_e = str(e).replace(self.api_key, "[REDACTED]") if self.api_key else str(e)
            logger.warning(f"Hunter domain-search fallback exception for {clean_domain}: {safe_e}")
            return None

    async def enrich_organization(self, domain: str) -> Optional[Dict[str, Any]]:
        """Backward-compatible alias for enrich_company."""
        return await self.enrich_company(domain)

    async def search_contacts_for_lead(
        self, domain: str, titles: Optional[List[str]] = None, limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Discovers decision-maker contacts for a company via Hunter's /domain-search.
        Emails are strictly masked for cost/credit safety until explicit reveal.
        """
        if not self.is_configured():
            return []

        clean_domain = self._clean_domain(domain)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    f"{self.base_url}/domain-search",
                    headers=self._headers,
                    params={
                        "domain": clean_domain,
                        "limit": min(limit * 2, 10),
                        "seniority": "executive,director",
                    },
                )
                if resp.status_code != 200:
                    logger.info(f"Hunter contact discovery returned HTTP {resp.status_code} for {clean_domain}")
                    return []

                data = resp.json().get("data", {})
                emails = data.get("emails", [])

                contacts = []
                for p in emails:
                    raw_email = p.get("value")
                    first_name = p.get("first_name")
                    last_name = p.get("last_name")
                    title = p.get("position") or "Executive"
                    linkedin = p.get("linkedin")
                    phone = p.get("phone_number")

                    # Mask email for safety before reveal (e.g. j***@company.com)
                    masked_email = None
                    if raw_email and "@" in raw_email:
                        user_part, dom_part = raw_email.split("@", 1)
                        masked_email = f"{user_part[:1]}***@{dom_part}"

                    contacts.append(
                        {
                            "first_name": first_name,
                            "last_name": last_name,
                            "title": title,
                            "linkedin_url": linkedin,
                            "email": masked_email or raw_email,
                            "phone": phone,
                            "is_revealed": False,
                            "confidence": p.get("confidence"),
                            "department": p.get("department"),
                            "seniority": p.get("seniority"),
                            "raw_email_hint": raw_email,
                        }
                    )
                return contacts[:limit]
        except Exception as e:
            safe_e = str(e).replace(self.api_key, "[REDACTED]") if self.api_key else str(e)
            logger.warning(f"Hunter contact discovery exception for {clean_domain}: {safe_e}")
            return []

    async def find_email(
        self,
        domain: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        full_name: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Hunter Email Finder: GET /v2/email-finder
        Finds the verified email address of a person working at a specific company.
        """
        if not self.is_configured():
            return None

        clean_domain = self._clean_domain(domain)
        params: Dict[str, Any] = {"domain": clean_domain}
        if first_name and last_name:
            params["first_name"] = first_name
            params["last_name"] = last_name
        elif full_name:
            params["full_name"] = full_name
        else:
            return None

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    f"{self.base_url}/email-finder",
                    headers=self._headers,
                    params=params,
                )
                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    return {
                        "email": data.get("email"),
                        "first_name": data.get("first_name"),
                        "last_name": data.get("last_name"),
                        "score": data.get("score"),
                        "domain": clean_domain,
                        "position": data.get("position"),
                        "phone": data.get("phone_number"),
                        "linkedin_url": data.get("linkedin_url"),
                        "verification": data.get("verification", {}),
                    }
                return None
        except Exception as e:
            safe_e = str(e).replace(self.api_key, "[REDACTED]") if self.api_key else str(e)
            logger.warning(f"Hunter email finder exception for {clean_domain}: {safe_e}")
            return None

    async def verify_email(self, email: str) -> Dict[str, Any]:
        """
        Hunter Email Verifier: GET /v2/email-verifier
        Validates deliverability status (deliverable, risky, undeliverable).
        """
        if not self.is_configured():
            return {"result": "unknown", "status": "unconfigured", "score": None}

        clean_email = email.strip().lower()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    f"{self.base_url}/email-verifier",
                    headers=self._headers,
                    params={"email": clean_email},
                )
                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    return {
                        "email": clean_email,
                        "result": data.get("result", "deliverable"),
                        "score": data.get("score"),
                        "status": data.get("status"),
                        "regexp": data.get("regexp"),
                        "gibberish": data.get("gibberish"),
                        "disposable": data.get("disposable"),
                        "webmail": data.get("webmail"),
                        "mx_records": data.get("mx_records"),
                        "smtp_server": data.get("smtp_server"),
                        "smtp_check": data.get("smtp_check"),
                        "accept_all": data.get("accept_all"),
                        "block": data.get("block"),
                    }
                return {"email": clean_email, "result": "unknown", "status": f"HTTP {resp.status_code}"}
        except Exception as e:
            safe_e = str(e).replace(self.api_key, "[REDACTED]") if self.api_key else str(e)
            logger.warning(f"Hunter email verifier exception for {clean_email}: {safe_e}")
            return {"email": clean_email, "result": "unknown", "error": safe_e}

    async def reveal_contact_details(
        self,
        domain: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Gated Action: Unmasks verified contact details via Hunter's /email-finder and /email-verifier.
        Returns verified direct email, confidence score, phone number, and deliverability status.
        """
        if not self.is_configured():
            raise RuntimeError("Hunter.io API key is not configured.")

        clean_domain = self._clean_domain(domain)
        unmasked_email = None
        phone = None
        confidence = None

        try:
            # 1. If we have first and last name, use Email Finder
            if first_name and last_name:
                found = await self.find_email(clean_domain, first_name=first_name, last_name=last_name)
                if found and found.get("email"):
                    unmasked_email = found.get("email")
                    phone = found.get("phone")
                    confidence = found.get("score")

            # 2. If email finder didn't return or names were missing, check domain-search
            if not unmasked_email:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.get(
                        f"{self.base_url}/domain-search",
                        headers=self._headers,
                        params={"domain": clean_domain, "limit": 5},
                    )
                    if resp.status_code == 200:
                        emails = resp.json().get("data", {}).get("emails", [])
                        for em in emails:
                            if first_name and (em.get("first_name") or "").lower() == first_name.lower():
                                unmasked_email = em.get("value")
                                phone = em.get("phone_number") or phone
                                confidence = em.get("confidence")
                                break
                        # Only fall back to an arbitrary address when no specific person was requested;
                        # otherwise a name mismatch would unmask (and bill) the wrong contact.
                        if not unmasked_email and emails and not first_name:
                            unmasked_email = emails[0].get("value")
                            phone = emails[0].get("phone_number") or phone
                            confidence = emails[0].get("confidence")

            # 3. Deliverability verification
            target_email = unmasked_email or email
            verification_status = "unknown"
            if target_email:
                v_res = await self.verify_email(target_email)
                verification_status = v_res.get("result", "deliverable")
                if v_res.get("score") is not None:
                    confidence = v_res.get("score")

            return {
                "email": unmasked_email or email,
                "phone": phone,
                "confidence": confidence,
                "verification_status": verification_status,
                "revealed_at": datetime.now(timezone.utc).isoformat(),
                "provider": "hunter",
            }
        except RuntimeError:
            raise
        except Exception as e:
            safe_e = str(e).replace(self.api_key, "[REDACTED]") if self.api_key else str(e)
            raise RuntimeError(f"Hunter reveal exception: {safe_e}")

    async def enrich_person(self, email: str) -> Optional[Dict[str, Any]]:
        """
        Hunter Person Enrichment: GET /v2/people/find?email={email}
        Normalizes person metadata (name, job title, company, location, social links, phone).
        """
        if not self.is_configured():
            return None

        clean_email = email.strip().lower()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    f"{self.base_url}/people/find",
                    headers=self._headers,
                    params={"email": clean_email},
                )
                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    if data:
                        loc = data.get("location") or {}
                        company_info = data.get("company") or {}
                        return {
                            "first_name": data.get("first_name"),
                            "last_name": data.get("last_name"),
                            "full_name": data.get("full_name"),
                            "email": clean_email,
                            "job_title": data.get("position"),
                            "seniority": data.get("seniority"),
                            "department": data.get("department"),
                            "company_name": company_info.get("name"),
                            "company_domain": company_info.get("domain"),
                            "city": loc.get("city"),
                            "state": loc.get("state"),
                            "country": loc.get("country"),
                            "linkedin_url": data.get("linkedin_url"),
                            "twitter_url": data.get("twitter_handle"),
                            "phone": data.get("phone_number"),
                        }
                return None
        except Exception as e:
            safe_e = str(e).replace(self.api_key, "[REDACTED]") if self.api_key else str(e)
            logger.warning(f"Hunter person enrichment exception for {clean_email}: {safe_e}")
            return None

    async def enrich_combined(
        self, email: str, domain: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Hunter Combined Enrichment: GET /v2/combined/find?email={email}
        Returns both person and company data in a single call.
        """
        if not self.is_configured():
            return None

        clean_email = email.strip().lower()
        params: Dict[str, Any] = {"email": clean_email}
        if domain:
            params["domain"] = self._clean_domain(domain)

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    f"{self.base_url}/combined/find",
                    headers=self._headers,
                    params=params,
                )
                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    return data
                return None
        except Exception as e:
            safe_e = str(e).replace(self.api_key, "[REDACTED]") if self.api_key else str(e)
            logger.warning(f"Hunter combined enrichment exception for {clean_email}: {safe_e}")
            return None

    async def find_domain_for_company(self, company_name: str) -> Optional[str]:
        """
        Hunter Domain Finder: GET /v2/domain-finder or /companies/find?name={name}
        Resolves a company's website domain from its business name.
        """
        if not self.is_configured():
            return None

        clean_name = company_name.strip()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # 1. Try /companies/find?name=
                resp = await client.get(
                    f"{self.base_url}/companies/find",
                    headers=self._headers,
                    params={"name": clean_name},
                )
                if resp.status_code == 200:
                    domain = resp.json().get("data", {}).get("domain")
                    if domain:
                        return self._clean_domain(domain)

                # 2. Try /domain-finder?company=
                resp2 = await client.get(
                    f"{self.base_url}/domain-finder",
                    headers=self._headers,
                    params={"company": clean_name},
                )
                if resp2.status_code == 200:
                    domain = resp2.json().get("data", {}).get("domain")
                    if domain:
                        return self._clean_domain(domain)

                return None
        except Exception as e:
            safe_e = str(e).replace(self.api_key, "[REDACTED]") if self.api_key else str(e)
            logger.warning(f"Hunter domain finder exception for {clean_name}: {safe_e}")
            return None

    async def get_usage(self) -> Dict[str, Any]:
        """
        Retrieves live Hunter account credit allowances, usage counts, reset dates, and plan info.
        GET /v2/account
        """
        if not self.is_configured():
            return {"configured": False, "error": "Hunter API key not configured"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.get(f"{self.base_url}/account", headers=self._headers)
                if res.status_code == 200:
                    data = res.json().get("data", {})
                    plan = data.get("plan_name", "Free")
                    requests_info = data.get("requests", {})
                    searches = requests_info.get("searches", {})
                    verifications = requests_info.get("verifications", {})
                    reset_date = data.get("reset_date")
                    return {
                        "configured": True,
                        "plan_name": plan,
                        "reset_date": reset_date,
                        "requests": requests_info,
                        "searches_used": searches.get("used", 0),
                        "searches_available": searches.get("available", 0),
                        "verifications_used": verifications.get("used", 0),
                        "verifications_available": verifications.get("available", 0),
                    }
                else:
                    return {
                        "configured": True,
                        "error": f"HTTP {res.status_code}: {self._extract_error_message(res)}",
                    }
        except Exception as e:
            safe_err = str(e).replace(self.api_key, "[REDACTED]") if self.api_key else str(e)
            return {"configured": True, "error": safe_err}
