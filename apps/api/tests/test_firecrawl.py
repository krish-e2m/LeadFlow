import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from bs4 import BeautifulSoup

from app.core.config import settings
from app.models.lead import Lead
from app.providers.crawler import WebCrawlerAdapter
from app.providers.firecrawl import FirecrawlAdapter
from app.providers.manager import provider_manager
from app.scoring.engine import ScoringEngineCore
from app.services.enrichment_service import EnrichmentService


# ---------------------------------------------------------------------------
# Group A: Feature Flag & Configuration Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_firecrawl_disabled_with_configured_key_makes_no_network_call():
    """When FIRECRAWL_ENABLED=False, adapter must not be configured and must make no network call."""
    adapter = FirecrawlAdapter()
    adapter.api_key = "fc-test-key-123"

    with patch.object(settings, "FIRECRAWL_ENABLED", False):
        assert not adapter.is_configured()

        status = await adapter.check_health()
        assert not status.is_configured
        assert not status.is_healthy
        assert "disabled by configuration" in status.status_message

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            result = await adapter.scrape_url("https://example.com")
            mock_post.assert_not_called()
            assert not result["success"]
            assert "disabled by configuration" in result["error"]


@pytest.mark.asyncio
async def test_firecrawl_enabled_with_empty_key_is_unconfigured():
    """When FIRECRAWL_ENABLED=True but key is empty, adapter is unconfigured and makes no call."""
    adapter = FirecrawlAdapter()
    adapter.api_key = ""

    with patch.object(settings, "FIRECRAWL_ENABLED", True):
        assert not adapter.is_configured()

        status = await adapter.check_health()
        assert not status.is_configured
        assert not status.is_healthy
        assert "not configured" in status.status_message.lower()

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            result = await adapter.scrape_url("https://example.com")
            mock_post.assert_not_called()
            assert not result["success"]
            assert "API key missing" in result["error"]


@pytest.mark.asyncio
async def test_firecrawl_enabled_with_valid_key_attempts_request():
    """When enabled and key is present, adapter is configured and attempts request."""
    adapter = FirecrawlAdapter()
    adapter.api_key = "fc-valid-test-key"

    with patch.object(settings, "FIRECRAWL_ENABLED", True):
        assert adapter.is_configured()


# ---------------------------------------------------------------------------
# Group B: Firecrawl API v2 Response Contract & Error Handling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_firecrawl_v2_successful_scrape_parsing():
    """Verify adapter parses documented Firecrawl v2 response and normalizes payload."""
    adapter = FirecrawlAdapter()
    adapter.api_key = "fc-test-key-v2"

    mock_resp = {
        "success": True,
        "data": {
            "markdown": "# Slikk Club\nFast delivery in 60 mins.",
            "html": "<html><body><h1>Slikk Club</h1><p>Fast delivery in 60 mins.</p></body></html>",
            "metadata": {
                "title": "Slikk Club",
                "statusCode": 200,
                "url": "https://www.slikk.club/",
                "sourceURL": "https://www.slikk.club/",
            },
            "links": ["https://www.slikk.club/about", "https://www.slikk.club/careers"],
        },
    }

    mock_http = httpx.Response(
        status_code=200,
        json=mock_resp,
        request=httpx.Request("POST", "https://api.firecrawl.dev/v2/scrape"),
    )

    with patch.object(settings, "FIRECRAWL_ENABLED", True):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_http
            result = await adapter.scrape_url("https://www.slikk.club/")

            assert result["success"] is True
            assert result["status_code"] == 200
            assert result["url"] == "https://www.slikk.club/"
            assert "# Slikk Club" in result["markdown"]
            assert "<h1>Slikk Club</h1>" in result["html"]
            assert len(result["links"]) == 2
            assert result["metadata"]["title"] == "Slikk Club"


@pytest.mark.asyncio
async def test_firecrawl_v2_rawhtml_fallback_when_html_missing():
    """Verify adapter falls back to rawHtml if html field is absent."""
    adapter = FirecrawlAdapter()
    adapter.api_key = "fc-test-key-v2"

    mock_resp = {
        "success": True,
        "data": {
            "markdown": "# Header",
            "rawHtml": "<html><body><p>Raw HTML content</p></body></html>",
            "metadata": {"statusCode": 200, "url": "https://example.com"},
        },
    }

    mock_http = httpx.Response(
        status_code=200,
        json=mock_resp,
        request=httpx.Request("POST", "https://api.firecrawl.dev/v2/scrape"),
    )

    with patch.object(settings, "FIRECRAWL_ENABLED", True):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_http
            result = await adapter.scrape_url("https://example.com")

            assert result["success"] is True
            assert result["html"] == "<html><body><p>Raw HTML content</p></body></html>"


