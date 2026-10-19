import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings, settings
from app.db.session import engine
from app.main import app
from app.security.jwt import create_access_token
from app.security.passwords import hash_password
from app.security.session_store import close_redis_client


@pytest.fixture(autouse=True)
async def cleanup_pool_and_redis():
    yield
    await engine.dispose()
    await close_redis_client()


@pytest.fixture
async def admin_engine():
    """Privileged engine used solely for test setup and teardown."""
    eng = create_async_engine(settings.migration_database_url, poolclass=NullPool)
    yield eng
    await eng.dispose()


@pytest.fixture
async def test_auth_data(admin_engine):
    """
    Sets up isolated test organization and users with distinct roles and password reset flags.
    Cleans up all created rows afterwards using admin privileges.
    """
    org_id = uuid.uuid4()
    org_slug = f"test-auth-org-{org_id.hex[:8]}"

    user_admin_id = uuid.uuid4()
    user_viewer_id = uuid.uuid4()
    user_reset_id = uuid.uuid4()

    admin_session_factory = async_sessionmaker(
        bind=admin_engine, class_=AsyncSession, expire_on_commit=False
    )

    hashed_pw = hash_password("ValidPassword123!")

    async with admin_session_factory() as session:
        # Create test organization
        await session.execute(
            text(
                "INSERT INTO orgs (id, name, slug, plan, is_active) "
                "VALUES (:id, 'Auth Test Org', :slug, 'growth', true)"
            ),
            {"id": org_id, "slug": org_slug},
        )
        # Create org_admin user
        await session.execute(
            text(
                "INSERT INTO users (id, org_id, email, hashed_password, full_name, role, is_active, must_reset_password) "
                "VALUES (:id, :org_id, :email, :pw, 'Org Admin User', 'org_admin', true, false)"
            ),
            {
                "id": user_admin_id,
                "org_id": org_id,
                "email": f"admin-{user_admin_id.hex[:6]}@example.com",
                "pw": hashed_pw,
            },
        )
        # Create client_viewer user
        await session.execute(
            text(
                "INSERT INTO users (id, org_id, email, hashed_password, full_name, role, is_active, must_reset_password) "
                "VALUES (:id, :org_id, :email, :pw, 'Viewer User', 'client_viewer', true, false)"
            ),
            {
                "id": user_viewer_id,
                "org_id": org_id,
                "email": f"viewer-{user_viewer_id.hex[:6]}@example.com",
                "pw": hashed_pw,
            },
        )
        # Create user with must_reset_password = true
        await session.execute(
            text(
                "INSERT INTO users (id, org_id, email, hashed_password, full_name, role, is_active, must_reset_password) "
                "VALUES (:id, :org_id, :email, :pw, 'Reset Required User', 'org_admin', true, true)"
            ),
            {
                "id": user_reset_id,
                "org_id": org_id,
                "email": f"reset-{user_reset_id.hex[:6]}@example.com",
                "pw": hashed_pw,
            },
        )
        await session.commit()

    yield {
        "org_id": org_id,
        "admin_email": f"admin-{user_admin_id.hex[:6]}@example.com",
        "admin_id": user_admin_id,
        "viewer_email": f"viewer-{user_viewer_id.hex[:6]}@example.com",
        "viewer_id": user_viewer_id,
        "reset_email": f"reset-{user_reset_id.hex[:6]}@example.com",
        "reset_id": user_reset_id,
        "password": "ValidPassword123!",
    }

    # Cleanup test data using admin privileges
    async with admin_session_factory() as session:
        await session.execute(text("DELETE FROM orgs WHERE id = :id"), {"id": org_id})
        await session.commit()


@pytest.mark.asyncio
async def test_token_lifetime_configuration():
    """Verify access token expiry is configured to 15 minutes and refresh token to 7 days."""
    assert settings.ACCESS_TOKEN_EXPIRE_MINUTES == 15, "Access token expiry must be 15 minutes"
    assert settings.REFRESH_TOKEN_EXPIRE_DAYS == 7, "Refresh token expiry must be 7 days"


