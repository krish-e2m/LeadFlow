import uuid
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.constants import ApprovalStatus, PipelineStatus, ScoreBand
from app.models.lead import Lead
from app.repositories.base import BaseRepository


class LeadRepository(BaseRepository[Lead]):
    def __init__(self, session):
        super().__init__(Lead, session)

    async def get_by_domain(self, domain: str, org_id: uuid.UUID) -> Optional[Lead]:
        stmt = select(Lead).where(
            Lead.org_id == org_id, Lead.domain == domain, Lead.deleted_at.is_(None)
        )
        res = await self.session.execute(stmt)
        return res.scalars().first()

    async def get_with_details(self, lead_id: uuid.UUID, org_id: uuid.UUID) -> Optional[Lead]:
        stmt = (
            select(Lead)
            .where(Lead.id == lead_id, Lead.org_id == org_id, Lead.deleted_at.is_(None))
            .options(
                selectinload(Lead.scores),
                selectinload(Lead.enrichments),
                selectinload(Lead.contacts),
                selectinload(Lead.drafts),
                selectinload(Lead.crm_syncs),
            )
        )
        res = await self.session.execute(stmt)
        return res.scalars().first()

    async def list_filtered(
        self,
        org_id: uuid.UUID,
        pipeline_status: Optional[PipelineStatus] = None,
        score_band: Optional[ScoreBand] = None,
        approval_status: Optional[ApprovalStatus] = None,
        search_query: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[Lead]:
        stmt = select(Lead).where(Lead.org_id == org_id, Lead.deleted_at.is_(None))

        if pipeline_status:
            stmt = stmt.where(Lead.pipeline_status == pipeline_status)
        if score_band:
            stmt = stmt.where(Lead.score_band == score_band)
        if approval_status:
            stmt = stmt.where(Lead.approval_status == approval_status)
        if search_query:
            term = f"%{search_query}%"
            stmt = stmt.where((Lead.company_name.ilike(term)) | (Lead.domain.ilike(term)))

        stmt = stmt.order_by(Lead.created_at.desc()).offset(skip).limit(limit)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())
