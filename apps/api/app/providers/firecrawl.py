from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings
from app.core.logging import logger
from app.providers.base import BaseProviderAdapter, ProviderStatus

DEFAULT_FIRECRAWL_BASE_URL = "https://api.firecrawl.dev/v2"


class FirecrawlAdapter(BaseProviderAdapter):
    """
    Firecrawl v2 provider adapter.
    Provides headless browser rendering, bot/Cloudflare bypass, clean LLM Markdown extraction,
    and metadata extraction via official Firecrawl API v2.
    """

    def __init__(self):
        super().__init__("firecrawl")
        self.api_key = settings.FIRECRAWL_API_KEY
        raw_url = (settings.FIRECRAWL_BASE_URL or DEFAULT_FIRECRAWL_BASE_URL).rstrip("/")
        # Migrate default cloud v1 URL to v2 seamlessly without requiring manual .env edit
        if raw_url == "https://api.firecrawl.dev/v1":
            raw_url = "https://api.firecrawl.dev/v2"
        self.base_url = raw_url
        self.timeout = getattr(settings, "FIRECRAWL_TIMEOUT_SECONDS", 15.0)

    def is_configured(self) -> bool:
        """
        Firecrawl is considered configured only when:
        1. FIRECRAWL_ENABLED is explicitly True.
        2. FIRECRAWL_API_KEY is non-empty.
        """
        enabled = getattr(settings, "FIRECRAWL_ENABLED", False)
        has_key = bool(self.api_key and len(self.api_key.strip()) > 0)
        return bool(enabled and has_key)

    async def check_health(self) -> ProviderStatus:
        """Verifies Firecrawl API connectivity and key validity."""
        enabled = getattr(settings, "FIRECRAWL_ENABLED", False)
        if not enabled:
            return ProviderStatus(
                name=self.name,
                is_configured=False,
                is_healthy=False,
                status_message="Firecrawl provider disabled by configuration (FIRECRAWL_ENABLED=False).",
                last_checked=datetime.now(timezone.utc),
            )

        if not self.api_key or len(self.api_key.strip()) == 0:
            return ProviderStatus(
                name=self.name,
                is_configured=False,
                is_healthy=False,
                status_message="Firecrawl API key not configured.",
                last_checked=datetime.now(timezone.utc),
            )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        # The credit-usage endpoint validates the key without spending a scrape credit.
        api_root = self.base_url[: -len("/scrape")] if self.base_url.endswith("/scrape") else self.base_url
        endpoint = f"{api_root}/team/credit-usage"

        try:
            async with httpx.AsyncClient(timeout=min(self.timeout, 15.0)) as client:
                res = await client.get(endpoint, headers=headers)
                is_healthy = res.status_code == 200
                if is_healthy:
                    try:
                        remaining = (res.json().get("data") or {}).get("remainingCredits")
                    except Exception:
                        remaining = None
                    msg = "Connected successfully to Firecrawl API v2" + (
                        f" ({remaining} credits remaining)" if remaining is not None else ""
                    )
                else:
                    msg = f"Firecrawl API returned HTTP {res.status_code}: {res.text[:100]}"
                safe_msg = msg.replace(self.api_key, "[REDACTED]") if self.api_key else msg
                return ProviderStatus(
                    name=self.name,
                    is_configured=True,
                    is_healthy=is_healthy,
                    status_message=safe_msg,
                    last_checked=datetime.now(timezone.utc),
                )
        except Exception as e:
            safe_err = str(e).replace(self.api_key, "[REDACTED]") if self.api_key else str(e)
            return ProviderStatus(
                name=self.name,
                is_configured=True,
                is_healthy=False,
                status_message=f"Firecrawl connection error: {safe_err}",
                last_checked=datetime.now(timezone.utc),
            )

    async def scrape_url(
        self,
        url: str,
        formats: Optional[List[str]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Scrapes a single URL via Firecrawl v2 API.
        Extracts rendered HTML, LLM-ready clean Markdown, and metadata.
        """
        if not self.is_configured():
            enabled = getattr(settings, "FIRECRAWL_ENABLED", False)
            reason = "disabled by configuration (FIRECRAWL_ENABLED=False)" if not enabled else "API key missing"
            return {
                "success": False,
                "error": f"Firecrawl unconfigured: {reason}",
                "markdown": "",
                "html": "",
                "metadata": {},
                "links": [],
            }

        target = url if url.startswith("http") else f"https://{url}"
        requested_formats = formats or ["markdown", "rawHtml", "links"]

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload = {
            "url": target,
            "formats": requested_formats,
            "onlyMainContent": False,
        }
        endpoint = f"{self.base_url}/scrape" if not self.base_url.endswith("/scrape") else self.base_url
        req_timeout = timeout or self.timeout

        try:
            async with httpx.AsyncClient(timeout=req_timeout) as client:
                resp = await client.post(
                    endpoint,
                    json=payload,
                    headers=headers,
                )

                if resp.status_code != 200:
                    err_text = resp.text[:200]
                    safe_err = err_text.replace(self.api_key, "[REDACTED]") if self.api_key else err_text
                    logger.warning(f"Firecrawl scrape failed for {target}: HTTP {resp.status_code} - {safe_err}")
                    return {
                        "success": False,
                        "status_code": resp.status_code,
                        "error": f"Firecrawl HTTP {resp.status_code}: {safe_err}",
                        "markdown": "",
                        "html": "",
                        "metadata": {},
                        "links": [],
                    }

                try:
                    res_json = resp.json()
                except Exception as parse_err:
                    return {
                        "success": False,
                        "status_code": 200,
                        "error": f"Malformed JSON from Firecrawl: {str(parse_err)}",
                        "markdown": "",
                        "html": "",
                        "metadata": {},
                        "links": [],
                    }

                if not isinstance(res_json, dict) or not res_json.get("success", False):
                    err_msg = res_json.get("error") if isinstance(res_json, dict) else "Unsuccessful scrape response"
                    safe_err = str(err_msg).replace(self.api_key, "[REDACTED]") if self.api_key else str(err_msg)
                    return {
                        "success": False,
                        "status_code": 200,
                        "error": safe_err,
                        "markdown": "",
                        "html": "",
                        "metadata": {},
                        "links": [],
                    }

                data = res_json.get("data", {})
                if not isinstance(data, dict):
                    data = {}

                metadata = data.get("metadata", {})
                if not isinstance(metadata, dict):
                    metadata = {}

                # Prefer rawHtml: Firecrawl's cleaned `html` format drops <head>, which hides the
                # title, meta description, viewport, Open Graph and generator tags the signals read.
                html_content = data.get("rawHtml") or data.get("html") or ""
                markdown_content = data.get("markdown") or ""
                links_list = data.get("links") or []
                if not isinstance(links_list, list):
                    links_list = []

                final_url = metadata.get("url") or metadata.get("sourceURL") or target
                reported_status = metadata.get("statusCode") or 200

                return {
                    "success": True,
                    "status_code": reported_status,
                    "url": final_url,
                    "markdown": markdown_content,
                    "html": html_content,
                    "metadata": metadata,
                    "links": links_list,
                }

        except Exception as e:
            safe_e = str(e).replace(self.api_key, "[REDACTED]") if self.api_key else str(e)
            logger.error(f"Firecrawl exception scraping {target}: {safe_e}")
            return {
                "success": False,
                "error": safe_e,
                "markdown": "",
                "html": "",
                "metadata": {},
                "links": [],
            }
