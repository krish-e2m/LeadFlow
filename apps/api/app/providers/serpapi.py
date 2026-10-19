import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.core.logging import logger
from app.providers.base import BaseProviderAdapter, ProviderStatus

DEFAULT_SERPAPI_BASE_URL = "https://serpapi.com"

_NAME_STOPWORDS = {"inc", "llc", "ltd", "the", "co", "corp", "company", "group", "and", "of", "pvt", "limited", "gmbh"}


def _host(url_or_domain: str) -> str:
    text = (url_or_domain or "").strip().lower()
    if "://" not in text:
        text = f"http://{text}"
    host = urlparse(text).hostname or ""
    return host[4:] if host.startswith("www.") else host


def _same_site(website: str, domain: str) -> bool:
    a, b = _host(website), _host(domain)
    return bool(a and b) and (a == b or a.endswith(f".{b}") or b.endswith(f".{a}"))


def _name_matches(title: str, company: str) -> bool:
    tokens = [t for t in re.findall(r"[a-z0-9]+", (company or "").lower()) if len(t) >= 3 and t not in _NAME_STOPWORDS]
    title_l = (title or "").lower()
    return bool(tokens) and any(t in title_l for t in tokens)


def pick_matching_place(data: Dict[str, Any], domain: str, company: str) -> Optional[Dict[str, Any]]:
    """
    The Maps result that is really this company. A listing whose website points elsewhere is a
    different business and its rating must not be attributed to the lead; a listing without a
    website is accepted only when its name matches the company.
    """
    candidates = []
    if isinstance(data.get("place_results"), dict):
        candidates.append(data["place_results"])
    candidates.extend(p for p in (data.get("local_results") or []) if isinstance(p, dict))

    for place in candidates:
        if place.get("website") and _same_site(place["website"], domain):
            return place
    for place in candidates:
        if not place.get("website") and _name_matches(place.get("title", ""), company):
            return place
    return None


def parse_review_count(raw: Any) -> int:
    """Review counts arrive as ints or display strings such as "1,234"."""
    if raw is None:
        return 0
    try:
        return int(str(raw).replace(",", "").strip() or 0)
    except (TypeError, ValueError):
        return 0


