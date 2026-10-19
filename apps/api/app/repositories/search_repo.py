import uuid
from typing import List

from sqlalchemy import select

from app.models.search import Search
from app.repositories.base import BaseRepository


class SearchRepository(BaseRepository[Search]):
    def __init__(self, session):
        super().__init__(Search, session)

    async def list_by_org(self, org_id: uuid.UUID, skip: int = 0, limit: int = 20) -> List[Search]:
        stmt = (
            select(Search)
            .where(Search.org_id == org_id)
            .order_by(Search.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())
