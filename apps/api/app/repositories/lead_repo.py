import uuid
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.constants import ApprovalStatus, PipelineStatus, ScoreBand
from app.models.enrichment import Enrichment
from app.models.lead import Lead
from app.models.score import Score
from app.repositories.base import BaseRepository


def latest_score_subquery():
    """The lead's most recent overall score, for ranking the pipeline by score."""
    return (
        select(Score.overall_score)
        .where(Score.lead_id == Lead.id)
        .order_by(Score.created_at.desc())
        .limit(1)
        .correlate(Lead)
        .scalar_subquery()
    )


class LeadRepository(BaseRepository[Lead]):
    def __init__(self, session):
        super().__init__(Lead, session)

    async def get_by_domain(self, domain: str, org_id: uuid.UUID) -> Optional[Lead]:
        stmt = select(Lead).where(
            Lead.org_id == org_id, Lead.domain == domain, Lead.deleted_at.is_(None)
        )
        res = await self.session.execute(stmt)
        return res.scalars().first()

    async def get_with_details(
        self, lead_id: uuid.UUID, org_id: uuid.UUID, include_archived: bool = False
    ) -> Optional[Lead]:
        stmt = (
            select(Lead)
            .where(Lead.id == lead_id, Lead.org_id == org_id)
            .options(
                selectinload(Lead.scores),
                selectinload(Lead.contacts),
                selectinload(Lead.drafts),
            )
        )
        if not include_archived:
            stmt = stmt.where(Lead.deleted_at.is_(None))
        res = await self.session.execute(stmt)
        return res.scalars().first()

    async def latest_enrichment(self, lead_id: uuid.UUID) -> Optional[Enrichment]:
        stmt = (
            select(Enrichment)
            .where(Enrichment.lead_id == lead_id)
            .order_by(Enrichment.version.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def list_filtered(
        self,
        org_id: uuid.UUID,
        pipeline_status: Optional[PipelineStatus] = None,
        score_band: Optional[ScoreBand] = None,
        approval_status: Optional[ApprovalStatus] = None,
        search_query: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
        archived: bool = False,
        sort: str = "score",
    ) -> List[Lead]:
        """
        Lists leads with their latest score attached as `overall_score`. Sorted by score (the
        ranked funnel the product promises) unless sort="newest". `archived=True` lists only
        archived leads so they can be found and restored.
        """
        score_col = latest_score_subquery()
        stmt = select(Lead, score_col.label("overall_score")).where(Lead.org_id == org_id)
        stmt = stmt.where(Lead.deleted_at.is_not(None) if archived else Lead.deleted_at.is_(None))

        if pipeline_status:
            stmt = stmt.where(Lead.pipeline_status == pipeline_status)
        if score_band:
            stmt = stmt.where(Lead.score_band == score_band)
        if approval_status:
            stmt = stmt.where(Lead.approval_status == approval_status)
        if search_query:
            term = f"%{search_query}%"
            stmt = stmt.where((Lead.company_name.ilike(term)) | (Lead.domain.ilike(term)))

        if sort == "newest":
            stmt = stmt.order_by(Lead.created_at.desc())
        else:
            stmt = stmt.order_by(score_col.desc().nulls_last(), Lead.created_at.desc())
        stmt = stmt.offset(skip).limit(limit)

        leads: List[Lead] = []
        for lead, overall_score in (await self.session.execute(stmt)).all():
            lead.overall_score = overall_score
            leads.append(lead)
        return leads
