from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings
from app.core.logging import logger
from app.providers.base import BaseProviderAdapter, ProviderStatus

DEFAULT_SERPAPI_BASE_URL = "https://serpapi.com"


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
                place = data.get("place_results")
                if not place:
                    local_list = data.get("local_results", [])
                    place = local_list[0] if local_list else None

                if not place:
                    return {
                        "signals": {
                            "low_review_rating": {
                                "value": None,
                                "evidence": f"No Google Maps business profile found via SerpApi for '{clean_term}'",
                                "provider": self.name,
                            }
                        },
                        "provenance": {"status": "not_found", "query": query},
                    }

                rating = place.get("rating")
                # reviews may be an int or a formatted string
                raw_reviews = place.get("reviews", 0)
                try:
                    review_count = int(raw_reviews) if raw_reviews is not None else 0
                except (ValueError, TypeError):
                    review_count = 0

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
