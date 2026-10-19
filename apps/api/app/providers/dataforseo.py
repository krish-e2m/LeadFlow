from datetime import datetime, timezone
from typing import Any, Dict

import httpx

from app.core.config import settings
from app.providers.base import BaseProviderAdapter, ProviderStatus


class DataForSEOAdapter(BaseProviderAdapter):
    """
    DataForSEO collector for organic search presence, domain trust, backlinks, and PPC ad spend.
    Supports being unconfigured gracefully without failing or blocking searches.
    """

    def __init__(self):
        super().__init__("dataforseo")
        self.login = settings.DATAFORSEO_LOGIN
        self.password = settings.DATAFORSEO_PASSWORD
        self.enabled = settings.DATAFORSEO_ENABLED
        self.base_url = "https://api.dataforseo.com/v3"

    def is_configured(self) -> bool:
        return bool(self.enabled and self.login and self.password)

    async def check_health(self) -> ProviderStatus:
        if not self.is_configured():
            return ProviderStatus(
                name=self.name,
                is_configured=False,
                is_healthy=False,
                status_message="DataForSEO credentials not configured. SEO/Trust signals will be preserved as unavailable.",
                last_checked=datetime.now(timezone.utc),
            )
        try:
            async with httpx.AsyncClient(timeout=5.0, auth=(self.login, self.password)) as client:
                res = await client.get(f"{self.base_url}/appendix/user")
                is_ok = res.status_code == 200
                return ProviderStatus(
                    name=self.name,
                    is_configured=True,
                    is_healthy=is_ok,
                    status_message="Connected to DataForSEO API"
                    if is_ok
                    else f"HTTP {res.status_code}",
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

    async def fetch_seo_signals(self, domain: str) -> Dict[str, Any]:
        """
        Retrieves domain ranking, authority metrics, and PPC spend.
        If unconfigured, returns None for all signals and tracks honest provenance.
        """
        if not self.is_configured():
            return {
                "signals": {
                    "poor_seo": {
                        "value": None,
                        "evidence": "DataForSEO provider unconfigured; organic SEO metrics skipped.",
                        "provider": self.name,
                    },
                    "low_domain_trust": {
                        "value": None,
                        "evidence": "DataForSEO provider unconfigured; domain trust skipped.",
                        "provider": self.name,
                    },
                    "ppc_spend": {
                        "value": None,
                        "evidence": "DataForSEO provider unconfigured; PPC ad spend skipped.",
                        "provider": self.name,
                    },
                },
                "provenance": {
                    "provider": self.name,
                    "status": "unconfigured",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            }

        try:
            # Query domain overview
            payload = [{"target": domain}]
            async with httpx.AsyncClient(timeout=15.0, auth=(self.login, self.password)) as client:
                res = await client.post(
                    f"{self.base_url}/dataforseo_labs/google/historical_rank_overview/live",
                    json=payload,
                )
                if res.status_code != 200:
                    return {
                        "signals": {
                            "poor_seo": {
                                "value": None,
                                "evidence": f"API error HTTP {res.status_code}",
                                "provider": self.name,
                            },
                            "low_domain_trust": {
                                "value": None,
                                "evidence": f"API error HTTP {res.status_code}",
                                "provider": self.name,
                            },
                            "ppc_spend": {
                                "value": None,
                                "evidence": f"API error HTTP {res.status_code}",
                                "provider": self.name,
                            },
                        },
                        "provenance": {"status": "error", "status_code": res.status_code},
                    }

                data = res.json()
                tasks = data.get("tasks", [])
                if not tasks or not tasks[0].get("result"):
                    return {
                        "signals": {
                            "poor_seo": {
                                "value": 1.0,
                                "evidence": "Zero ranking keywords detected",
                                "provider": self.name,
                            },
                            "low_domain_trust": {
                                "value": 1.0,
                                "evidence": "Domain authority undetectable / unindexed",
                                "provider": self.name,
                            },
                            "ppc_spend": {
                                "value": 0.0,
                                "evidence": "No active PPC ad spend found",
                                "provider": self.name,
                            },
                        },
                        "provenance": {"status": "no_data"},
                    }

                result = tasks[0]["result"][0] or {}
                # Labs overview endpoints nest the numbers under items[].metrics; accept both shapes.
                items = result.get("items") if isinstance(result.get("items"), list) else []
                metrics = result.get("metrics") or (
                    items[0].get("metrics") if items and isinstance(items[0], dict) else None
                ) or {}
                organic = metrics.get("organic") or {}
                paid = metrics.get("paid") or {}
                organic_keywords = organic.get("count") or 0
                paid_keywords = paid.get("count") or 0
                paid_cost = paid.get("estimated_paid_traffic_cost")

                is_poor_seo = organic_keywords < 50
                # Handbook rule: >$1k/month estimated paid traffic cost is a real buying signal.
                has_ppc = paid_cost > 1000 if isinstance(paid_cost, (int, float)) else paid_keywords > 0

                return {
                    "signals": {
                        "poor_seo": {
                            "value": 1.0 if is_poor_seo else 0.0,
                            "evidence": f"Organic keywords ranked: {organic_keywords}",
                            "provider": self.name,
                        },
                        "low_domain_trust": {
                            "value": 0.0,
                            "evidence": "Domain indexed with organic footprint",
                            "provider": self.name,
                        },
                        "ppc_spend": {
                            "value": 1.0 if has_ppc else 0.0,
                            "evidence": (
                                f"Estimated paid search spend ~${paid_cost:,.0f}/month ({paid_keywords} paid keywords)"
                                if isinstance(paid_cost, (int, float))
                                else f"Active paid PPC keywords: {paid_keywords}"
                            ),
                            "provider": self.name,
                        },
                    },
                    "provenance": {
                        "organic_keywords": organic_keywords,
                        "paid_keywords": paid_keywords,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                }
        except Exception as e:
            return {
                "signals": {
                    "poor_seo": {
                        "value": None,
                        "evidence": f"Error: {str(e)}",
                        "provider": self.name,
                    },
                    "low_domain_trust": {
                        "value": None,
                        "evidence": f"Error: {str(e)}",
                        "provider": self.name,
                    },
                    "ppc_spend": {
                        "value": None,
                        "evidence": f"Error: {str(e)}",
                        "provider": self.name,
                    },
                },
                "provenance": {"error": str(e), "status": "error"},
            }
