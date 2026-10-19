import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.repositories.crm_repo import CrmRepository
from app.schemas.crm import CrmSyncRequest, CrmSyncResponse
from app.security.rbac import AuthenticatedUser, require_org_admin
from app.services.audit_service import AuditService
from app.services.crm_service import CrmService

router = APIRouter(tags=["CRM Synchronization"])


@router.post("/leads/{lead_id}/sync-crm", response_model=CrmSyncResponse)
async def sync_lead_to_crm(
    lead_id: uuid.UUID,
    req: CrmSyncRequest,
    current_user: AuthenticatedUser = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Idempotent CRM Export:
    Pushes company and contact to HubSpot CRM and logs the approved draft as an engagement note.
    Enforces Draft Approval Gate: Outreach copy must be APPROVED before sync is allowed.
    """
    service = CrmService(db)
    crm_sync = await service.sync_lead_to_hubspot(
        lead_id=lead_id,
        org_id=current_user.org_id,
        draft_id=req.draft_id,
    )

    audit = AuditService(db)
    await audit.log_action(
        action="crm.sync",
        entity_type="crm_sync",
        entity_id=crm_sync.id,
        changes={
            "lead_id": str(lead_id),
            "provider": crm_sync.crm_provider,
            "status": crm_sync.sync_status.value,
        },
        org_id=current_user.org_id,
        actor_user_id=current_user.id,
    )
    await db.commit()

    return crm_sync


@router.get("/leads/{lead_id}/sync-status", response_model=CrmSyncResponse)
async def get_lead_crm_status(
    lead_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db),
):
    """Queries current HubSpot synchronization status and mapped external record IDs."""
    repo = CrmRepository(db)
    crm_sync = await repo.get_by_lead(lead_id, current_user.org_id)
    if not crm_sync:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No CRM sync record found for this lead."
        )
    return CrmService.with_links(crm_sync)
