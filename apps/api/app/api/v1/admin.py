import uuid
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import UserRole
from app.db.session import get_db
from app.models.organization import Organization
from app.providers.manager import provider_manager
from app.repositories.audit_repo import AuditRepository
from app.schemas.admin import (
    AuditLogResponse,
    ProviderStatusResponse,
    TestEmailRequest,
    TestEmailResponse,
    UsageMetricsResponse,
)
from app.schemas.organization import OperatorAccessUpdate, OrgCreate, OrgResponse
from app.security.rbac import AuthenticatedUser, require_org_admin, require_super_admin
from app.security.session_store import SessionStore
from app.services.audit_service import AuditService
from app.services.quota_service import QuotaService

router = APIRouter(prefix="/admin", tags=["Administration & Health"])


@router.get("/orgs", response_model=List[OrgResponse])
async def list_organizations(
    current_user: AuthenticatedUser = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """Super Admin: Lists all organizations in the multi-tenant system."""
    stmt = (
        select(Organization)
        .where(Organization.deleted_at.is_(None))
        .order_by(Organization.created_at.desc())
    )
    res = await db.execute(stmt)
    return list(res.scalars().all())


@router.get("/orgs/{org_id}", response_model=OrgResponse)
async def get_organization(
    org_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Retrieves authorized organization details and status.
    Super admin can access any organization; org admin can access only their own organization.
    """
    if current_user.role != UserRole.SUPER_ADMIN and current_user.org_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cross-tenant organization access denied.",
        )

    stmt = select(Organization).where(Organization.id == org_id)
    org = (await db.execute(stmt)).scalars().first()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")
    return org


@router.post("/orgs", response_model=OrgResponse, status_code=status.HTTP_201_CREATED)
async def create_organization(
    req: OrgCreate,
    current_user: AuthenticatedUser = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """Super Admin: Provisions a new tenant organization."""
    org = Organization(
        name=req.name,
        slug=req.slug.lower(),
        plan=req.plan,
        settings=req.settings or {},
        is_active=True,
    )
    db.add(org)
    await db.flush()

    audit_service = AuditService(db)
    await audit_service.log_action(
        action="org.create",
        entity_type="org",
        entity_id=org.id,
        changes={"name": org.name, "slug": org.slug, "plan": org.plan},
        org_id=org.id,
        actor_user_id=current_user.id,
    )
    await db.commit()
    return org


@router.post("/orgs/{org_id}/suspend", response_model=OrgResponse)
async def suspend_organization(
    org_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Super Admin: Suspends a tenant organization.
    Immediately blocks users from accessing protected features, rejects background jobs,
    and records an audit event.
    """
    stmt = select(Organization).where(Organization.id == org_id, Organization.deleted_at.is_(None))
    org = (await db.execute(stmt)).scalars().first()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")

    org.is_active = False
    await db.flush()

    # Synchronize suspension to Redis for fail-closed edge enforcement
    await SessionStore.set_org_suspended(str(org_id), True)

    audit_service = AuditService(db)
    await audit_service.log_action(
        action="org.suspend",
        entity_type="org",
        entity_id=org.id,
        changes={"is_active": {"from": True, "to": False}},
        org_id=org.id,
        actor_user_id=current_user.id,
    )
    await db.commit()
    return org


@router.post("/orgs/{org_id}/reactivate", response_model=OrgResponse)
async def reactivate_organization(
    org_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Super Admin: Reactivates a suspended organization.
    Restores authorized access without bypassing quotas or permissions.
    """
    stmt = select(Organization).where(Organization.id == org_id, Organization.deleted_at.is_(None))
    org = (await db.execute(stmt)).scalars().first()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")

    org.is_active = True
    await db.flush()

    # Clear suspension in Redis
    await SessionStore.set_org_suspended(str(org_id), False)

    audit_service = AuditService(db)
    await audit_service.log_action(
        action="org.reactivate",
        entity_type="org",
        entity_id=org.id,
        changes={"is_active": {"from": False, "to": True}},
        org_id=org.id,
        actor_user_id=current_user.id,
    )
    await db.commit()
    return org


@router.post("/orgs/{org_id}/offboard", response_model=OrgResponse)
async def offboard_organization(
    org_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Super Admin: Safely offboards a tenant organization.
    Deactivates access and soft-deletes the organization record while preserving
    historical leads, audit records, and evidence. Never hard-deletes data.
    """
    stmt = select(Organization).where(Organization.id == org_id, Organization.deleted_at.is_(None))
    org = (await db.execute(stmt)).scalars().first()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")

    now = datetime.now(timezone.utc)
    org.is_active = False
    org.deleted_at = now
    await db.flush()

    # Suspend organization in Redis
    await SessionStore.set_org_suspended(str(org_id), True)

    audit_service = AuditService(db)
    await audit_service.log_action(
        action="org.offboard",
        entity_type="org",
        entity_id=org.id,
        changes={"offboarded_at": now.isoformat(), "is_active": False},
        org_id=org.id,
        actor_user_id=current_user.id,
    )
    await db.commit()
    return org


@router.patch("/orgs/{org_id}/operator-access", response_model=OrgResponse)
async def update_operator_access(
    org_id: uuid.UUID,
    payload: OperatorAccessUpdate,
    current_user: AuthenticatedUser = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """Super Admin only: enables or disables operator elevation for an organization."""
    stmt = select(Organization).where(Organization.id == org_id, Organization.deleted_at.is_(None))
    org = (await db.execute(stmt)).scalars().first()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")

    settings_dict = dict(org.settings or {})
    previous_state = settings_dict.get("operator_access", False)
    settings_dict["operator_access"] = payload.enabled
    org.settings = settings_dict
    await db.flush()

    audit_service = AuditService(db)
    await audit_service.log_action(
        action="org.operator_access",
        entity_type="org",
        entity_id=org.id,
        changes={"operator_access": {"from": previous_state, "to": payload.enabled}},
        org_id=org.id,
        actor_user_id=current_user.id,
    )
    await db.commit()
    return org


@router.get("/providers", response_model=List[ProviderStatusResponse])
async def check_all_providers(
    current_user: AuthenticatedUser = Depends(require_org_admin),
):
    """Checks live connectivity and configuration across all 8 external provider adapters."""
    statuses = await provider_manager.get_all_provider_statuses()
    return [
        ProviderStatusResponse(
            name=s.name,
            is_configured=s.is_configured,
            is_healthy=s.is_healthy,
            status_message=s.status_message,
            last_checked=s.last_checked,
        )
        for s in statuses
    ]


@router.get("/audit-logs", response_model=List[AuditLogResponse])
async def list_audit_logs(
    skip: int = 0,
    limit: int = 50,
    current_user: AuthenticatedUser = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db),
):
    """Queries security, spend, and mutation audit records."""
    repo = AuditRepository(db)
    target_org = None if current_user.role == UserRole.SUPER_ADMIN else current_user.org_id
    return await repo.list_events(org_id=target_org, skip=skip, limit=limit)


@router.get("/usage", response_model=UsageMetricsResponse)
async def get_usage_metrics(
    current_user: AuthenticatedUser = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Summarizes genuine lead throughput, quota consumption, and provider usage statistics.
    All figures derived strictly from database records and atomic counters.
    """
    org_id = current_user.org_id
    if not org_id and current_user.role == UserRole.SUPER_ADMIN:
        # If super_admin has no org selected, pick first active org or return empty
        first_org = (
            await db.execute(
                select(Organization.id)
                .where(Organization.deleted_at.is_(None))
                .order_by(Organization.created_at.desc())
            )
        ).scalar()
        org_id = first_org

    if not org_id:
        return UsageMetricsResponse(
            org_id=None,
            total_searches_run=0,
            total_leads_sourced=0,
            total_contacts_revealed=0,
            total_ai_drafts_generated=0,
            total_crm_syncs=0,
            credits_used=0,
            credits_limit=500,
        )

    usage_summary = await QuotaService.get_usage_summary(org_id, db)
    return UsageMetricsResponse(**usage_summary)


@router.post("/email/test", response_model=TestEmailResponse)
async def send_test_email(
    payload: TestEmailRequest,
    current_user: AuthenticatedUser = Depends(require_org_admin),
):
    """
    Sends a test email via Resend to verify API key configuration and deliverability.
    """
    if not provider_manager.resend.is_configured():
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Resend email provider is not configured. Please supply RESEND_API_KEY and set RESEND_ENABLED=true in .env.",
        )

    html_content = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 520px; margin: 0 auto; padding: 24px; color: #1e293b; background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px;">
        <h2 style="font-size: 18px; font-weight: 600; color: #0284c7; margin-top: 0; margin-bottom: 8px;">LeadFlow Resend Integration Test</h2>
        <p style="font-size: 14px; line-height: 1.5; color: #475569;">
            This email confirms that your Resend API configuration and outbound transactional email channel in LeadFlow are working correctly.
        </p>
        <p style="font-size: 12px; color: #94a3b8; margin-top: 24px; margin-bottom: 0;">
            Sent by LeadFlow Platform &bull; {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}
        </p>
    </div>
    """

    res = await provider_manager.resend.send_email(
        to=payload.to_email,
        subject=payload.subject or "LeadFlow Resend Test Email",
        html=html_content,
        text=f"LeadFlow Resend Integration Test: Your Resend email service is working. Sent at {datetime.now(timezone.utc).isoformat()}.",
    )

    if not res.get("success"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Resend delivery failed: {res.get('error')}",
        )

    return TestEmailResponse(
        success=True,
        message="Test email sent successfully via Resend.",
        message_id=res.get("id"),
        to=payload.to_email,
        from_email=provider_manager.resend.from_email,
    )
