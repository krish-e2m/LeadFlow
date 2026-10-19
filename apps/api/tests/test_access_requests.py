import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.constants import UserRole
from app.main import app
from app.security.jwt import create_access_token
from app.security.passwords import hash_password


@pytest.fixture
async def admin_engine():
    eng = create_async_engine(settings.migration_database_url, poolclass=NullPool)
    yield eng
    await eng.dispose()


@pytest.fixture
async def setup_tenants(admin_engine):
    """Creates two isolated test organizations and their Org Admins + a Super Admin."""
    org_a_id = uuid.uuid4()
    org_b_id = uuid.uuid4()

    super_admin_id = uuid.uuid4()
    org_a_admin_id = uuid.uuid4()
    org_b_admin_id = uuid.uuid4()

    hashed_pw = hash_password("ValidPassword123!")

    session_factory = async_sessionmaker(
        bind=admin_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as session:
        # Create Org A and Org B
        await session.execute(
            text(
                "INSERT INTO orgs (id, name, slug, plan, is_active) "
                "VALUES (:id_a, 'Tenant Alpha', :slug_a, 'starter', true), "
                "       (:id_b, 'Tenant Beta', :slug_b, 'growth', true)"
            ),
            {
                "id_a": org_a_id,
                "slug_a": f"tenant-alpha-{org_a_id.hex[:6]}",
                "id_b": org_b_id,
                "slug_b": f"tenant-beta-{org_b_id.hex[:6]}",
            },
        )

        # Create Super Admin, Org A Admin, Org B Admin
        await session.execute(
            text(
                "INSERT INTO users (id, org_id, email, hashed_password, full_name, role, is_active) "
                "VALUES (:s_id, NULL, :s_email, :pw, 'Super Admin', 'super_admin', true), "
                "       (:a_id, :org_a, :a_email, :pw, 'Admin Alpha', 'org_admin', true), "
                "       (:b_id, :org_b, :b_email, :pw, 'Admin Beta', 'org_admin', true)"
            ),
            {
                "s_id": super_admin_id,
                "s_email": f"super-{super_admin_id.hex[:6]}@example.com",
                "a_id": org_a_admin_id,
                "org_a": org_a_id,
                "a_email": f"admin-a-{org_a_admin_id.hex[:6]}@example.com",
                "b_id": org_b_admin_id,
                "org_b": org_b_id,
                "b_email": f"admin-b-{org_b_admin_id.hex[:6]}@example.com",
                "pw": hashed_pw,
            },
        )
        await session.commit()

    # Generate access tokens
    super_token = create_access_token(
        subject=str(super_admin_id),
        org_id=None,
        role=UserRole.SUPER_ADMIN.value,
        email=f"super-{super_admin_id.hex[:6]}@example.com",
    )
    org_a_token = create_access_token(
        subject=str(org_a_admin_id),
        org_id=str(org_a_id),
        role=UserRole.ORG_ADMIN.value,
        email=f"admin-a-{org_a_admin_id.hex[:6]}@example.com",
    )
    org_b_token = create_access_token(
        subject=str(org_b_admin_id),
        org_id=str(org_b_id),
        role=UserRole.ORG_ADMIN.value,
        email=f"admin-b-{org_b_admin_id.hex[:6]}@example.com",
    )

    yield {
        "org_a_id": org_a_id,
        "org_b_id": org_b_id,
        "super_token": super_token,
        "org_a_token": org_a_token,
        "org_b_token": org_b_token,
        "password": "ValidPassword123!",
    }

    # Teardown
    async with session_factory() as session:
        await session.execute(
            text("DELETE FROM access_requests WHERE org_id IN (:a, :b)"),
            {"a": org_a_id, "b": org_b_id},
        )
        await session.execute(
            text("DELETE FROM users WHERE org_id IN (:a, :b) OR id = :s_id"),
            {"a": org_a_id, "b": org_b_id, "s_id": super_admin_id},
        )
        await session.execute(
            text("DELETE FROM orgs WHERE id IN (:a, :b)"),
            {"a": org_a_id, "b": org_b_id},
        )
        await session.commit()


@pytest.mark.asyncio
async def test_public_organizations_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/auth/organizations")
        assert resp.status_code == 200
        orgs = resp.json()
        assert isinstance(orgs, list)
        if len(orgs) > 0:
            assert "id" in orgs[0]
            assert "name" in orgs[0]
            assert "slug" in orgs[0]


@pytest.mark.asyncio
async def test_access_request_org_admin_flow(setup_tenants):
    """
    Scenario: Applicant requests org_admin access.
    - Routed to Super Admin approval.
    - Org Admin cannot approve it.
    - Pending login fails with 403.
    - Super Admin approves it.
    - Account activated; user can now log in.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        org_id = str(setup_tenants["org_a_id"])
        applicant_email = f"applicant-admin-{uuid.uuid4().hex[:6]}@example.com"
        applicant_pw = "ApplicantPass123!"

        # 1. Submit org_admin access request
        req_resp = await client.post(
            "/api/v1/auth/access-requests",
            json={
                "email": applicant_email,
                "password": applicant_pw,
                "full_name": "Applicant Admin",
                "org_id": org_id,
                "requested_role": "org_admin",
            },
        )
        assert req_resp.status_code == 201, req_resp.text
        req_data = req_resp.json()
        assert req_data["status"] == "pending"
        assert req_data["requested_role"] == "org_admin"
        request_id = req_data["id"]

        # 2. Login attempt while pending must be 403
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": applicant_email, "password": applicant_pw},
        )
        assert login_resp.status_code == 403
        assert "pending administrative approval" in login_resp.json()["detail"]

        # 3. Org Admin cannot view org_admin access requests
        oa_view = await client.get(
            "/api/v1/access-requests",
            headers={"Authorization": f"Bearer {setup_tenants['org_a_token']}"},
        )
        assert oa_view.status_code == 200
        oa_req_ids = [r["id"] for r in oa_view.json()]
        assert request_id not in oa_req_ids

        # 4. Org Admin cannot approve org_admin access request
        oa_approve = await client.post(
            f"/api/v1/access-requests/{request_id}/approve",
            headers={"Authorization": f"Bearer {setup_tenants['org_a_token']}"},
        )
        # Expect 403 or 404 (due to RLS or permission check)
        assert oa_approve.status_code in (403, 404)

        # 5. Super Admin sees the request
        sa_view = await client.get(
            "/api/v1/access-requests",
            headers={"Authorization": f"Bearer {setup_tenants['super_token']}"},
        )
        assert sa_view.status_code == 200
        sa_req_ids = [r["id"] for r in sa_view.json()]
        assert request_id in sa_req_ids

        # 6. Super Admin approves it
        sa_approve = await client.post(
            f"/api/v1/access-requests/{request_id}/approve",
            headers={"Authorization": f"Bearer {setup_tenants['super_token']}"},
        )
        assert sa_approve.status_code == 200
        assert sa_approve.json()["status"] == "approved"

        # 7. User can now successfully log in!
        login_success = await client.post(
            "/api/v1/auth/login",
            json={"email": applicant_email, "password": applicant_pw},
        )
        assert login_success.status_code == 200
        user_info = login_success.json()["user"]
        assert user_info["email"] == applicant_email
        assert user_info["role"] == "org_admin"
        assert user_info["org_id"] == org_id


@pytest.mark.asyncio
async def test_access_request_client_viewer_flow(setup_tenants):
    """
    Scenario: Applicant requests client_viewer access to Org A.
    - Org A Admin sees and approves it.
    - Org B Admin cannot see or approve it (cross-tenant isolation).
    - Subsequent approvals fail with 409 (race-safe).
    - User account created with client_viewer role.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        org_a = str(setup_tenants["org_a_id"])
        applicant_email = f"client-viewer-{uuid.uuid4().hex[:6]}@example.com"
        applicant_pw = "ClientViewerPass123!"

        # 1. Submit client_viewer request
        req_resp = await client.post(
            "/api/v1/auth/access-requests",
            json={
                "email": applicant_email,
                "password": applicant_pw,
                "full_name": "Client Viewer One",
                "org_id": org_a,
                "requested_role": "client_viewer",
            },
        )
        assert req_resp.status_code == 201
        request_id = req_resp.json()["id"]

        # 2. Org B Admin cannot see Org A's request
        b_view = await client.get(
            "/api/v1/access-requests",
            headers={"Authorization": f"Bearer {setup_tenants['org_b_token']}"},
        )
        assert b_view.status_code == 200
        b_ids = [r["id"] for r in b_view.json()]
        assert request_id not in b_ids

        # 3. Org B Admin cannot approve Org A's request
        b_approve = await client.post(
            f"/api/v1/access-requests/{request_id}/approve",
            headers={"Authorization": f"Bearer {setup_tenants['org_b_token']}"},
        )
        assert b_approve.status_code in (403, 404)

        # 4. Org A Admin can see the request
        a_view = await client.get(
            "/api/v1/access-requests",
            headers={"Authorization": f"Bearer {setup_tenants['org_a_token']}"},
        )
        assert a_view.status_code == 200
        a_ids = [r["id"] for r in a_view.json()]
        assert request_id in a_ids

        # 5. Org A Admin approves the request
        a_approve = await client.post(
            f"/api/v1/access-requests/{request_id}/approve",
            headers={"Authorization": f"Bearer {setup_tenants['org_a_token']}"},
        )
        assert a_approve.status_code == 200
        assert a_approve.json()["status"] == "approved"

        # 6. Concurrency / race condition test: second approval attempt fails with 409
        dup_approve = await client.post(
            f"/api/v1/access-requests/{request_id}/approve",
            headers={"Authorization": f"Bearer {setup_tenants['org_a_token']}"},
        )
        assert dup_approve.status_code == 409

        # 7. Applicant can now log in as client_viewer
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": applicant_email, "password": applicant_pw},
        )
        assert login_resp.status_code == 200
        user_info = login_resp.json()["user"]
        assert user_info["role"] == "client_viewer"
        assert user_info["org_id"] == org_a