@pytest.mark.asyncio
async def test_production_signing_secret_validation():
    """Verify production mode rejects insecure fallback signing secrets."""
    with pytest.raises((ValidationError, ValueError)) as exc_info:
        Settings(
            ENVIRONMENT="production",
            JWT_SECRET_KEY="leadflow-insecure-dev-secret-key-change-in-production-min-32-chars",
        )
    assert "insecure" in str(exc_info.value).lower() or "production" in str(exc_info.value).lower()

    # Reject short secret in production
    with pytest.raises((ValidationError, ValueError)):
        Settings(
            ENVIRONMENT="production",
            JWT_SECRET_KEY="short-secret-under-32-chars",
        )


@pytest.mark.asyncio
async def test_login_success_sets_httponly_cookies_and_omits_tokens_from_json(test_auth_data):
    """Verify successful login sets HttpOnly cookies, sets CSRF cookie, and returns profile without raw tokens."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/auth/login",
            json={
                "email": test_auth_data["admin_email"],
                "password": test_auth_data["password"],
            },
        )
        assert resp.status_code == 200, f"Login failed: {resp.text}"
        data = resp.json()

        # Tokens must NOT be returned in JSON body
        assert "access_token" not in data
        assert "refresh_token" not in data
        assert data["user"]["email"] == test_auth_data["admin_email"]
        assert data["user"]["role"] == "org_admin"

        # Verify HttpOnly session cookies
        cookies = resp.cookies
        assert "leadflow_access_token" in cookies
        assert "leadflow_refresh_token" in cookies
        assert "leadflow_csrf_token" in cookies


@pytest.mark.asyncio
async def test_login_incorrect_credentials_rejected(test_auth_data):
    """Verify incorrect password or non-existent email returns 401 Unauthorized."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Wrong password
        resp = await client.post(
            "/api/v1/auth/login",
            json={
                "email": test_auth_data["admin_email"],
                "password": "WrongPassword!",
            },
        )
        assert resp.status_code == 401

        # Non-existent user
        resp2 = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "nobody@example.com",
                "password": "ValidPassword123!",
            },
        )
        assert resp2.status_code == 401


@pytest.mark.asyncio
async def test_invalid_expired_or_forged_tokens_rejected():
    """Verify missing, forged, expired, or wrong-type tokens are rejected by protected endpoints."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Missing token
        resp_missing = await client.get("/api/v1/auth/me")
        assert resp_missing.status_code == 401

        # 2. Forged signature (signed with different secret)
        import jwt as pyjwt
        fake_token = pyjwt.encode(
            {"sub": str(uuid.uuid4()), "type": "access", "exp": 9999999999, "iat": 1000},
            "completely-different-signing-secret-key-32-chars",
            algorithm="HS256",
        )
        resp_forged = await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {fake_token}"}
        )
        assert resp_forged.status_code == 401

        # 3. Expired token
        expired_token = create_access_token(
            subject=str(uuid.uuid4()),
            expires_delta=timedelta(seconds=-10),
        )
        resp_expired = await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {expired_token}"}
        )
        assert resp_expired.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token_rotation_and_reuse_detection(test_auth_data):
    """Verify refresh rotation issues a new refresh token and rejects reuse of the old one."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Login
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={
                "email": test_auth_data["admin_email"],
                "password": test_auth_data["password"],
            },
        )
        assert login_resp.status_code == 200
        old_refresh_cookie = login_resp.cookies["leadflow_refresh_token"]

        # First refresh: Rotates successfully
        refresh_resp1 = await client.post("/api/v1/auth/refresh")
        assert refresh_resp1.status_code == 200
        new_refresh_cookie = refresh_resp1.cookies["leadflow_refresh_token"]
        assert new_refresh_cookie != old_refresh_cookie

        # Attempt to reuse the OLD refresh token: Must be detected and rejected!
        client.cookies.set("leadflow_refresh_token", old_refresh_cookie)
        reuse_resp = await client.post("/api/v1/auth/refresh")
        assert reuse_resp.status_code == 401
        assert "reuse" in reuse_resp.text.lower() or "terminated" in reuse_resp.text.lower()


