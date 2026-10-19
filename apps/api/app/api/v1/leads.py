import csv
import io
import json
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.constants import ApprovalStatus, PipelineStatus, ScoreBand, UserRole
from app.db.session import get_db
from app.models.lead import Lead
from app.repositories.lead_repo import LeadRepository
from app.schemas.lead import (
    BulkActionType,
    BulkItemResult,
    BulkLeadActionRequest,
    BulkLeadActionResponse,
    LeadApprovalUpdate,
    LeadDetailResponse,
    LeadResponse,
)
from app.schemas.score import ScoreResponse
from app.security.rbac import AuthenticatedUser, require_authenticated, require_org_admin
from app.services.audit_service import AuditService
from app.services.auto_draft import QUEUED, dispatch_auto_drafts, plan_auto_drafts
from app.services.scoring_service import ScoringService

router = APIRouter(prefix="/leads", tags=["Leads & Pipeline"])


def _sanitize_csv_cell(val: Any) -> Any:
    """Neutralizes CSV formula injection by prefixing suspicious symbols with a single quote."""
    if val is None:
        return ""
    if isinstance(val, (int, float, bool)):
        return val
    s = str(val).strip()
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{s}"
    return s


@router.get("/export")
async def export_leads(
    format: str = Query("csv", pattern="^(csv|json)$", description="Export file format: csv or json"),
    pipeline_status: Optional[PipelineStatus] = None,
    score_band: Optional[ScoreBand] = None,
    approval_status: Optional[ApprovalStatus] = None,
    search: Optional[str] = Query(None, description="Search by domain or company name"),
    limit: int = Query(500, ge=1, le=1000, description="Max leads to export (up to 1000)"),
    current_user: AuthenticatedUser = Depends(require_authenticated),
    db: AsyncSession = Depends(get_db),
):
    """
    Exports authorized tenant leads in CSV or JSON format.
    - Tenant-scoped: strictly restricted to current organization.
    - Client viewer mode restricted to approved leads only.
    - Contact privacy: strictly omits unrevealed contact emails and phone numbers.
    - CSV formula injection protection: neutralizes =, +, -, @ prefixes.
    - Records an audit event for export execution.
    """
    effective_approval = approval_status
    if current_user.role == UserRole.CLIENT_VIEWER:
        effective_approval = ApprovalStatus.APPROVED

    stmt = (
        select(Lead)
        .where(Lead.org_id == current_user.org_id, Lead.deleted_at.is_(None))
        .options(
            selectinload(Lead.scores),
            selectinload(Lead.contacts),
        )
    )

    if pipeline_status:
        stmt = stmt.where(Lead.pipeline_status == pipeline_status)
    if score_band:
        stmt = stmt.where(Lead.score_band == score_band)
    if effective_approval:
        stmt = stmt.where(Lead.approval_status == effective_approval)
    if search:
        term = f"%{search}%"
        stmt = stmt.where((Lead.company_name.ilike(term)) | (Lead.domain.ilike(term)))

    stmt = stmt.order_by(Lead.created_at.desc()).limit(limit)
    res = await db.execute(stmt)
    leads_list = list(res.scalars().all())

    # Build sanitized record rows
    records = []
    for lead in leads_list:
        latest_score = lead.scores[0] if lead.scores else None

        # Collect strictly revealed contact details
        revealed_contact_name = ""
        revealed_contact_email = ""
        revealed_contact_phone = ""
        revealed_contact_title = ""
        for c in lead.contacts:
            if c.is_revealed:
                full_n = f"{c.first_name or ''} {c.last_name or ''}".strip()
                revealed_contact_name = full_n or revealed_contact_name
                revealed_contact_email = c.email or revealed_contact_email
                revealed_contact_phone = c.phone or revealed_contact_phone
                revealed_contact_title = c.title or revealed_contact_title
                break

        records.append({
            "id": str(lead.id),
            "company_name": lead.company_name,
            "domain": lead.domain,
            "industry": lead.industry or "",
            "country": lead.country or "",
            "city": lead.city or "",
            "employee_count": lead.employee_count or "",
            "pipeline_status": lead.pipeline_status.value,
            "score_band": lead.score_band.value if lead.score_band else "unscored",
            "approval_status": lead.approval_status.value,
            "overall_score": latest_score.overall_score if latest_score else "",
            "website_subscore": latest_score.website_subscore if latest_score else "",
            "marketing_subscore": latest_score.marketing_subscore if latest_score else "",
            "contact_name": revealed_contact_name,
            "contact_title": revealed_contact_title,
            "contact_email": revealed_contact_email,
            "contact_phone": revealed_contact_phone,
            "created_at": lead.created_at.isoformat(),
        })

    # Log audit event
    audit_service = AuditService(db)
    await audit_service.log_action(
        action="export.leads",
        entity_type="export",
        entity_id=current_user.id,
        changes={"format": format, "count": len(records), "limit": limit},
        org_id=current_user.org_id,
        actor_user_id=current_user.id,
    )
    await db.commit()

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    if format == "json":
        json_content = json.dumps(records, indent=2, default=str)
        return Response(
            content=json_content,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="leads_export_{timestamp}.json"'
            },
        )

    # Format == "csv"
    output = io.StringIO()
    headers = [
        "id",
        "company_name",
        "domain",
        "industry",
        "country",
        "city",
        "employee_count",
        "pipeline_status",
        "score_band",
        "approval_status",
        "overall_score",
        "website_subscore",
        "marketing_subscore",
        "contact_name",
        "contact_title",
        "contact_email",
        "contact_phone",
        "created_at",
    ]
    writer = csv.writer(output)
    writer.writerow(headers)

    for r in records:
        row = [_sanitize_csv_cell(r[h]) for h in headers]
        writer.writerow(row)

    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="leads_export_{timestamp}.csv"'
        },
    )


