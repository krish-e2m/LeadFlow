# ruff: noqa: F811, F401
"""Company contact reveal, contact discovery and the automatic email draft queued on approval."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.constants import ApprovalStatus, DraftApprovalStatus, PipelineStatus, ScoreBand
from app.db.session import tenant_session
from app.jobs.draft_tasks import generate_lead_draft
from app.main import app
from app.models.contact import Contact
from app.models.draft import Draft
from app.models.lead import Lead
from app.providers.manager import provider_manager
from app.services import auto_draft
from tests.test_business_workflows import (
    admin_engine,
    cleanup_pool_and_redis,
    setup_test_tenants,
)

HUNTER = provider_manager.hunter
OPENROUTER = provider_manager.openrouter

FAKE_DRAFT = {
    "subject": "A quick idea for your site",
    "body": "Hi Jane,\n\nYour mobile page is slow.",
    "citations_used": [],
    "model_used": "test-model",
}


async def _lead(org_id, *, approved=True, contacts=(), band=ScoreBand.QUALIFIED):
    async with tenant_session(org_id) as session:
        lead = Lead(
            org_id=org_id,
            domain=f"rev-{uuid.uuid4().hex[:6]}.example.com",
            company_name="Reveal Test Co",
            pipeline_status=PipelineStatus.APPROVED if approved else PipelineStatus.SCORED,
            score_band=band,
            approval_status=ApprovalStatus.APPROVED if approved else ApprovalStatus.PENDING,
        )
        session.add(lead)
        await session.flush()
        ids = []
        for first, last in contacts:
            c = Contact(
                org_id=org_id, lead_id=lead.id, first_name=first, last_name=last, title="CEO",
                email=f"{first[0].lower()}***@{lead.domain}", is_revealed=False,
            )
            session.add(c)
            await session.flush()
            ids.append(c.id)
        await session.commit()
        return lead.id, ids


def _auth(tokens):
    return {"Authorization": f"Bearer {tokens['org_a_admin']}"}


@pytest.mark.asyncio
async def test_failed_hunter_lookup_does_not_reveal_or_spend(setup_test_tenants):
    tokens, ids = setup_test_tenants["tokens"], setup_test_tenants["ids"]
    lead_id, (contact_id,) = await _lead(ids["org_a_id"], contacts=[("Jane", "Doe")])

    transport = ASGITransport(app=app)
    with patch.object(HUNTER, "is_configured", return_value=True), patch.object(
        HUNTER, "reveal_contact_details", new=AsyncMock(return_value={"email": None})
    ), patch("app.services.contact_service.QuotaService.release_contact_reveal", new=AsyncMock()) as release:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post(f"/api/v1/contacts/{contact_id}/reveal", json={}, headers=_auth(tokens))

    assert res.status_code == 404
    assert "Nothing was revealed" in res.json()["detail"]
    release.assert_awaited_once()

    async with tenant_session(ids["org_a_id"]) as session:
        contact = await session.get(Contact, contact_id)
        assert contact.is_revealed is False


@pytest.mark.asyncio
async def test_reveal_requires_hunter(setup_test_tenants):
    tokens, ids = setup_test_tenants["tokens"], setup_test_tenants["ids"]
    _, (contact_id,) = await _lead(ids["org_a_id"], contacts=[("Jane", "Doe")])

    transport = ASGITransport(app=app)
    with patch.object(HUNTER, "is_configured", return_value=False):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post(f"/api/v1/contacts/{contact_id}/reveal", json={}, headers=_auth(tokens))
    assert res.status_code == 503
    assert "HUNTER_API_KEY" in res.json()["detail"]


@pytest.mark.asyncio
async def test_company_reveal_discovers_then_reveals_top_contact(setup_test_tenants):
    tokens, ids = setup_test_tenants["tokens"], setup_test_tenants["ids"]
    lead_id, _ = await _lead(ids["org_a_id"])  # no contacts stored yet

    found = [
        {"first_name": "Jane", "last_name": "Doe", "title": "CEO", "email": "j***@x.com", "linkedin_url": None},
        {"first_name": "Raj", "last_name": "Patel", "title": "CTO", "email": "r***@x.com", "linkedin_url": None},
    ]
    transport = ASGITransport(app=app)
    with patch.object(HUNTER, "is_configured", return_value=True), patch.object(
        HUNTER, "search_contacts_for_lead", new=AsyncMock(return_value=found)
    ), patch.object(
        HUNTER, "reveal_contact_details", new=AsyncMock(return_value={"email": "jane@x.com", "phone": "+44 1"})
    ) as reveal:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post(f"/api/v1/leads/{lead_id}/reveal-contact", json={}, headers=_auth(tokens))
            assert first.status_code == 200, first.text
            body = first.json()
            assert body["contact"]["email"] == "jane@x.com"
            assert body["contacts_discovered"] == 2
            assert body["already_revealed"] is False

            # The next click reveals the next unrevealed person, never Jane twice
            reveal.return_value = {"email": "raj@x.com"}
            second = await client.post(f"/api/v1/leads/{lead_id}/reveal-contact", json={}, headers=_auth(tokens))
            assert second.json()["contact"]["email"] == "raj@x.com"

            # Everyone revealed: answered without another lookup
            third = await client.post(f"/api/v1/leads/{lead_id}/reveal-contact", json={}, headers=_auth(tokens))
            assert third.json()["already_revealed"] is True

    assert reveal.await_count == 2


@pytest.mark.asyncio
async def test_company_reveal_requires_approved_lead(setup_test_tenants):
    tokens, ids = setup_test_tenants["tokens"], setup_test_tenants["ids"]
    lead_id, _ = await _lead(ids["org_a_id"], approved=False, contacts=[("Jane", "Doe")])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(f"/api/v1/leads/{lead_id}/reveal-contact", json={}, headers=_auth(tokens))
        viewer = await client.post(
            f"/api/v1/leads/{lead_id}/reveal-contact", json={}, headers={"Authorization": f"Bearer {setup_test_tenants['tokens']['org_a_viewer']}"}
        )
    assert res.status_code == 400
    assert viewer.status_code == 403


@pytest.mark.asyncio
async def test_discover_contacts_dedupes_people(setup_test_tenants):
    tokens, ids = setup_test_tenants["tokens"], setup_test_tenants["ids"]
    lead_id, _ = await _lead(ids["org_a_id"], approved=False, contacts=[("Jane", "Doe")])
    found = [
        {"first_name": "Jane", "last_name": "Doe", "title": "CEO", "email": "j***@x.com"},
        {"first_name": "Ana", "last_name": "Silva", "title": "CMO", "email": "a***@x.com"},
    ]
    transport = ASGITransport(app=app)
    with patch.object(HUNTER, "is_configured", return_value=True), patch.object(
        HUNTER, "search_contacts_for_lead", new=AsyncMock(return_value=found)
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post(f"/api/v1/leads/{lead_id}/contacts/discover", headers=_auth(tokens))
    assert res.status_code == 200, res.text
    assert res.json()["created"] == 1
    assert len(res.json()["contacts"]) == 2
    assert all(c["is_revealed"] is False for c in res.json()["contacts"])


@pytest.mark.asyncio
async def test_approval_queues_one_auto_draft(setup_test_tenants, monkeypatch):
    tokens, ids = setup_test_tenants["tokens"], setup_test_tenants["ids"]
    monkeypatch.setattr(settings, "AUTO_DRAFT_ON_APPROVAL", True)
    lead_id, _ = await _lead(ids["org_a_id"], approved=False)

    transport = ASGITransport(app=app)
    with patch.object(OPENROUTER, "is_configured", return_value=True), patch(
        "app.services.auto_draft.create_pool", new=AsyncMock()
    ) as create_pool:
        pool = create_pool.return_value
        pool.enqueue_job = AsyncMock()
        pool.close = AsyncMock()
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.patch(
                f"/api/v1/leads/{lead_id}/approval", json={"approval_status": "approved"}, headers=_auth(tokens)
            )
            assert res.status_code == 200, res.text
            assert res.json()["auto_draft"] == "queued"
            pool.enqueue_job.assert_awaited_once_with("generate_lead_draft", str(lead_id), str(ids["org_a_id"]))

            # Approving again is not a new approval, so nothing more is queued
            again = await client.patch(
                f"/api/v1/leads/{lead_id}/approval", json={"approval_status": "approved"}, headers=_auth(tokens)
            )
            assert again.json()["auto_draft"] is None
            assert pool.enqueue_job.await_count == 1


@pytest.mark.asyncio
async def test_approval_reports_missing_openrouter_and_disabled_setting(setup_test_tenants, monkeypatch):
    tokens, ids = setup_test_tenants["tokens"], setup_test_tenants["ids"]
    transport = ASGITransport(app=app)

    monkeypatch.setattr(settings, "AUTO_DRAFT_ON_APPROVAL", True)
    lead_a, _ = await _lead(ids["org_a_id"], approved=False)
    with patch.object(OPENROUTER, "is_configured", return_value=False):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.patch(f"/api/v1/leads/{lead_a}/approval", json={"approval_status": "approved"}, headers=_auth(tokens))
    assert res.json()["auto_draft"] == "not_configured"

    monkeypatch.setattr(settings, "AUTO_DRAFT_ON_APPROVAL", False)
    lead_b, _ = await _lead(ids["org_a_id"], approved=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.patch(f"/api/v1/leads/{lead_b}/approval", json={"approval_status": "approved"}, headers=_auth(tokens))
    assert res.json()["auto_draft"] == "disabled"


@pytest.mark.asyncio
async def test_bulk_approve_queues_drafts(setup_test_tenants, monkeypatch):
    tokens, ids = setup_test_tenants["tokens"], setup_test_tenants["ids"]
    monkeypatch.setattr(settings, "AUTO_DRAFT_ON_APPROVAL", True)
    lead_a, _ = await _lead(ids["org_a_id"], approved=False)
    lead_b, _ = await _lead(ids["org_a_id"], approved=False)

    transport = ASGITransport(app=app)
    with patch.object(OPENROUTER, "is_configured", return_value=True), patch(
        "app.services.auto_draft.create_pool", new=AsyncMock()
    ) as create_pool:
        pool = create_pool.return_value
        pool.enqueue_job = AsyncMock()
        pool.close = AsyncMock()
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post(
                "/api/v1/leads/bulk", json={"action": "approve", "lead_ids": [str(lead_a), str(lead_b)]}, headers=_auth(tokens)
            )
    assert res.status_code == 200, res.text
    assert res.json()["drafts_queued"] == 2


@pytest.mark.asyncio
async def test_draft_job_writes_one_draft_for_best_contact(setup_test_tenants):
    ids = setup_test_tenants["ids"]
    org_id = ids["org_a_id"]
    lead_id, contact_ids = await _lead(org_id, contacts=[("Jane", "Doe"), ("Raj", "Patel")])

    # Raj is revealed, so the draft is addressed to him
    async with tenant_session(org_id) as session:
        raj = await session.get(Contact, contact_ids[1])
        raj.is_revealed = True
        raj.email = "raj@x.com"
        await session.commit()

    with patch.object(OPENROUTER, "is_configured", return_value=True), patch.object(
        OPENROUTER, "generate_outreach_draft", new=AsyncMock(return_value=FAKE_DRAFT)
    ) as gen:
        first = await generate_lead_draft({}, str(lead_id), str(org_id))
        second = await generate_lead_draft({}, str(lead_id), str(org_id))

    assert first["status"] == "completed"
    assert second == {"status": "skipped", "reason": "draft_exists"}
    assert gen.await_count == 1
    assert gen.await_args.kwargs["contact_name"] == "Raj Patel"

    async with tenant_session(org_id) as session:
        drafts = (await session.execute(select(Draft).where(Draft.lead_id == lead_id))).scalars().all()
        lead = await session.get(Lead, lead_id)
    assert len(drafts) == 1
    assert drafts[0].approval_status == DraftApprovalStatus.PENDING
    assert drafts[0].contact_id == contact_ids[1]
    assert lead.pipeline_status == PipelineStatus.DRAFTED


@pytest.mark.asyncio
async def test_draft_job_skips_unapproved_lead_and_releases_quota_on_llm_failure(setup_test_tenants):
    org_id = setup_test_tenants["ids"]["org_a_id"]
    pending_lead, _ = await _lead(org_id, approved=False)
    assert (await generate_lead_draft({}, str(pending_lead), str(org_id)))["reason"] == "lead_not_approved"

    lead_id, _ = await _lead(org_id)
    with patch.object(OPENROUTER, "is_configured", return_value=True), patch.object(
        OPENROUTER, "generate_outreach_draft", new=AsyncMock(side_effect=RuntimeError("OpenRouter HTTP 500"))
    ), patch("app.services.quota_service.QuotaService.release_draft_generation", new=AsyncMock()) as release:
        result = await generate_lead_draft({}, str(lead_id), str(org_id))
    assert result["status"] == "failed"
    release.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_draft_endpoint_accepts_empty_body(setup_test_tenants):
    tokens, ids = setup_test_tenants["tokens"], setup_test_tenants["ids"]
    lead_id, _ = await _lead(ids["org_a_id"], contacts=[("Jane", "Doe")])
    transport = ASGITransport(app=app)
    with patch.object(OPENROUTER, "is_configured", return_value=True), patch.object(
        OPENROUTER, "generate_outreach_draft", new=AsyncMock(return_value=FAKE_DRAFT)
    ):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post(f"/api/v1/leads/{lead_id}/drafts", headers=_auth(tokens))
    assert res.status_code == 201, res.text
    assert res.json()["subject"] == FAKE_DRAFT["subject"]


def _completion(content: str, finish: str = "stop"):
    import httpx

    return httpx.Response(
        200,
        json={"choices": [{"finish_reason": finish, "message": {"content": content}}]},
        request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"),
    )


@pytest.mark.asyncio
async def test_openrouter_draft_parses_json_and_limits_reasoning():
    from app.providers.openrouter import OpenRouterAdapter

    adapter = OpenRouterAdapter()
    adapter.api_key = "sk-test"
    reply = '{"subject": "Faster site for Delta", "body": "Hi Jane,\nYour site is slow.", "citations_used": []}'
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=_completion(reply))) as post:
        draft = await adapter.generate_outreach_draft("Delta", "delta.com", "Jane", "CEO", 90.0, "qualified", {})

    assert draft["subject"] == "Faster site for Delta"
    sent = post.await_args.kwargs["json"]
    assert sent["max_tokens"] >= 1500
    assert sent["reasoning"] == {"effort": "low", "exclude": True}


@pytest.mark.asyncio
async def test_openrouter_truncated_reply_raises_instead_of_placeholder():
    from app.providers.openrouter import OpenRouterAdapter, OpenRouterParsingError

    adapter = OpenRouterAdapter()
    adapter.api_key = "sk-test"
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=_completion('{"subject": "Hi', "length"))):
        with pytest.raises(OpenRouterParsingError) as exc:
            await adapter.generate_outreach_draft("Delta", "delta.com", None, None, 90.0, "qualified", {})
    assert "cut off" in str(exc.value)
