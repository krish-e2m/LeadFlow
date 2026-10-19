import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.constants import ApprovalStatus, PipelineStatus, RunStatus, RunType, ScoreBand, UserRole
from app.db.session import tenant_session
from app.main import app
from app.models.lead import Lead
from app.models.organization import Organization
from app.models.run import Run
from app.repositories.run_repo import RunRepository
from app.security.jwt import create_access_token
from app.services.quota_service import QuotaService
from app.services.search_service import SearchService


@pytest.mark.asyncio
async def test_request_correlation_and_security_headers():
    """Verify X-Request-ID tracking, security headers, and health endpoint cache control."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Automatic Request ID assignment
        resp1 = await client.get("/healthz")
        assert resp1.status_code == 200
        req_id1 = resp1.headers.get("X-Request-ID")
        assert req_id1 is not None and len(req_id1) >= 16
        assert resp1.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp1.headers.get("X-Frame-Options") == "DENY"
        assert "no-store" in resp1.headers.get("Cache-Control", "")

        # 2. Client-supplied Request ID preservation
        client_req_id = "test-custom-request-id-12345"
        resp2 = await client.get("/healthz", headers={"X-Request-ID": client_req_id})
        assert resp2.headers.get("X-Request-ID") == client_req_id


@pytest.mark.asyncio
async def test_readyz_readiness_probe():
    """Verify /readyz probe tests database connectivity."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/readyz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
        assert data["database"] == "connected"


@pytest.mark.asyncio
async def test_run_repository_stuck_run_recovery(admin_engine):
    """
    Verify RunRepository.recover_stuck_runs identifies runs that exceeded timeout,
    transitions them safely to FAILED with sanitized error notes, and leaves active runs intact.
    """
    admin_session_maker = async_sessionmaker(bind=admin_engine, class_=AsyncSession, expire_on_commit=False)
    org_id = uuid.uuid4()
    org_slug = f"stuck-org-{org_id.hex[:6]}"

    async with admin_session_maker() as admin_s:
        org = Organization(id=org_id, name="Stuck Test Org", slug=org_slug)
        admin_s.add(org)
        await admin_s.commit()

    try:
        now = datetime.now(timezone.utc)
        old_time = now - timedelta(seconds=7200)  # 2 hours ago

        async with admin_session_maker() as admin_s:
            # Run 1: Stuck RUNNING from 2 hours ago
            run1 = Run(
                id=uuid.uuid4(),
                org_id=org_id,
                run_type=RunType.SEARCH,
                status=RunStatus.RUNNING,
                progress_pct=25,
                started_at=old_time,
                created_at=old_time,
            )
            # Run 2: Fresh RUNNING just started 10 seconds ago
            run2 = Run(
                id=uuid.uuid4(),
                org_id=org_id,
                run_type=RunType.SEARCH,
                status=RunStatus.RUNNING,
                progress_pct=10,
                started_at=now - timedelta(seconds=10),
                created_at=now - timedelta(seconds=15),
            )
            admin_s.add_all([run1, run2])
            await admin_s.commit()

            # Execute recovery
            repo = RunRepository(admin_s)
            recovered = await repo.recover_stuck_runs(max_age_seconds=3600, org_id=org_id)
            await admin_s.commit()

            assert len(recovered) == 1
            assert recovered[0].id == run1.id
            assert recovered[0].status == RunStatus.FAILED
            assert "timed out" in recovered[0].error_details["error"].lower()
            assert recovered[0].completed_at is not None

            # Verify run2 is still RUNNING
            fresh_run = await repo.get_by_id(run2.id)
            assert fresh_run.status == RunStatus.RUNNING

    finally:
        async with admin_session_maker() as admin_s:
            await admin_s.execute(text("DELETE FROM orgs WHERE id = :oid"), {"oid": org_id})
            await admin_s.commit()


@pytest.mark.asyncio
async def test_stuck_run_polling_timeout_recovery(admin_engine):
    """
    Verify polling /runs/{id} automatically recovers a run that exceeded ARQ_JOB_TIMEOUT + 60,
    transitions it to FAILED, releases concurrent quota, and returns status without hanging.
    """
    admin_session_maker = async_sessionmaker(bind=admin_engine, class_=AsyncSession, expire_on_commit=False)
    org_id = uuid.uuid4()
    org_slug = f"poll-to-org-{org_id.hex[:6]}"

    async with admin_session_maker() as admin_s:
        org = Organization(id=org_id, name="Poll Timeout Org", slug=org_slug)
        admin_s.add(org)
        await admin_s.commit()

    try:
        old_time = datetime.now(timezone.utc) - timedelta(seconds=settings.ARQ_JOB_TIMEOUT + 120)
        run_id = uuid.uuid4()

        async with admin_session_maker() as admin_s:
            run = Run(
                id=run_id,
                org_id=org_id,
                run_type=RunType.SEARCH,
                status=RunStatus.RUNNING,
                progress_pct=30,
                started_at=old_time,
                created_at=old_time,
            )
            admin_s.add(run)
            await admin_s.commit()

        # Generate auth token for this org
        token = create_access_token(
            subject=str(uuid.uuid4()),
            org_id=str(org_id),
            role="admin",
            email="admin@polltest.com",
        )
        headers = {"Authorization": f"Bearer {token}"}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/v1/runs/{run_id}", headers=headers)
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "failed"
            assert "timed out" in data["error_details"]["error"].lower()

    finally:
        async with admin_session_maker() as admin_s:
            await admin_s.execute(text("DELETE FROM orgs WHERE id = :oid"), {"oid": org_id})
            await admin_s.commit()


