"""
Search pipeline behaviour added in the October 2026 audit. Every provider is mocked: these tests
never call a paid API.
"""
import asyncio
import uuid
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.constants import ApprovalStatus, PipelineStatus, RunStatus, ScoreBand
from app.jobs.search_tasks import _dedupe, run_search_pipeline
from app.models.contact import Contact
from app.models.lead import Lead
from app.models.organization import Organization
from app.models.run import Run
from app.providers.manager import provider_manager
from app.providers.serpapi import parse_review_count, pick_matching_place
from app.scoring.catalog import DEFAULT_SIGNAL_WEIGHTS
from app.services.enrichment_service import coerce_employee_count

CRAWLER_KEYS = [k for k in DEFAULT_SIGNAL_WEIGHTS if k not in {"slow_site", "low_domain_trust", "ppc_spend", "low_review_rating"}]


def crawl_result(value: float, reachable: bool = True) -> dict:
    if not reachable:
        return {
            "signals": {k: {"value": None, "evidence": "Crawl failed: unreachable"} for k in DEFAULT_SIGNAL_WEIGHTS},
            "provenance": {"reachable": False, "error": "Unable to reach domain dead.example within 12.0s."},
        }
    return {
        "signals": {k: {"value": value, "evidence": f"{k} evidence"} for k in CRAWLER_KEYS},
        "provenance": {"reachable": True, "ssl_valid": True},
    }


EMPTY = {"signals": {}, "provenance": {"status": "ok"}}


@pytest.fixture
async def org_and_run(admin_engine):
    maker = async_sessionmaker(bind=admin_engine, class_=AsyncSession, expire_on_commit=False)
    org_id, run_id = uuid.uuid4(), uuid.uuid4()
    async with maker() as s:
        s.add(Organization(id=org_id, name="Pipeline Audit Org", slug=f"pipe-{org_id.hex[:8]}"))
        await s.flush()
        s.add(
            Run(
                id=run_id, org_id=org_id, run_type="search", status=RunStatus.PENDING,
                items_total=10, items_processed=0, items_succeeded=0, items_failed=0, error_details={},
            )
        )
        await s.commit()
    yield maker, org_id, run_id
    async with maker() as s:
        await s.execute(text("DELETE FROM orgs WHERE id = :oid"), {"oid": org_id})
        await s.commit()


def mocked_providers(stack: ExitStack, crawl_side_effect, contacts=None):
    """Patches every collector. Returns the mocks a test may want to inspect."""
    mocks = {
        "crawl": stack.enter_context(patch.object(provider_manager.crawler, "crawl_domain", new_callable=AsyncMock, side_effect=crawl_side_effect)),
        "pagespeed": stack.enter_context(patch.object(provider_manager.pagespeed, "audit_url", new_callable=AsyncMock, return_value=EMPTY)),
        "places": stack.enter_context(patch.object(provider_manager.places, "fetch_place_signals", new_callable=AsyncMock, return_value=EMPTY)),
        "dataforseo": stack.enter_context(patch.object(provider_manager.dataforseo, "fetch_seo_signals", new_callable=AsyncMock, return_value=EMPTY)),
        "serpapi": stack.enter_context(patch.object(provider_manager.serpapi, "fetch_review_signals", new_callable=AsyncMock, return_value=EMPTY)),
        "hunter_configured": stack.enter_context(patch.object(provider_manager.hunter, "is_configured", return_value=True)),
        "enrich_company": stack.enter_context(patch.object(provider_manager.hunter, "enrich_company", new_callable=AsyncMock, return_value=None)),
        "contacts": stack.enter_context(
            patch.object(
                provider_manager.hunter, "search_contacts_for_lead", new_callable=AsyncMock,
                return_value=contacts if contacts is not None else [
                    {"first_name": "Ada", "last_name": "Lovelace", "title": "CEO", "email": "a***@x.com"}
                ],
            )
        ),
    }
    return mocks


@pytest.mark.asyncio
async def test_new_search_does_not_reset_an_approved_lead(org_and_run):
    maker, org_id, run_id = org_and_run
    domain = f"approved-{uuid.uuid4().hex[:8]}.com"
    async with maker() as s:
        s.add(Lead(org_id=org_id, domain=domain, company_name="Approved Co",
                   pipeline_status=PipelineStatus.APPROVED, approval_status=ApprovalStatus.APPROVED,
                   score_band=ScoreBand.QUALIFIED))
        await s.commit()

    with ExitStack() as stack:
        mocks = mocked_providers(stack, crawl_side_effect=lambda d: crawl_result(1.0))
        result = await run_search_pipeline({}, str(run_id), str(org_id), 10, {"domains": [domain]})

    assert result["skipped"] == 1
    mocks["crawl"].assert_not_awaited()
    async with maker() as s:
        lead = (await s.execute(select(Lead).where(Lead.domain == domain))).scalars().one()
        assert lead.pipeline_status == PipelineStatus.APPROVED
        run = await s.get(Run, run_id)
        assert run.status == RunStatus.COMPLETED
        assert run.error_details.get("already_reviewed_skipped") == 1


