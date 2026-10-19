import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.constants import ApprovalStatus, PipelineStatus, RunStatus
from app.core.filter_catalog import (
    FilterValidationError,
    resolve_effective_search_params,
    validate_and_normalize_search_params,
)
from app.jobs.search_tasks import run_search_pipeline
from app.main import app
from app.models.audience import Audience
from app.models.lead import Lead
from app.models.run import Run
from app.models.search import Search
from app.providers.manager import provider_manager
from tests.test_business_workflows import admin_engine, cleanup_pool_and_redis, setup_test_tenants


# ==============================================================================
# 1. Unit Tests: Search Parameter & Effective Filter Resolution
# ==============================================================================

def test_validate_and_normalize_search_params_direct_domains():
    params = {
        "domains": [
            "https://stripe.com/pricing",
            "datadoghq.com",
            "  http://notion.so/about  ",
            "stripe.com",  # Duplicate
        ]
    }
    normalized = validate_and_normalize_search_params(params)
    assert normalized["domains"] == ["stripe.com", "datadoghq.com", "notion.so"]


def test_validate_and_normalize_search_params_singular_industry_alias():
    params = {"industry": "FinTech"}
    normalized = validate_and_normalize_search_params(params)
    assert normalized["industries"] == ["FinTech"]


def test_validate_and_normalize_search_params_unsupported_key_rejected():
    with pytest.raises(FilterValidationError) as exc:
        validate_and_normalize_search_params({"funding_stage": "Series A"})
    assert "Unsupported search parameter key" in str(exc.value)


def test_resolve_effective_search_params_precedence():
    audience_filters = {
        "locations": ["Ahmedabad", "Surat"],
        "employee_ranges": ["11-50", "51-200"],
        "verticals": ["Digital Marketing"],
        "exclude_domains": ["competitor.com"],
        "exclude_existing_crm": True,
    }
    # User provides manual domains and a refined location override
    overrides = {
        "domains": ["direct-target.com"],
        "locations": ["Ahmedabad"],
    }
    effective = resolve_effective_search_params(audience_filters, overrides)
    assert effective["domains"] == ["direct-target.com"]
    assert effective["locations"] == ["Ahmedabad"]  # Overridden
    assert effective["employee_ranges"] == ["11-50", "51-200"]  # Preserved from audience
    assert effective["verticals"] == ["Digital Marketing"]  # Preserved from audience
    assert effective["exclude_domains"] == ["competitor.com"]  # Preserved from audience
    assert effective["exclude_existing_crm"] is True  # Preserved from audience


def test_resolve_effective_search_params_no_overrides():
    audience_filters = {
        "locations": ["London", "Manchester"],
        "employee_ranges": ["51-200"],
    }
    effective = resolve_effective_search_params(audience_filters, None)
    assert effective["locations"] == ["London", "Manchester"]
    assert effective["employee_ranges"] == ["51-200"]
    assert "domains" not in effective


# ==============================================================================
# 2. Integration Tests: API /searches Endpoint & Tenant Enforcement
# ==============================================================================

@pytest.mark.asyncio
async def test_search_creation_with_saved_audience(setup_test_tenants, admin_engine):
    tokens = setup_test_tenants["tokens"]
    ids = setup_test_tenants["ids"]
    transport = ASGITransport(app=app)

    # 1. Create a saved audience in Org A
    session_factory = async_sessionmaker(
        bind=admin_engine, class_=AsyncSession, expire_on_commit=False
    )
    audience_id = uuid.uuid4()
    async with session_factory() as session:
        aud = Audience(
            id=audience_id,
            org_id=ids["org_a_id"],
            name="Gujarat SaaS SMBs",
            description="Software SMBs in Ahmedabad and Surat",
            filters={
                "locations": ["Ahmedabad", "Surat"],
                "employee_ranges": ["11-50"],
                "verticals": ["B2B SaaS"],
                "exclude_domains": ["bad-actor.com"],
                "exclude_existing_crm": True,
            },
            ai_rationale="High-density industrial clusters seeking cloud modernization.",
            is_active=True,
            version=1,
        )
        session.add(aud)
        await session.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 2. Submit new search referencing the saved audience with empty overrides
        with patch("app.services.search_service.create_pool", new_callable=AsyncMock) as mock_pool:
            mock_redis = AsyncMock()
            mock_pool.return_value = mock_redis

            res = await client.post(
                "/api/v1/searches",
                headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
                json={
                    "name": "Gujarat SaaS SMBs Discovery",
                    "audience_id": str(audience_id),
                    "query_params": {},
                    "limit": 25,
                },
            )
            assert res.status_code == 202
            data = res.json()
            assert "run_id" in data
            assert data["status"] == "pending"
            assert mock_redis.enqueue_job.called

            # Verify the arguments enqueued to Redis
            enqueue_args = mock_redis.enqueue_job.call_args[0]
            assert enqueue_args[0] == "run_search_pipeline"
            enqueued_query = enqueue_args[4]
            assert enqueued_query["locations"] == ["Ahmedabad", "Surat"]
            assert enqueued_query["employee_ranges"] == ["11-50"]
            assert enqueued_query["exclude_domains"] == ["bad-actor.com"]
            assert enqueued_query["exclude_existing_crm"] is True
            # Crucial: verify hardcoded "United States" is NOT present
            assert enqueued_query["locations"] != ["United States"]

    # 3. Verify Search record in the database
    async with session_factory() as session:
        run_stmt = select(Run).where(Run.id == uuid.UUID(data["run_id"]))
        run = (await session.execute(run_stmt)).scalars().first()
        assert run is not None
        assert run.search_id is not None

        search = (await session.execute(select(Search).where(Search.id == run.search_id))).scalars().first()
        assert search is not None
        assert search.audience_id == audience_id
        assert search.query_params["locations"] == ["Ahmedabad", "Surat"]
        assert search.query_params["exclude_domains"] == ["bad-actor.com"]


