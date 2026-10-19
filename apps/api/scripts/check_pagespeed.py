"""
LeadFlow - Google PageSpeed Insights API Live Smoke Test.

Submits exactly one verification request for https://web.dev/ using the
configured backend settings.
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

import httpx  # noqa: E402

from app.core.config import settings  # noqa: E402


async def run_pagespeed_smoke_test() -> int:
    print("=================================================================")
    print("   LeadFlow: Official Google PageSpeed Insights Live Smoke Test  ")
    print("=================================================================")

    # 1. Configuration verification
    api_key = settings.PAGESPEED_API_KEY
    if not api_key or not api_key.strip():
        print("[CONFIG ERROR] PAGESPEED_API_KEY is not configured or is empty.")
        print("Action: Ensure PAGESPEED_API_KEY is set in your .env file.")
        return 1

    print("[CONFIG] API key present in backend settings (value redacted).")

    base_url = (
        settings.PAGESPEED_BASE_URL
        or "https://pagespeedonline.googleapis.com/pagespeedonline/v5/runPagespeed"
    )
    target_url = "https://web.dev/"
    print(f"[TARGET]  URL:        {target_url}")
    print(f"[TARGET]  Endpoint:   {base_url}")
    print("[TARGET]  Strategy:   mobile")
    print("[TARGET]  Categories: performance, accessibility, seo")
    print("\nSending single request to Google PageSpeed Insights API (approx. 10-25s)...")

    params = {
        "url": target_url,
        "key": api_key,
        "category": ["performance", "accessibility", "seo"],
        "strategy": "mobile",
    }

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.get(base_url, params=params)

            print(f"[RESPONSE] HTTP Status: {resp.status_code} {resp.reason_phrase}")

            if resp.status_code != 200:
                try:
                    err_data = resp.json().get("error", {})
                    err_msg = err_data.get("message", f"HTTP {resp.status_code}")
                except Exception:
                    err_msg = f"HTTP {resp.status_code}"

                # Redact any accidental key leakage in error text
                safe_err = err_msg.replace(api_key, "[REDACTED]")
                print(f"[API ERROR] Google API returned error: {safe_err}")
                return 1

            data = resp.json()
            lighthouse = data.get("lighthouseResult", {})
            categories = lighthouse.get("categories", {})
            audits = lighthouse.get("audits", {})

            # Extract category scores (0.0 to 1.0)
            perf_score = categories.get("performance", {}).get("score")
            access_score = categories.get("accessibility", {}).get("score")
            seo_score = categories.get("seo", {}).get("score")

            # Extract Web Vitals & key metrics
            fcp = audits.get("first-contentful-paint", {}).get("displayValue", "N/A")
            lcp = audits.get("largest-contentful-paint", {}).get("displayValue", "N/A")
            tbt = audits.get("total-blocking-time", {}).get("displayValue", "N/A")
            cls = audits.get("cumulative-layout-shift", {}).get("displayValue", "N/A")
            speed_index = audits.get("speed-index", {}).get("displayValue", "N/A")

            print("\n---------------- Category Scores (Lighthouse) ----------------")
            print(f"  Performance:    {int(perf_score * 100) if perf_score is not None else 'N/A'}/100")
            print(f"  Accessibility:  {int(access_score * 100) if access_score is not None else 'N/A'}/100")
            print(f"  SEO:            {int(seo_score * 100) if seo_score is not None else 'N/A'}/100")

            print("\n---------------- Core Web Vitals & Metrics -------------------")
            print(f"  First Contentful Paint (FCP):   {fcp}")
            print(f"  Largest Contentful Paint (LCP): {lcp}")
            print(f"  Total Blocking Time (TBT):      {tbt}")
            print(f"  Cumulative Layout Shift (CLS):  {cls}")
            print(f"  Speed Index:                    {speed_index}")

            print("\n[SUCCESS] Official Google PageSpeed Insights API is live and verified!")
            return 0

    except httpx.TimeoutException:
        print("[ERROR] Request timed out after 45.0 seconds.")
        return 1
    except Exception as e:
        safe_msg = str(e).replace(api_key, "[REDACTED]")
        print(f"[ERROR] Request failed with exception: {safe_msg}")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(run_pagespeed_smoke_test())
    sys.exit(exit_code)