@pytest.mark.asyncio
async def test_access_request_rejection(setup_tenants):
    """
    Scenario: Access request is rejected with reason.
    - Login shows 403 with rejection reason.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        org_a = str(setup_tenants["org_a_id"])
        applicant_email = f"reject-test-{uuid.uuid4().hex[:6]}@example.com"
        applicant_pw = "RejectPass123!"

        req_resp = await client.post(
            "/api/v1/auth/access-requests",
            json={
                "email": applicant_email,
                "password": applicant_pw,
                "full_name": "Rejected User",
                "org_id": org_a,
                "requested_role": "client_viewer",
            },
        )
        assert req_resp.status_code == 201
        request_id = req_resp.json()["id"]

        # Org A Admin rejects it with reason
        rejection_reason = "Organization membership quota exceeded."
        rej_resp = await client.post(
            f"/api/v1/access-requests/{request_id}/reject",
            headers={"Authorization": f"Bearer {setup_tenants['org_a_token']}"},
            json={"rejection_reason": rejection_reason},
        )
        assert rej_resp.status_code == 200
        assert rej_resp.json()["status"] == "rejected"

        # Attempt to login gives 403 explaining rejection
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": applicant_email, "password": applicant_pw},
        )
        assert login_resp.status_code == 403
        assert rejection_reason in login_resp.json()["detail"]


@pytest.mark.asyncio
async def test_invalid_requests_and_duplicate_prevention(setup_tenants):
    """
    Scenario:
    - User cannot request super_admin.
    - Short password rejected.
    - Duplicate pending request rejected with 409.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        org_a = str(setup_tenants["org_a_id"])

        # 1. Reject super_admin request
        sa_req = await client.post(
            "/api/v1/auth/access-requests",
            json={
                "email": "hacker@example.com",
                "password": "Password123!",
                "org_id": org_a,
                "requested_role": "super_admin",
            },
        )
        assert sa_req.status_code == 400

        # 2. Reject short password
        short_pw = await client.post(
            "/api/v1/auth/access-requests",
            json={
                "email": "short@example.com",
                "password": "short",
                "org_id": org_a,
                "requested_role": "client_viewer",
            },
        )
        assert short_pw.status_code in (400, 422)

        # 3. Duplicate pending request
        email = f"dup-test-{uuid.uuid4().hex[:6]}@example.com"
        first_req = await client.post(
            "/api/v1/auth/access-requests",
            json={
                "email": email,
                "password": "ValidPassword123!",
                "org_id": org_a,
                "requested_role": "client_viewer",
            },
        )
        assert first_req.status_code == 201

        dup_req = await client.post(
            "/api/v1/auth/access-requests",
            json={
                "email": email,
                "password": "ValidPassword123!",
                "org_id": org_a,
                "requested_role": "client_viewer",
            },
        )
        assert dup_req.status_code == 409
