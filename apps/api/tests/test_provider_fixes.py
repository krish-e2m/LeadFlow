"""Regression tests for provider/crawler defects found during the live provider audit."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from bs4 import BeautifulSoup

from app.core.config import settings
from app.providers.crawler import WebCrawlerAdapter, extract_dates, latest_content_date
from app.providers.firecrawl import FirecrawlAdapter
from app.providers.hunter import HunterAdapter


def _page(url: str, html: str, markdown: str = "") -> dict:
    soup = BeautifulSoup(html, "html.parser")
    body = soup.body.get_text(separator=" ", strip=True) if soup.body else ""
    return {
        "url": url,
        "status_code": 200,
        "html": html,
        "soup": soup,
        "body_text": body,
        "words": len(body.split()),
        "markdown": markdown,
    }


def _evaluate(pages: list, domain: str = "example.com") -> dict:
    return WebCrawlerAdapter()._evaluate_signals_across_pages(pages, True, domain)


# ---------------------------------------------------------------------------
# Hunter: live /companies/find payload is camelCase with a string `location`
# ---------------------------------------------------------------------------

LIVE_COMPANY_FIND = {
    "data": {
        "name": "Stripe",
        "legalName": "Stripe, Inc.",
        "domain": "stripe.com",
        "domainAliases": [],
        "site": {"phoneNumbers": ["+1 888 926 2289"], "emailAddresses": ["info@stripe.com"]},
        "category": {"sector": "Information Technology", "industry": "Internet Software & Services"},
        "tags": ["Payments"],
        "description": "Financial infrastructure",
        "foundedYear": 2010,
        "location": "Oyster Point Blvd, 94080, South San Francisco, California, United States",
        "geo": {"city": "South San Francisco", "state": "California", "country": "United States", "countryCode": "US"},
        "facebook": {"handle": "stripe", "likes": None},
        "linkedin": {"handle": "company/stripe"},
        "twitter": {"handle": "stripe"},
        "companyType": "privately held",
        "phone": "+1 888 926 2289",
        "metrics": {"employees": "10K-50K", "employeesCount": 16597, "raised": 8700000000},
        "tech": ["stripe", "react-js"],
    }
}


@pytest.mark.asyncio
async def test_hunter_company_find_parses_live_camelcase_payload():
    adapter = HunterAdapter()
    adapter.api_key = "test_hunter_key_123"
    adapter.is_enabled = True
    response = httpx.Response(
        200, json=LIVE_COMPANY_FIND, request=httpx.Request("GET", "https://api.hunter.io/v2/companies/find")
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = response
        enrichment = await adapter.enrich_company("stripe.com")

    assert enrichment is not None
    assert enrichment["provider"] == "hunter_company_find"
    assert enrichment["company_name"] == "Stripe"
    assert enrichment["legal_name"] == "Stripe, Inc."
    assert enrichment["industry"] == "Internet Software & Services"
    assert enrichment["employee_count"] == 16597
    assert enrichment["city"] == "South San Francisco"
    assert enrichment["country"] == "US"
    assert enrichment["year_founded"] == 2010
    assert enrichment["phone"] == "+1 888 926 2289"
    assert enrichment["linkedin_url"] == "https://www.linkedin.com/company/stripe"
    assert enrichment["twitter_url"] == "https://twitter.com/stripe"
    assert enrichment["technologies"] == ["stripe", "react-js"]


@pytest.mark.asyncio
async def test_hunter_reveal_never_falls_back_to_a_different_person():
    """A requested first name that matches nobody must not unmask another employee's email."""
    adapter = HunterAdapter()
    adapter.api_key = "test_hunter_key_123"
    adapter.is_enabled = True
    domain_search = httpx.Response(
        200,
        json={"data": {"emails": [{"value": "other.person@acme.com", "first_name": "Other", "confidence": 90}]}},
        request=httpx.Request("GET", "https://api.hunter.io/v2/domain-search"),
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = domain_search
        result = await adapter.reveal_contact_details("acme.com", first_name="Jane")

    assert result["email"] is None


@pytest.mark.asyncio
async def test_hunter_reveal_tolerates_null_first_name_in_results():
    adapter = HunterAdapter()
    adapter.api_key = "test_hunter_key_123"
    adapter.is_enabled = True
    domain_search = httpx.Response(
        200,
        json={
            "data": {
                "emails": [
                    {"value": "info@acme.com", "first_name": None},
                    {"value": "jane@acme.com", "first_name": "Jane", "confidence": 88},
                ]
            }
        },
        request=httpx.Request("GET", "https://api.hunter.io/v2/domain-search"),
    )
    verifier = httpx.Response(
        200,
        json={"data": {"result": "deliverable", "score": 95}},
        request=httpx.Request("GET", "https://api.hunter.io/v2/email-verifier"),
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = [domain_search, verifier]
        result = await adapter.reveal_contact_details("acme.com", first_name="Jane")

    assert result["email"] == "jane@acme.com"


@pytest.mark.asyncio
async def test_hunter_health_probe_result_is_cached_to_save_search_credits():
    adapter = HunterAdapter()
    adapter.api_key = "test_hunter_key_123"
    adapter.is_enabled = True
    account = httpx.Response(
        200,
        json={"data": {"plan_name": "Free", "requests": {"searches": {"used": 1, "available": 50}}}},
        request=httpx.Request("GET", "https://api.hunter.io/v2/account"),
    )
    probe = httpx.Response(200, json={"data": {}}, request=httpx.Request("GET", "https://api.hunter.io/v2/domain-search"))

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = [account, probe, account]  # a second probe would exhaust the mock
        first = await adapter.check_health()
        second = await adapter.check_health()

    assert first.is_healthy and second.is_healthy
    assert mock_get.await_count == 3  # account, probe, account (no second probe)


# ---------------------------------------------------------------------------
# Firecrawl: health check must not spend a scrape credit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_firecrawl_health_uses_free_credit_usage_endpoint():
    adapter = FirecrawlAdapter()
    adapter.api_key = "fc-test-key"
    usage = httpx.Response(
        200,
        json={"success": True, "data": {"remainingCredits": 1315}},
        request=httpx.Request("GET", "https://api.firecrawl.dev/v2/team/credit-usage"),
    )

    with patch.object(settings, "FIRECRAWL_ENABLED", True):
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, patch(
            "httpx.AsyncClient.post", new_callable=AsyncMock
        ) as mock_post:
            mock_get.return_value = usage
            status = await adapter.check_health()

    mock_post.assert_not_called()
    assert mock_get.await_args.args[0].endswith("/team/credit-usage")
    assert status.is_healthy
    assert "1315" in status.status_message


# ---------------------------------------------------------------------------
# Crawler heuristics
# ---------------------------------------------------------------------------


def test_extract_dates_supports_common_formats():
    dates = extract_dates("Posted March 3, 2024 and 5 June 2023, updated 2022-11-09")
    assert {d.date().isoformat() for d in dates} == {"2024-03-03", "2023-06-05", "2022-11-09"}


def test_social_detection_ignores_lookalike_domains_and_tracking_pixels():
    html = (
        "<html lang='en'><body>"
        "<a href='https://wix.com/features'>Built on Wix</a>"
        "<img src='https://www.facebook.com/tr?id=123&ev=PageView'>"
        "<a href='https://www.youtube.com/watch?v=abc'>Watch</a>"
        "</body></html>"
    )
    signals = _evaluate([_page("https://example.com/", html)])
    assert signals["weak_social"]["value"] == 1.0


def test_social_detection_finds_real_profiles():
    html = (
        "<html lang='en'><body>"
        "<a href='https://www.linkedin.com/company/acme'>LinkedIn</a>"
        "<a href='https://twitter.com/acme'>X</a>"
        "</body></html>"
    )
    signals = _evaluate([_page("https://example.com/", html)])
    assert signals["weak_social"]["value"] == 0.0
    assert "LinkedIn" in signals["weak_social"]["evidence"]


def test_channel_link_is_not_counted_as_embedded_video():
    html = "<html><body><a href='https://www.youtube.com/channel/UC123'>Our channel</a></body></html>"
    assert _evaluate([_page("https://example.com/", html)])["no_video"]["value"] == 1.0


def test_youtube_iframe_embed_counts_as_video():
    html = "<html><body><iframe src='https://www.youtube.com/embed/abc'></iframe></body></html>"
    assert _evaluate([_page("https://example.com/", html)])["no_video"]["value"] == 0.0


def test_host_name_keywords_do_not_create_false_blog_press_or_careers_matches():
    """A domain such as newsmax-jobs-press.com must not satisfy blog/press/careers URL checks."""
    html = "<html lang='en'><body><h1>Welcome</h1></body></html>"
    signals = _evaluate([_page("https://newsmax-jobs-press.com/", html)], domain="newsmax-jobs-press.com")
    assert signals["stale_blog"]["value"] == 1.0
    assert signals["no_press"]["value"] == 1.0
    assert signals["hiring"]["value"] is None


def test_blog_with_old_posts_is_flagged_stale():
    old = (datetime.now(timezone.utc) - timedelta(days=500)).date().isoformat()
    blog_html = f"<html><body><article><time datetime='{old}'>old</time></article></body></html>"
    signals = _evaluate([_page("https://example.com/", "<html></html>"), _page("https://example.com/blog", blog_html)])
    assert signals["stale_blog"]["value"] == 1.0
    assert "Stale blog" in signals["stale_blog"]["evidence"]


def test_blog_with_recent_post_is_not_stale():
    recent = (datetime.now(timezone.utc) - timedelta(days=20)).date().isoformat()
    blog_html = f"<html><body><article><time datetime='{recent}'>new</time></article></body></html>"
    signals = _evaluate([_page("https://example.com/", "<html></html>"), _page("https://example.com/blog", blog_html)])
    assert signals["stale_blog"]["value"] == 0.0


def test_old_press_releases_are_flagged():
    old = (datetime.now(timezone.utc) - timedelta(days=800)).date().isoformat()
    press_html = f"<html><body><time datetime='{old}'>old</time></body></html>"
    signals = _evaluate([_page("https://example.com/", "<html></html>"), _page("https://example.com/press", press_html)])
    assert signals["no_press"]["value"] == 1.0


def test_latest_content_date_ignores_future_dates():
    future = (datetime.now(timezone.utc) + timedelta(days=400)).date().isoformat()
    page = _page("https://example.com/blog", f"<html><body><time datetime='{future}'>x</time></body></html>")
    assert latest_content_date(page) is None


@pytest.mark.asyncio
async def test_firecrawl_prefers_raw_html_so_head_tags_survive():
    """Firecrawl's cleaned `html` format strips <head>; signals need rawHtml (title, viewport, OG...)."""
    adapter = FirecrawlAdapter()
    adapter.api_key = "fc-test-key"
    payload = {
        "success": True,
        "data": {
            "html": "<body><h1>Cleaned</h1></body>",
            "rawHtml": "<html><head><title>Full</title><meta name='viewport' content='width=device-width'></head><body></body></html>",
            "markdown": "# Cleaned",
            "metadata": {"statusCode": 200},
        },
    }
    response = httpx.Response(200, json=payload, request=httpx.Request("POST", "https://api.firecrawl.dev/v2/scrape"))

    with patch.object(settings, "FIRECRAWL_ENABLED", True):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = response
            result = await adapter.scrape_url("https://example.com")

    assert "rawHtml" in mock_post.await_args.kwargs["json"]["formats"]
    assert "<title>Full</title>" in result["html"]


@pytest.mark.asyncio
async def test_pagespeed_healthy_result_is_cached_to_avoid_repeat_lighthouse_runs():
    from app.providers.pagespeed import PageSpeedAdapter

    adapter = PageSpeedAdapter()
    adapter.api_key = "psi-test-key"
    ok = httpx.Response(200, json={}, request=httpx.Request("GET", "https://pagespeedonline.googleapis.com/x"))

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = ok
        first = await adapter.check_health()
        second = await adapter.check_health()

    assert first.is_healthy and second.is_healthy
    assert mock_get.await_count == 1
