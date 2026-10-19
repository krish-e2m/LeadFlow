"""
LeadFlow - Firecrawl Live Smoke Test.

Verifies live connectivity to Firecrawl API v2 by testing the configured
FIRECRAWL_API_KEY against https://web.dev/ or an example URL.
Strictly adheres to zero-exposure constraints: never prints the API key,
request headers containing the key, or full raw payloads.
"""

import asyncio
import os
import sys

# Windows consoles default to cp1252 and crash on symbols such as the star in ratings.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# Ensure apps/api is on the python search path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import settings  # noqa: E402
from app.providers.firecrawl import FirecrawlAdapter  # noqa: E402


async def run_firecrawl_smoke_test() -> int:
    print("=================================================================")
    print("         LeadFlow: Firecrawl v2 Live Smoke Test                  ")
    print("=================================================================")

    adapter = FirecrawlAdapter()

    # 1. Configuration verification
    if not adapter.is_configured():
        if not settings.FIRECRAWL_ENABLED:
            print("[CONFIG ERROR] FIRECRAWL_ENABLED is False in .env.")
            print("Action: Set FIRECRAWL_ENABLED=true in your .env file to enable Firecrawl.")
        elif not adapter.api_key:
            print("[CONFIG ERROR] FIRECRAWL_API_KEY is not configured or is empty in .env.")
            print("Action: Add FIRECRAWL_API_KEY=fc-... to your .env file.")
        return 1

    print("[CONFIG] Firecrawl API key detected (value redacted).")
    print(f"[CONFIG] Endpoint: {adapter.base_url}")

    # 2. Health check
    print("\nPinging Firecrawl health check...")
    status = await adapter.check_health()
    print(f"[HEALTH] Is Configured: {status.is_configured}")
    print(f"[HEALTH] Is Healthy:    {status.is_healthy}")
    print(f"[HEALTH] Status Msg:    {status.status_message}")

    if not status.is_healthy:
        print("\n[ERROR] Health check failed. Please verify your API key and quota at https://firecrawl.dev.")
        return 1

    # 3. Test Scrape & LLM Markdown Extraction
    target_url = "https://example.com"
    print(f"\nTesting live scrape & markdown extraction for {target_url}...")
    result = await adapter.scrape_url(target_url, formats=["markdown", "rawHtml"])

    if not result.get("success"):
        print(f"[ERROR] Scrape failed: {result.get('error')}")
        return 1

    markdown_snippet = (result.get("markdown", "") or "")[:250].replace("\n", " ")
    print(f"[SUCCESS] Scraped successfully! Status: {result.get('status_code')}")
    print(f"[METRIC]  Rendered HTML size:     {len(result.get('html', ''))} characters")
    print(f"[METRIC]  Extracted Markdown size: {len(result.get('markdown', ''))} characters")
    print(f"[PREVIEW] Markdown sample:        \"{markdown_snippet}...\"")
    print("\n[SUCCESS] Firecrawl provider adapter is operational and ready for live lead runs!")
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(run_firecrawl_smoke_test())
    sys.exit(exit_code)
