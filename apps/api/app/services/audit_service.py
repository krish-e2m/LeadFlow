import uuid
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.repositories.audit_repo import AuditRepository


class AuditService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.audit_repo = AuditRepository(session)

    async def log_action(
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
        return await self.audit_repo.record_event(
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            changes=changes,
            org_id=org_id,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
