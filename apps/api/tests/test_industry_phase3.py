import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.constants import ApprovalStatus, PipelineStatus, RunStatus
from app.core.filter_catalog import (
    validate_and_normalize_filters,
    validate_and_normalize_search_params,
    resolve_effective_search_params,
)
from app.jobs.search_tasks import run_search_pipeline
from app.main import app
from app.models.audience import Audience
from app.models.lead import Lead
from app.models.run import Run
from app.models.search import Search
from app.providers.hunter import HunterAdapter
from app.providers.manager import provider_manager
from app.providers.openrouter import OpenRouterAdapter
from tests.test_business_workflows import admin_engine, cleanup_pool_and_redis, setup_test_tenants


# ==============================================================================
# 1. Provider Parameter Mapping Unit Tests (HunterAdapter Discover)
# ==============================================================================

@pytest.mark.asyncio
async def test_hunter_provider_maps_verticals_and_keywords_to_discover_payload():
    adapter = HunterAdapter()
    adapter.api_key = "test-hunter-key"

    filters = {
        "verticals": ["B2B SaaS", "FinTech"],
        "keywords": ["AI", "B2B SaaS"],  # Includes duplicate
        "locations": ["Ahmedabad"],
        "employee_ranges": ["11-50"],
    }

    captured_payload = {}

    async def mock_post(url, headers, json):
        nonlocal captured_payload
        captured_payload = json
        return Response(
            200,
            json={
                "data": {
                    "companies": [
                        {
                            "name": "CloudCo",
                            "domain": "cloudco.io",
                            "industry": "Computer Software",
                            "keywords": ["B2B SaaS", "AI"],
                            "headcount": "11-50",
                            "headquarters_location": {
                                "city": "Ahmedabad",
                                "country": "IN",
                            },
                        }
                    ],
                    "total": 1,
                },
                "meta": {"results": 1, "limit": 10, "page": 1},
            },
        )

    with patch("httpx.AsyncClient.post", side_effect=mock_post):
        res = await adapter.search_organizations(filters, limit=10)
        assert res["total"] == 1
        assert len(res["organizations"]) == 1
        org = res["organizations"][0]
        assert org["domain"] == "cloudco.io"
        assert org["industry"] == "Computer Software"
        assert "B2B SaaS" in org["keywords"]
        assert org["city"] == "Ahmedabad"
        assert org["country"] == "IN"

        # Verify translated parameters in Hunter Discover request payload
        assert "filters" in captured_payload
        h_filters = captured_payload["filters"]
        assert h_filters["industry"]["include"] == ["B2B SaaS", "FinTech"]
        assert h_filters["keywords"]["include"] == ["AI", "B2B SaaS"]
        assert h_filters["headcount"] == ["11-50"]
        assert h_filters["headquarters_location"]["city"] == "Ahmedabad"
        assert h_filters["headquarters_location"]["country"] == "IN"


# ==============================================================================
# 2. Heuristic Parser: Distinguishing Service Sold from Client Industry
# ==============================================================================

def test_heuristic_distinguishes_service_sold_from_client_industry():
    adapter = OpenRouterAdapter()
    prompt = "Small and medium businesses in Ahmedabad and Surat that could benefit from a better website or digital marketing"
    result = adapter._heuristic_icp_parse(prompt)

    filters = result["filters"]
    # Crucial: "Website Development" or "Digital Marketing" describes the vendor's service,
    # NOT the client's industry. The target industry must be empty/broad!
    assert filters["verticals"] == []
    assert filters["industries"] == []
    assert "Ahmedabad" in filters["locations"]
    assert "Surat" in filters["locations"]
    assert "unrestricted" in result["ai_rationale"].lower() or "service offering" in result["ai_rationale"].lower()


def test_heuristic_preserves_explicit_client_industries():
    adapter = OpenRouterAdapter()
    prompt = "Healthcare clinics and dental practices in Gujarat needing better patient booking software"
    result = adapter._heuristic_icp_parse(prompt)

    filters = result["filters"]
    # Healthcare is the target client industry
    assert any("health" in v.lower() for v in filters["verticals"])


# ==============================================================================
# 3. Filter Catalog Verticals & Industries Bidirectional Sync
# ==============================================================================

