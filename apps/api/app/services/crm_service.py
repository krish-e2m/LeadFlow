import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import ApprovalStatus, CrmSyncStatus, DraftApprovalStatus, PipelineStatus
from app.core.logging import logger
from app.models.contact import Contact
from app.models.crm_sync import CrmSync
from app.models.draft import Draft
from app.models.lead import Lead
from app.models.score import Score
from app.providers.hubspot import HubSpotError, record_url
from app.providers.manager import provider_manager


def idempotency_key(provider: str, lead_id: uuid.UUID, draft_id: uuid.UUID) -> str:
    return f"{provider}:{lead_id}:{draft_id}"


class CrmService:
    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def with_links(crm_sync: CrmSync, already_synced: bool = False) -> CrmSync:
        """Attaches the non-persisted response fields (record links, replay flag) to a sync record."""
        portal = provider_manager.hubspot.portal_id
        crm_sync.already_synced = already_synced  # type: ignore[attr-defined]
        crm_sync.crm_company_url = record_url(portal, "0-2", crm_sync.crm_company_id)  # type: ignore[attr-defined]
        crm_sync.crm_contact_url = record_url(portal, "0-1", crm_sync.crm_contact_id)  # type: ignore[attr-defined]
        return crm_sync

    async def _score_context(self, lead: Lead) -> List[str]:
        """Short, factual lines for the CRM note: the score, band and the strongest findings."""
        stmt = select(Score).where(Score.lead_id == lead.id).order_by(Score.created_at.desc())
        score = (await self.session.execute(stmt)).scalars().first()
        if not score or score.overall_score is None:
            return []
        band = score.score_band.value if score.score_band else "unscored"
        lines = [f"LeadFlow score: {score.overall_score:.1f}/100 ({band})"]
        findings = [
            f"- {d.get('label')}: {d.get('evidence')}"
            for key, d in (score.signal_details or {}).items()
            if not key.startswith("_")
            and isinstance(d, dict)
            and d.get("is_available")
            and (d.get("value") or 0) >= 0.7
            and d.get("evidence")
        ]
        return lines + findings[:3]

    async def sync_lead_to_hubspot(
        self,
        lead_id: uuid.UUID,
        org_id: uuid.UUID,
        draft_id: Optional[uuid.UUID] = None,
    ) -> CrmSync:
        """
        Idempotently synchronizes an approved lead and its approved outreach draft to HubSpot.

        SAFETY GATES (poc.md): the lead must be approved, a draft must be provided, and that
        draft must be approved. Syncing the same lead and draft again returns the existing
        record without calling HubSpot, so a double click never creates a second note.
        """
        # 1. Lead
        l_stmt = select(Lead).where(Lead.id == lead_id, Lead.org_id == org_id, Lead.deleted_at.is_(None))
        lead = (await self.session.execute(l_stmt)).scalars().first()
        if not lead:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found.")

        if lead.approval_status != ApprovalStatus.APPROVED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Workflow Policy Violation: Lead must be approved by an operator before CRM export.",
            )

        # 2. Draft (required) and its approval gate
        if not draft_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Workflow Policy Violation: An approved draft is required before CRM synchronization.",
            )
        d_stmt = select(Draft).where(Draft.id == draft_id, Draft.org_id == org_id, Draft.lead_id == lead.id)
        draft = (await self.session.execute(d_stmt)).scalars().first()
        if not draft:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found for this lead.")
        if draft.approval_status != DraftApprovalStatus.APPROVED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Workflow Policy Violation: Draft must be approved by an operator before CRM synchronization.",
            )

        # 3. Idempotency: one sync record per lead; the same draft never syncs twice
        key = idempotency_key("hubspot", lead.id, draft.id)
        sync_stmt = select(CrmSync).where(CrmSync.lead_id == lead.id, CrmSync.org_id == org_id)
        crm_sync = (await self.session.execute(sync_stmt)).scalars().first()
        if crm_sync and crm_sync.sync_status == CrmSyncStatus.SUCCESS and crm_sync.idempotency_key == key:
            return self.with_links(crm_sync, already_synced=True)

        if not provider_manager.hubspot.is_configured():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="HubSpot isn't connected. Set HUBSPOT_ENABLED=true and HUBSPOT_ACCESS_TOKEN, then try again.",
            )

        if not crm_sync:
            crm_sync = CrmSync(org_id=org_id, lead_id=lead.id, crm_provider="hubspot", sync_status=CrmSyncStatus.PENDING)
            self.session.add(crm_sync)
        crm_sync.draft_id = draft.id
        crm_sync.idempotency_key = key
        await self.session.flush()

        # 4. Contact: only a revealed email is ever sent to the CRM
        contact: Optional[Contact] = None
        if draft.contact_id:
            c_stmt = select(Contact).where(Contact.id == draft.contact_id, Contact.org_id == org_id)
            contact = (await self.session.execute(c_stmt)).scalars().first()
        revealed = bool(contact and contact.is_revealed and contact.email)

        # 5. Live HubSpot call
        try:
            result = await provider_manager.hubspot.sync_prospect(
                company_name=lead.company_name,
                domain=lead.domain,
                contact_email=contact.email if (contact and revealed) else None,
                contact_first_name=contact.first_name if contact else None,
                contact_last_name=contact.last_name if contact else None,
                contact_title=contact.title if contact else None,
                draft_subject=draft.subject,
                draft_body=draft.body,
                company_city=lead.city,
                company_country=lead.country,
                company_employees=lead.employee_count,
                note_context=await self._score_context(lead),
            )
        except (HubSpotError, RuntimeError) as exc:
            crm_sync.sync_status = CrmSyncStatus.FAILED
            crm_sync.retry_count += 1
            crm_sync.error_message = str(exc)[:1000]
            # Persist the failure before raising: the request transaction rolls back on an exception.
            await self.session.commit()
            logger.warning(f"HubSpot sync failed for lead {lead.id}: {exc}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=f"HubSpot synchronization failed: {exc}"
            )

        crm_sync.crm_company_id = result.get("crm_company_id")
        crm_sync.crm_contact_id = result.get("crm_contact_id")
        crm_sync.crm_engagement_id = result.get("crm_engagement_id")
        crm_sync.sync_status = CrmSyncStatus.SUCCESS
        crm_sync.synced_at = datetime.now(timezone.utc)
        crm_sync.error_message = None
        lead.pipeline_status = PipelineStatus.SYNCED
        await self.session.flush()
        return self.with_links(crm_sync)