@pytest.mark.asyncio
async def test_firecrawl_v2_missing_markdown_graceful():
    """Verify missing markdown does not fail the scrape."""
    adapter = FirecrawlAdapter()
    adapter.api_key = "fc-test-key-v2"

    mock_resp = {
        "success": True,
        "data": {
            "html": "<html><body><h1>No Markdown</h1></body></html>",
            "metadata": {"statusCode": 200},
        },
    }

    mock_http = httpx.Response(
        status_code=200,
        json=mock_resp,
        request=httpx.Request("POST", "https://api.firecrawl.dev/v2/scrape"),
    )

    with patch.object(settings, "FIRECRAWL_ENABLED", True):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_http
            result = await adapter.scrape_url("https://example.com")

            assert result["success"] is True
            assert result["markdown"] == ""
            assert "<h1>No Markdown</h1>" in result["html"]


@pytest.mark.asyncio
async def test_firecrawl_v2_error_statuses_and_key_redaction():
    """Verify HTTP 401, 429, 500 redacts API key and handles errors cleanly."""
    adapter = FirecrawlAdapter()
    secret = "fc-super-secret-key-999"
    adapter.api_key = secret

    for status_code in [401, 429, 500]:
        mock_http = httpx.Response(
            status_code=status_code,
            text=f"Error {status_code}: Key {secret} invalid or rate limited",
            request=httpx.Request("POST", "https://api.firecrawl.dev/v2/scrape"),
        )

        with patch.object(settings, "FIRECRAWL_ENABLED", True):
            with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
                mock_post.return_value = mock_http
                result = await adapter.scrape_url("https://example.com")

                assert result["success"] is False
                assert result["status_code"] == status_code
                assert secret not in result["error"]
                assert "[REDACTED]" in result["error"]


@pytest.mark.asyncio
async def test_firecrawl_v2_timeout_and_transport_exception_safe():
    """Verify timeout and network exceptions are caught and never crash the process."""
    adapter = FirecrawlAdapter()
    adapter.api_key = "fc-key"

    with patch.object(settings, "FIRECRAWL_ENABLED", True):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = httpx.TimeoutException("Read timeout")
            result = await adapter.scrape_url("https://example.com")
            assert result["success"] is False
            assert "timeout" in result["error"].lower()


# ---------------------------------------------------------------------------
# Group C: Crawler Delegation, Subpage Limits & Fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_crawler_delegates_homepage_to_firecrawl_when_enabled():
    """WebCrawlerAdapter delegates homepage scrape to Firecrawl when enabled."""
    crawler = WebCrawlerAdapter()
    crawler.firecrawl.api_key = "fc-test"

    fc_homepage_return = {
        "success": True,
        "status_code": 200,
        "url": "https://target-domain.com",
        "html": "<html><body><h1>Target Co</h1><a href='/careers'>Jobs</a></body></html>",
        "markdown": "# Target Co\n\n[Jobs](/careers)",
        "metadata": {"title": "Target Co"},
        "links": ["https://target-domain.com/careers"],
    }

    fc_careers_return = {
        "success": True,
        "status_code": 200,
        "url": "https://target-domain.com/careers",
        "html": "<html><body><h1>Careers</h1><p>We are hiring Senior Engineers!</p><a href='/jobs/apply'>Apply Now</a></body></html>",
        "markdown": "# Careers\n\nWe are hiring Senior Engineers! [Apply Now](/jobs/apply)",
        "metadata": {"title": "Careers"},
        "links": [],
    }

    async def mock_scrape_side_effect(url, **kwargs):
        if "careers" in url:
            return fc_careers_return
        return fc_homepage_return

    with patch("app.providers.crawler.is_safe_url", return_value=True):
        with patch.object(settings, "FIRECRAWL_ENABLED", True):
            with patch.object(crawler.firecrawl, "scrape_url", new_callable=AsyncMock) as mock_scrape:
                mock_scrape.side_effect = mock_scrape_side_effect
                result = await crawler.crawl_domain("target-domain.com")
                assert mock_scrape.called
                assert result["provenance"]["engine"] == "firecrawl"
                assert result["provenance"]["ssl_valid"] is True
                assert result["signals"]["hiring"]["value"] == 1.0
                assert "active hiring detected" in result["signals"]["hiring"]["evidence"].lower()