class SerpApiAdapter(BaseProviderAdapter):
    """
    SerpApi provider adapter for Google Maps business discovery, ratings, and reviews.
    Powers the 22-signal qualification engine's `low_review_rating` metric.
    """

    def __init__(self):
        super().__init__("serpapi")
        self.api_key = settings.SERPAPI_API_KEY
        self.enabled = settings.SERPAPI_ENABLED
        self.base_url = (settings.SERPAPI_BASE_URL or DEFAULT_SERPAPI_BASE_URL).rstrip("/")
        self.timeout = 15.0

    def is_configured(self) -> bool:
        return bool(self.enabled and self.api_key and len(self.api_key.strip()) > 0)

    async def check_health(self) -> ProviderStatus:
        """
        Verifies SerpApi connectivity and credit status via the free /account.json endpoint.
        Does not consume any monthly search quota.
        """
        if not self.is_configured():
            disabled = not self.enabled and bool(self.api_key)
            return ProviderStatus(
                name=self.name,
                is_configured=False,
                is_healthy=False,
                status_message=(
                    "SerpApi disabled by configuration (SERPAPI_ENABLED=false)."
                    if disabled
                    else "SerpApi API key not configured."
                ),
                last_checked=datetime.now(timezone.utc),
            )

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                res = await client.get(
                    f"{self.base_url}/account.json",
                    params={"api_key": self.api_key},
                )

                if res.status_code == 200:
                    data = res.json()
                    plan_name = data.get("plan_name", "SerpApi Plan")
                    searches_left = data.get(
                        "total_searches_left", data.get("plan_searches_left", "unlimited")
                    )
                    return ProviderStatus(
                        name=self.name,
                        is_configured=True,
                        is_healthy=True,
                        status_message=f"Connected to SerpApi ({plan_name}, {searches_left} searches left)",
                        last_checked=datetime.now(timezone.utc),
                    )

                safe_err = res.text.replace(self.api_key, "[REDACTED]") if self.api_key else res.text
                return ProviderStatus(
                    name=self.name,
                    is_configured=True,
                    is_healthy=False,
                    status_message=f"SerpApi HTTP {res.status_code}: {safe_err[:120]}",
                    last_checked=datetime.now(timezone.utc),
                )
        except Exception as e:
            safe_e = str(e).replace(self.api_key, "[REDACTED]") if self.api_key else str(e)
            return ProviderStatus(
                name=self.name,
                is_configured=True,
                is_healthy=False,
                status_message=f"SerpApi connection error: {safe_e}",
                last_checked=datetime.now(timezone.utc),
            )

    async def fetch_review_signals(
        self,
        company_name: str,
        domain: str,
        location: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Queries Google Maps via SerpApi to discover the business profile,
        reputation rating, and total customer review count.
        Evaluates the canonical `low_review_rating` signal.
        """
        if not self.is_configured():
            return {
                "signals": {
                    "low_review_rating": {
                        "value": None,
                        "evidence": "SerpApi provider unconfigured; review rating unavailable.",
                        "provider": self.name,
                    }
                },
                "provenance": {
                    "provider": self.name,
                    "status": "unconfigured",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            }

        clean_term = company_name.strip() if company_name else ""
        if not clean_term or clean_term == domain:
            clean_term = domain.split(".")[0].capitalize()

        loc = location.strip() if location and location.strip() else ""
        query = f"{clean_term} {loc}".strip() if loc else f"{clean_term} {domain}"

        params = {
            "engine": "google_maps",
            "q": query,
            "api_key": self.api_key,
            "hl": "en",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.get(
                    f"{self.base_url}/search.json",
                    params=params,
                )

                if res.status_code != 200:
                    safe_err = res.text.replace(self.api_key, "[REDACTED]") if self.api_key else res.text
                    logger.info(f"SerpApi query failed HTTP {res.status_code} for '{query}': {safe_err[:100]}")
                    return {
                        "signals": {
                            "low_review_rating": {
                                "value": None,
                                "evidence": f"SerpApi query failed (HTTP {res.status_code})",
                                "provider": self.name,
                            }
                        },
                        "provenance": {"error": f"HTTP {res.status_code}", "status": "error"},
                    }

                data = res.json()

                # SerpApi Google Maps returns either `place_results` (direct match) or `local_results` (list)
                place = pick_matching_place(data, domain, clean_term)

                if not place:
                    return {
                        "signals": {
                            "low_review_rating": {
                                "value": None,
                                "evidence": f"No Google Maps business profile matching {domain} found via SerpApi for '{clean_term}'",
                                "provider": self.name,
                            }
                        },
                        "provenance": {"status": "not_found", "query": query},
                    }

                rating = place.get("rating")
                review_count = parse_review_count(place.get("reviews"))

                title = place.get("title", clean_term)
                address = place.get("address")
                phone = place.get("phone")
                website = place.get("website")
                place_id = place.get("place_id") or place.get("data_id")

                # Canonical signal logic: Rating < 3.8 indicates operational pain/reputation opportunity
                if rating is None or review_count == 0:
                    val = None
                    evidence = f"Google Maps profile found via SerpApi for '{title}', but 0 published customer reviews exist"
                elif rating < 3.8:
                    val = 1.0  # Reputation opportunity flag raised
                    evidence = f"Sub-par Google rating via SerpApi: {rating}★ ({review_count} reviews) indicates reputation/service pain points"
                else:
                    val = 0.0  # Reputation is solid
                    evidence = f"Strong Google rating via SerpApi: {rating}★ ({review_count} reviews) demonstrates positive local reputation"

                return {
                    "signals": {
                        "low_review_rating": {
                            "value": val,
                            "evidence": evidence,
                            "provider": self.name,
                            "source_url": website or place.get("link"),
                        }
                    },
                    "provenance": {
                        "provider": self.name,
                        "engine": "google_maps",
                        "title": title,
                        "rating": rating,
                        "review_count": review_count,
                        "address": address,
                        "phone": phone,
                        "website": website,
                        "place_id": place_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                }

        except Exception as e:
            safe_e = str(e).replace(self.api_key, "[REDACTED]") if self.api_key else str(e)
            logger.warning(f"SerpApi exception querying '{query}': {safe_e}")
            return {
                "signals": {
                    "low_review_rating": {
                        "value": None,
                        "evidence": f"Error querying SerpApi: {safe_e}",
                        "provider": self.name,
                    }
                },
                "provenance": {"error": safe_e, "status": "error"},
            }
