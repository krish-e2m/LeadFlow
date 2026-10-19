import uuid
from typing import Any, Dict

from fastapi import HTTPException

from app.core.constants import ApprovalStatus
from app.core.logging import logger
from app.db.session import tenant_session
from app.models.lead import Lead
from app.security.tenant import set_current_tenant
from app.services.audit_service import AuditService
from app.services.auto_draft import leads_with_open_drafts
from app.services.draft_service import DraftService


async def generate_lead_draft(ctx: Dict[str, Any], lead_id_str: str, org_id_str: str) -> Dict[str, Any]:
    """
    ARQ task queued when a lead is approved: writes one AI email draft addressed to the lead's best
    contact. It is skipped if the lead is no longer approved or already has an open draft.
    """
    lead_id = uuid.UUID(lead_id_str)
    org_id = uuid.UUID(org_id_str)
    set_current_tenant(org_id)

    try:
        async with tenant_session(org_id) as session:
            lead = await session.get(Lead, lead_id)
            if not lead or lead.org_id != org_id or lead.approval_status != ApprovalStatus.APPROVED:
                return {"status": "skipped", "reason": "lead_not_approved"}
            if lead_id in await leads_with_open_drafts(session, [lead_id]):
                return {"status": "skipped", "reason": "draft_exists"}

            draft = await DraftService(session).generate_draft(lead_id=lead_id, org_id=org_id)
            await AuditService(session).log_action(
                action="draft.generate",
                entity_type="draft",
                entity_id=draft.id,
                changes={"lead_id": str(lead_id), "model": draft.model_used, "trigger": "lead_approval"},
                org_id=org_id,
            )
            draft_id = str(draft.id)
        logger.info(f"Auto draft {draft_id} written for lead {lead_id}")
        return {"status": "completed", "draft_id": draft_id}
    except HTTPException as exc:
        logger.warning(f"Auto draft skipped for lead {lead_id}: {exc.detail}")
        return {"status": "failed", "reason": str(exc.detail)}
    except Exception as exc:
        logger.error(f"Auto draft failed for lead {lead_id}: {exc}")
        return {"status": "failed", "reason": str(exc)}