@router.post("/bulk", response_model=BulkLeadActionResponse)
async def bulk_lead_action(
    payload: BulkLeadActionRequest,
    current_user: AuthenticatedUser = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Executes bounded bulk workflow actions on leads.
    - Supported actions: approve, reject, archive, unarchive, rescore.
    - Validates batch size ceiling (max 100 leads per request).
    - Prevents workflow bypass (disqualified leads cannot be approved).
    - Preserves tenant isolation: unauthorized or missing leads fail safely.
    - Records comprehensive audit trail with outcome metrics.
    """
    if not payload.lead_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No lead IDs provided for bulk operation.",
        )

    if len(payload.lead_ids) > settings.MAX_BULK_BATCH_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Batch size ({len(payload.lead_ids)}) exceeds maximum limit of {settings.MAX_BULK_BATCH_SIZE} leads.",
        )

    scoring_service = ScoringService(db) if payload.action == BulkActionType.RESCORE else None
    results: List[BulkItemResult] = []
    succeeded = 0
    failed = 0
    now = datetime.now(timezone.utc)
    newly_approved: List[uuid.UUID] = []

    for lead_id in payload.lead_ids:
        # Query within tenant organization boundary
        stmt = select(Lead).where(Lead.id == lead_id, Lead.org_id == current_user.org_id)
        lead = (await db.execute(stmt)).scalars().first()

        if not lead:
            results.append(
                BulkItemResult(
                    lead_id=lead_id,
                    success=False,
                    error="Lead not found or unauthorized.",
                )
            )
            failed += 1
            continue

        try:
            if payload.action == BulkActionType.APPROVE:
                # Workflow gate: Disqualified or rejected leads cannot be approved in bulk
                if (
                    lead.pipeline_status == PipelineStatus.DISQUALIFIED
                    or lead.score_band == ScoreBand.DISQUALIFIED
                    or lead.approval_status == ApprovalStatus.REJECTED
                ):
                    results.append(
                        BulkItemResult(
                            lead_id=lead_id,
                            success=False,
                            error="Cannot approve disqualified or rejected lead.",
                        )
                    )
                    failed += 1
                    continue

                if lead.approval_status != ApprovalStatus.APPROVED:
                    newly_approved.append(lead.id)
                lead.approval_status = ApprovalStatus.APPROVED
                lead.approved_by = current_user.id
                lead.approved_at = now
                if lead.pipeline_status in [PipelineStatus.SCORED, PipelineStatus.SOURCED]:
                    lead.pipeline_status = PipelineStatus.APPROVED
                results.append(
                    BulkItemResult(lead_id=lead_id, success=True, status="approved")
                )
                succeeded += 1

            elif payload.action == BulkActionType.REJECT:
                lead.approval_status = ApprovalStatus.REJECTED
                lead.pipeline_status = PipelineStatus.DISQUALIFIED
                results.append(
                    BulkItemResult(lead_id=lead_id, success=True, status="rejected")
                )
                succeeded += 1

            elif payload.action == BulkActionType.ARCHIVE:
                lead.deleted_at = now
                results.append(
                    BulkItemResult(lead_id=lead_id, success=True, status="archived")
                )
                succeeded += 1

            elif payload.action == BulkActionType.UNARCHIVE:
                lead.deleted_at = None
                results.append(
                    BulkItemResult(lead_id=lead_id, success=True, status="unarchived")
                )
                succeeded += 1

            elif payload.action == BulkActionType.RESCORE:
                if (
                    lead.pipeline_status == PipelineStatus.DISQUALIFIED
                    or lead.approval_status == ApprovalStatus.REJECTED
                ):
                    results.append(
                        BulkItemResult(
                            lead_id=lead_id,
                            success=False,
                            error="Cannot rescore disqualified lead.",
                        )
                    )
                    failed += 1
                    continue

                await scoring_service.score_lead(lead, engine_id=payload.engine_id)
                results.append(
                    BulkItemResult(lead_id=lead_id, success=True, status="rescored")
                )
                succeeded += 1

        except Exception as e:
            results.append(
                BulkItemResult(lead_id=lead_id, success=False, error=str(e))
            )
            failed += 1

    await db.flush()

    # Record Audit Event
    audit_service = AuditService(db)
    await audit_service.log_action(
        action=f"lead.bulk_{payload.action.value}",
        entity_type="lead_bulk",
        entity_id=current_user.id,
        changes={
            "action": payload.action.value,
            "total_requested": len(payload.lead_ids),
            "succeeded": succeeded,
            "failed": failed,
        },
        org_id=current_user.org_id,
        actor_user_id=current_user.id,
    )
    draft_plan = await plan_auto_drafts(db, newly_approved) if newly_approved else None
    await db.commit()

    drafts_queued = 0
    if draft_plan is not None:
        outcome = await dispatch_auto_drafts(current_user.org_id, draft_plan)
        drafts_queued = sum(1 for v in outcome.values() if v == QUEUED)

    return BulkLeadActionResponse(
        action=payload.action.value,
        total_requested=len(payload.lead_ids),
        total_succeeded=succeeded,
        total_failed=failed,
        results=results,
        drafts_queued=drafts_queued,
    )


@router.get("", response_model=List[LeadResponse])
async def list_leads(
    pipeline_status: Optional[PipelineStatus] = None,
    score_band: Optional[ScoreBand] = None,
    approval_status: Optional[ApprovalStatus] = None,
    search: Optional[str] = Query(None, description="Search by domain or company name"),
    skip: int = 0,
    limit: int = 50,
    current_user: AuthenticatedUser = Depends(require_authenticated),
    db: AsyncSession = Depends(get_db),
):
    """
    Lists leads for the active organization with multi-attribute filtering.
    Restricted client_viewers may only observe approved leads.
    """
    # Enforce client_viewer boundary
    effective_approval = approval_status
    if current_user.role == UserRole.CLIENT_VIEWER:
        effective_approval = ApprovalStatus.APPROVED

    repo = LeadRepository(db)
    return await repo.list_filtered(
        org_id=current_user.org_id,
        pipeline_status=pipeline_status,
        score_band=score_band,
        approval_status=effective_approval,
        search_query=search,
        skip=skip,
        limit=limit,
    )


@router.get("/{lead_id}", response_model=LeadDetailResponse)
async def get_lead(
    lead_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_authenticated),
    db: AsyncSession = Depends(get_db),
):
    """Retrieves full lead details including historical scores, technical audits, contacts, and drafts."""
    repo = LeadRepository(db)
    lead = await repo.get_with_details(lead_id, org_id=current_user.org_id)
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found.")

    if (
        current_user.role == UserRole.CLIENT_VIEWER
        and lead.approval_status != ApprovalStatus.APPROVED
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to unapproved lead."
        )

    return lead


@router.patch("/{lead_id}/approval", response_model=LeadResponse)
async def update_lead_approval(
    lead_id: uuid.UUID,
    payload: LeadApprovalUpdate,
    current_user: AuthenticatedUser = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Human Approval Gate:
    Explicitly approve or reject a scored lead before AI drafting, contact reveals, or CRM export.
    """
    repo = LeadRepository(db)
    lead = await repo.get_by_id(lead_id, org_id=current_user.org_id)
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found.")

    previous_status = lead.approval_status.value

    # Workflow Gate: Disqualified leads cannot be silently approved
    is_disqualified = (
        lead.score_band == ScoreBand.DISQUALIFIED
        or lead.pipeline_status == PipelineStatus.DISQUALIFIED
        or lead.approval_status == ApprovalStatus.REJECTED
    )

    if payload.approval_status == ApprovalStatus.APPROVED and is_disqualified:
        if not payload.manual_override or not (payload.override_reason and payload.override_reason.strip()):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Workflow Policy Violation: Disqualified leads cannot be approved without an explicit manual override and reason.",
            )

    lead.approval_status = payload.approval_status
    if payload.approval_status == ApprovalStatus.APPROVED:
        lead.approved_by = current_user.id
        lead.approved_at = datetime.now(timezone.utc)
        if lead.pipeline_status in [PipelineStatus.SCORED, PipelineStatus.SOURCED, PipelineStatus.DISQUALIFIED]:
            lead.pipeline_status = PipelineStatus.APPROVED
    elif payload.approval_status == ApprovalStatus.REJECTED:
        lead.pipeline_status = PipelineStatus.DISQUALIFIED

    await db.flush()

    # Record Audit Event
    audit_action = (
        "lead.approved_override"
        if (payload.approval_status == ApprovalStatus.APPROVED and is_disqualified and payload.manual_override)
        else f"lead.{payload.approval_status.value}"
    )
    audit_changes: dict = {"from": previous_status, "to": payload.approval_status.value}
    if is_disqualified and payload.manual_override and payload.approval_status == ApprovalStatus.APPROVED:
        audit_changes["manual_override"] = True
        audit_changes["override_reason"] = payload.override_reason.strip()

    audit_service = AuditService(db)
    await audit_service.log_action(
        action=audit_action,
        entity_type="lead",
        entity_id=lead.id,
        changes=audit_changes,
        org_id=current_user.org_id,
        actor_user_id=current_user.id,
    )

    # A newly approved lead gets an email draft written in the background.
    newly_approved = (
        payload.approval_status == ApprovalStatus.APPROVED and previous_status != ApprovalStatus.APPROVED.value
    )
    draft_plan = await plan_auto_drafts(db, [lead.id]) if newly_approved else None
    await db.commit()

    if draft_plan is not None:
        outcome = await dispatch_auto_drafts(current_user.org_id, draft_plan)
        lead.auto_draft = outcome.get(lead.id)

    return lead


@router.post("/{lead_id}/rescore", response_model=ScoreResponse)
async def rescore_lead(
    lead_id: uuid.UUID,
    engine_id: Optional[uuid.UUID] = None,
    current_user: AuthenticatedUser = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Re-scores a lead using existing enrichment data and active engine weights.
    Preserves audit history and appends a new Score record.
    """
    repo = LeadRepository(db)
    lead = await repo.get_by_id(lead_id, org_id=current_user.org_id)
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found.")

    scoring_service = ScoringService(db)
    new_score = await scoring_service.score_lead(lead, engine_id=engine_id)
    await db.commit()
    return new_score