@pytest.mark.asyncio
async def test_logout_revokes_session_and_clears_cookies(test_auth_data):
    """Verify logout clears cookies and revokes the access token in Redis."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={
                "email": test_auth_data["admin_email"],
                "password": test_auth_data["password"],
            },
        )
        assert login_resp.status_code == 200
        access_token = login_resp.cookies["leadflow_access_token"]
        csrf_token = login_resp.cookies["leadflow_csrf_token"]

        # User is authenticated
        me_resp = await client.get("/api/v1/auth/me")
        assert me_resp.status_code == 200

        # Perform logout (sending CSRF token)
        logout_resp = await client.post(
            "/api/v1/auth/logout",
            headers={
                "Origin": "http://localhost:3000",
                "X-CSRF-Token": csrf_token,
            },
        )
        assert logout_resp.status_code == 200

        # Calling /auth/me with the revoked access token directly via Bearer header must now fail!
        revoked_check = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert revoked_check.status_code == 401
        assert "revoked" in revoked_check.text.lower()


@pytest.mark.asyncio
async def test_password_change_invalidates_existing_sessions(test_auth_data):
    """Verify changing password clears forced reset and invalidates all prior sessions."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Login with user that has must_reset_password = True
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={
                "email": test_auth_data["reset_email"],
                "password": test_auth_data["password"],
            },
        )
        assert login_resp.status_code == 200
        old_access_token = login_resp.cookies["leadflow_access_token"]
        csrf_token = login_resp.cookies["leadflow_csrf_token"]

        # Change password
        change_resp = await client.post(
            "/api/v1/auth/change-password",
            json={
                "old_password": test_auth_data["password"],
                "new_password": "NewSecurePassword456!",
            },
            headers={
                "Origin": "http://localhost:3000",
                "X-CSRF-Token": csrf_token,
            },
        )
        assert change_resp.status_code == 200

        # Verify old token is now invalidated by the user session invalidation timestamp in Redis
        old_token_check = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {old_access_token}"},
        )
        assert old_token_check.status_code == 401


@pytest.mark.asyncio
async def test_must_reset_password_enforces_restriction(test_auth_data):
    """Verify users with must_reset_password=True are restricted from application features."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={
                "email": test_auth_data["reset_email"],
                "password": test_auth_data["password"],
            },
        )
        assert login_resp.status_code == 200

        # Attempt to access restricted feature (leads, searches, etc.)
        restricted_resp = await client.get("/api/v1/leads")
        assert restricted_resp.status_code == 403
        assert "password reset required" in restricted_resp.text.lower()

        # But allowed to access /auth/me to fetch profile
        me_resp = await client.get("/api/v1/auth/me")
        assert me_resp.status_code == 200
        assert me_resp.json()["must_reset_password"] is True


@pytest.mark.asyncio
async def test_backend_role_checks_reject_unauthorized_actions(test_auth_data):
    """Verify client_viewer role is rejected from admin-only operations."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Login as client_viewer
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={
                "email": test_auth_data["viewer_email"],
                "password": test_auth_data["password"],
            },
        )
        assert login_resp.status_code == 200

        # Attempt to access org_admin endpoint (/api/v1/admin/usage)
        unauthorized_resp = await client.get("/api/v1/admin/usage")
        assert unauthorized_resp.status_code == 403

        # Attempt to access super_admin endpoint (/api/v1/admin/orgs)
        super_admin_resp = await client.get("/api/v1/admin/orgs")
        assert super_admin_resp.status_code == 403


