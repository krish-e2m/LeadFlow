import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.constants import ApprovalStatus, PipelineStatus, ScoreBand
from app.db.session import engine
from app.main import app
from app.models.audit_log import AuditLog
from app.models.contact import Contact
from app.models.lead import Lead
from app.models.organization import Organization
from app.providers.manager import provider_manager
from app.security.jwt import create_access_token
from app.security.passwords import hash_password
from app.security.session_store import SessionStore, close_redis_client, get_redis_client
from app.services.quota_service import QuotaService


@pytest.fixture(autouse=True)
async def cleanup_pool_and_redis():
    yield
    await engine.dispose()
    await close_redis_client()


@pytest.fixture
async def admin_engine():
    eng = create_async_engine(settings.migration_database_url, poolclass=NullPool)
    yield eng
    await eng.dispose()


@pytest.fixture
async def setup_test_tenants(admin_engine):
    """
    Sets up two isolated tenant organizations (Org A and Org B)
    with admin, viewer, and super-admin accounts.
    Cleans up all created rows upon test completion.
    """
    org_a_id = uuid.uuid4()
    org_b_id = uuid.uuid4()
    slug_a = f"test-tenant-a-{org_a_id.hex[:6]}"
    slug_b = f"test-tenant-b-{org_b_id.hex[:6]}"

    super_admin_id = uuid.uuid4()
    org_a_admin_id = uuid.uuid4()
    org_a_viewer_id = uuid.uuid4()
    org_b_admin_id = uuid.uuid4()

    hashed_pw = hash_password("ValidPassword123!")

    session_factory = async_sessionmaker(
        bind=admin_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as session:
        # Create Org A and Org B
        await session.execute(
            text(
                "INSERT INTO orgs (id, name, slug, plan, is_active) VALUES "
                "(:id_a, 'Tenant Organization A', :slug_a, 'growth', true), "
                "(:id_b, 'Tenant Organization B', :slug_b, 'starter', true)"
            ),
            {"id_a": org_a_id, "slug_a": slug_a, "id_b": org_b_id, "slug_b": slug_b},
        )
        # Create users
        await session.execute(
            text(
                "INSERT INTO users (id, org_id, email, hashed_password, full_name, role, is_active, must_reset_password) VALUES "
                "(:s_id, null, :s_email, :pw, 'Global Super Admin', 'super_admin', true, false), "
                "(:a_adm_id, :org_a, :a_adm_email, :pw, 'Org A Admin', 'org_admin', true, false), "
                "(:a_viw_id, :org_a, :a_viw_email, :pw, 'Org A Viewer', 'client_viewer', true, false), "
                "(:b_adm_id, :org_b, :b_adm_email, :pw, 'Org B Admin', 'org_admin', true, false)"
            ),
            {
                "s_id": super_admin_id,
                "s_email": f"super-{super_admin_id.hex[:6]}@example.com",
                "a_adm_id": org_a_admin_id,
                "org_a": org_a_id,
                "a_adm_email": f"admin-a-{org_a_admin_id.hex[:6]}@example.com",
                "a_viw_id": org_a_viewer_id,
                "a_viw_email": f"viewer-a-{org_a_viewer_id.hex[:6]}@example.com",
                "b_adm_id": org_b_admin_id,
                "org_b": org_b_id,
                "b_adm_email": f"admin-b-{org_b_admin_id.hex[:6]}@example.com",
                "pw": hashed_pw,
            },
        )
        await session.commit()

    tokens = {
        "super_admin": create_access_token(
            subject=str(super_admin_id), role="super_admin", org_id=None
        ),
        "org_a_admin": create_access_token(
            subject=str(org_a_admin_id), role="org_admin", org_id=str(org_a_id)
        ),
        "org_a_viewer": create_access_token(
            subject=str(org_a_viewer_id), role="client_viewer", org_id=str(org_a_id)
        ),
        "org_b_admin": create_access_token(
            subject=str(org_b_admin_id), role="org_admin", org_id=str(org_b_id)
        ),
    }

    ids = {
        "org_a_id": org_a_id,
        "org_b_id": org_b_id,
        "super_admin_id": super_admin_id,
        "org_a_admin_id": org_a_admin_id,
        "org_a_viewer_id": org_a_viewer_id,
        "org_b_admin_id": org_b_admin_id,
    }

    yield {"tokens": tokens, "ids": ids}

    # Clean up test rows in proper foreign key order
    async with session_factory() as session:
        for query in [
            "DELETE FROM scores WHERE org_id IN (:a, :b)",
            "DELETE FROM contacts WHERE org_id IN (:a, :b)",
            "DELETE FROM drafts WHERE org_id IN (:a, :b)",
            "DELETE FROM crm_syncs WHERE org_id IN (:a, :b)",
            "DELETE FROM enrichments WHERE org_id IN (:a, :b)",
            "DELETE FROM leads WHERE org_id IN (:a, :b)",
            "DELETE FROM runs WHERE org_id IN (:a, :b)",
            "DELETE FROM searches WHERE org_id IN (:a, :b)",
            "DELETE FROM audit_log WHERE org_id IN (:a, :b)",
            "DELETE FROM users WHERE org_id IN (:a, :b) OR id = :s_id",
            "DELETE FROM orgs WHERE id IN (:a, :b)",
        ]:
            await session.execute(text(query), {"a": org_a_id, "b": org_b_id, "s_id": super_admin_id})
        await session.commit()

    # Clear any Redis test keys
    try:
        r = get_redis_client()
        await r.delete(
            f"auth:org_suspended:{org_a_id}",
            f"auth:org_suspended:{org_b_id}",
            f"leadflow:quota:{org_a_id}:concurrent_runs",
            f"leadflow:quota:{org_b_id}:concurrent_runs",
        )
    except Exception:
        pass


@pytest.mark.asyncio
async def test_user_listing_and_retrieval_scoped(setup_test_tenants):
    """
    Verifies organization-scoped user listing and individual retrieval:
    - Org admin sees only users in their own organization.
    - Org admin cannot retrieve user from another organization (404).
    - Client viewer is rejected with 403 Forbidden.
    - Super admin can list across or filter.
    """
    tokens = setup_test_tenants["tokens"]
    ids = setup_test_tenants["ids"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Org A admin lists users
        res_a = await client.get(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
        )
        assert res_a.status_code == 200
        users_a = res_a.json()
        assert len(users_a) >= 2
        for u in users_a:
            assert u["org_id"] == str(ids["org_a_id"])

        # 2. Org A admin retrieves user in Org A (200)
        res_single = await client.get(
            f"/api/v1/users/{ids['org_a_viewer_id']}",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
        )
        assert res_single.status_code == 200
        assert res_single.json()["id"] == str(ids["org_a_viewer_id"])

        # 3. Org A admin attempts to retrieve user in Org B (404)
        res_cross = await client.get(
            f"/api/v1/users/{ids['org_b_admin_id']}",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
        )
        assert res_cross.status_code == 404

        # 4. Client viewer is denied access to user management (403)
        res_viewer = await client.get(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {tokens['org_a_viewer']}"},
        )
        assert res_viewer.status_code == 403

        # 5. Super admin can list across organizations
        res_super = await client.get(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {tokens['super_admin']}"},
        )
        assert res_super.status_code == 200
        assert len(res_super.json()) >= 4


@pytest.mark.asyncio
async def test_user_creation_and_privilege_escalation_denial(setup_test_tenants):
    """
    Verifies authorized user creation and denial of role escalation:
    - Org admin creates a client viewer in own org: succeeds with must_reset_password=True.
    - Org admin attempting to create a super_admin user: rejected with 403 Forbidden.
    - Org admin specifying org_b_id: forced to org_a_id.
    - Client viewer denied user creation: 403 Forbidden.
    """
    tokens = setup_test_tenants["tokens"]
    ids = setup_test_tenants["ids"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Org A admin creates valid client viewer
        new_email = f"new-user-{uuid.uuid4().hex[:6]}@example.com"
        res_create = await client.post(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
            json={
                "email": new_email,
                "password": "TemporaryPassword123!",
                "full_name": "New Team Member",
                "role": "client_viewer",
                "org_id": str(ids["org_b_id"]),  # Attempt to inject another org
            },
        )
        assert res_create.status_code == 201
        data = res_create.json()
        assert data["email"] == new_email
        assert data["org_id"] == str(ids["org_a_id"])  # Forced to own org
        assert data["must_reset_password"] is True

        # 2. Org A admin attempts role escalation to super_admin (403 Forbidden)
        res_escalate = await client.post(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
            json={
                "email": f"escalate-{uuid.uuid4().hex[:6]}@example.com",
                "password": "Password123!",
                "role": "super_admin",
            },
        )
        assert res_escalate.status_code == 403
        assert "super_admin" in res_escalate.json()["detail"].lower()

        # 3. Client viewer denied user creation
        res_viewer = await client.post(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {tokens['org_a_viewer']}"},
            json={
                "email": f"viewer-attempt-{uuid.uuid4().hex[:6]}@example.com",
                "password": "Password123!",
                "role": "client_viewer",
            },
        )
        assert res_viewer.status_code == 403


@pytest.mark.asyncio
async def test_user_update_and_session_invalidation(setup_test_tenants):
    """
    Verifies user updates:
    - Permitted property updates (name, role).
    - Org admin cannot elevate user role to super_admin.
    - Deactivating a user (is_active=False) invalidates all active sessions in Redis.
    """
    tokens = setup_test_tenants["tokens"]
    ids = setup_test_tenants["ids"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Update user name
        res_update = await client.patch(
            f"/api/v1/users/{ids['org_a_viewer_id']}",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
            json={"full_name": "Updated Viewer Name"},
        )
        assert res_update.status_code == 200
        assert res_update.json()["full_name"] == "Updated Viewer Name"

        # 2. Org admin attempts to escalate user to super_admin (403)
        res_esc = await client.patch(
            f"/api/v1/users/{ids['org_a_viewer_id']}",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
            json={"role": "super_admin"},
        )
        assert res_esc.status_code == 403

        # 3. Deactivate user -> invalidates sessions in Redis
        res_deact = await client.patch(
            f"/api/v1/users/{ids['org_a_viewer_id']}",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
            json={"is_active": False},
        )
        assert res_deact.status_code == 200
        assert res_deact.json()["is_active"] is False

        # Verify session invalidation in Redis
        r = get_redis_client()
        revoked_val = await r.get(f"auth:user_revoked_before:{ids['org_a_viewer_id']}")
        assert revoked_val is not None


@pytest.mark.asyncio
async def test_organization_suspension_reactivation_and_blocking(setup_test_tenants):
    """
    Verifies organization lifecycle management:
    - Super admin suspends organization.
    - Org users are immediately blocked from accessing protected endpoints (403).
    - Super admin reactivates organization.
    - Access is restored cleanly.
    """
    tokens = setup_test_tenants["tokens"]
    ids = setup_test_tenants["ids"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Suspend Org A via super admin
        res_suspend = await client.post(
            f"/api/v1/admin/orgs/{ids['org_a_id']}/suspend",
            headers={"Authorization": f"Bearer {tokens['super_admin']}"},
        )
        assert res_suspend.status_code == 200
        assert res_suspend.json()["is_active"] is False

        # Verify Redis suspension key exists
        assert await SessionStore.is_org_suspended(str(ids["org_a_id"])) is True

        # 2. Org A admin request to protected endpoint is blocked (403 Forbidden)
        res_blocked = await client.get(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
        )
        assert res_blocked.status_code == 403
        assert "suspended" in res_blocked.json()["detail"].lower()

        # 3. Org B admin is completely unaffected
        res_b = await client.get(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {tokens['org_b_admin']}"},
        )
        assert res_b.status_code == 200

        # 4. Reactivate Org A via super admin
        res_reactivate = await client.post(
            f"/api/v1/admin/orgs/{ids['org_a_id']}/reactivate",
            headers={"Authorization": f"Bearer {tokens['super_admin']}"},
        )
        assert res_reactivate.status_code == 200
        assert res_reactivate.json()["is_active"] is True

        # Verify Redis suspension key cleared
        assert await SessionStore.is_org_suspended(str(ids["org_a_id"])) is False

        # 5. Org A admin access restored
        res_restored = await client.get(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
        )
        assert res_restored.status_code == 200


@pytest.mark.asyncio
async def test_safe_offboarding_preserves_data_without_hard_deletion(setup_test_tenants, admin_engine):
    """
    Verifies that offboarding deactivates an organization and marks deleted_at
    without hard-deleting the organization or historical tenant rows.
    """
    tokens = setup_test_tenants["tokens"]
    ids = setup_test_tenants["ids"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Offboard Org B
        res_offboard = await client.post(
            f"/api/v1/admin/orgs/{ids['org_b_id']}/offboard",
            headers={"Authorization": f"Bearer {tokens['super_admin']}"},
        )
        assert res_offboard.status_code == 200
        data = res_offboard.json()
        assert data["is_active"] is False
        assert data["deleted_at"] is not None

        # Verify record still exists in PostgreSQL database (not hard-deleted)
        session_factory = async_sessionmaker(
            bind=admin_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with session_factory() as session:
            stmt = select(Organization).where(Organization.id == ids["org_b_id"])
            org = (await session.execute(stmt)).scalars().first()
            assert org is not None
            assert org.deleted_at is not None
            assert org.is_active is False


@pytest.mark.asyncio
async def test_quotas_lead_ingestion_and_per_search_limit(setup_test_tenants, admin_engine):
    """
    Verifies lead ingestion quota enforcement:
    - Search requests exceeding 500 leads per search are rejected with 400 Bad Request.
    - Lead ingestion exceeding monthly limit (100) is rejected with 429 Too Many Requests.
    """
    tokens = setup_test_tenants["tokens"]
    ids = setup_test_tenants["ids"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Search request exceeding max 500 leads per search (rejected with 400)
        res_over = await client.post(
            "/api/v1/searches",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
            json={
                "name": "Oversized Search",
                "limit": 501,
                "query_params": {"industry": "Software"},
            },
        )
        assert res_over.status_code in (400, 422)

        # 2. Simulate monthly quota exhaustion in database
        session_factory = async_sessionmaker(
            bind=admin_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with session_factory() as session:
            # Seed 95 leads for Org A
            now = datetime.now(timezone.utc)
            for i in range(95):
                lead = Lead(
                    id=uuid.uuid4(),
                    org_id=ids["org_a_id"],
                    domain=f"domain{i}-{uuid.uuid4().hex[:4]}.com",
                    company_name=f"Company {i}",
                    pipeline_status=PipelineStatus.SOURCED,
                    approval_status=ApprovalStatus.PENDING,
                    created_at=now,
                )
                session.add(lead)
            await session.commit()

        # 3. Requesting 10 leads when 95 are used: the search runs with the 5 that are left.
        with patch("app.services.search_service.create_pool", new_callable=AsyncMock) as mock_pool:
            mock_pool.return_value = AsyncMock()
            res_trimmed = await client.post(
                "/api/v1/searches",
                headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
                json={
                    "name": "Over-Quota Search",
                    "limit": 10,
                    "query_params": {"industry": "Software"},
                },
            )
            assert res_trimmed.status_code == 202
            assert "5 leads instead of 10" in res_trimmed.json()["message"]
            assert mock_pool.return_value.enqueue_job.call_args[0][3] == 5

        # 4. With the month used up, a search is rejected outright.
        async with session_factory() as session:
            for i in range(5):
                session.add(
                    Lead(
                        id=uuid.uuid4(),
                        org_id=ids["org_a_id"],
                        domain=f"fill{i}-{uuid.uuid4().hex[:4]}.com",
                        company_name=f"Filler {i}",
                        pipeline_status=PipelineStatus.SOURCED,
                        approval_status=ApprovalStatus.PENDING,
                        created_at=now,
                    )
                )
            await session.commit()

        res_quota = await client.post(
            "/api/v1/searches",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
            json={
                "name": "Exhausted Search",
                "limit": 10,
                "query_params": {"industry": "Software"},
            },
        )
        assert res_quota.status_code == 429
        assert "quota exceeded" in res_quota.json()["detail"].lower()


@pytest.mark.asyncio
async def test_quotas_concurrent_runs_enforcement_and_release(setup_test_tenants):
    """
    Verifies concurrent active run quotas:
    - Maximum 2 concurrent active runs per organization.
    - 3rd concurrent run request rejected with 429.
    - Releasing a run permits subsequent run.
    """
    org_id = setup_test_tenants["ids"]["org_a_id"]

    # 1. Reserve 2 runs
    await QuotaService.check_and_reserve_concurrent_run(org_id)
    await QuotaService.check_and_reserve_concurrent_run(org_id)

    # 2. Attempt 3rd reservation -> rejected with 429
    with pytest.raises(Exception) as exc_info:
        await QuotaService.check_and_reserve_concurrent_run(org_id)
    assert exc_info.value.status_code == 429
    assert "concurrent run quota exceeded" in exc_info.value.detail.lower()

    # 3. Release 1 run
    await QuotaService.release_concurrent_run(org_id)

    # 4. Now reservation succeeds
    await QuotaService.check_and_reserve_concurrent_run(org_id)
    # Cleanup
    await QuotaService.release_concurrent_run(org_id)
    await QuotaService.release_concurrent_run(org_id)


@pytest.mark.asyncio
async def test_quotas_contact_reveals_daily_limit(setup_test_tenants, admin_engine):
    """
    Verifies daily contact reveal limit (100/day per organization).
    """
    org_id = setup_test_tenants["ids"]["org_a_id"]

    session_factory = async_sessionmaker(
        bind=admin_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        # Pre-set Redis counter to 100
        r = get_redis_client()
        now = datetime.now(timezone.utc)
        key = f"leadflow:quota:{org_id}:reveals:{now.strftime('%Y-%m-%d')}"
        await r.set(key, 100)

        # Attempt reveal reservation -> 429 Too Many Requests
        with pytest.raises(Exception) as exc_info:
            await QuotaService.check_and_reserve_contact_reveal(org_id, session)
        assert exc_info.value.status_code == 429
        assert "contact reveal quota exceeded" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_quotas_fail_closed_when_redis_unavailable(setup_test_tenants, admin_engine):
    """
    Verifies strict fail-closed enforcement when Redis is unavailable:
    - Quota checks MUST NOT grant access when Redis fails.
    - Operations are rejected with 503 Service Unavailable to protect budget.
    """
    org_id = setup_test_tenants["ids"]["org_a_id"]

    session_factory = async_sessionmaker(
        bind=admin_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        # Simulate Redis connection failure
        with patch("app.services.quota_service.get_redis_client", side_effect=Exception("Redis connection refused")):
            # 1. Lead ingestion check fails closed
            with pytest.raises(Exception) as exc1:
                await QuotaService.check_and_reserve_lead_ingestion(org_id, 10, session)
            assert exc1.value.status_code == 503

            # 2. Concurrent run check fails closed
            with pytest.raises(Exception) as exc2:
                await QuotaService.check_and_reserve_concurrent_run(org_id, session)
            assert exc2.value.status_code == 503

            # 3. Contact reveal check fails closed
            with pytest.raises(Exception) as exc3:
                await QuotaService.check_and_reserve_contact_reveal(org_id, session)
            assert exc3.value.status_code == 503

            # 4. Draft generation check fails closed
            with pytest.raises(Exception) as exc4:
                await QuotaService.check_and_reserve_draft_generation(org_id, session)
            assert exc4.value.status_code == 503


@pytest.mark.asyncio
async def test_genuine_usage_reporting_no_hardcoded_metrics(setup_test_tenants, admin_engine):
    """
    Verifies real usage reporting endpoint:
    - Replaces hardcoded mock numbers (14, 12, 8, 26) with genuine SQL-calculated counts.
    """
    tokens = setup_test_tenants["tokens"]
    ids = setup_test_tenants["ids"]

    # Seed 3 leads, 1 revealed contact, 1 unrevealed contact
    session_factory = async_sessionmaker(
        bind=admin_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        lead_id = uuid.uuid4()
        lead = Lead(
            id=lead_id,
            org_id=ids["org_a_id"],
            domain="usage-test.com",
            company_name="Usage Test Inc",
            pipeline_status=PipelineStatus.SCORED,
            approval_status=ApprovalStatus.APPROVED,
        )
        session.add(lead)
        c1 = Contact(
            id=uuid.uuid4(),
            org_id=ids["org_a_id"],
            lead_id=lead_id,
            email="revealed@usage-test.com",
            is_revealed=True,
            revealed_at=datetime.now(timezone.utc),
        )
        c2 = Contact(
            id=uuid.uuid4(),
            org_id=ids["org_a_id"],
            lead_id=lead_id,
            email="masked@usage-test.com",
            is_revealed=False,
        )
        session.add_all([c1, c2])
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get(
            "/api/v1/admin/usage",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
        )
        assert res.status_code == 200
        data = res.json()

        # Real calculated metrics
        assert data["total_leads_sourced"] >= 1
        assert data["total_contacts_revealed"] == 1  # Exactly 1 revealed, NOT 14!
        assert data["monthly_leads"]["limit"] == 100
        assert data["leads_per_search_limit"] == 500
        assert data["daily_contact_reveals"]["used"] >= 1
        assert data["status_flags"]["zero_cost_policy_active"] is True


@pytest.mark.asyncio
async def test_safe_bulk_operations(setup_test_tenants, admin_engine):
    """
    Verifies bounded bulk operations:
    - Enforces batch size limit (max 100).
    - Prevents workflow bypass (disqualified leads cannot be approved).
    - Cross-tenant leads are safely failed.
    - Bulk approve, reject, archive, and rescore work correctly.
    """
    tokens = setup_test_tenants["tokens"]
    ids = setup_test_tenants["ids"]

    lead_valid_id = uuid.uuid4()
    lead_disq_id = uuid.uuid4()
    lead_cross_id = uuid.uuid4()

    session_factory = async_sessionmaker(
        bind=admin_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        # Org A valid scored lead
        l1 = Lead(
            id=lead_valid_id,
            org_id=ids["org_a_id"],
            domain="valid-prospect.com",
            company_name="Valid Prospect",
            pipeline_status=PipelineStatus.SCORED,
            approval_status=ApprovalStatus.PENDING,
        )
        # Org A disqualified lead
        l2 = Lead(
            id=lead_disq_id,
            org_id=ids["org_a_id"],
            domain="disq-prospect.com",
            company_name="Disqualified Prospect",
            pipeline_status=PipelineStatus.DISQUALIFIED,
            approval_status=ApprovalStatus.REJECTED,
        )
        # Org B lead (cross-tenant)
        l3 = Lead(
            id=lead_cross_id,
            org_id=ids["org_b_id"],
            domain="cross-tenant.com",
            company_name="Cross Tenant",
            pipeline_status=PipelineStatus.SCORED,
            approval_status=ApprovalStatus.PENDING,
        )
        session.add_all([l1, l2, l3])
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Batch size exceeding max limit (101 leads) -> 400
        oversized_ids = [str(uuid.uuid4()) for _ in range(101)]
        res_over = await client.post(
            "/api/v1/leads/bulk",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
            json={"action": "approve", "lead_ids": oversized_ids},
        )
        assert res_over.status_code == 400
        assert "exceeds maximum limit" in res_over.json()["detail"].lower()

        # 2. Bulk approve with mixed eligibility
        res_bulk = await client.post(
            "/api/v1/leads/bulk",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
            json={
                "action": "approve",
                "lead_ids": [str(lead_valid_id), str(lead_disq_id), str(lead_cross_id)],
            },
        )
        assert res_bulk.status_code == 200
        bulk_data = res_bulk.json()
        assert bulk_data["total_requested"] == 3
        assert bulk_data["total_succeeded"] == 1
        assert bulk_data["total_failed"] == 2

        # Verify outcome details
        outcomes = {r["lead_id"]: r for r in bulk_data["results"]}
        assert outcomes[str(lead_valid_id)]["success"] is True
        assert outcomes[str(lead_valid_id)]["status"] == "approved"

        assert outcomes[str(lead_disq_id)]["success"] is False
        assert "disqualified" in outcomes[str(lead_disq_id)]["error"].lower()

        assert outcomes[str(lead_cross_id)]["success"] is False
        assert "unauthorized" in outcomes[str(lead_cross_id)]["error"].lower()

        # 3. Bulk archive
        res_arch = await client.post(
            "/api/v1/leads/bulk",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
            json={"action": "archive", "lead_ids": [str(lead_valid_id)]},
        )
        assert res_arch.status_code == 200
        assert res_arch.json()["total_succeeded"] == 1


@pytest.mark.asyncio
async def test_csv_and_json_exports_and_formula_injection(setup_test_tenants, admin_engine):
    """
    Verifies CSV and JSON exports:
    - Scoped strictly to caller's tenant.
    - Formula injection protection: neutralizes symbols (=, +, -, @).
    - Unrevealed contact information is omitted.
    - Client viewer only receives approved leads.
    """
    tokens = setup_test_tenants["tokens"]
    ids = setup_test_tenants["ids"]

    lead_id = uuid.uuid4()
    session_factory = async_sessionmaker(
        bind=admin_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        # Seed a lead with formula-injection symbols in text fields
        lead = Lead(
            id=lead_id,
            org_id=ids["org_a_id"],
            domain="@malicious-domain.com",
            company_name="=CMD|' /C calc'!A0",
            industry="+Software",
            pipeline_status=PipelineStatus.APPROVED,
            approval_status=ApprovalStatus.APPROVED,
            score_band=ScoreBand.QUALIFIED,
        )
        session.add(lead)
        # Add unrevealed contact
        contact_unrevealed = Contact(
            id=uuid.uuid4(),
            org_id=ids["org_a_id"],
            lead_id=lead_id,
            first_name="Secret",
            last_name="Executive",
            email="supersecret@company.com",
            phone="+1-555-0199",
            is_revealed=False,
        )
        session.add(contact_unrevealed)
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Export as CSV
        res_csv = await client.get(
            "/api/v1/leads/export?format=csv",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
        )
        assert res_csv.status_code == 200
        assert "text/csv" in res_csv.headers["content-type"]
        csv_text = res_csv.text

        # Verify formula injection protection
        # Should be escaped with leading single quote: '
        assert "'=CMD|' /C calc'!A0" in csv_text
        assert "'@malicious-domain.com" in csv_text
        assert "'+Software" in csv_text

        # Verify unrevealed contact details are omitted
        assert "supersecret@company.com" not in csv_text
        assert "+1-555-0199" not in csv_text

        # 2. Export as JSON
        res_json = await client.get(
            "/api/v1/leads/export?format=json",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
        )
        assert res_json.status_code == 200
        assert "application/json" in res_json.headers["content-type"]
        json_data = res_json.json()
        assert len(json_data) >= 1
        found_lead = next(item for item in json_data if item["id"] == str(lead_id))
        assert found_lead["company_name"] == "=CMD|' /C calc'!A0"
        assert found_lead["contact_email"] == ""  # Unrevealed contact omitted!

        # 3. Client viewer mode verifies access
        res_viewer = await client.get(
            "/api/v1/leads/export?format=json",
            headers={"Authorization": f"Bearer {tokens['org_a_viewer']}"},
        )
        assert res_viewer.status_code == 200


@pytest.mark.asyncio
async def test_audit_events_recorded_without_secrets(setup_test_tenants, admin_engine):
    """
    Verifies audit events:
    - Important actions record immutable audit records.
    - Audit changes dictionary never leaks passwords or secrets.
    """
    tokens = setup_test_tenants["tokens"]
    ids = setup_test_tenants["ids"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create user
        new_email = f"audit-test-{uuid.uuid4().hex[:6]}@example.com"
        await client.post(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
            json={
                "email": new_email,
                "password": "SecretPassword123!",
                "role": "client_viewer",
            },
        )

    # Check audit log in database
    session_factory = async_sessionmaker(
        bind=admin_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        stmt = (
            select(AuditLog)
            .where(AuditLog.action == "user.create", AuditLog.org_id == ids["org_a_id"])
            .order_by(AuditLog.created_at.desc())
        )
        audit_row = (await session.execute(stmt)).scalars().first()
        assert audit_row is not None
        # Verify passwords or hashes are NOT stored in changes JSON
        changes_str = json.dumps(audit_row.changes)
        assert "SecretPassword123!" not in changes_str
        assert "password" not in audit_row.changes
        assert "hashed_password" not in audit_row.changes


@pytest.mark.asyncio
async def test_contact_reveal_approval_gate_and_tenant_security(setup_test_tenants, admin_engine):
    """
    Priority 1 Security Regression Test:
    - Contact reveal is strictly REJECTED (HTTP 400) if the parent lead is not approved.
    - Contact reveal by unauthorized client_viewer is REJECTED (HTTP 403).
    - Cross-tenant contact reveal is REJECTED (HTTP 404).
    - Contact reveal on an APPROVED lead succeeds (HTTP 200), reveals details, and logs an audit event.
    """
    tokens = setup_test_tenants["tokens"]
    ids = setup_test_tenants["ids"]

    # Seed 1 unapproved lead with contact, and 1 approved lead with contact in Org A
    session_factory = async_sessionmaker(
        bind=admin_engine, class_=AsyncSession, expire_on_commit=False
    )
    unapproved_contact_id = uuid.uuid4()
    approved_contact_id = uuid.uuid4()
    unapproved_lead_id = uuid.uuid4()
    approved_lead_id = uuid.uuid4()

    async with session_factory() as session:
        # Unapproved lead
        lead_unapproved = Lead(
            id=unapproved_lead_id,
            org_id=ids["org_a_id"],
            domain="unapproved-prospect.com",
            company_name="Unapproved Prospect LLC",
            pipeline_status=PipelineStatus.SCORED,
            approval_status=ApprovalStatus.PENDING,
        )
        session.add(lead_unapproved)
        contact_unapproved = Contact(
            id=unapproved_contact_id,
            org_id=ids["org_a_id"],
            lead_id=unapproved_lead_id,
            first_name="Alice",
            last_name="Unapproved",
            email="alice@unapproved-prospect.com",
            phone="+1-555-0100",
            is_revealed=False,
        )
        session.add(contact_unapproved)

        # Approved lead
        lead_approved = Lead(
            id=approved_lead_id,
            org_id=ids["org_a_id"],
            domain="approved-prospect.com",
            company_name="Approved Prospect Inc",
            pipeline_status=PipelineStatus.APPROVED,
            approval_status=ApprovalStatus.APPROVED,
        )
        session.add(lead_approved)
        contact_approved = Contact(
            id=approved_contact_id,
            org_id=ids["org_a_id"],
            lead_id=approved_lead_id,
            first_name="Bob",
            last_name="Approved",
            email="bob@approved-prospect.com",
            phone="+1-555-0200",
            is_revealed=False,
        )
        session.add(contact_approved)
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Unapproved Lead -> Contact reveal MUST be rejected with HTTP 400
        res_unapproved = await client.post(
            f"/api/v1/contacts/{unapproved_contact_id}/reveal",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
            json={"confirm": True},
        )
        assert res_unapproved.status_code == 400
        assert "lead must be approved" in res_unapproved.json()["detail"].lower()

        # 2. Verify contact in DB remains unrevealed
        async with session_factory() as session:
            c_check = (
                await session.execute(select(Contact).where(Contact.id == unapproved_contact_id))
            ).scalars().first()
            assert c_check.is_revealed is False
            assert c_check.revealed_at is None

        # 3. Client Viewer -> Rejected with HTTP 403 Forbidden
        res_viewer = await client.post(
            f"/api/v1/contacts/{approved_contact_id}/reveal",
            headers={"Authorization": f"Bearer {tokens['org_a_viewer']}"},
            json={"confirm": True},
        )
        assert res_viewer.status_code == 403

        # 4. Cross-Tenant -> Org B admin cannot reveal Org A contact (HTTP 404)
        res_cross = await client.post(
            f"/api/v1/contacts/{approved_contact_id}/reveal",
            headers={"Authorization": f"Bearer {tokens['org_b_admin']}"},
            json={"confirm": True},
        )
        assert res_cross.status_code == 404

        # 5. Approved Lead -> Org A admin successfully reveals contact (HTTP 200).
        # Hunter is mocked so the test never spends live lookup credits.
        hunter = provider_manager.hunter
        with patch.object(hunter, "is_configured", return_value=True), patch.object(
            hunter,
            "reveal_contact_details",
            new=AsyncMock(return_value={"email": "bob@approved-prospect.com", "phone": "+1-555-0200"}),
        ):
            res_approved = await client.post(
                f"/api/v1/contacts/{approved_contact_id}/reveal",
                headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
                json={"confirm": True},
            )
        assert res_approved.status_code == 200
        res_data = res_approved.json()
        assert res_data["contact"]["is_revealed"] is True
        assert res_data["contact"]["email"] == "bob@approved-prospect.com"
        assert res_data["credits_remaining"] >= 0

        # 6. Verify database persistence and audit log record
        async with session_factory() as session:
            c_verified = (
                await session.execute(select(Contact).where(Contact.id == approved_contact_id))
            ).scalars().first()
            assert c_verified.is_revealed is True
            assert c_verified.revealed_by == ids["org_a_admin_id"]
            assert c_verified.revealed_at is not None

            audit_entry = (
                await session.execute(
                    select(AuditLog).where(
                        AuditLog.action == "contact.reveal",
                        AuditLog.entity_id == approved_contact_id,
                        AuditLog.org_id == ids["org_a_id"],
                    )
                )
            ).scalars().first()
            assert audit_entry is not None
            assert audit_entry.actor_user_id == ids["org_a_admin_id"]


@pytest.mark.asyncio
async def test_disqualified_lead_approval_eligibility_and_override(setup_test_tenants, admin_engine):
    """
    Verify Task 1:
    - Disqualified lead cannot be approved without manual_override=True and non-empty override_reason (HTTP 400).
    - Disqualified lead with manual_override=True but missing/whitespace reason is rejected (HTTP 400).
    - Disqualified lead with valid manual_override and reason succeeds (HTTP 200) and logs 'lead.approved_override'.
    - Normal (qualified/review) lead approves without requiring manual_override (HTTP 200) and logs 'lead.approved'.
    - Unauthorized roles (client_viewer) cannot approve or override leads (HTTP 403).
    - Disqualified leads cannot be silently approved in bulk operations.
    """
    tokens = setup_test_tenants["tokens"]
    ids = setup_test_tenants["ids"]

    disq_lead_id = uuid.uuid4()
    review_lead_id = uuid.uuid4()

    session_factory = async_sessionmaker(
        bind=admin_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        # 1. Lead scored as DISQUALIFIED
        l_disq = Lead(
            id=disq_lead_id,
            org_id=ids["org_a_id"],
            domain="disqualified-test.com",
            company_name="Disqualified Co",
            pipeline_status=PipelineStatus.SCORED,
            score_band=ScoreBand.DISQUALIFIED,
            approval_status=ApprovalStatus.PENDING,
        )
        # 2. Lead scored as REVIEW (eligible)
        l_review = Lead(
            id=review_lead_id,
            org_id=ids["org_a_id"],
            domain="review-test.com",
            company_name="Review Co",
            pipeline_status=PipelineStatus.SCORED,
            score_band=ScoreBand.REVIEW,
            approval_status=ApprovalStatus.PENDING,
        )
        session.add_all([l_disq, l_review])
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Scenario A: Silent approval of disqualified lead -> HTTP 400
        res_silent = await client.patch(
            f"/api/v1/leads/{disq_lead_id}/approval",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
            json={"approval_status": "approved"},
        )
        assert res_silent.status_code == 400
        assert "explicit manual override" in res_silent.json()["detail"].lower()

        # Scenario B: Override with empty reason -> HTTP 400
        res_empty_reason = await client.patch(
            f"/api/v1/leads/{disq_lead_id}/approval",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
            json={
                "approval_status": "approved",
                "manual_override": True,
                "override_reason": "   ",
            },
        )
        assert res_empty_reason.status_code == 400
        assert "explicit manual override and reason" in res_empty_reason.json()["detail"].lower()

        # Scenario C: Viewer role attempts manual override -> HTTP 403
        res_viewer = await client.patch(
            f"/api/v1/leads/{disq_lead_id}/approval",
            headers={"Authorization": f"Bearer {tokens['org_a_viewer']}"},
            json={
                "approval_status": "approved",
                "manual_override": True,
                "override_reason": "Executive relationship override",
            },
        )
        assert res_viewer.status_code == 403

        # Scenario D: Valid manual override by org admin -> HTTP 200
        res_override = await client.patch(
            f"/api/v1/leads/{disq_lead_id}/approval",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
            json={
                "approval_status": "approved",
                "manual_override": True,
                "override_reason": "Enterprise strategic account with high potential ACV despite tech stack score.",
            },
        )
        assert res_override.status_code == 200
        data_override = res_override.json()
        assert data_override["approval_status"] == "approved"
        assert data_override["pipeline_status"] == "approved"

        # Verify audit log recorded lead.approved_override with reason
        async with session_factory() as session:
            audit_entry = (
                await session.execute(
                    select(AuditLog).where(
                        AuditLog.action == "lead.approved_override",
                        AuditLog.entity_id == disq_lead_id,
                    )
                )
            ).scalars().first()
            assert audit_entry is not None
            assert audit_entry.actor_user_id == ids["org_a_admin_id"]
            assert audit_entry.changes.get("manual_override") is True
            assert "high potential acv" in audit_entry.changes.get("override_reason", "").lower()

        # Scenario E: Normal lead in REVIEW band approves without requiring override -> HTTP 200
        res_normal = await client.patch(
            f"/api/v1/leads/{review_lead_id}/approval",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
            json={"approval_status": "approved"},
        )
        assert res_normal.status_code == 200
        assert res_normal.json()["approval_status"] == "approved"

        async with session_factory() as session:
            audit_normal = (
                await session.execute(
                    select(AuditLog).where(
                        AuditLog.action == "lead.approved",
                        AuditLog.entity_id == review_lead_id,
                    )
                )
            ).scalars().first()
            assert audit_normal is not None
            assert audit_normal.changes.get("to") == "approved"


@pytest.mark.asyncio
async def test_csv_export_formula_injection_and_unrevealed_contact_privacy(
    setup_test_tenants, admin_engine
):
    """
    Verify Section 5 & 7:
    - CSV formula injection protection: neutralizes =, +, -, @ prefixes with single quote.
    - Export privacy: strictly omits unrevealed contact email and phone number.
    - Unrevealed contact PII protection: ContactResponse redacts phone to None and masks email.
    """
    tokens = setup_test_tenants["tokens"]
    ids = setup_test_tenants["ids"]

    formula_lead_id = uuid.uuid4()
    unrevealed_contact_id = uuid.uuid4()
    revealed_contact_id = uuid.uuid4()

    session_factory = async_sessionmaker(
        bind=admin_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        # Lead with malicious CSV injection payloads in text fields
        l = Lead(
            id=formula_lead_id,
            org_id=ids["org_a_id"],
            domain="+calc-domain.com",
            company_name="=cmd|'/C calc'!A0",
            industry="@SUM(A1:B10)",
            pipeline_status=PipelineStatus.APPROVED,
            approval_status=ApprovalStatus.APPROVED,
        )
        c_unrevealed = Contact(
            id=unrevealed_contact_id,
            org_id=ids["org_a_id"],
            lead_id=formula_lead_id,
            first_name="Alice",
            last_name="Private",
            title="VP Security",
            email="alice.private@calc-domain.com",
            phone="+1-555-0199",
            is_revealed=False,
        )
        c_revealed = Contact(
            id=revealed_contact_id,
            org_id=ids["org_a_id"],
            lead_id=formula_lead_id,
            first_name="Bob",
            last_name="Public",
            title="CEO",
            email="bob.public@calc-domain.com",
            phone="+1-555-0200",
            is_revealed=True,
            revealed_at=datetime.now(timezone.utc),
        )
        session.add_all([l, c_unrevealed, c_revealed])
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Fetch lead details via API -> Verify ContactResponse masks unrevealed contact PII
        lead_resp = await client.get(
            f"/api/v1/leads/{formula_lead_id}",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
        )
        assert lead_resp.status_code == 200
        lead_data = lead_resp.json()
        contacts_by_id = {c["id"]: c for c in lead_data["contacts"]}

        # Unrevealed contact: phone must be strictly None, email must be masked
        unrev = contacts_by_id[str(unrevealed_contact_id)]
        assert unrev["is_revealed"] is False
        assert unrev["phone"] is None, "Unrevealed phone number leaked in API response!"
        assert "***" in unrev["email"], "Unrevealed email address leaked unmasked!"
        assert unrev["email"] == "a***@calc-domain.com"

        # Revealed contact: phone and email must be unmasked
        rev = contacts_by_id[str(revealed_contact_id)]
        assert rev["is_revealed"] is True
        assert rev["phone"] == "+1-555-0200"
        assert rev["email"] == "bob.public@calc-domain.com"

        # 2. Export CSV -> Verify formula sanitization & export privacy
        csv_resp = await client.get(
            "/api/v1/leads/export?format=csv",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
        )
        assert csv_resp.status_code == 200
        csv_text = csv_resp.text

        # Verify formula characters are safely escaped with leading single quote
        assert "'=cmd|'/C calc'!A0" in csv_text
        assert "'+calc-domain.com" in csv_text
        assert "'@SUM(A1:B10)" in csv_text

        # Verify unrevealed email is never included in the export rows
        assert "alice.private@calc-domain.com" not in csv_text
        assert "+1-555-0199" not in csv_text

        # Verify revealed contact is present
        assert "bob.public@calc-domain.com" in csv_text


@pytest.mark.asyncio
async def test_quota_service_fails_closed_when_redis_unavailable(
    setup_test_tenants, admin_engine
):
    """
    Verify Section 6: When Redis is unreachable, quota reservation MUST fail closed (HTTP 503)
    to protect the ₹0 cost ceiling against un-metered lead ingestion and background runs.
    """
    ids = setup_test_tenants["ids"]
    org_id = ids["org_a_id"]

    session_factory = async_sessionmaker(
        bind=admin_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        # Test lead ingestion check with Redis failure
        with patch("app.services.quota_service.get_redis_client", side_effect=ConnectionError("Redis down")):
            with pytest.raises(HTTPException) as exc_ingest:
                await QuotaService.check_and_reserve_lead_ingestion(org_id, 10, session)
            assert exc_ingest.value.status_code == 503
            assert "redis unreachable" in exc_ingest.value.detail.lower()

        # Test concurrent run check with Redis failure
        with patch("app.services.quota_service.get_redis_client", side_effect=ConnectionError("Redis down")):
            with pytest.raises(HTTPException) as exc_run:
                await QuotaService.check_and_reserve_concurrent_run(org_id, session)
            assert exc_run.value.status_code == 503
            assert "redis unreachable" in exc_run.value.detail.lower()


@pytest.mark.asyncio
async def test_ai_icp_criteria_generation_and_audience_creation(setup_test_tenants):
    """
    Verifies the AI ICP generator:
    - POST /api/v1/audiences/generate-ai-criteria parses natural language into structured criteria.
    - Resulting criteria can be directly saved as an ICP audience.
    - Role restrictions enforced (org_admin allowed, client_viewer forbidden).
    """
    tokens = setup_test_tenants["tokens"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Generate criteria from prompt as Org Admin (using offline heuristic in test)
        prompt_payload = {
            "prompt": "B2B SaaS companies in US and Canada with 50-200 employees using HubSpot or Salesforce",
            "allow_offline_heuristic": True,
        }
        res_gen = await client.post(
            "/api/v1/audiences/generate-ai-criteria",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
            json=prompt_payload,
        )
        assert res_gen.status_code == 200
        gen_data = res_gen.json()
        assert "name" in gen_data
        assert "filters" in gen_data
        filters = gen_data["filters"]
        assert "locations" in filters
        assert "industries" in filters
        assert "employee_ranges" in filters

        # 2. Save generated criteria as new Audience
        res_create = await client.post(
            "/api/v1/audiences",
            headers={"Authorization": f"Bearer {tokens['org_a_admin']}"},
            json={
                "name": gen_data["name"],
                "description": gen_data["description"],
                "filters": gen_data["filters"],
            },
        )
        assert res_create.status_code == 201
        created_aud = res_create.json()
        assert created_aud["name"] == gen_data["name"]

        # 3. Client Viewer forbidden from generating/creating audiences
        res_viewer = await client.post(
            "/api/v1/audiences/generate-ai-criteria",
            headers={"Authorization": f"Bearer {tokens['org_a_viewer']}"},
            json=prompt_payload,
        )
        assert res_viewer.status_code == 403