@pytest.mark.asyncio
async def test_search_creation_with_audience_and_manual_overrides(setup_test_tenants, admin_engine):
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
            name="London FinTech",
            description="UK FinTechs",
            filters={
                "locations": ["London"],
                "employee_ranges": ["51-200"],
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
                    "name": "London FinTech Custom",
                    "audience_id": str(audience_id),
                    "query_params": {
                        "domains": ["monzo.com", "revolut.com"],
                    },
                    "limit": 10,
                },
            )
            assert res.status_code == 202

            # Check that enqueued payload merges domain overrides while keeping audience location
            enqueued_query = mock_redis.enqueue_job.call_args[0][4]
            assert enqueued_query["domains"] == ["monzo.com", "revolut.com"]
            assert enqueued_query["locations"] == ["London"]
            assert enqueued_query["employee_ranges"] == ["51-200"]


@pytest.mark.asyncio
async def test_manual_search_without_audience_preserved(setup_test_tenants):
    tokens = setup_test_tenants["tokens"]
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("app.services.search_service.create_pool", new_callable=AsyncMock) as mock_pool:
            mock_redis = AsyncMock()
            mock_pool.return_value = mock_redis

            res = await client.post(
                "/api/v1/searches",
                headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
                json={
                    "name": "Direct Input Discovery",
                    "audience_id": None,
                    "query_params": {
                        "domains": ["stripe.com", "github.com"],
                    },
                    "limit": 10,
                },
            )
            assert res.status_code == 202
            enqueued_query = mock_redis.enqueue_job.call_args[0][4]
            assert enqueued_query["domains"] == ["stripe.com", "github.com"]


@pytest.mark.asyncio
async def test_empty_criteria_rejected(setup_test_tenants):
    tokens = setup_test_tenants["tokens"]
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/v1/searches",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
            json={
                "name": "Empty Search",
                "audience_id": None,
                "query_params": {},
                "limit": 10,
            },
        )
        assert res.status_code == 400
        assert "Search must contain at least one criteria" in res.json()["detail"]


@pytest.mark.asyncio
async def test_unsupported_filter_keys_rejected(setup_test_tenants):
    tokens = setup_test_tenants["tokens"]
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/v1/searches",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
            json={
                "name": "Invalid Filter Search",
                "audience_id": None,
                "query_params": {"unknown_field": "some_value"},
                "limit": 10,
            },
        )
        assert res.status_code == 422
        assert "Unsupported search parameter key" in res.json()["detail"]


@pytest.mark.asyncio
async def test_inactive_audience_rejected(setup_test_tenants, admin_engine):
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
            name="Decommissioned Audience",
            description="Inactive profile",
            filters={"locations": ["London"]},
            is_active=False,  # Inactive
            version=1,
        )
        session.add(aud)
        await session.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/v1/searches",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
            json={
                "name": "Attempt Search With Inactive Audience",
                "audience_id": str(audience_id),
                "query_params": {},
                "limit": 10,
            },
        )
        assert res.status_code == 400
        assert "inactive and cannot be used" in res.json()["detail"]


