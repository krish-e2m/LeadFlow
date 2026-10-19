import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import httpx

from app.core.config import settings
from app.providers.base import BaseProviderAdapter, ProviderStatus

OFFICIAL_PAGESPEED_ENDPOINT = "https://pagespeedonline.googleapis.com/pagespeedonline/v5/runPagespeed"


class PageSpeedAdapter(BaseProviderAdapter):
    """Google PageSpeed Insights API v5 collector for performance, accessibility, and Core Web Vitals."""

    # Live Lighthouse runs routinely take 25-45s for heavy sites; 45s caused intermittent timeouts.
    AUDIT_TIMEOUT_SECONDS = 90.0
    # A health check is a full Lighthouse run (10-30s) that also uses API quota, so a healthy
    # result is reused for an hour instead of re-running on every admin page load.
    HEALTH_CACHE_SECONDS = 3600

    def __init__(self):
        super().__init__("google_pagespeed")
        self.api_key = settings.PAGESPEED_API_KEY
        self._healthy_status: Optional[Tuple[float, ProviderStatus]] = None
        base = settings.PAGESPEED_BASE_URL or OFFICIAL_PAGESPEED_ENDPOINT
        if "www.googleapis.com/pagespeedonline" in base:
            self.base_url = OFFICIAL_PAGESPEED_ENDPOINT
        else:
            self.base_url = base

    def is_configured(self) -> bool:
        return bool(self.api_key and len(self.api_key.strip()) > 0)

    async def check_health(self) -> ProviderStatus:
        if not self.is_configured():
            return ProviderStatus(
                name=self.name,
                is_configured=False,
                is_healthy=False,
                status_message="Google PageSpeed API key not configured.",
                last_checked=datetime.now(timezone.utc),
            )
        cached = self._healthy_status
        if cached and time.monotonic() - cached[0] < self.HEALTH_CACHE_SECONDS:
            return cached[1]

        try:
            # Ping with test domain
            async with httpx.AsyncClient(timeout=self.AUDIT_TIMEOUT_SECONDS) as client:
                params = {
                    "url": "https://example.com",
                    "key": self.api_key,
                    "category": "performance",
                }
                res = await client.get(self.base_url, params=params)
                is_healthy = res.status_code == 200
                msg = (
                    "Connected successfully"
                    if is_healthy
                    else f"PageSpeed API returned HTTP {res.status_code}"
                )
                status = ProviderStatus(
                    name=self.name,
                    is_configured=True,
                    is_healthy=is_healthy,
                    status_message=msg,
                    last_checked=datetime.now(timezone.utc),
                )
                if is_healthy:
                    self._healthy_status = (time.monotonic(), status)
                return status
        except Exception as e:
            return ProviderStatus(
                name=self.name,
                is_configured=True,
                is_healthy=False,
                status_message=f"Connection error: {str(e)}",
                last_checked=datetime.now(timezone.utc),
            )

    async def audit_url(self, url: str) -> Dict[str, Any]:
        """Audits a domain URL and extracts slow_site, not_mobile_friendly, and accessibility signals."""
        if not self.is_configured():
            return {
                "signals": {
                    "slow_site": {
                        "value": None,
                        "evidence": "PageSpeed provider unconfigured",
                        "provider": self.name,
                    },
                    "not_mobile_friendly": {
                        "value": None,
                        "evidence": "PageSpeed provider unconfigured",
                        "provider": self.name,
                    },
                    "accessibility": {
                        "value": None,
                        "evidence": "PageSpeed provider unconfigured",
                        "provider": self.name,
                    },
                },
                "provenance": {"configured": False, "status": "skipped"},
            }

        target = url if url.startswith("http") else f"https://{url}"
        params = {
            "url": target,
            "key": self.api_key,
            "category": ["performance", "accessibility", "seo"],
            "strategy": "mobile",
        }

        try:
            async with httpx.AsyncClient(timeout=self.AUDIT_TIMEOUT_SECONDS) as client:
                resp = await client.get(self.base_url, params=params)
                if resp.status_code != 200:
                    try:
                        err_payload = resp.json().get("error", {})
                        err_msg = err_payload.get("message", f"HTTP {resp.status_code}")
                    except Exception:
                        err_msg = f"HTTP {resp.status_code}"
                    safe_err = err_msg.replace(self.api_key, "[REDACTED]") if self.api_key else err_msg

                    return {
                        "signals": {
                            "slow_site": {
                                "value": None,
                                "evidence": f"PageSpeed API error: {safe_err}",
                                "provider": self.name,
                            },
                            "not_mobile_friendly": {
                                "value": None,
                                "evidence": f"PageSpeed API error: {safe_err}",
                                "provider": self.name,
                            },
                            "accessibility": {
                                "value": None,
                                "evidence": f"PageSpeed API error: {safe_err}",
                                "provider": self.name,
                            },
                        },
                        "provenance": {"status_code": resp.status_code, "error": safe_err},
                    }

                data = resp.json()
                lighthouse = data.get("lighthouseResult", {})
                categories = lighthouse.get("categories", {})

                perf_score = categories.get("performance", {}).get("score")  # 0.0 to 1.0 or None
                access_score = categories.get("accessibility", {}).get("score")  # 0.0 to 1.0 or None

                audits = lighthouse.get("audits", {})
                fcp = audits.get("first-contentful-paint", {}).get("displayValue", "N/A")
                lcp = audits.get("largest-contentful-paint", {}).get("displayValue", "N/A")
                tbt = audits.get("total-blocking-time", {}).get("displayValue", "N/A")

                viewport_audit = audits.get("viewport")
                viewport_score = viewport_audit.get("score") if isinstance(viewport_audit, dict) else None

                # Slow site signal (weight: 1.3): perf_score < 0.5 is severe opportunity
                if perf_score is not None:
                    is_slow = perf_score < 0.5
                    slow_val = 1.0 if is_slow else 0.0
                    slow_evidence = f"Lighthouse mobile score: {int(perf_score * 100)}/100 (FCP: {fcp}, LCP: {lcp})"
                else:
                    slow_val = None
                    slow_evidence = "Lighthouse performance score unavailable"

                # Mobile friendly signal (weight: 0.8): viewport_score < 0.9 is deficient
                if viewport_score is not None:
                    not_mobile = viewport_score < 0.9
                    not_mobile_val = 1.0 if not_mobile else 0.0
                    not_mobile_evidence = (
                        "Missing or deficient viewport configuration"
                        if not_mobile
                        else "Valid mobile viewport detected"
                    )
                else:
                    not_mobile_val = None
                    not_mobile_evidence = "Lighthouse viewport audit unavailable"

                # Accessibility signal (weight: 0.6): access_score < 0.6 is poor accessibility
                if access_score is not None:
                    poor_accessibility = access_score < 0.6
                    access_val = 1.0 if poor_accessibility else 0.0
                    access_evidence = f"Accessibility score: {int(access_score * 100)}/100"
                else:
                    access_val = None
                    access_evidence = "Lighthouse accessibility score unavailable"

                signals = {
                    "slow_site": {
                        "value": slow_val,
                        "evidence": slow_evidence,
                        "provider": self.name,
                    },
                    "not_mobile_friendly": {
                        "value": not_mobile_val,
                        "evidence": not_mobile_evidence,
                        "provider": self.name,
                    },
                    "accessibility": {
                        "value": access_val,
                        "evidence": access_evidence,
                        "provider": self.name,
                    },
                }

                return {
                    "signals": signals,
                    "provenance": {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "perf_score": perf_score,
                        "access_score": access_score,
                        "fcp": fcp,
                        "lcp": lcp,
                        "tbt": tbt,
                    },
                }
        except Exception as e:
            raw_e = str(e) or type(e).__name__  # httpx timeouts stringify to ""
            safe_e = raw_e.replace(self.api_key, "[REDACTED]") if self.api_key else raw_e
            return {
                "signals": {
                    "slow_site": {
                        "value": None,
                        "evidence": f"PageSpeed timeout/error: {safe_e}",
                        "provider": self.name,
                    },
                    "not_mobile_friendly": {
                        "value": None,
                        "evidence": f"PageSpeed timeout/error: {safe_e}",
                        "provider": self.name,
                    },
                    "accessibility": {
                        "value": None,
                        "evidence": f"PageSpeed timeout/error: {safe_e}",
                        "provider": self.name,
                    },
                },
                "provenance": {"error": safe_e},
            }