@pytest.mark.asyncio
async def test_concurrent_run_reconciliation_unblocks_crashed_worker(admin_engine):
    """
    Verify that when Redis counter is stuck at limit (2) due to an abrupt worker termination,
    check_and_reserve_concurrent_run reconciles against DB active runs and unblocks new work.
    """
    admin_session_maker = async_sessionmaker(bind=admin_engine, class_=AsyncSession, expire_on_commit=False)
    org_id = uuid.uuid4()
    org_slug = f"reconcile-org-{org_id.hex[:6]}"

    async with admin_session_maker() as admin_s:
        org = Organization(id=org_id, name="Reconcile Org", slug=org_slug)
        admin_s.add(org)
        await admin_s.commit()

    try:
        # Mock Redis client with counter set to limit
        mock_redis = AsyncMock()
        mock_redis.incr.side_effect = [3, 1]  # First incr returns 3 (> limit=2), after reconcile returns 1
        mock_redis.set.return_value = True
        mock_redis.expire.return_value = True

        with patch("app.services.quota_service.get_redis_client", return_value=mock_redis):
            async with tenant_session(org_id) as session:
                # Should NOT raise 429 because DB has 0 active runs, so reconciliation succeeds!
                await QuotaService.check_and_reserve_concurrent_run(org_id, db=session)
                assert mock_redis.set.called

    finally:
        async with admin_session_maker() as admin_s:
            await admin_s.execute(text("DELETE FROM orgs WHERE id = :oid"), {"oid": org_id})
            await admin_s.commit()


@pytest.mark.asyncio
async def test_search_dispatch_failure_rolls_back_concurrent_quota(admin_engine):
    """
    Verify that if ARQ queue dispatch fails during initiate_search,
    the concurrent run reservation is rolled back, the run is marked FAILED, and 503 is raised.
    """
    admin_session_maker = async_sessionmaker(bind=admin_engine, class_=AsyncSession, expire_on_commit=False)
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    org_slug = f"dispatch-fail-{org_id.hex[:6]}"

    async with admin_session_maker() as admin_s:
        org = Organization(id=org_id, name="Dispatch Fail Org", slug=org_slug)
        admin_s.add(org)
        await admin_s.flush()
        from app.models.user import User
        from app.security.passwords import hash_password
        user = User(
            id=user_id,
            org_id=org_id,
            email=f"user-{user_id.hex[:6]}@dispatch.com",
            hashed_password=hash_password("Password123!"),
            role=UserRole.ORG_ADMIN,
            is_active=True,
        )
        admin_s.add(user)
        await admin_s.commit()

    try:
        async with tenant_session(org_id) as session:
            service = SearchService(session)

            with patch("app.services.search_service.create_pool", side_effect=Exception("Redis Connection Refused")), \
                 patch("app.services.quota_service.QuotaService.check_and_reserve_lead_ingestion", new_callable=AsyncMock), \
                 patch("app.services.quota_service.QuotaService.check_and_reserve_concurrent_run", new_callable=AsyncMock), \
                 patch("app.services.quota_service.QuotaService.release_concurrent_run", new_callable=AsyncMock) as mock_release:

                with pytest.raises(Exception) as exc_info:
                    await service.initiate_search(
                        org_id=org_id,
                        user_id=user_id,
                        name="Failing Search",
                        query_params={"domains": ["test.com"]},
                        limit=5,
                    )

                assert "503" in str(exc_info.value) or "Worker queue dispatch failed" in str(exc_info.value)
                assert mock_release.called

    finally:
        async with admin_session_maker() as admin_s:
            await admin_s.execute(text("DELETE FROM orgs WHERE id = :oid"), {"oid": org_id})
            await admin_s.commit()


