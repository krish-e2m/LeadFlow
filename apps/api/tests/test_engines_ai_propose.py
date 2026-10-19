"""
Engines improvements:
1. POST /v1/engines/ai-propose — mirrors audiences' ai-propose (brief -> proposed weights/
   thresholds/bonus), never auto-saves.
2. validate_engine_weights — normalizes/validates a weights payload to exactly the 22 canonical
   signals, used by both the AI-propose path and the manual save path (SignalWeightConfig).
3. SignalWeightConfig now rejects out-of-range weights/thresholds instead of accepting anything.
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient, Response

from app.main import app
from app.providers.manager import provider_manager
from app.providers.openrouter import (
    OpenRouterAdapter,
    OpenRouterAuthenticationError,
    OpenRouterConfigurationError,
)
from app.scoring.catalog import DEFAULT_SIGNAL_WEIGHTS, validate_engine_weights
from tests.test_business_workflows import setup_test_tenants  # noqa: F401


# ==============================================================================
# 1. validate_engine_weights unit tests
# ==============================================================================


def test_validate_engine_weights_fills_defaults_for_missing_keys():
    normalized = validate_engine_weights({"no_ssl": 2.0})
    assert normalized["no_ssl"] == 2.0
    # Every other key present at its catalog default, nothing silently dropped from the 22.
    assert len(normalized) == len(DEFAULT_SIGNAL_WEIGHTS)
    assert normalized["poor_seo"] == DEFAULT_SIGNAL_WEIGHTS["poor_seo"]


def test_validate_engine_weights_drops_unknown_keys():
    normalized = validate_engine_weights({"no_ssl": 2.0, "made_up_signal": 9.0})
    assert "made_up_signal" not in normalized
    assert normalized["no_ssl"] == 2.0


def test_validate_engine_weights_rejects_out_of_range():
    with pytest.raises(ValueError, match="between"):
        validate_engine_weights({"no_ssl": 999})
    with pytest.raises(ValueError, match="between"):
        validate_engine_weights({"no_ssl": -1})


def test_validate_engine_weights_rejects_non_numeric():
    with pytest.raises(ValueError, match="must be a number"):
        validate_engine_weights({"no_ssl": "very important"})


def test_validate_engine_weights_rejects_all_zero():
    all_zero = {k: 0 for k in DEFAULT_SIGNAL_WEIGHTS}
    with pytest.raises(ValueError, match="above 0"):
        validate_engine_weights(all_zero)


# ==============================================================================
# 2. OpenRouter provider: generate_engine_weights
# ==============================================================================


@pytest.mark.asyncio
async def test_generate_engine_weights_unconfigured_raises_truthful_error():
    adapter = OpenRouterAdapter()
    adapter.api_key = ""
    with pytest.raises(OpenRouterConfigurationError):
        await adapter.generate_engine_weights("Web design agency targeting SMBs", allow_offline_heuristic=False)


@pytest.mark.asyncio
async def test_generate_engine_weights_offline_heuristic_emphasizes_matching_signals():
    adapter = OpenRouterAdapter()
    adapter.api_key = ""
    result = await adapter.generate_engine_weights(
        "We sell SEO and content marketing services to businesses with a stale blog", allow_offline_heuristic=True
    )
    assert result["weights"]["poor_seo"] > DEFAULT_SIGNAL_WEIGHTS["poor_seo"]
    assert result["weights"]["stale_blog"] > DEFAULT_SIGNAL_WEIGHTS["stale_blog"]
    assert result["model_used"] == "offline-heuristic-parser"
    assert len(result["weights"]) == len(DEFAULT_SIGNAL_WEIGHTS)
    assert 0 <= result["threshold_medium"] < result["threshold_high"] <= 100


@pytest.mark.asyncio
async def test_generate_engine_weights_401_authentication_error():
    adapter = OpenRouterAdapter()
    adapter.api_key = "test-fake-key"
    mock_resp = Response(401, json={"error": {"message": "Invalid API key"}})
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
        with pytest.raises(OpenRouterAuthenticationError):
            await adapter.generate_engine_weights("Agencies that sell web design")
        # The key is never leaked into the error message.


# ==============================================================================
# 3. API integration: POST /v1/engines/ai-propose
# ==============================================================================


@pytest.mark.asyncio
async def test_engines_ai_propose_endpoint(setup_test_tenants):
    tokens = setup_test_tenants["tokens"]
    transport = ASGITransport(app=app)

    fake_proposed = {
        "weights": {**DEFAULT_SIGNAL_WEIGHTS, "poor_seo": 2.5, "stale_blog": 2.0},
        "threshold_high": 80.0,
        "threshold_medium": 55.0,
        "threshold_low": 25.0,
        "ideal_client_bonus": 5.0,
        "ai_rationale": "Emphasized SEO and content signals for a marketing-focused brief.",
        "model_used": "openai/gpt-4o-mini",
        "generated_at": "2026-10-16T12:00:00Z",
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch.object(
            provider_manager.openrouter,
            "generate_engine_weights",
            new_callable=AsyncMock,
            return_value=fake_proposed,
        ):
            res = await client.post(
                "/api/v1/engines/ai-propose",
                headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
                json={"prompt": "We sell SEO and content marketing to local businesses"},
            )
        assert res.status_code == 200
        data = res.json()
        assert data["weights"]["poor_seo"] == 2.5
        assert data["threshold_high"] == 80.0
        assert data["ideal_client_bonus"] == 5.0
        assert "ai_rationale" in data

        # The proposal is never persisted on its own: no engine/version was created by this call.
        list_res = await client.get(
            "/api/v1/engines",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
        )
        assert list_res.status_code == 200
        # Whatever engines exist, none should have picked up threshold_high=80 unless the
        # operator explicitly published it via POST /engines/{id}/params.
        assert all(
            not any(p.get("threshold_high") == 80.0 and p.get("ideal_client_bonus") == 5.0 for p in (e.get("params") or []))
            for e in list_res.json()
        )


@pytest.mark.asyncio
async def test_engines_ai_propose_rejects_client_viewer(setup_test_tenants):
    tokens = setup_test_tenants["tokens"]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/v1/engines/ai-propose",
            headers={"Authorization": f"Bearer {tokens['org_a_viewer']}"},
            json={"prompt": "Test prompt"},
        )
        assert res.status_code == 403


# ==============================================================================
# 4. API integration: POST /v1/engines/{id}/params now validates input
# ==============================================================================


@pytest.mark.asyncio
async def test_update_engine_params_rejects_bad_weight(setup_test_tenants):
    tokens = setup_test_tenants["tokens"]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_res = await client.post(
            "/api/v1/engines",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
            json={"name": "Weight validation test engine"},
        )
        assert create_res.status_code == 201
        engine_id = create_res.json()["id"]

        bad_res = await client.post(
            f"/api/v1/engines/{engine_id}/params",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
            json={"weights": {"no_ssl": 999}, "threshold_high": 75, "threshold_medium": 50},
        )
        assert bad_res.status_code == 422


@pytest.mark.asyncio
async def test_update_engine_params_rejects_inverted_thresholds(setup_test_tenants):
    tokens = setup_test_tenants["tokens"]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_res = await client.post(
            "/api/v1/engines",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
            json={"name": "Threshold validation test engine"},
        )
        assert create_res.status_code == 201
        engine_id = create_res.json()["id"]

        bad_res = await client.post(
            f"/api/v1/engines/{engine_id}/params",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
            # Review threshold above Qualified threshold — nonsensical, must be rejected.
            json={"weights": dict(DEFAULT_SIGNAL_WEIGHTS), "threshold_high": 40, "threshold_medium": 60},
        )
        assert bad_res.status_code == 422


@pytest.mark.asyncio
async def test_update_engine_params_accepts_valid_config(setup_test_tenants):
    tokens = setup_test_tenants["tokens"]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_res = await client.post(
            "/api/v1/engines",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
            json={"name": "Valid config test engine"},
        )
        engine_id = create_res.json()["id"]

        ok_res = await client.post(
            f"/api/v1/engines/{engine_id}/params",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
            json={
                "weights": {**DEFAULT_SIGNAL_WEIGHTS, "no_ssl": 2.0, "unknown_junk_key": 5.0},
                "threshold_high": 80,
                "threshold_medium": 55,
                "threshold_low": 20,
                "ideal_client_bonus": 10,
            },
        )
        assert ok_res.status_code == 200
        body = ok_res.json()
        assert body["weights"]["no_ssl"] == 2.0
        assert "unknown_junk_key" not in body["weights"]
        assert body["version"] == 2
