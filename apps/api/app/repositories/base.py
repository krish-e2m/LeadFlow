import uuid
from typing import Generic, List, Optional, Type, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """Base async repository providing tenant-scoped query and mutation primitives."""

    def __init__(self, model: Type[ModelType], session: AsyncSession):
        self.model = model
        self.session = session

    async def get_by_id(
        self, entity_id: uuid.UUID, org_id: Optional[uuid.UUID] = None
    ) -> Optional[ModelType]:
        stmt = select(self.model).where(self.model.id == entity_id)
        if org_id and hasattr(self.model, "org_id"):
            stmt = stmt.where(self.model.org_id == org_id)
        if hasattr(self.model, "deleted_at"):
            stmt = stmt.where(self.model.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list(
        self, org_id: Optional[uuid.UUID] = None, skip: int = 0, limit: int = 50, order_by=None
    ) -> List[ModelType]:
        stmt = select(self.model)
        if org_id and hasattr(self.model, "org_id"):
            stmt = stmt.where(self.model.org_id == org_id)
        if hasattr(self.model, "deleted_at"):
            stmt = stmt.where(self.model.deleted_at.is_(None))
        if order_by is not None:
            stmt = stmt.order_by(order_by)
        stmt = stmt.offset(skip).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count(self, org_id: Optional[uuid.UUID] = None) -> int:
        stmt = select(func.count(self.model.id))
        if org_id and hasattr(self.model, "org_id"):
            stmt = stmt.where(self.model.org_id == org_id)
        if hasattr(self.model, "deleted_at"):
            stmt = stmt.where(self.model.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def create(self, **kwargs) -> ModelType:
        instance = self.model(**kwargs)
        self.session.add(instance)
        await self.session.flush()
        return instance

    async def update(
        self, entity_id: uuid.UUID, org_id: Optional[uuid.UUID] = None, **kwargs
    ) -> Optional[ModelType]:
        instance = await self.get_by_id(entity_id, org_id=org_id)
        if not instance:
            return None
        for key, value in kwargs.items():
            if hasattr(instance, key):
                setattr(instance, key, value)
        await self.session.flush()
        return instance

    async def soft_delete(self, entity_id: uuid.UUID, org_id: Optional[uuid.UUID] = None) -> bool:
        from datetime import datetime, timezone

        instance = await self.get_by_id(entity_id, org_id=org_id)
        if not instance or not hasattr(instance, "deleted_at"):
            return False
        instance.deleted_at = datetime.now(timezone.utc)
        await self.session.flush()
        return True
