# ruff: noqa: F811, F401
"""Smoke test: every read route and the main create routes must answer without a server error."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.test_business_workflows import (  # noqa: F401  (pytest fixtures)
    admin_engine,
    cleanup_pool_and_redis,
    setup_test_tenants,
)

ORG_ADMIN_GET_ROUTES = [
    "/api/v1/auth/me",
    "/api/v1/audiences",
    "/api/v1/engines",
    "/api/v1/leads",
    "/api/v1/leads/export?format=csv",
    "/api/v1/leads/export?format=json",
    "/api/v1/drafts",
    "/api/v1/runs",
    "/api/v1/searches",
    "/api/v1/users",
    "/api/v1/admin/usage",
    "/api/v1/admin/audit-logs",
    "/api/v1/access-requests",
]

SUPER_ADMIN_GET_ROUTES = [
    "/api/v1/admin/orgs",
    "/api/v1/admin/usage",
    "/api/v1/admin/audit-logs",
    "/api/v1/users",
    "/api/v1/access-requests",
]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_org_admin_read_routes_do_not_error(setup_test_tenants):
    tokens = setup_test_tenants["tokens"]
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    failures = []
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for path in ORG_ADMIN_GET_ROUTES:
            res = await client.get(path, headers=_auth(tokens["org_a_admin"]))
            if res.status_code >= 500:
                failures.append((path, res.status_code, res.text[:200]))
    assert not failures, failures


@pytest.mark.asyncio
async def test_super_admin_read_routes_do_not_error(setup_test_tenants):
    tokens = setup_test_tenants["tokens"]
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    failures = []
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for path in SUPER_ADMIN_GET_ROUTES:
            res = await client.get(path, headers=_auth(tokens["super_admin"]))
            if res.status_code >= 500:
                failures.append((path, res.status_code, res.text[:200]))
    assert not failures, failures


@pytest.mark.asyncio
async def test_create_flows_round_trip(setup_test_tenants):
    """Create an audience and an engine, then read each back through the list endpoints."""
    tokens = setup_test_tenants["tokens"]
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = _auth(tokens["org_a_admin"])

        audience = await client.post(
            "/api/v1/audiences",
            json={"name": "Smoke Audience", "filters": {"locations": ["Ahmedabad"], "location_match": "or"}},
            headers=headers,
        )
        assert audience.status_code == 201, audience.text

        engine_res = await client.post("/api/v1/engines", json={"name": "Smoke Engine"}, headers=headers)
        assert engine_res.status_code == 201, engine_res.text

        audiences = (await client.get("/api/v1/audiences", headers=headers)).json()
        engines = (await client.get("/api/v1/engines", headers=headers)).json()
        assert any(a["name"] == "Smoke Audience" for a in audiences)
        assert any(e["name"] == "Smoke Engine" for e in engines)
