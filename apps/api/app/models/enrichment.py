import uuid
from typing import TYPE_CHECKING, List

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.lead import Lead
    from app.models.score import Score


class Enrichment(Base, UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin):
    """Raw audit data and provider provenance stored as immutable JSONB versions."""

    __tablename__ = "enrichments"

    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    provider_provenance: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # Relationships
    lead: Mapped["Lead"] = relationship("Lead", back_populates="enrichments")
    scores: Mapped[List["Score"]] = relationship("Score", back_populates="enrichment")