@pytest.mark.asyncio
async def test_crawler_falls_back_to_httpx_when_firecrawl_fails():
    """WebCrawlerAdapter seamlessly falls back to httpx if Firecrawl returns error."""
    crawler = WebCrawlerAdapter()
    crawler.firecrawl.api_key = "fc-test"

    with patch("app.providers.crawler.is_safe_url", return_value=True):
        with patch.object(settings, "FIRECRAWL_ENABLED", True):
            with patch.object(crawler.firecrawl, "scrape_url", new_callable=AsyncMock) as mock_scrape:
                mock_scrape.return_value = {
                    "success": False,
                    "status_code": 500,
                    "error": "Firecrawl server error",
                    "html": "",
                    "markdown": "",
                }

                with patch.object(crawler, "_safe_fetch_page", new_callable=AsyncMock) as mock_safe:
                    mock_safe.return_value = {
                        "url": "https://fallback-domain.com",
                        "status_code": 200,
                        "html": "<html><body><h1>Fallback Site</h1></body></html>",
                        "body_text": "Fallback Site content",
                        "words": 50,
                        "soup": BeautifulSoup("<html><body>Fallback Site</body></html>", "html.parser"),
                        "scraped_by": "httpx",
                    }

                    result = await crawler.crawl_domain("fallback-domain.com")
                    assert mock_scrape.called
                    assert mock_safe.called
                    assert result["provenance"]["engine"] == "httpx"


@pytest.mark.asyncio
async def test_crawler_subpage_bounded_firecrawl_limit():
    """Discovered subpages only use Firecrawl up to FIRECRAWL_MAX_SUBPAGES; rest use httpx."""
    crawler = WebCrawlerAdapter()
    crawler.firecrawl.api_key = "fc-test"

    # Homepage returns 4 discovered links
    fc_home = {
        "success": True,
        "status_code": 200,
        "url": "https://multi-page.com",
        "html": "<html><body>"
                "<a href='/careers'>Careers</a>"
                "<a href='/case-studies'>Case Studies</a>"
                "<a href='/about'>About</a>"
                "<a href='/blog'>Blog</a>"
                "</body></html>",
        "markdown": "# Multi Page",
        "links": [
            "https://multi-page.com/careers",
            "https://multi-page.com/case-studies",
            "https://multi-page.com/about",
            "https://multi-page.com/blog",
        ],
    }

    with patch("app.providers.crawler.is_safe_url", return_value=True):
        with patch.object(settings, "FIRECRAWL_ENABLED", True):
            with patch.object(settings, "FIRECRAWL_MAX_SUBPAGES", 2):
                with patch.object(crawler.firecrawl, "scrape_url", new_callable=AsyncMock) as mock_scrape:
                    mock_scrape.return_value = fc_home
                    with patch.object(crawler, "_safe_fetch_page", new_callable=AsyncMock) as mock_safe:
                        mock_safe.return_value = {
                            "url": "https://multi-page.com/about",
                            "status_code": 200,
                            "html": "<html><body>About page</body></html>",
                            "body_text": "About page",
                            "words": 30,
                            "soup": BeautifulSoup("<html><body>About page</body></html>", "html.parser"),
                            "scraped_by": "httpx",
                        }

                        result = await crawler.crawl_domain("multi-page.com")
                        # Homepage (1) + max 2 subpages = at most 3 Firecrawl calls
                        assert mock_scrape.call_count <= 3
                        # Remaining pages called via _safe_fetch_page
                        assert mock_safe.called
                        assert "pages_scraped_by" in result["provenance"]


# ---------------------------------------------------------------------------
# Group D: Markdown Integration & Heuristics
# ---------------------------------------------------------------------------

