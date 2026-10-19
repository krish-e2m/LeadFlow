import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.db.session import engine
from app.main import app
from app.security.session_store import close_redis_client
from app.services.google_auth_service import GoogleAuthService, GoogleUserProfile


@pytest.fixture(autouse=True)
async def cleanup():
    yield
    await engine.dispose()
    await close_redis_client()


@pytest.mark.asyncio
async def test_google_url_unconfigured_returns_501():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch.object(settings, "GOOGLE_CLIENT_ID", ""):
            res = await client.get("/api/v1/auth/google/url")
            assert res.status_code == 501
            assert "Google OAuth is not configured" in res.json()["detail"]


@pytest.mark.asyncio
async def test_google_url_configured_returns_url_and_state():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch.object(settings, "GOOGLE_CLIENT_ID", "mock-client-id"), \
             patch.object(settings, "GOOGLE_CLIENT_SECRET", "mock-secret"):
            res = await client.get("/api/v1/auth/google/url")
            assert res.status_code == 200
            data = res.json()
            assert "accounts.google.com" in data["url"]
            assert "client_id=mock-client-id" in data["url"]
            assert data["state"] is not None


@pytest.mark.asyncio
async def test_google_oauth_callback_invalid_state_redirects_error():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=False) as client:
        res = await client.get("/api/v1/auth/google/callback?code=fake-code&state=nonexistent-state")
        assert res.status_code == 302
        assert "login?error=" in res.headers["location"]
        assert "Invalid+or+expired" in res.headers["location"] or "Invalid%20or%20expired" in res.headers["location"]


@pytest.mark.asyncio
async def test_google_oauth_callback_success_provisions_user():
    transport = ASGITransport(app=app)
    mock_email = f"google-user-{uuid.uuid4().hex[:6]}@example.com"
    mock_profile = GoogleUserProfile(
        sub=f"google-sub-{uuid.uuid4().hex[:8]}",
        email=mock_email,
        email_verified=True,
        name="Google Test User",
        picture="https://example.com/photo.jpg",
    )

    with patch.object(settings, "GOOGLE_CLIENT_ID", "mock-id"), \
         patch.object(settings, "GOOGLE_CLIENT_SECRET", "mock-secret"), \
         patch.object(GoogleAuthService, "validate_state", AsyncMock(return_value="/dashboard")), \
         patch.object(GoogleAuthService, "exchange_code_for_profile", AsyncMock(return_value=mock_profile)):

        async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=False) as client:
            res = await client.get("/api/v1/auth/google/callback?code=valid-code&state=valid-state")
            assert res.status_code == 302
            assert "/dashboard" in res.headers["location"]
            # Check cookies were set
            cookies = res.cookies
            assert settings.COOKIE_ACCESS_NAME in cookies
            assert settings.COOKIE_REFRESH_NAME in cookies


@pytest.mark.asyncio
async def test_google_token_login_success():
    transport = ASGITransport(app=app)
    mock_email = f"gis-user-{uuid.uuid4().hex[:6]}@example.com"
    mock_profile = GoogleUserProfile(
        sub=f"google-sub-{uuid.uuid4().hex[:8]}",
        email=mock_email,
        email_verified=True,
        name="GIS Test User",
        picture="https://example.com/avatar.jpg",
    )

    with patch.object(settings, "GOOGLE_CLIENT_ID", "mock-id"), \
         patch.object(GoogleAuthService, "verify_id_token_credential", AsyncMock(return_value=mock_profile)):

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post("/api/v1/auth/google/token", json={"credential": "mock-google-id-token"})
            assert res.status_code == 200
            data = res.json()
            assert data["user"]["email"] == mock_email
            assert data["user"]["full_name"] == "GIS Test User"
            assert data["user"]["avatar_url"] == "https://example.com/avatar.jpg"
            assert settings.COOKIE_ACCESS_NAME in res.cookies
