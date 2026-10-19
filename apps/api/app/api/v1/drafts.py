import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.constants import DraftApprovalStatus
from app.db.session import get_db
from app.models.contact import Contact
from app.models.draft import Draft
from app.providers.manager import provider_manager
from app.repositories.draft_repo import DraftRepository
from app.schemas.draft import (
    DraftApprovalUpdate,
    DraftGenerateRequest,
    DraftResponse,
    DraftSendResponse,
    DraftUpdate,
)
from app.security.rbac import AuthenticatedUser, require_org_admin
from app.services.audit_service import AuditService
from app.services.draft_service import DraftService


router = APIRouter(tags=["AI Draft Studio & Approval"])


@router.get("/drafts", response_model=List[DraftResponse])
async def list_org_drafts(
    current_user: AuthenticatedUser = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db),
):
    """Lists all outreach drafts for the active tenant organization."""
    stmt = (
        select(Draft)
        .where(Draft.org_id == current_user.org_id)
        .order_by(Draft.created_at.desc())
    )
    res = await db.execute(stmt)
    return list(res.scalars().all())


@router.post(
    "/leads/{lead_id}/drafts", response_model=DraftResponse, status_code=status.HTTP_201_CREATED
)
async def generate_outreach_draft(
    lead_id: uuid.UUID,
    req: Optional[DraftGenerateRequest] = None,
    current_user: AuthenticatedUser = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Generates an AI personalized cold outreach draft using OpenRouter.
    The body is optional: without a contact_id the best contact on file is used.
    Enforces Lead Approval Gate: Target lead must be APPROVED by operator first.
    """
    service = DraftService(db)
    draft = await service.generate_draft(
        lead_id=lead_id,
        org_id=current_user.org_id,
        contact_id=req.contact_id if req else None,
        model=req.model if req else None,
    )

    audit = AuditService(db)
    await audit.log_action(
        action="draft.generate",
        entity_type="draft",
        entity_id=draft.id,
        changes={"lead_id": str(lead_id), "model": draft.model_used},
        org_id=current_user.org_id,
        actor_user_id=current_user.id,
    )
    await db.commit()

    return draft


@router.get("/leads/{lead_id}/drafts", response_model=List[DraftResponse])
async def list_lead_drafts(
    lead_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db),
):
    """Lists all AI-generated outreach drafts for a lead."""
    repo = DraftRepository(db)
    return await repo.list_by_lead(lead_id, current_user.org_id)


@router.patch("/drafts/{draft_id}/approval", response_model=DraftResponse)
async def update_draft_approval(
    draft_id: uuid.UUID,
    req: DraftApprovalUpdate,
    current_user: AuthenticatedUser = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Draft Approval Gate:
    Operator approves or rejects generated outreach copy prior to CRM sync.
    """
    repo = DraftRepository(db)
    draft = await repo.update_approval(
        draft_id=draft_id,
        org_id=current_user.org_id,
        approval_status=req.approval_status,
        approved_by=current_user.id,
    )
    if not draft:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found.")

    audit = AuditService(db)
    await audit.log_action(
        action=f"draft.{req.approval_status.value}",
        entity_type="draft",
        entity_id=draft.id,
        changes={"status": req.approval_status.value},
        org_id=current_user.org_id,
        actor_user_id=current_user.id,
    )
    await db.commit()

    return draft


@router.patch("/drafts/{draft_id}", response_model=DraftResponse)
async def update_draft_content(
    draft_id: uuid.UUID,
    req: DraftUpdate,
    current_user: AuthenticatedUser = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db),
):
    """Allows manual human editing and refinement of AI outreach subject and body."""
    repo = DraftRepository(db)
    draft = await repo.get_by_id(draft_id, org_id=current_user.org_id)
    if not draft:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found.")

    if req.subject is not None:
        draft.subject = req.subject
    if req.body is not None:
        draft.body = req.body

    await db.commit()
    return draft


@router.post("/drafts/{draft_id}/send", response_model=DraftSendResponse)
async def send_draft_email(
    draft_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Sends an approved AI outreach draft directly to the contact's email address via Resend.
    Enforces that:
    - The draft must be in APPROVED status.
    - The contact must be revealed and have an active email address.
    - Resend provider must be configured.
    """
    stmt = (
        select(Draft)
        .options(selectinload(Draft.contact))
        .where(Draft.id == draft_id, Draft.org_id == current_user.org_id)
    )
    draft = (await db.execute(stmt)).scalars().first()
    if not draft:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found.")

    if draft.approval_status != DraftApprovalStatus.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Draft must be approved by an operator before sending.",
        )

    # Resolve recipient contact email
    contact = draft.contact
    if not contact or not contact.email:
        # Check if there is any other revealed contact on the lead with an email
        contact_stmt = (
            select(Contact)
            .where(Contact.lead_id == draft.lead_id, Contact.email.isnot(None), Contact.is_revealed.is_(True))
            .order_by(Contact.created_at.asc())
        )
        contact = (await db.execute(contact_stmt)).scalars().first()

    if not contact or not contact.email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Target prospect has no revealed email address. Please reveal a contact first.",
        )

    if not provider_manager.resend.is_configured():
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Resend email provider is not configured. Please supply RESEND_API_KEY and set RESEND_ENABLED=true in .env.",
        )

    res = await provider_manager.resend.send_outreach_email(
        to_email=contact.email,
        subject=draft.subject,
        body=draft.body,
    )

    if not res.get("success"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Resend failed to deliver email: {res.get('error')}",
        )

    # Log action in audit log
    audit = AuditService(db)
    await audit.log_action(
        action="draft.send_email",
        entity_type="draft",
        entity_id=draft.id,
        changes={
            "recipient": contact.email,
            "subject": draft.subject,
            "message_id": res.get("id"),
        },
        org_id=current_user.org_id,
        actor_user_id=current_user.id,
    )
    await db.commit()

    return DraftSendResponse(
        draft_id=draft.id,
        recipient=contact.email,
        subject=draft.subject,
        message_id=res.get("id"),
        status="sent",
        sent_at=datetime.now(timezone.utc),
    )