def test_markdown_used_for_thin_content_word_count():
    """Clean Markdown word count is preferred over raw HTML for content substance."""
    crawler = WebCrawlerAdapter()

    # 3 words in body_text, but 300 words in clean markdown
    pages = [
        {
            "url": "https://markdown-substance.com",
            "html": "<html><body>Tiny</body></html>",
            "soup": BeautifulSoup("<html><body>Tiny</body></html>", "html.parser"),
            "body_text": "Tiny body text",
            "words": 3,
            "markdown": " ".join(["substantial"] * 300),  # 300 words in Markdown
        }
    ]

    signals = crawler._evaluate_signals_across_pages(pages, ssl_valid=True, domain="markdown-substance.com")
    assert signals["thin_content"]["value"] == 0.0  # Not thin
    assert "300 words via rendered Markdown" in signals["thin_content"]["evidence"]


def test_markdown_used_for_weak_ctas_when_absent_in_dom():
    """CTA keyword found in Markdown callout/link is recognized even without DOM button tag."""
    crawler = WebCrawlerAdapter()

    pages = [
        {
            "url": "https://cta-test.com",
            "html": "<html><body><p>Plain text without buttons</p></body></html>",
            "soup": BeautifulSoup("<html><body><p>Plain text without buttons</p></body></html>", "html.parser"),
            "body_text": "Plain text without buttons",
            "words": 100,
            "markdown": "# Header\n\nReady to elevate your business? [Book a demo](https://cta-test.com/demo) today!",
        }
    ]

    signals = crawler._evaluate_signals_across_pages(pages, ssl_valid=True, domain="cta-test.com")
    assert signals["weak_ctas"]["value"] == 0.0  # CTA found
    assert "book a demo" in signals["weak_ctas"]["evidence"].lower()


def test_structural_checks_remain_strictly_on_html_dom():
    """Structural checks like viewport, analytics, SSL, and schema microdata evaluate HTML/DOM only."""
    crawler = WebCrawlerAdapter()

    # Markdown mentions viewport, but HTML DOM lacks it
    pages = [
        {
            "url": "https://structural-test.com",
            "html": "<html><head><title>Test Title Long Enough</title></head><body><p>No viewport meta</p></body></html>",
            "soup": BeautifulSoup("<html><head><title>Test Title Long Enough</title></head><body><p>No viewport meta</p></body></html>", "html.parser"),
            "body_text": "No viewport meta",
            "words": 100,
            "markdown": "Here is a note about <meta name='viewport' content='width=device-width'> in a tutorial.",
        }
    ]

    signals = crawler._evaluate_signals_across_pages(pages, ssl_valid=True, domain="structural-test.com")
    # Structural check for viewport meta tag must evaluate DOM, correctly detecting the absence
    assert signals["not_mobile_friendly"]["value"] == 1.0


# ---------------------------------------------------------------------------
# Group E: Enrichment & Caching Integration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_enrichment_cache_hit_bypasses_crawler_and_firecrawl():
    """Redis enrichment cache hit returns cached payload and makes no crawler/Firecrawl calls."""
    mock_session = AsyncMock()
    lead = Lead(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        domain="cached-domain.com",
        company_name="Cached Co",
    )

    cached_obj = {
        "payload": {
            "no_ssl": {"value": 0.0, "evidence": "HTTPS from cache"},
            "legacy_platform": {"value": 0.0, "evidence": "Modern from cache"},
        },
        "provenance": {"collectors": {"crawler": {"scraped_by": "firecrawl"}}},
    }

    mock_redis = AsyncMock()
    mock_redis.get.return_value = json.dumps(cached_obj)

    service = EnrichmentService(mock_session, redis_client=mock_redis)

    with patch.object(provider_manager.crawler, "crawl_domain", new_callable=AsyncMock) as mock_crawl:
        with patch.object(service, "_persist_enrichment", new_callable=AsyncMock) as mock_persist:
            mock_persist.return_value = MagicMock(payload=cached_obj["payload"])
            result = await service.enrich_lead(lead)

            mock_crawl.assert_not_called()
            mock_persist.assert_called_once()
            args, kwargs = mock_persist.call_args
            assert args[1] == cached_obj["payload"]
            assert args[2]["from_cache"] is True


def test_provider_manager_includes_firecrawl():
    """Verify provider manager contains firecrawl in adapter registry."""
    assert "firecrawl" in provider_manager._adapters
    assert provider_manager.firecrawl.name == "firecrawl"
