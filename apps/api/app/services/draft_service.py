import uuid
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import ApprovalStatus, DraftApprovalStatus, PipelineStatus
from app.models.contact import Contact
from app.models.draft import Draft
from app.models.lead import Lead
from app.models.score import Score
from app.providers.manager import provider_manager


class DraftService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def pick_contact(self, lead_id: uuid.UUID, org_id: uuid.UUID) -> Optional[Contact]:
        """The person a draft is addressed to: the first revealed contact, else the first one found."""
        stmt = (
            select(Contact)
            .where(Contact.lead_id == lead_id, Contact.org_id == org_id)
            .order_by(Contact.is_revealed.desc(), Contact.created_at.asc())
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def generate_draft(
        self,
        lead_id: uuid.UUID,
        org_id: uuid.UUID,
        contact_id: Optional[uuid.UUID] = None,
        model: Optional[str] = None,
    ) -> Draft:
        """
        Generates an AI outreach draft tailored to verified technical audit findings.

        SAFETY GATE:
        Enforces that the target Lead MUST be in APPROVED status before any AI credits
        are spent or drafts are generated.
        """
        # 0. Validate Organization active status
        from app.models.organization import Organization
        from app.services.quota_service import QuotaService

        org_stmt = select(Organization).where(
            Organization.id == org_id, Organization.deleted_at.is_(None)
        )
        org = (await self.session.execute(org_stmt)).scalars().first()
        if not org or not org.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Organization is inactive or suspended. Cannot generate outreach draft.",
            )

        # 1. Fetch and validate Lead
        stmt = select(Lead).where(
            Lead.id == lead_id, Lead.org_id == org_id, Lead.deleted_at.is_(None)
        )
        lead = (await self.session.execute(stmt)).scalars().first()
        if not lead:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found.")

        # Hard Guardrail Check
        if lead.approval_status != ApprovalStatus.APPROVED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Workflow Policy Violation: Lead must be approved by an operator before generating an outreach draft.",
            )

        if not provider_manager.openrouter.is_configured():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Draft writing needs OpenRouter. Set OPENROUTER_API_KEY, then try again.",
            )

        # 2. Check and reserve daily draft generation quota
        await QuotaService.check_and_reserve_draft_generation(org_id, self.session)

        # 3. Contact: the one requested, otherwise the best one on file
        contact: Optional[Contact] = None
        if contact_id:
            c_stmt = select(Contact).where(
                Contact.id == contact_id, Contact.org_id == org_id, Contact.lead_id == lead.id
            )
            contact = (await self.session.execute(c_stmt)).scalars().first()
        else:
            contact = await self.pick_contact(lead.id, org_id)

        # 3. Fetch latest score and signal evidence
        s_stmt = select(Score).where(Score.lead_id == lead.id).order_by(Score.created_at.desc())
        latest_score = (await self.session.execute(s_stmt)).scalars().first()

        signal_details = latest_score.signal_details if latest_score else {}
        overall_score = latest_score.overall_score if latest_score else 0.0
        score_band = latest_score.score_band.value if (latest_score and latest_score.score_band) else "unscored"

        # 4. Invoke OpenRouter Provider Adapter
        lead.pipeline_status = PipelineStatus.DRAFTING
        await self.session.flush()

        contact_name = " ".join(p for p in [contact.first_name, contact.last_name] if p) if contact else None
        try:
            ai_response = await provider_manager.openrouter.generate_outreach_draft(
                company_name=lead.company_name,
                domain=lead.domain,
                contact_name=contact_name or None,
                contact_title=contact.title if contact else None,
                score=overall_score or 0.0,
                score_band=score_band,
                signal_details=signal_details,
                model=model,
            )
        except Exception as exc:
            # Nothing was written, so the draft doesn't count against today's quota.
            await QuotaService.release_draft_generation(org_id)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"The AI draft couldn't be written: {str(exc)[:300]}",
            )

        # 5. Persist Draft with PENDING approval status
        draft = Draft(
            org_id=org_id,
            lead_id=lead.id,
            contact_id=contact.id if contact else None,
            subject=ai_response["subject"],
            body=ai_response["body"],
            model_used=ai_response["model_used"],
            audit_citations=ai_response["citations_used"],
            approval_status=DraftApprovalStatus.PENDING,  # Must be approved before CRM sync
        )
        self.session.add(draft)

        lead.pipeline_status = PipelineStatus.DRAFTED
        await self.session.flush()

        return draft
