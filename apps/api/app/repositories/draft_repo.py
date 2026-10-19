import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select

from app.core.constants import DraftApprovalStatus
from app.models.draft import Draft
from app.repositories.base import BaseRepository


class DraftRepository(BaseRepository[Draft]):
    def __init__(self, session):
        super().__init__(Draft, session)

    async def list_by_lead(self, lead_id: uuid.UUID, org_id: uuid.UUID) -> List[Draft]:
        stmt = (
            select(Draft)
            .where(Draft.lead_id == lead_id, Draft.org_id == org_id)
            .order_by(Draft.created_at.desc())
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def update_approval(
        self,
        draft_id: uuid.UUID,
        org_id: uuid.UUID,
        approval_status: DraftApprovalStatus,
        approved_by: uuid.UUID,
    ) -> Optional[Draft]:
        draft = await self.get_by_id(draft_id, org_id=org_id)
        if not draft:
            return None

        draft.approval_status = approval_status
        draft.approved_by = approved_by
        draft.approved_at = datetime.now(timezone.utc)
        await self.session.flush()
        return draft