@pytest.mark.asyncio
async def test_cross_tenant_audience_rejected(setup_test_tenants, admin_engine):
    tokens = setup_test_tenants["tokens"]
    ids = setup_test_tenants["ids"]
    transport = ASGITransport(app=app)

    session_factory = async_sessionmaker(
        bind=admin_engine, class_=AsyncSession, expire_on_commit=False
    )
    audience_b_id = uuid.uuid4()
    async with session_factory() as session:
        # Audience belongs to Org B
        aud = Audience(
            id=audience_b_id,
            org_id=ids["org_b_id"],
            name="Org B Private Audience",
            description="Org B only",
            filters={"locations": ["Paris"]},
            is_active=True,
            version=1,
        )
        session.add(aud)
        await session.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Org A attempts to access Org B's audience
        res = await client.post(
            "/api/v1/searches",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
            json={
                "name": "Cross Tenant Search",
                "audience_id": str(audience_b_id),
                "query_params": {},
                "limit": 10,
            },
        )
        assert res.status_code == 404
        assert "not found in active organization" in res.json()["detail"]


# ==============================================================================
# 3. Worker Execution Tests: Discovery & Downstream Exclusions
# ==============================================================================

@pytest.mark.asyncio
async def test_worker_discovery_hunter_criteria_and_downstream_exclusions(setup_test_tenants, admin_engine):
    ids = setup_test_tenants["ids"]
    org_id = ids["org_a_id"]
    user_id = ids["org_a_admin_id"]

    session_factory = async_sessionmaker(
        bind=admin_engine, class_=AsyncSession, expire_on_commit=False
    )

    # 1. Seed existing CRM-synced lead to test exclude_existing_crm
    synced_domain = f"existing-synced-{uuid.uuid4().hex[:6]}.com"
    async with session_factory() as session:
        existing_lead = Lead(
            id=uuid.uuid4(),
            org_id=org_id,
            domain=synced_domain,
            company_name="Synced Corp",
            pipeline_status=PipelineStatus.SYNCED,
            approval_status=ApprovalStatus.APPROVED,
        )
        session.add(existing_lead)

        # 2. Seed Search and Run records
        search_id = uuid.uuid4()
        run_id = uuid.uuid4()

        query_params = {
            "locations": ["Ahmedabad", "Surat"],
            "employee_ranges": ["11-50"],
            "exclude_domains": ["excluded-competitor.com"],
            "exclude_existing_crm": True,
        }

        search = Search(
            id=search_id,
            org_id=org_id,
            name="Gujarat Discovery Run",
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

    # 3. Mock Hunter search_organizations to return 3 prospects:
    #    - valid-lead.com (should be ingested)
    #    - excluded-competitor.com (should be dropped by exclude_domains)
    #    - synced_domain (should be dropped by exclude_existing_crm)
    mock_hunter_results = {
        "organizations": [
            {
                "company_name": "Valid Lead Tech",
                "domain": "valid-lead.com",
                "industry": "Software",
                "country": "India",
                "city": "Ahmedabad",
                "employee_count": 25,
            },
            {
                "company_name": "Competitor Org",
                "domain": "excluded-competitor.com",
                "industry": "Software",
                "country": "India",
                "city": "Surat",
                "employee_count": 30,
            },
            {
                "company_name": "Synced Corp",
                "domain": synced_domain,
                "industry": "Software",
                "country": "India",
                "city": "Ahmedabad",
                "employee_count": 40,
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
    ) as mock_search_orgs:
        # Execute the background task
        result = await run_search_pipeline(
            ctx={},
            run_id_str=str(run_id),
            org_id_str=str(org_id),
            limit=10,
            query_params=query_params,
        )

        assert result["status"] == "completed"
        # Hunter search must have been called with locations & employee_ranges
        assert mock_search_orgs.called
        called_filters = mock_search_orgs.call_args[0][0]
        assert called_filters["locations"] == ["Ahmedabad", "Surat"]
        assert called_filters["employee_ranges"] == ["11-50"]

    # 4. Verify in DB that only 'valid-lead.com' was ingested and linked to search_id
    async with session_factory() as session:
        leads_stmt = select(Lead).where(
            Lead.org_id == org_id,
            Lead.domain.in_(["valid-lead.com", "excluded-competitor.com"]),
        )
        leads = (await session.execute(leads_stmt)).scalars().all()
        leads_by_domain = {l.domain: l for l in leads}

        assert "valid-lead.com" in leads_by_domain
        assert leads_by_domain["valid-lead.com"].search_id == search_id
        # 'excluded-competitor.com' must NOT have been ingested
        assert "excluded-competitor.com" not in leads_by_domain