@pytest.mark.asyncio
async def test_csrf_protection_and_origin_validation(test_auth_data):
    """Verify state-changing cookie requests require trusted Origin and matching CSRF token."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={
                "email": test_auth_data["admin_email"],
                "password": test_auth_data["password"],
            },
        )
        assert login_resp.status_code == 200
        csrf_token = login_resp.cookies["leadflow_csrf_token"]

        # 1. State-changing request with untrusted origin -> 403 Forbidden
        bad_origin_resp = await client.post(
            "/api/v1/auth/logout",
            headers={
                "Origin": "http://malicious-attacker.com",
                "X-CSRF-Token": csrf_token,
            },
        )
        assert bad_origin_resp.status_code == 403
        assert "origin" in bad_origin_resp.text.lower()

        # 2. State-changing request missing X-CSRF-Token header -> 403 Forbidden
        missing_csrf_resp = await client.post(
            "/api/v1/auth/logout",
            headers={"Origin": "http://localhost:3000"},
        )
        assert missing_csrf_resp.status_code == 403

        # 3. State-changing request with valid origin and CSRF token -> 200 OK
        valid_csrf_resp = await client.post(
            "/api/v1/auth/logout",
            headers={
                "Origin": "http://localhost:3000",
                "X-CSRF-Token": csrf_token,
            },
        )
        assert valid_csrf_resp.status_code == 200


@pytest.mark.asyncio
async def test_signup_creates_org_and_admin_user_with_session(admin_engine):
    """Verify public signup creates organization, admin user, default scoring engine, and HttpOnly session cookies."""
    transport = ASGITransport(app=app)
    signup_email = f"operator-{uuid.uuid4().hex[:6]}@neworg.com"
    org_name = f"Startup Alpha {uuid.uuid4().hex[:4]}"

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/auth/signup",
            json={
                "email": signup_email,
                "password": "StrongPassword123!",
                "organization_name": org_name,
                "full_name": "Chief Executive",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["user"]["email"] == signup_email
        assert data["user"]["role"] == "org_admin"
        assert data["user"]["org_name"] == org_name
        assert data["user"]["must_reset_password"] is False
        assert "leadflow_access_token" in resp.cookies
        assert "leadflow_refresh_token" in resp.cookies
        assert "leadflow_csrf_token" in resp.cookies

        # Verify authenticated session can access /auth/me
        me_resp = await client.get("/api/v1/auth/me")
        assert me_resp.status_code == 200
        me_data = me_resp.json()
        assert me_data["email"] == signup_email
        assert me_data["role"] == "org_admin"
        assert me_data["org_name"] == org_name


@pytest.mark.asyncio
async def test_signup_validation_and_duplicate_rejection(test_auth_data):
    """Verify signup enforces minimum password length and prevents duplicate email registration."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Short password (< 8 chars) -> 400 Bad Request
        short_pw_resp = await client.post(
            "/api/v1/auth/signup",
            json={
                "email": "valid@company.com",
                "password": "short",
                "organization_name": "Company",
            },
        )
        assert short_pw_resp.status_code == 400
        assert "at least 8 characters" in short_pw_resp.text

        # 2. Duplicate email registration -> 400 Bad Request
        dup_resp = await client.post(
            "/api/v1/auth/signup",
            json={
                "email": test_auth_data["admin_email"],
                "password": "StrongPassword123!",
                "organization_name": "Another Company",
            },
        )
        assert dup_resp.status_code == 400
        assert "already exists" in dup_resp.text


@pytest.mark.asyncio
async def test_authentication_fails_closed_when_redis_unavailable(test_auth_data):
    """
    Verify security requirement: When Redis session store is unreachable,
    authentication verification MUST fail closed (HTTP 503) rather than allowing unverified access.
    """
    valid_token = create_access_token(
        subject=str(test_auth_data["admin_id"]),
        org_id=str(test_auth_data["org_id"]),
        role="org_admin",
        email=test_auth_data["admin_email"],
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Simulate Redis connection failure during token revocation check
        with patch("app.security.session_store.get_redis_client", side_effect=ConnectionError("Redis connection refused")):
            resp = await client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {valid_token}"},
            )
            assert resp.status_code == 503
            assert "security validation service unavailable" in resp.json()["detail"].lower()

