import json
import uuid
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient, Response

from app.core.filter_catalog import FilterValidationError, validate_and_normalize_filters
from app.main import app
from app.providers.manager import provider_manager
from app.providers.openrouter import (
    OpenRouterAdapter,
    OpenRouterAuthenticationError,
    OpenRouterConfigurationError,
    OpenRouterParsingError,
    OpenRouterRateLimitError,
    OpenRouterTimeoutError,
    OpenRouterValidationError,
)
from tests.test_business_workflows import admin_engine, cleanup_pool_and_redis, setup_test_tenants


# ==============================================================================
# 1. Filter Catalog Validation Unit Tests
# ==============================================================================

def test_filter_catalog_validation_valid():
    raw = {
        "verticals": ["Website Development", "Digital Marketing"],
        "locations": ["Ahmedabad", "Surat"],
        "vertical_match": "or",
        "location_match": "or",
        "exclude_locations": ["Mumbai"],
        "exclude_verticals": ["Government"],
        "exclude_domains": ["competitor.com"],
        "exclude_existing_crm": True,
        "employee_ranges": ["11-50", "51-200"],
    }
    normalized = validate_and_normalize_filters(raw)
    assert normalized["verticals"] == ["Website Development", "Digital Marketing"]
    assert normalized["locations"] == ["Ahmedabad", "Surat"]
    assert normalized["vertical_match"] == "or"
    assert normalized["location_match"] == "or"
    assert normalized["exclude_locations"] == ["Mumbai"]
    assert normalized["exclude_existing_crm"] is True
    assert normalized["employee_ranges"] == ["11-50", "51-200"]


def test_filter_catalog_validation_defaults_applied():
    raw = {
        "verticals": ["SaaS"],
        "locations": ["Ahmedabad"],
    }
    normalized = validate_and_normalize_filters(raw)
    assert normalized["vertical_match"] == "or"
    assert normalized["location_match"] == "or"
    assert normalized["exclude_existing_crm"] is False
    assert normalized["exclude_locations"] == []
    assert normalized["exclude_verticals"] == []
    assert normalized["exclude_domains"] == []


def test_filter_catalog_unsupported_keys_rejected():
    raw = {
        "verticals": ["Fintech"],
        "invalid_custom_key": "some_value",
    }
    with pytest.raises(FilterValidationError) as exc:
        validate_and_normalize_filters(raw)
    assert "Unsupported filter key(s): invalid_custom_key" in str(exc.value)


def test_filter_catalog_invalid_match_modes_rejected():
    with pytest.raises(FilterValidationError) as exc1:
        validate_and_normalize_filters({"vertical_match": "xor"})
    assert "Invalid vertical_match" in str(exc1.value)

    with pytest.raises(FilterValidationError) as exc2:
        validate_and_normalize_filters({"location_match": "not"})
    assert "Invalid location_match" in str(exc2.value)


def test_filter_catalog_invalid_types_rejected():
    with pytest.raises(FilterValidationError) as exc1:
        validate_and_normalize_filters({"locations": "NotAList"})
    assert "must be a list of strings" in str(exc1.value)

    with pytest.raises(FilterValidationError) as exc2:
        validate_and_normalize_filters({"exclude_existing_crm": "yes"})
    assert "Must be a boolean" in str(exc2.value)


# ==============================================================================
# 2. OpenRouter Provider Truthful Error & Validation Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_openrouter_unconfigured_raises_truthful_error():
    adapter = OpenRouterAdapter()
    adapter.api_key = ""  # Force unconfigured
    with pytest.raises(OpenRouterConfigurationError) as exc:
        await adapter.generate_icp_criteria("Find agencies in Ahmedabad", allow_offline_heuristic=False)
    assert "OpenRouter API key is not configured" in str(exc.value)


@pytest.mark.asyncio
async def test_openrouter_401_authentication_error():
    adapter = OpenRouterAdapter()
    adapter.api_key = "test-fake-key"
    mock_resp = Response(401, json={"error": {"message": "Invalid API key"}})

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
        with pytest.raises(OpenRouterAuthenticationError) as exc:
            await adapter.generate_icp_criteria("Web agencies in Ahmedabad")
        assert "authentication failed (HTTP 401)" in str(exc.value)
        assert "test-fake-key" not in str(exc.value)


@pytest.mark.asyncio
async def test_openrouter_429_rate_limit_error():
    adapter = OpenRouterAdapter()
    adapter.api_key = "test-fake-key"
    mock_resp = Response(429, json={"error": {"message": "Rate limit exceeded"}})

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
        with pytest.raises(OpenRouterRateLimitError):
            await adapter.generate_icp_criteria("Web agencies in Ahmedabad")


@pytest.mark.asyncio
async def test_openrouter_timeout_error():
    adapter = OpenRouterAdapter()
    adapter.api_key = "test-fake-key"

    with patch("httpx.AsyncClient.post", side_effect=httpx.TimeoutException("Read timeout")):
        with pytest.raises(OpenRouterTimeoutError) as exc:
            await adapter.generate_icp_criteria("Web agencies in Ahmedabad")
        assert "timed out after 20 seconds" in str(exc.value)


