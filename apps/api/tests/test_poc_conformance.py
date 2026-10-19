# ruff: noqa: F811, F401
"""Regression tests for conformance gaps against docs/poc.md found during the audit."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.test_business_workflows import (  # noqa: F401  (pytest fixtures)
    admin_engine,
    cleanup_pool_and_redis,
    setup_test_tenants,
)


def _auth(token: str, **extra: str) -> dict:
    return {"Authorization": f"Bearer {token}", **extra}


@pytest.mark.asyncio
async def test_operator_elevation_is_super_admin_only(setup_test_tenants):
    """poc 2.2: 'Super Admin toggles this per org' - an org admin must not elevate their own org."""
    tokens = setup_test_tenants["tokens"]
    org_a = str(setup_test_tenants["ids"]["org_a_id"])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        denied = await client.patch(
            f"/api/v1/admin/orgs/{org_a}/operator-access",
            json={"enabled": True},
            headers=_auth(tokens["org_a_admin"]),
        )
        assert denied.status_code == 403

        allowed = await client.patch(
            f"/api/v1/admin/orgs/{org_a}/operator-access",
            json={"enabled": True},
            headers=_auth(tokens["super_admin"]),
        )
        assert allowed.status_code == 200


@pytest.mark.asyncio
async def test_x_org_context_header_is_honoured_and_validated(setup_test_tenants):
    """poc 4.1: super_admin switches tenant with X-Org-Context; org users can never cross tenants."""
    tokens = setup_test_tenants["tokens"]
    org_b = str(setup_test_tenants["ids"]["org_b_id"])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        bad_format = await client.get(
            "/api/v1/leads", headers=_auth(tokens["super_admin"], **{"X-Org-Context": "not-a-uuid"})
        )
        assert bad_format.status_code == 400
        assert "X-Org-Context" in bad_format.json()["detail"]

        valid_switch = await client.get(
            "/api/v1/leads", headers=_auth(tokens["super_admin"], **{"X-Org-Context": org_b})
        )
        assert valid_switch.status_code == 200

        cross_tenant = await client.get(
            "/api/v1/leads", headers=_auth(tokens["org_a_admin"], **{"X-Org-Context": org_b})
        )
        assert cross_tenant.status_code == 403


@pytest.mark.asyncio
async def test_engine_params_persist_ideal_client_bonus(setup_test_tenants):
    """poc 9.2: ideal_client_bonus is a per-engine, versioned setting."""
    tokens = setup_test_tenants["tokens"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/engines", json={"name": "Bonus Engine"}, headers=_auth(tokens["org_a_admin"])
        )
        assert created.status_code == 201
        engine_id = created.json()["id"]
        assert created.json()["params"][0]["ideal_client_bonus"] == 0.0

        published = await client.post(
            f"/api/v1/engines/{engine_id}/params",
            json={"ideal_client_bonus": 15.0},
            headers=_auth(tokens["org_a_admin"]),
        )
        assert published.status_code == 200
        assert published.json()["ideal_client_bonus"] == 15.0
        assert published.json()["version"] == 2

        invalid = await client.post(
            f"/api/v1/engines/{engine_id}/params",
            json={"ideal_client_bonus": 500.0},
            headers=_auth(tokens["org_a_admin"]),
        )
        assert invalid.status_code == 422
