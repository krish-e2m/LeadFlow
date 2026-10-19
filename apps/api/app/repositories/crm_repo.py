import uuid
from typing import Optional

from sqlalchemy import select

from app.models.crm_sync import CrmSync
from app.repositories.base import BaseRepository


class CrmRepository(BaseRepository[CrmSync]):
    def __init__(self, session):
        super().__init__(CrmSync, session)

    async def get_by_lead(self, lead_id: uuid.UUID, org_id: uuid.UUID) -> Optional[CrmSync]:
        stmt = (
            select(CrmSync)
            .where(CrmSync.lead_id == lead_id, CrmSync.org_id == org_id)
            .order_by(CrmSync.created_at.desc())
        )
        res = await self.session.execute(stmt)
        return res.scalars().first()
