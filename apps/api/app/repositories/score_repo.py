import uuid
from typing import List, Optional

from sqlalchemy import select

from app.models.score import Score
from app.repositories.base import BaseRepository


class ScoreRepository(BaseRepository[Score]):
    def __init__(self, session):
        super().__init__(Score, session)

    async def get_latest_for_lead(self, lead_id: uuid.UUID, org_id: uuid.UUID) -> Optional[Score]:
        stmt = (
            select(Score)
            .where(Score.lead_id == lead_id, Score.org_id == org_id)
            .order_by(Score.created_at.desc())
        )
        res = await self.session.execute(stmt)
        return res.scalars().first()

    async def list_history_for_lead(self, lead_id: uuid.UUID, org_id: uuid.UUID) -> List[Score]:
        stmt = (
            select(Score)
            .where(Score.lead_id == lead_id, Score.org_id == org_id)
            .order_by(Score.created_at.desc())
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())
