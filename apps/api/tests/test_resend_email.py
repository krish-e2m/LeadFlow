import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient, Response

from app.core.config import settings
from app.core.constants import ApprovalStatus, DraftApprovalStatus, UserRole
from app.db.session import engine
from app.main import app
from app.models.contact import Contact
from app.models.draft import Draft
from app.models.lead import Lead
from app.models.organization import Organization
from app.models.user import User
from app.providers.manager import provider_manager
from app.security.jwt import create_access_token
from app.security.passwords import hash_password
from app.security.session_store import close_redis_client


@pytest.fixture(autouse=True)
async def cleanup():
    yield
    await engine.dispose()
    await close_redis_client()


@pytest.mark.asyncio
async def test_resend_adapter_is_configured_behavior():
    with patch.object(settings, "RESEND_API_KEY", ""), patch.object(settings, "RESEND_ENABLED", False):
        assert not provider_manager.resend.is_configured()

    with patch.object(settings, "RESEND_API_KEY", "re_test_123456"), patch.object(settings, "RESEND_ENABLED", True):
        assert provider_manager.resend.is_configured()


@pytest.mark.asyncio
async def test_resend_check_health_unconfigured():
    with patch.object(settings, "RESEND_API_KEY", ""), patch.object(settings, "RESEND_ENABLED", False):
        status = await provider_manager.resend.check_health()
        assert not status.is_configured
        assert not status.is_healthy
        assert "unconfigured" in status.status_message.lower()


@pytest.mark.asyncio
async def test_resend_check_health_healthy():
    with patch.object(settings, "RESEND_API_KEY", "re_mock_key"), patch.object(settings, "RESEND_ENABLED", True):
        mock_response = Response(200, json={"data": [{"id": "key_1"}]})
        with patch("httpx.AsyncClient.get", AsyncMock(return_value=mock_response)):
            status = await provider_manager.resend.check_health()
            assert status.is_configured
            assert status.is_healthy
            assert "Connected to Resend" in status.status_message


@pytest.mark.asyncio
async def test_resend_send_email_success():
    with patch.object(settings, "RESEND_API_KEY", "re_mock_key"), patch.object(settings, "RESEND_ENABLED", True):
        mock_response = Response(200, json={"id": "email_msg_123"})
        with patch("httpx.AsyncClient.post", AsyncMock(return_value=mock_response)):
            res = await provider_manager.resend.send_email(
                to="prospect@example.com",
                subject="Quick question",
                html="<p>Hello world</p>",
            )
            assert res["success"] is True
            assert res["id"] == "email_msg_123"


@pytest.mark.asyncio
async def test_admin_email_test_endpoint_unconfigured():
    transport = ASGITransport(app=app)
    admin_token = create_access_token(
        subject=str(uuid.uuid4()),
        role=UserRole.SUPER_ADMIN.value,
    )
    headers = {"Authorization": f"Bearer {admin_token}"}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch.object(settings, "RESEND_API_KEY", ""), patch.object(settings, "RESEND_ENABLED", False):
            res = await client.post(
                "/api/v1/admin/email/test",
                json={"to_email": "test@example.com"},
                headers=headers,
            )
            assert res.status_code == 501
            assert "Resend email provider is not configured" in res.json()["detail"]


@pytest.mark.asyncio
async def test_admin_email_test_endpoint_success():
    transport = ASGITransport(app=app)
    admin_token = create_access_token(
        subject=str(uuid.uuid4()),
        role=UserRole.SUPER_ADMIN.value,
    )
    headers = {"Authorization": f"Bearer {admin_token}"}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch.object(settings, "RESEND_API_KEY", "re_mock_key"), patch.object(settings, "RESEND_ENABLED", True):
            mock_send = AsyncMock(return_value={"success": True, "id": "email_test_999"})
            with patch.object(provider_manager.resend, "send_email", mock_send):
                res = await client.post(
                    "/api/v1/admin/email/test",
                    json={"to_email": "operator@company.com"},
                    headers=headers,
                )
                assert res.status_code == 200
                data = res.json()
                assert data["success"] is True
                assert data["message_id"] == "email_test_999"
                assert data["to"] == "operator@company.com"


@pytest.mark.asyncio
async def test_draft_send_email_endpoint():
    from app.db.session import AsyncSessionLocal
    transport = ASGITransport(app=app)
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    lead_id = uuid.uuid4()
    contact_id = uuid.uuid4()
    draft_id = uuid.uuid4()

    async with AsyncSessionLocal() as session:
        from sqlalchemy import text
        await session.execute(
            text(
                "SELECT set_config('leadflow.is_super_admin', 'true', true), "
                "set_config('leadflow.auth_context', 'true', true)"
            )
        )
        # Create test records
        org = Organization(id=org_id, name="Email Org", slug=f"email-org-{org_id.hex[:6]}", plan="starter", settings={}, is_active=True)
        session.add(org)
        user = User(
            id=user_id,
            org_id=org_id,
            email=f"sender-{user_id.hex[:6]}@example.com",
            hashed_password=hash_password("password123"),
            role=UserRole.ORG_ADMIN,
            is_active=True,
        )
        session.add(user)
        lead = Lead(id=lead_id, org_id=org_id, company_name="Target Corp", domain="targetcorp.com", approval_status=ApprovalStatus.APPROVED)
        session.add(lead)
        contact = Contact(
            id=contact_id,
            org_id=org_id,
            lead_id=lead_id,
            first_name="Jane",
            last_name="Doe",
            email="jane.doe@targetcorp.com",
            is_revealed=True,
        )
        session.add(contact)
        draft = Draft(
            id=draft_id,
            org_id=org_id,
            lead_id=lead_id,
            contact_id=contact_id,
            subject="Partnership inquiry",
            body="Hi Jane, would love to connect.",
            model_used="test-model",
            approval_status=DraftApprovalStatus.APPROVED,
        )
        session.add(draft)
        await session.commit()

    token = create_access_token(
        subject=str(user_id),
        org_id=str(org_id),
        role=UserRole.ORG_ADMIN.value,
    )
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch.object(settings, "RESEND_API_KEY", "re_mock_key"), patch.object(settings, "RESEND_ENABLED", True):
            mock_send = AsyncMock(return_value={"success": True, "id": "resend_msg_777"})
            with patch.object(provider_manager.resend, "send_outreach_email", mock_send):
                res = await client.post(f"/api/v1/drafts/{draft_id}/send", headers=headers)
                assert res.status_code == 200
                data = res.json()
                assert data["draft_id"] == str(draft_id)
                assert data["recipient"] == "jane.doe@targetcorp.com"
                assert data["message_id"] == "resend_msg_777"
                assert data["status"] == "sent"