@pytest.mark.asyncio
async def test_pagination_and_query_isolation_under_rls(admin_engine):
    """
    Verify pagination (skip, limit) and sorting work correctly under PostgreSQL RLS,
    and cross-tenant isolation prevents any record visibility across organizations.
    """
    admin_session_maker = async_sessionmaker(bind=admin_engine, class_=AsyncSession, expire_on_commit=False)
    org1_id = uuid.uuid4()
    org2_id = uuid.uuid4()

    async with admin_session_maker() as admin_s:
        org1 = Organization(id=org1_id, name="Org One", slug=f"org1-{org1_id.hex[:6]}")
        org2 = Organization(id=org2_id, name="Org Two", slug=f"org2-{org2_id.hex[:6]}")
        admin_s.add_all([org1, org2])
        await admin_s.commit()

    try:
        # Ingest 15 leads for org1 and 5 leads for org2
        async with admin_session_maker() as admin_s:
            leads1 = [
                Lead(
                    id=uuid.uuid4(),
                    org_id=org1_id,
                    domain=f"org1-lead-{i}.com",
                    company_name=f"Org1 Co {i}",
                    pipeline_status=PipelineStatus.SOURCED,
                    created_at=datetime.now(timezone.utc) - timedelta(minutes=i),
                )
                for i in range(15)
            ]
            leads2 = [
                Lead(
                    id=uuid.uuid4(),
                    org_id=org2_id,
                    domain=f"org2-lead-{i}.com",
                    company_name=f"Org2 Co {i}",
                    pipeline_status=PipelineStatus.SOURCED,
                    created_at=datetime.now(timezone.utc) - timedelta(minutes=i),
                )
                for i in range(5)
            ]
            admin_s.add_all(leads1 + leads2)
            await admin_s.commit()

        token1 = create_access_token(
            subject=str(uuid.uuid4()), org_id=str(org1_id), role=UserRole.ORG_ADMIN.value, email="a@org1.com"
        )
        headers1 = {"Authorization": f"Bearer {token1}"}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Page 1: limit=10, skip=0
            resp_p1 = await client.get("/api/v1/leads?skip=0&limit=10", headers=headers1)
            assert resp_p1.status_code == 200
            page1 = resp_p1.json()
            assert len(page1) == 10
            # Ensure none of org2's leads are present
            assert all("org1-lead-" in l["domain"] for l in page1)

            # Page 2: limit=10, skip=10
            resp_p2 = await client.get("/api/v1/leads?skip=10&limit=10", headers=headers1)
            assert resp_p2.status_code == 200
            page2 = resp_p2.json()
            assert len(page2) == 5
            assert all("org1-lead-" in l["domain"] for l in page2)

            # Cross-tenant check: no org2 leads leaked
            all_domains = {l["domain"] for l in page1 + page2}
            assert len(all_domains) == 15
            assert not any("org2-lead-" in d for d in all_domains)

    finally:
        async with admin_session_maker() as admin_s:
            await admin_s.execute(text("DELETE FROM orgs WHERE id IN (:o1, :o2)"), {"o1": org1_id, "o2": org2_id})
            await admin_s.commit()


@pytest.mark.asyncio
async def test_lead_quota_reconciliation_unblocks_stale_reservation(admin_engine):
    """
    Verify that if Redis has an inflated/stale lead quota counter (from past runs or crashed workers),
    QuotaService reconciles against genuine DB leads and in-flight active runs instead of falsely rejecting.
    """
    from app.security.session_store import get_redis_client
    from app.services.quota_service import QuotaService

    admin_session_maker = async_sessionmaker(bind=admin_engine, class_=AsyncSession, expire_on_commit=False)
    org_id = uuid.uuid4()

    async with admin_session_maker() as admin_s:
        org = Organization(id=org_id, name="Quota Test Org", slug=f"quota-{org_id.hex[:6]}")
        admin_s.add(org)
        await admin_s.commit()

    try:
        now = datetime.now(timezone.utc)
        r = get_redis_client()
        key = f"leadflow:quota:{org_id}:leads:{now.strftime('%Y-%m')}"

        # 1. Artificially inflate Redis reservation to 95 (simulating stale completed runs)
        await r.set(key, 95)

        # 2. Ingesting 25 leads would exceed 100 if stale Redis was not reconciled (95 + 25 = 120 > 100)
        async with admin_session_maker() as session:
            await QuotaService.check_and_reserve_lead_ingestion(org_id, 25, session)

        # 3. Redis should have reconciled to actual in-use (0) + 25 = 25
        val = await r.get(key)
        assert int(val) == 25

        # 4. Reconcile explicitly and verify it sets to 0
        async with admin_session_maker() as session:
            reconciled = await QuotaService.reconcile_lead_ingestion(org_id, session)
            assert reconciled == 0

        val_after = await r.get(key)
        assert int(val_after) == 0

    finally:
        async with admin_session_maker() as admin_s:
            await admin_s.execute(text("DELETE FROM orgs WHERE id = :oid"), {"oid": org_id})
            await admin_s.commit()

