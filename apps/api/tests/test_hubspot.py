# ruff: noqa: F811, F401
"""HubSpot integration: free-plan adapter behavior and the approval/idempotency gates around it."""

import json
import uuid
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.constants import ApprovalStatus, DraftApprovalStatus, PipelineStatus
from app.db.session import tenant_session
from app.main import app
from app.models.contact import Contact
from app.models.draft import Draft
from app.models.lead import Lead
from app.providers.hubspot import HubSpotAdapter, HubSpotError, normalize_domain, record_url
from app.providers.manager import provider_manager
from tests.test_business_workflows import (
    admin_engine,
    cleanup_pool_and_redis,
    setup_test_tenants,
)


def _adapter() -> HubSpotAdapter:
    adapter = HubSpotAdapter()
    adapter.access_token = "pat-test-token"
    adapter.portal_id = "12345"
    adapter.enabled = True
    return adapter


def _resp(status: int, body: dict | None = None, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(status, json=body or {}, headers=headers, request=httpx.Request("GET", "https://api.hubapi.com/x"))


class FakeHubSpot:
    """Routes adapter requests by (method, path) and records every call."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[tuple[str, str, dict]] = []

    def __call__(self, method, url, **kwargs):
        path = url.replace("https://api.hubapi.com", "")
        self.calls.append((method, path, kwargs.get("json") or {}))
        handler = self.routes.get((method, path))
        if handler is None:
            raise AssertionError(f"Unexpected HubSpot call: {method} {path}")
        return handler(kwargs.get("json") or {}) if callable(handler) else handler


def test_normalize_domain_and_record_links():
    assert normalize_domain("https://WWW.Slikk.club/about?x=1") == "slikk.club"
    assert normalize_domain("example.com:8080") == "example.com"
    assert record_url("12345", "0-2", "99") == "https://app.hubspot.com/contacts/12345/record/0-2/99"
    assert record_url("", "0-2", "99") is None


def test_is_configured_requires_flag_and_token():
    adapter = _adapter()
    assert adapter.is_configured()
    adapter.enabled = False
    assert not adapter.is_configured()
    adapter.enabled, adapter.access_token = True, ""
    assert not adapter.is_configured()


@pytest.mark.asyncio
async def test_sync_creates_company_contact_association_and_escaped_note():
    adapter = _adapter()
    fake = FakeHubSpot(
        {
            ("POST", "/crm/v3/objects/companies/search"): _resp(200, {"results": []}),
            ("POST", "/crm/v3/objects/companies"): _resp(201, {"id": "C1"}),
            ("POST", "/crm/v3/objects/contacts/search"): _resp(200, {"results": []}),
            ("POST", "/crm/v3/objects/contacts"): _resp(201, {"id": "P1"}),
            ("PUT", "/crm/v4/objects/contacts/P1/associations/default/companies/C1"): _resp(200),
            ("POST", "/crm/v3/objects/notes"): _resp(201, {"id": "N1"}),
        }
    )
    with patch("httpx.AsyncClient.request", new=AsyncMock(side_effect=fake)):
        result = await adapter.sync_prospect(
            company_name="Slikk",
            domain="https://www.slikk.club/",
            contact_email="Prateek@Slikk.club",
            contact_first_name="Prateek",
            contact_last_name="Singh",
            contact_title="Founder",
            draft_subject="Speed <b>fix</b>",
            draft_body="Hi,\n<script>alert(1)</script>",
            company_city="Gurugram",
            company_country="India",
            company_employees=132,
            note_context=["LeadFlow score: 83.4/100 (qualified)"],
        )

    assert result["crm_company_id"] == "C1" and result["crm_contact_id"] == "P1" and result["crm_engagement_id"] == "N1"
    assert result["company_url"].endswith("/record/0-2/C1")

    created_company = next(c for c in fake.calls if c[:2] == ("POST", "/crm/v3/objects/companies"))[2]["properties"]
    assert created_company == {
        "name": "Slikk",
        "domain": "slikk.club",
        "city": "Gurugram",
        "country": "India",
        "numberofemployees": 132,
    }
    created_contact = next(c for c in fake.calls if c[:2] == ("POST", "/crm/v3/objects/contacts"))[2]["properties"]
    assert created_contact["email"] == "prateek@slikk.club"

    note = next(c for c in fake.calls if c[:2] == ("POST", "/crm/v3/objects/notes"))[2]
    body = note["properties"]["hs_note_body"]
    assert "<script>" not in body and "&lt;script&gt;" in body
    assert "Speed &lt;b&gt;fix&lt;/b&gt;" in body
    assert "LeadFlow score: 83.4/100 (qualified)" in body
    assert {a["types"][0]["associationTypeId"] for a in note["associations"]} == {190, 202}


@pytest.mark.asyncio
async def test_sync_never_overwrites_existing_crm_data():
    adapter = _adapter()
    patches: list[dict] = []
    fake = FakeHubSpot(
        {
            ("POST", "/crm/v3/objects/companies/search"): _resp(
                200, {"results": [{"id": "C9", "properties": {"name": "Slikk Pvt Ltd", "domain": "slikk.club", "city": ""}}]}
            ),
            ("PATCH", "/crm/v3/objects/companies/C9"): lambda body: patches.append(body) or _resp(200, {"id": "C9"}),
        }
    )
    with patch("httpx.AsyncClient.request", new=AsyncMock(side_effect=fake)):
        result = await adapter.sync_prospect(
            company_name="Slikk",
            domain="slikk.club",
            contact_email=None,
            contact_first_name=None,
            contact_last_name=None,
            contact_title=None,
            draft_subject=None,
            draft_body=None,
            company_city="Gurugram",
        )

    assert result["crm_company_id"] == "C9" and result["company_created"] is False
    # The existing name is kept; only the empty city is filled.
    assert patches == [{"properties": {"city": "Gurugram"}}]


@pytest.mark.asyncio
async def test_failed_create_is_not_reported_as_success():
    adapter = _adapter()
    fake = FakeHubSpot(
        {
            ("POST", "/crm/v3/objects/companies/search"): _resp(200, {"results": []}),
            ("POST", "/crm/v3/objects/companies"): _resp(403, {"message": "scope missing"}),
        }
    )
    with patch("httpx.AsyncClient.request", new=AsyncMock(side_effect=fake)):
        with pytest.raises(HubSpotError) as exc:
            await adapter.sync_prospect("Slikk", "slikk.club", None, None, None, None, None, None)
    assert exc.value.status_code == 403
    assert "missing a required scope" in str(exc.value)
    assert "pat-test-token" not in str(exc.value)


@pytest.mark.asyncio
async def test_rate_limit_is_retried_once_then_succeeds():
    adapter = _adapter()
    attempts = {"n": 0}

    def search(_body):
        attempts["n"] += 1
        return _resp(429, {"message": "slow down"}, {"Retry-After": "1"}) if attempts["n"] == 1 else _resp(200, {"results": []})

    fake = FakeHubSpot({("POST", "/crm/v3/objects/companies/search"): search})
    with patch("httpx.AsyncClient.request", new=AsyncMock(side_effect=fake)), patch("asyncio.sleep", new=AsyncMock()) as sleep:
        found = await adapter.find_existing_company_domains(["slikk.club"])

    assert found == set() and attempts["n"] == 2
    sleep.assert_awaited_once()


@pytest.mark.asyncio
async def test_existing_company_lookup_batches_100_domains_per_request():
    adapter = _adapter()
    seen_sizes: list[int] = []

    def search(body):
        values = body["filterGroups"][0]["filters"][0]["values"]
        seen_sizes.append(len(values))
        return _resp(200, {"results": [{"id": "1", "properties": {"domain": "www.d0.com"}}]})

    fake = FakeHubSpot({("POST", "/crm/v3/objects/companies/search"): search})
    with patch("httpx.AsyncClient.request", new=AsyncMock(side_effect=fake)):
        found = await adapter.find_existing_company_domains([f"d{i}.com" for i in range(230)])

    assert sorted(seen_sizes) == [30, 100, 100]
    assert found == {"d0.com"}


@pytest.mark.asyncio
async def test_health_check_reports_missing_scope():
    adapter = _adapter()
    fake = FakeHubSpot({("GET", "/crm/v3/objects/contacts"): _resp(403, {"message": "forbidden"})})
    with patch("httpx.AsyncClient.request", new=AsyncMock(side_effect=fake)):
        status = await adapter.check_health()
    assert status.is_configured and not status.is_healthy
    assert "scope" in status.status_message


# --------------------------------------------------------------------------- service gates


async def _make_lead(org_id: uuid.UUID, *, approved: bool = True, draft_status=DraftApprovalStatus.APPROVED, reveal: bool = True):
    async with tenant_session(org_id) as session:
        lead = Lead(
            org_id=org_id,
            domain=f"crm-{uuid.uuid4().hex[:6]}.example.com",
            company_name="CRM Test Co",
            city="Leeds",
            country="UK",
            pipeline_status=PipelineStatus.SCORED,
            approval_status=ApprovalStatus.APPROVED if approved else ApprovalStatus.PENDING,
        )
        session.add(lead)
        await session.flush()
        contact = Contact(
            org_id=org_id, lead_id=lead.id, first_name="Jane", last_name="Doe", title="CEO",
            email="jane@crm-test.example.com" if reveal else "j***@crm-test.example.com", is_revealed=reveal,
        )
        session.add(contact)
        await session.flush()
        draft = Draft(
            org_id=org_id, lead_id=lead.id, contact_id=contact.id, subject="Hello", body="Body text",
            model_used="test-model", audit_citations={}, approval_status=draft_status,
        )
        session.add(draft)
        await session.commit()
        return lead.id, draft.id


FAKE_RESULT = {
    "crm_company_id": "C1",
    "crm_contact_id": "P1",
    "crm_engagement_id": "N1",
}


@pytest.mark.asyncio
async def test_sync_endpoint_gates_idempotency_and_failure_persistence(setup_test_tenants):
    tokens, ids = setup_test_tenants["tokens"], setup_test_tenants["ids"]
    headers = {"Authorization": f"Bearer {tokens['org_a_admin']}"}
    hubspot = provider_manager.hubspot
    transport = ASGITransport(app=app)

    lead_id, draft_id = await _make_lead(ids["org_a_id"])

    with patch.object(hubspot, "is_configured", return_value=True), patch.object(
        hubspot, "sync_prospect", new=AsyncMock(return_value=FAKE_RESULT)
    ) as sync:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # A draft is required
            missing = await client.post(f"/api/v1/leads/{lead_id}/sync-crm", json={}, headers=headers)
            assert missing.status_code == 400

            first = await client.post(f"/api/v1/leads/{lead_id}/sync-crm", json={"draft_id": str(draft_id)}, headers=headers)
            assert first.status_code == 200, first.text
            assert first.json()["sync_status"] == "success"
            assert first.json()["crm_engagement_id"] == "N1"
            assert first.json()["already_synced"] is False

            # The same lead and draft never creates a second note
            again = await client.post(f"/api/v1/leads/{lead_id}/sync-crm", json={"draft_id": str(draft_id)}, headers=headers)
            assert again.status_code == 200
            assert again.json()["already_synced"] is True
            assert again.json()["id"] == first.json()["id"]

        assert sync.await_count == 1
        kwargs = sync.await_args.kwargs
        assert kwargs["contact_email"] == "jane@crm-test.example.com"
        assert kwargs["company_city"] == "Leeds"

    # An unapproved draft is rejected before HubSpot is touched
    lead2, draft2 = await _make_lead(ids["org_a_id"], draft_status=DraftApprovalStatus.PENDING)
    with patch.object(hubspot, "is_configured", return_value=True), patch.object(
        hubspot, "sync_prospect", new=AsyncMock(return_value=FAKE_RESULT)
    ) as sync2:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post(f"/api/v1/leads/{lead2}/sync-crm", json={"draft_id": str(draft2)}, headers=headers)
        assert res.status_code == 400 and "Draft must be approved" in res.json()["detail"]
        sync2.assert_not_awaited()

    # An unrevealed contact's masked email is never sent
    lead3, draft3 = await _make_lead(ids["org_a_id"], reveal=False)
    with patch.object(hubspot, "is_configured", return_value=True), patch.object(
        hubspot, "sync_prospect", new=AsyncMock(return_value={**FAKE_RESULT, "crm_contact_id": None})
    ) as sync3:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post(f"/api/v1/leads/{lead3}/sync-crm", json={"draft_id": str(draft3)}, headers=headers)
        assert res.status_code == 200
        assert sync3.await_args.kwargs["contact_email"] is None

    # A HubSpot failure answers 502 and the failed attempt is still recorded
    lead4, draft4 = await _make_lead(ids["org_a_id"])
    with patch.object(hubspot, "is_configured", return_value=True), patch.object(
        hubspot, "sync_prospect", new=AsyncMock(side_effect=HubSpotError("HubSpot HTTP 401 (the access token is invalid or expired)", 401))
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post(f"/api/v1/leads/{lead4}/sync-crm", json={"draft_id": str(draft4)}, headers=headers)
            assert res.status_code == 502
            status_res = await client.get(f"/api/v1/leads/{lead4}/sync-status", headers=headers)
    assert status_res.status_code == 200
    assert status_res.json()["sync_status"] == "failed"
    assert status_res.json()["retry_count"] == 1
    assert "access token" in status_res.json()["error_message"]


@pytest.mark.asyncio
async def test_sync_reports_clear_error_when_hubspot_is_not_connected(setup_test_tenants):
    tokens, ids = setup_test_tenants["tokens"], setup_test_tenants["ids"]
    headers = {"Authorization": f"Bearer {tokens['org_a_admin']}"}
    lead_id, draft_id = await _make_lead(ids["org_a_id"])

    transport = ASGITransport(app=app)
    with patch.object(provider_manager.hubspot, "is_configured", return_value=False):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post(f"/api/v1/leads/{lead_id}/sync-crm", json={"draft_id": str(draft_id)}, headers=headers)
    assert res.status_code == 503
    assert "HUBSPOT_ACCESS_TOKEN" in res.json()["detail"]