def test_vertical_and_industries_synchronization_in_filter_catalog():
    # 1. Specifying canonical verticals populates backward-compatible industries
    normalized_v = validate_and_normalize_filters({"verticals": ["B2B SaaS"]})
    assert normalized_v["verticals"] == ["B2B SaaS"]
    assert normalized_v["industries"] == ["B2B SaaS"]

    # 2. Specifying legacy industries populates canonical verticals
    normalized_i = validate_and_normalize_filters({"industries": ["Fintech & Banking"]})
    assert normalized_i["verticals"] == ["Fintech & Banking"]
    assert normalized_i["industries"] == ["Fintech & Banking"]

    # 3. Singular industry search param alias populates both
    search_params = validate_and_normalize_search_params({"industry": "E-Commerce"})
    assert search_params["verticals"] == ["E-Commerce"]
    assert search_params["industries"] == ["E-Commerce"]


# ==============================================================================
# 4. Worker Execution: Downstream Industry Matching & Exclusions
# ==============================================================================

@pytest.mark.asyncio
async def test_downstream_exclude_verticals_filters_prospects(setup_test_tenants, admin_engine):
    ids = setup_test_tenants["ids"]
    org_id = ids["org_a_id"]
    user_id = ids["org_a_admin_id"]

    session_factory = async_sessionmaker(
        bind=admin_engine, class_=AsyncSession, expire_on_commit=False
    )

    search_id = uuid.uuid4()
    run_id = uuid.uuid4()

    query_params = {
        "locations": ["Ahmedabad"],
        "exclude_verticals": ["Marketing & Advertising", "Government"],
    }

    async with session_factory() as session:
        search = Search(
            id=search_id,
            org_id=org_id,
            name="Exclude Agency Test",
            query_params=query_params,
            created_by=user_id,
        )
        run = Run(
            id=run_id,
            org_id=org_id,
            search_id=search_id,
            run_type="search",
            status=RunStatus.PENDING,
            items_total=10,
            items_processed=0,
            items_succeeded=0,
            items_failed=0,
            error_details={},
        )
        session.add(search)
        session.add(run)
        await session.commit()

    # Mock Apollo returning 3 prospects:
    # 1. Tech company (allowed)
    # 2. Marketing agency (should be dropped by exclude_verticals)
    # 3. Government office (should be dropped by exclude_verticals)
    mock_hunter_results = {
        "organizations": [
            {
                "company_name": "SaaS Platform Ltd",
                "domain": "saasplatform-valid.com",
                "industry": "Computer Software",
                "keywords": ["Cloud", "Analytics"],
                "country": "India",
                "city": "Ahmedabad",
                "employee_count": 25,
            },
            {
                "company_name": "Creative Ad Agency",
                "domain": "creative-ad-agency.com",
                "industry": "Marketing & Advertising",
                "keywords": ["SEO", "Digital Marketing"],
                "country": "India",
                "city": "Ahmedabad",
                "employee_count": 15,
            },
            {
                "company_name": "Municipal Council",
                "domain": "local-gov-council.gov",
                "industry": "Government Administration",
                "keywords": ["Public Sector"],
                "country": "India",
                "city": "Ahmedabad",
                "employee_count": 100,
            },
        ],
        "total": 3,
    }

    with patch.object(
        provider_manager.hunter,
        "is_configured",
        return_value=True,
    ), patch.object(
        provider_manager.hunter,
        "search_organizations",
        new_callable=AsyncMock,
        return_value=mock_hunter_results,
    ):
        result = await run_search_pipeline(
            ctx={},
            run_id_str=str(run_id),
            org_id_str=str(org_id),
            limit=10,
            query_params=query_params,
        )

        assert result["status"] == "completed"

    # Verify only the non-excluded tech company was ingested as a Lead
    async with session_factory() as session:
        leads_stmt = select(Lead).where(
            Lead.org_id == org_id,
            Lead.domain.in_([
                "saasplatform-valid.com",
                "creative-ad-agency.com",
                "local-gov-council.gov",
            ]),
        )
        leads = (await session.execute(leads_stmt)).scalars().all()
        leads_by_domain = {l.domain: l for l in leads}

        assert "saasplatform-valid.com" in leads_by_domain
        assert "creative-ad-agency.com" not in leads_by_domain
        assert "local-gov-council.gov" not in leads_by_domain


