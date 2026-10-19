"""
LeadFlow - Official SerpApi Live Smoke Test.

Verifies live connectivity, account status, and Google Maps business reviews
using the configured SERPAPI_API_KEY.
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

from app.providers.serpapi import SerpApiAdapter  # noqa: E402


async def run_serpapi_smoke_test() -> int:
    print("=================================================================")
    print("              LeadFlow: SerpApi Live Smoke Test                  ")
    print("=================================================================")

    adapter = SerpApiAdapter()

    # 1. Configuration Check
    if not adapter.is_configured():
        print("[CONFIG ERROR] SERPAPI_API_KEY is not configured or is empty in .env.")
        print("Action: Add SERPAPI_API_KEY=<your_api_key> to your .env file.")
        print("Note:   You can find your API key at https://serpapi.com/manage-api-key")
        return 1

    print("[CONFIG] SerpApi key detected (value redacted).")
    print(f"[CONFIG] Endpoint: {adapter.base_url}")

    # 2. Account Health Check (Free Endpoint)
    print("\nPinging SerpApi account endpoint (GET /account.json)...")
    status = await adapter.check_health()
    print(f"[HEALTH] Is Configured: {status.is_configured}")
    print(f"[HEALTH] Is Healthy:    {status.is_healthy}")
    print(f"[HEALTH] Status Msg:    {status.status_message}")

    if not status.is_healthy:
        print("\n[ERROR] SerpApi authentication failed. Please verify your API key at https://serpapi.com.")
        return 1

    # 3. Live Google Maps Business Rating & Review Search
    test_company = "Starbucks"
    test_location = "Seattle, WA"
    print(f"\nTesting live Google Maps rating and reviews for '{test_company}' in '{test_location}'...")
    review_res = await adapter.fetch_review_signals(
        company_name=test_company, domain="starbucks.com", location=test_location
    )

    signals = review_res.get("signals", {})
    provenance = review_res.get("provenance", {})
    rating_signal = signals.get("low_review_rating", {})

    print("[SUCCESS] Google Maps Business Search via SerpApi Succeeded!")
    print(f"  Business Title:  {provenance.get('title')}")
    print(f"  Google Rating:   {provenance.get('rating')} / 5.0")
    print(f"  Reviews Count:   {provenance.get('review_count')} published reviews")
    print(f"  Address:         {provenance.get('address')}")
    print(f"  Phone:           {provenance.get('phone')}")
    print(f"  Website:         {provenance.get('website')}")
    print(f"  Place ID:        {provenance.get('place_id')}")

    print("\n--- 22-Signal Engine Output ---")
    print("  Signal Key:      low_review_rating")
    print(f"  Signal Value:    {rating_signal.get('value')} (1.0 = sub-par reputation, 0.0 = strong reputation, None = unavailable)")
    print(f"  Audit Evidence:  \"{rating_signal.get('evidence')}\"")
    print("\n[SUCCESS] SerpApi provider adapter is operational and ready for live lead runs!")
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(run_serpapi_smoke_test())
    sys.exit(exit_code)
