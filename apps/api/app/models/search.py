import uuid
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.audience import Audience
    from app.models.lead import Lead
    from app.models.run import Run
    from app.models.user import User


class Search(Base, UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin):
    """Lead discovery search definition."""

    __tablename__ = "searches"

    audience_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audiences.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    query_params: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    # Relationships
    audience: Mapped[Optional["Audience"]] = relationship("Audience", back_populates="searches")
    creator: Mapped["User"] = relationship("User")
    leads: Mapped[List["Lead"]] = relationship("Lead", back_populates="search")
    runs: Mapped[List["Run"]] = relationship("Run", back_populates="search")