@pytest.mark.asyncio
async def test_unreachable_site_goes_to_error_stage_without_paid_calls(org_and_run):
    maker, org_id, run_id = org_and_run
    domain = f"dead-{uuid.uuid4().hex[:8]}.example"

    with ExitStack() as stack:
        mocks = mocked_providers(stack, crawl_side_effect=lambda d: crawl_result(0.0, reachable=False))
        result = await run_search_pipeline({}, str(run_id), str(org_id), 10, {"domains": [domain]})

    assert result["failed"] == 1
    for paid in ("serpapi", "places", "dataforseo", "enrich_company", "contacts"):
        mocks[paid].assert_not_awaited()
    async with maker() as s:
        lead = (await s.execute(select(Lead).where(Lead.domain == domain))).scalars().one()
        assert lead.pipeline_status == PipelineStatus.ERROR
        assert "Unable to reach" in lead.error_reason
        assert lead.score_band is None
        run = await s.get(Run, run_id)
        assert domain in run.error_details["failed_leads"]


@pytest.mark.asyncio
async def test_contacts_are_only_looked_up_for_leads_worth_contacting(org_and_run):
    maker, org_id, run_id = org_and_run
    strong = f"strong-{uuid.uuid4().hex[:8]}.com"
    weak = f"weak-{uuid.uuid4().hex[:8]}.com"

    def crawl(domain):
        return crawl_result(1.0 if domain == strong else 0.0)

    with ExitStack() as stack:
        mocks = mocked_providers(stack, crawl_side_effect=crawl)
        await run_search_pipeline({}, str(run_id), str(org_id), 10, {"domains": [strong, weak]})

    looked_up = [call.args[0] for call in mocks["contacts"].await_args_list]
    assert looked_up == [strong]
    async with maker() as s:
        leads = {lead.domain: lead for lead in (await s.execute(select(Lead).where(Lead.org_id == org_id))).scalars()}
        assert leads[strong].score_band == ScoreBand.QUALIFIED
        assert leads[weak].score_band == ScoreBand.DISQUALIFIED
        contacts = (await s.execute(select(Contact).where(Contact.org_id == org_id))).scalars().all()
        assert [c.lead_id for c in contacts] == [leads[strong].id]


@pytest.mark.asyncio
async def test_leads_run_in_parallel_and_duplicates_are_merged(org_and_run, monkeypatch):
    maker, org_id, run_id = org_and_run
    from app.core.config import settings

    monkeypatch.setattr(settings, "SEARCH_LEAD_CONCURRENCY", 3)
    in_flight = {"now": 0, "peak": 0}

    async def slow_crawl(domain):
        in_flight["now"] += 1
        in_flight["peak"] = max(in_flight["peak"], in_flight["now"])
        await asyncio.sleep(0.05)
        in_flight["now"] -= 1
        return crawl_result(0.0)

    tag = uuid.uuid4().hex[:6]
    domains = [f"par{i}-{tag}.com" for i in range(6)] + [f"PAR0-{tag}.com", f"https://par1-{tag}.com/about"]
    with ExitStack() as stack:
        mocked_providers(stack, crawl_side_effect=slow_crawl)
        result = await run_search_pipeline({}, str(run_id), str(org_id), 10, {"domains": domains})

    assert result["items_processed"] == 6
    assert 1 < in_flight["peak"] <= 3
    async with maker() as s:
        run = await s.get(Run, run_id)
        assert run.status == RunStatus.COMPLETED
        assert run.items_processed == 6 and run.progress_pct == 100


@pytest.mark.asyncio
async def test_interrupted_run_is_marked_failed(org_and_run):
    maker, org_id, run_id = org_and_run

    with patch("app.jobs.search_tasks._process_prospect", new_callable=AsyncMock, side_effect=asyncio.CancelledError()):
        with pytest.raises(asyncio.CancelledError):
            await run_search_pipeline({}, str(run_id), str(org_id), 10, {"domains": ["interrupted.example"]})

    async with maker() as s:
        run = await s.get(Run, run_id)
        assert run.status == RunStatus.FAILED
        assert "interrupted" in run.error_details["error"]


def test_dedupe_and_headcount_helpers():
    assert [p["domain"] for p in _dedupe([{"domain": "A.com"}, {"domain": "https://a.com/x"}, {"domain": "b.com"}])] == ["a.com", "b.com"]
    assert coerce_employee_count("11-50") == 11
    assert coerce_employee_count("10,000+") == 10000
    assert coerce_employee_count(42) == 42
    assert coerce_employee_count(None) is None


def test_serpapi_ignores_listings_for_other_businesses():
    data = {
        "local_results": [
            {"title": "Acme Plumbing", "website": "https://other-company.com", "rating": 2.1, "reviews": 80},
            {"title": "Acme Roofing", "website": "https://www.acme.com/", "rating": 4.8, "reviews": "1,204"},
        ]
    }
    place = pick_matching_place(data, "acme.com", "Acme")
    assert place["rating"] == 4.8
    assert parse_review_count(place["reviews"]) == 1204

    wrong_only = {"local_results": [{"title": "Acme", "website": "https://not-acme.org", "rating": 1.0}]}
    assert pick_matching_place(wrong_only, "acme.com", "Acme") is None

    no_site = {"local_results": [{"title": "Acme Dental Clinic", "rating": 3.1}]}
    assert pick_matching_place(no_site, "acmedental.com", "Acme Dental")["rating"] == 3.1
