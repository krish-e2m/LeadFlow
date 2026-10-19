from datetime import datetime, timezone
from typing import Any, Dict

import httpx

from app.core.config import settings
from app.providers.base import BaseProviderAdapter, ProviderStatus


class GooglePlacesAdapter(BaseProviderAdapter):
    """
    Google Places API collector for physical presence, review counts, and reputation ratings.
    Supports being unconfigured gracefully without failing or blocking searches.
    """

    def __init__(self):
        super().__init__("google_places")
        self.api_key = settings.GOOGLE_PLACES_API_KEY
        self.enabled = settings.GOOGLE_PLACES_ENABLED

    def is_configured(self) -> bool:
        return bool(self.enabled and self.api_key and len(self.api_key.strip()) > 0)

    async def check_health(self) -> ProviderStatus:
        if not self.is_configured():
            return ProviderStatus(
                name=self.name,
                is_configured=False,
                is_healthy=False,
                status_message="Google Places API credentials not configured. Signals will be marked unavailable.",
                last_checked=datetime.now(timezone.utc),
            )
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.get(
                    "https://maps.googleapis.com/maps/api/place/findplacefromtext/json",
                    params={"input": "Google", "inputtype": "textquery", "key": self.api_key},
                )
                is_ok = res.status_code == 200 and res.json().get("status") in [
                    "OK",
                    "ZERO_RESULTS",
                ]
                return ProviderStatus(
                    name=self.name,
                    is_configured=True,
                    is_healthy=is_ok,
                    status_message="Connected to Google Places API"
                    if is_ok
                    else f"API response status: {res.json().get('status')}",
                    last_checked=datetime.now(timezone.utc),
                )
        except Exception as e:
            return ProviderStatus(
                name=self.name,
                is_configured=True,
                is_healthy=False,
                status_message=f"Healthcheck failed: {str(e)}",
                last_checked=datetime.now(timezone.utc),
            )

    async def fetch_place_signals(self, company_name: str, domain: str) -> Dict[str, Any]:
        """
        Queries Google Places for company reviews and ratings.
        If unconfigured, returns signals as None and documents missing provenance.
        """
        if not self.is_configured():
            return {
                "signals": {
                    "low_review_rating": {
                        "value": None,
                        "evidence": "Google Places provider unconfigured; review rating unavailable.",
                        "provider": self.name,
                    }
                },
                "provenance": {
                    "provider": self.name,
                    "status": "unconfigured",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                find_res = await client.get(
                    "https://maps.googleapis.com/maps/api/place/findplacefromtext/json",
                    params={
                        "input": f"{company_name} {domain}",
                        "inputtype": "textquery",
                        "fields": "place_id,name,rating,user_ratings_total",
                        "key": self.api_key,
                    },
                )
                data = find_res.json()
                candidates = data.get("candidates", [])
                if not candidates:
                    return {
                        "signals": {
                            "low_review_rating": {
                                "value": None,
                                "evidence": f"No Google Places profile found for {company_name}",
                                "provider": self.name,
                            }
                        },
                        "provenance": {"status": "not_found", "candidates": 0},
                    }

                place = candidates[0]
                rating = place.get("rating")
                total_reviews = place.get("user_ratings_total", 0)

                # low_review_rating: Rating < 3.8 indicates operational pain/reputation opportunity
                is_low_rating = rating is not None and rating < 3.8
                val = 1.0 if is_low_rating else (0.0 if rating is not None else None)

                return {
                    "signals": {
                        "low_review_rating": {
                            "value": val,
                            "evidence": f"Google Places rating: {rating}★ ({total_reviews} reviews)",
                            "provider": self.name,
                        }
                    },
                    "provenance": {
                        "place_id": place.get("place_id"),
                        "rating": rating,
                        "total_reviews": total_reviews,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                }
        except Exception as e:
            return {
                "signals": {
                    "low_review_rating": {
                        "value": None,
                        "evidence": f"Error querying Places: {str(e)}",
                        "provider": self.name,
                    }
                },
                "provenance": {"error": str(e), "status": "error"},
            }
