import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from app.models.audit_log import AuditLog
from app.repositories.base import BaseRepository


class AuditRepository(BaseRepository[AuditLog]):
    def __init__(self, session):
        super().__init__(AuditLog, session)

    async def record_event(
        self,
        action: str,
        entity_type: str,
        entity_id: uuid.UUID,
        changes: Dict[str, Any],
        org_id: Optional[uuid.UUID] = None,
        actor_user_id: Optional[uuid.UUID] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> AuditLog:
        return await self.create(
            org_id=org_id,
            actor_user_id=actor_user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            changes=changes,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    async def list_events(
        self, org_id: Optional[uuid.UUID] = None, skip: int = 0, limit: int = 50
    ) -> List[AuditLog]:
        stmt = select(AuditLog)
        if org_id:
            stmt = stmt.where(AuditLog.org_id == org_id)
        stmt = stmt.order_by(AuditLog.created_at.desc()).offset(skip).limit(limit)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())
