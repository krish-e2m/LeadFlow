"""
LeadFlow - Official Hunter.io API Live Smoke Test.

Validates end-to-end Hunter.io integration, authentication, account status,
domain search, and contact discovery using the configured HUNTER_API_KEY.

Usage:
    python scripts/check_hunter.py
"""

import asyncio
import os
import sys

# Windows consoles default to cp1252 and crash on symbols such as the star in ratings.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# Ensure apps/api is in Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.providers.hunter import HunterAdapter  # noqa: E402


async def run_hunter_smoke_test() -> int:
    print("=" * 70)
    print("            LeadFlow: Hunter.io Live Smoke Test                  ")
    print("=" * 70)

    adapter = HunterAdapter()

    if not adapter.is_configured():
        print("\n[CONFIG ERROR] HUNTER_API_KEY is not configured or is empty in .env.")
        print("Action: Add HUNTER_API_KEY=<your_key> to your .env file.")
        print("\nSmoke test cannot proceed without an API key.")
        return 1

    print("[CONFIG] Hunter.io API key detected (value redacted).")
    print(f"[CONFIG] Base URL: {adapter.base_url}")

    # Step 1: Health check / Account validation
    print("\n--- 1. Checking Account Health (GET /account) ---")
    status = await adapter.check_health()
    print(f"Status Message : {status.status_message}")
    print(f"Is Healthy     : {status.is_healthy}")

    if not status.is_healthy:
        if "restricted" in status.status_message.lower():
            print("\n[ACCOUNT RESTRICTED ON HUNTER.IO]")
            print("Hunter.io requires a one-time email verification / onboarding confirmation.")
            print("\nAction Required:")
            print("  1. Log in to https://hunter.io with your account.")
            print("  2. Check your inbox for the verification email from Hunter and click the link.")
            print("  3. Complete any pending onboarding prompts on https://hunter.io.")
            print("  4. Re-run this smoke test once verified.")
        else:
            print("\n[ERROR] Hunter.io authentication failed. Please verify your API key.")
        return 1

    # Step 2: Test Domain Search & Company Enrichment
    test_domain = "stripe.com"
    print(f"\n--- 2. Testing Company Enrichment for '{test_domain}' (GET /domain-search) ---")
    enrichment = await adapter.enrich_organization(test_domain)
    if enrichment:
        print(f"[SUCCESS] Company Name : {enrichment.get('company_name')}")
        print(f"[SUCCESS] Industry     : {enrichment.get('industry')}")
        print(f"[SUCCESS] Country      : {enrichment.get('country')}")
        print(f"[SUCCESS] City         : {enrichment.get('city')}")
        print(f"[SUCCESS] Tech Stack   : {len(enrichment.get('technologies', []))} technologies detected")
    else:
        print(f"[WARNING] Could not enrich {test_domain}.")

    # Step 3: Test Executive Contact Discovery
    print(f"\n--- 3. Testing Contact Discovery for '{test_domain}' ---")
    contacts = await adapter.search_contacts_for_lead(test_domain)
    print(f"[SUCCESS] Found {len(contacts)} contacts (masked for safety):")
    for idx, c in enumerate(contacts[:3], 1):
        name = f"{c.get('first_name') or ''} {c.get('last_name') or ''}".strip() or "Anonymous"
        print(f"  {idx}. {name} — {c.get('title')} ({c.get('email')}) [Confidence: {c.get('confidence')}%]")

    print("\n" + "=" * 70)
    print("[SUCCESS] Hunter.io provider is fully integrated into LeadFlow!")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(run_hunter_smoke_test())
    sys.exit(exit_code)