@pytest.mark.asyncio
async def test_downstream_vertical_match_and_vs_or(setup_test_tenants, admin_engine):
    ids = setup_test_tenants["ids"]
    org_id = ids["org_a_id"]
    user_id = ids["org_a_admin_id"]

    session_factory = async_sessionmaker(
        bind=admin_engine, class_=AsyncSession, expire_on_commit=False
    )

    # 1. Test AND matching rule: must match ALL specified verticals
    search_id = uuid.uuid4()
    run_id = uuid.uuid4()

    query_params_and = {
        "locations": ["Ahmedabad"],
        "verticals": ["Software", "Healthcare"],
        "vertical_match": "and",
    }

    async with session_factory() as session:
        search = Search(
            id=search_id,
            org_id=org_id,
            name="AND Matching Test",
            query_params=query_params_and,
            created_by=user_id,
        )
        run = Run(
            id=run_id,
            org_id=org_id,
            search_id=search_id,
            run_type="search",
            status=RunStatus.PENDING,
            items_total=10,
            items_processed=0,
            items_succeeded=0,
            items_failed=0,
            error_details={},
        )
        session.add(search)
        session.add(run)
        await session.commit()

    # Company 1: Matches Software AND Healthcare keywords
    # Company 2: Matches Software only
    mock_hunter_results = {
        "organizations": [
            {
                "company_name": "HealthTech Solutions",
                "domain": "healthtech-both.com",
                "industry": "Computer Software",
                "keywords": ["Healthcare", "EHR"],
                "country": "India",
                "city": "Ahmedabad",
                "employee_count": 30,
            },
            {
                "company_name": "Fintech App",
                "domain": "fintech-software-only.com",
                "industry": "Computer Software",
                "keywords": ["Banking", "Finance"],
                "country": "India",
                "city": "Ahmedabad",
                "employee_count": 40,
            },
        ],
        "total": 2,
    }

    with patch.object(
        provider_manager.hunter,
        "is_configured",
        return_value=True,
    ), patch.object(
        provider_manager.hunter,
        "search_organizations",
        new_callable=AsyncMock,
        return_value=mock_hunter_results,
    ):
        result = await run_search_pipeline(
            ctx={},
            run_id_str=str(run_id),
            org_id_str=str(org_id),
            limit=10,
            query_params=query_params_and,
        )
        assert result["status"] == "completed"

    async with session_factory() as session:
        leads_stmt = select(Lead).where(
            Lead.org_id == org_id,
            Lead.domain.in_(["healthtech-both.com", "fintech-software-only.com"]),
        )
        leads = (await session.execute(leads_stmt)).scalars().all()
        leads_by_domain = {l.domain: l for l in leads}

        # In AND mode, only healthtech-both.com matched both terms
        assert "healthtech-both.com" in leads_by_domain
        assert "fintech-software-only.com" not in leads_by_domain


# ==============================================================================
# 5. API Integration: Audience Vertical Criteria Survive to Search & Worker
# ==============================================================================

@pytest.mark.asyncio
async def test_audience_vertical_criteria_survive_to_search_and_worker(setup_test_tenants, admin_engine):
    tokens = setup_test_tenants["tokens"]
    ids = setup_test_tenants["ids"]
    transport = ASGITransport(app=app)

    session_factory = async_sessionmaker(
        bind=admin_engine, class_=AsyncSession, expire_on_commit=False
    )
    audience_id = uuid.uuid4()
    async with session_factory() as session:
        aud = Audience(
            id=audience_id,
            org_id=ids["org_a_id"],
            name="Fintech Specialists",
            description="Targeting FinTech startups",
            filters={
                "verticals": ["Fintech & Banking"],
                "vertical_match": "or",
                "locations": ["London"],
                "employee_ranges": ["11-50"],
                "exclude_verticals": ["Retail Banking"],
            },
            is_active=True,
            version=1,
        )
        session.add(aud)
        await session.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.services.search_service.create_pool", new_callable=AsyncMock) as mock_pool:
            mock_redis = AsyncMock()
            mock_pool.return_value = mock_redis

            res = await client.post(
                "/api/v1/searches",
                headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
                json={
                    "name": "Fintech Specialists Search",
                    "audience_id": str(audience_id),
                    "query_params": {},
                    "limit": 15,
                },
            )
            assert res.status_code == 202
            data = res.json()
            assert "run_id" in data

            # Verify arguments enqueued to Redis
            enqueued_query = mock_redis.enqueue_job.call_args[0][4]
            assert enqueued_query["verticals"] == ["Fintech & Banking"]
            assert enqueued_query["industries"] == ["Fintech & Banking"]
            assert enqueued_query["exclude_verticals"] == ["Retail Banking"]
            assert enqueued_query["vertical_match"] == "or"
