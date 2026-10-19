from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.providers.manager import provider_manager
from app.providers.serpapi import SerpApiAdapter


@pytest.mark.asyncio
async def test_serpapi_unconfigured_behavior():
    """Verify adapter gracefully marks unconfigured and returns unavailable signal without error."""
    adapter = SerpApiAdapter()
    adapter.api_key = ""

    assert not adapter.is_configured()
    status = await adapter.check_health()
    assert not status.is_configured
    assert not status.is_healthy
    assert "not configured" in status.status_message.lower()

    res = await adapter.fetch_review_signals("Acme Corp", "acme.com")
    assert res["signals"]["low_review_rating"]["value"] is None
    assert "unconfigured" in res["signals"]["low_review_rating"]["evidence"].lower()


@pytest.mark.asyncio
async def test_serpapi_health_check_success():
    """Verify health check parses free /account.json endpoint cleanly."""
    adapter = SerpApiAdapter()
    adapter.api_key = "serp_test_secret_123"
    adapter.enabled = True

    mock_resp = {
        "account_id": "test_acc_1",
        "plan_name": "Developer Plan",
        "total_searches_left": 4500,
    }

    mock_http_response = httpx.Response(
        status_code=200,
        json=mock_resp,
        request=httpx.Request("GET", "https://serpapi.com/account.json"),
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_http_response
        status = await adapter.check_health()

        assert status.is_configured
        assert status.is_healthy
        assert "Developer Plan" in status.status_message
        assert "4500 searches left" in status.status_message


@pytest.mark.asyncio
async def test_serpapi_evaluates_high_rating_as_healthy():
    """Verify Google rating >= 3.8 yields signal value 0.0 (good reputation)."""
    adapter = SerpApiAdapter()
    adapter.api_key = "serp_test_secret_123"
    adapter.enabled = True

    mock_resp = {
        "place_results": {
            "title": "Acme Software",
            "rating": 4.6,
            "reviews": 120,
            "address": "123 Tech Way, San Francisco, CA",
            "phone": "+14155551234",
            "website": "https://acme.com",
            "place_id": "ChIJN1t_tDeuEmsRUsoyG83frY4",
        }
    }

    mock_http_response = httpx.Response(
        status_code=200,
        json=mock_resp,
        request=httpx.Request("GET", "https://serpapi.com/search.json"),
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_http_response
        result = await adapter.fetch_review_signals("Acme Software", "acme.com", location="San Francisco")

        sig = result["signals"]["low_review_rating"]
        assert sig["value"] == 0.0
        assert "4.6★" in sig["evidence"]
        assert "120 reviews" in sig["evidence"]
        assert result["provenance"]["place_id"] == "ChIJN1t_tDeuEmsRUsoyG83frY4"


@pytest.mark.asyncio
async def test_serpapi_evaluates_low_rating_as_reputation_pain():
    """Verify Google rating < 3.8 yields signal value 1.0 (pain flag raised for outreach)."""
    adapter = SerpApiAdapter()
    adapter.api_key = "serp_test_secret_123"
    adapter.enabled = True

    mock_resp = {
        "local_results": [
            {
                "title": "Subpar Services",
                "rating": 2.9,
                "reviews": 38,
                "address": "456 Market St, Austin, TX",
            }
        ]
    }

    mock_http_response = httpx.Response(
        status_code=200,
        json=mock_resp,
        request=httpx.Request("GET", "https://serpapi.com/search.json"),
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_http_response
        result = await adapter.fetch_review_signals("Subpar Services", "subpar.com", location="Austin")

        sig = result["signals"]["low_review_rating"]
        assert sig["value"] == 1.0
        assert "2.9★" in sig["evidence"]
        assert "pain points" in sig["evidence"].lower()


@pytest.mark.asyncio
async def test_serpapi_error_redacts_api_key():
    """Verify adapter redacts API key from error outputs on failure."""
    adapter = SerpApiAdapter()
    secret = "serp_super_secret_999"
    adapter.api_key = secret
    adapter.enabled = True

    mock_http_response = httpx.Response(
        status_code=401,
        text=f"Unauthorized: Key {secret} is invalid",
        request=httpx.Request("GET", "https://serpapi.com/search.json"),
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_http_response
        result = await adapter.fetch_review_signals("Acme Corp", "acme.com")

        assert secret not in result["signals"]["low_review_rating"]["evidence"]
        assert secret not in str(result["provenance"])


def test_provider_manager_includes_serpapi():
    """Verify provider manager contains serpapi in adapter registry."""
    assert "serpapi" in provider_manager._adapters
    assert provider_manager.serpapi.name == "serpapi"