@pytest.mark.asyncio
async def test_openrouter_malformed_json_not_swallowed():
    adapter = OpenRouterAdapter()
    adapter.api_key = "test-fake-key"
    mock_resp = Response(
        200,
        json={"choices": [{"message": {"content": "I could not generate JSON, here is text instead."}}]},
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
        with pytest.raises(OpenRouterParsingError) as exc:
            await adapter.generate_icp_criteria("Web agencies in Ahmedabad")
        assert "did not contain a valid JSON object" in str(exc.value)


@pytest.mark.asyncio
async def test_openrouter_preserves_ahmedabad_and_surat():
    adapter = OpenRouterAdapter()
    adapter.api_key = "test-fake-key"
    mock_ai_content = json.dumps({
        "name": "Gujarat SME Web Growth",
        "description": "Small and medium businesses in Ahmedabad and Surat needing website development.",
        "ai_rationale": "Selected businesses in Ahmedabad and Surat seeking digital transformation.",
        "filters": {
            "verticals": ["Website Development", "Digital Marketing"],
            "vertical_match": "or",
            "locations": ["Ahmedabad", "Surat"],
            "location_match": "or",
            "employee_ranges": ["11-50", "51-200"],
            "exclude_existing_crm": False,
        },
    })
    mock_resp = Response(200, json={"choices": [{"message": {"content": mock_ai_content}}]})

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
        res = await adapter.generate_icp_criteria(
            "Find small and medium businesses in Ahmedabad and Surat that could benefit from a better website"
        )
        assert res["name"] == "Gujarat SME Web Growth"
        assert res["ai_rationale"] == "Selected businesses in Ahmedabad and Surat seeking digital transformation."
        assert res["filters"]["locations"] == ["Ahmedabad", "Surat"]
        assert res["filters"]["vertical_match"] == "or"
        assert res["filters"]["location_match"] == "or"


# ==============================================================================
# 3. API Integration Endpoint Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_ai_propose_endpoint_alias_and_persistence(setup_test_tenants):
    tokens = setup_test_tenants["tokens"]
    transport = ASGITransport(app=app)

    fake_proposed = {
        "name": "Gujarat Digital Agency ICP",
        "description": "Targeting SMBs in Ahmedabad & Surat",
        "ai_rationale": "High-density commercial hubs in Gujarat with strong digital agency demand.",
        "filters": {
            "verticals": ["Website Development", "Digital Marketing"],
            "vertical_match": "or",
            "locations": ["Ahmedabad", "Surat"],
            "location_match": "or",
            "exclude_locations": ["Mumbai"],
            "exclude_existing_crm": False,
            "employee_ranges": ["11-50", "51-200"],
        },
        "model_used": "openai/gpt-4o-mini",
        "generated_at": "2026-10-15T12:00:00Z",
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Test /api/v1/audiences/ai-propose route alias
        with patch.object(
            provider_manager.openrouter,
            "generate_icp_criteria",
            new_callable=AsyncMock,
            return_value=fake_proposed,
        ):
            res_alias = await client.post(
                "/api/v1/audiences/ai-propose",
                headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
                json={"prompt": "SMBs in Ahmedabad and Surat needing website services"},
            )
            assert res_alias.status_code == 200
            data = res_alias.json()
            assert data["name"] == "Gujarat Digital Agency ICP"
            assert "ai_rationale" in data
            assert data["ai_rationale"] == "High-density commercial hubs in Gujarat with strong digital agency demand."
            assert data["filters"]["locations"] == ["Ahmedabad", "Surat"]

        # 2. Test original route /api/v1/audiences/generate-ai-criteria works identically
        with patch.object(
            provider_manager.openrouter,
            "generate_icp_criteria",
            new_callable=AsyncMock,
            return_value=fake_proposed,
        ):
            res_gen = await client.post(
                "/api/v1/audiences/generate-ai-criteria",
                headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
                json={"prompt": "SMBs in Ahmedabad and Surat needing website services"},
            )
            assert res_gen.status_code == 200
            assert res_gen.json()["name"] == "Gujarat Digital Agency ICP"

        # 3. Persist audience with ai_rationale
        res_create = await client.post(
            "/api/v1/audiences",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
            json={
                "name": data["name"],
                "description": data["description"],
                "ai_rationale": data["ai_rationale"],
                "filters": data["filters"],
            },
        )
        assert res_create.status_code == 201
        created = res_create.json()
        assert created["ai_rationale"] == data["ai_rationale"]
        assert created["filters"]["vertical_match"] == "or"

        # 4. Fetch created audience and verify persistence of rationale & filters
        res_get = await client.post(
            "/api/v1/audiences",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
            json={
                "name": "Edited Audience",
                "description": "User edited description",
                "ai_rationale": "User reviewed rationale",
                "filters": {
                    "verticals": ["Website Development"],
                    "locations": ["Ahmedabad"],
                    "vertical_match": "and",
                },
            },
        )
        assert res_get.status_code == 201
        aud_id = res_get.json()["id"]

        res_fetch = await client.get(
            f"/api/v1/audiences/{aud_id}",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
        )
        assert res_fetch.status_code == 200
        fetched = res_fetch.json()
        assert fetched["ai_rationale"] == "User reviewed rationale"
        assert fetched["filters"]["vertical_match"] == "and"
        assert fetched["filters"]["location_match"] == "or"


@pytest.mark.asyncio
async def test_client_viewer_rejected_from_generating_and_saving(setup_test_tenants):
    tokens = setup_test_tenants["tokens"]
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Viewer rejected on /ai-propose
        res1 = await client.post(
            "/api/v1/audiences/ai-propose",
            headers={"Authorization": f"Bearer {tokens['org_a_viewer']}"},
            json={"prompt": "Test prompt"},
        )
        assert res1.status_code == 403

        # Viewer rejected on /audiences create
        res2 = await client.post(
            "/api/v1/audiences",
            headers={"Authorization": f"Bearer {tokens['org_a_viewer']}"},
            json={
                "name": "Unauthorized Audience",
                "filters": {"locations": ["Ahmedabad"]},
            },
        )
        assert res2.status_code == 403
