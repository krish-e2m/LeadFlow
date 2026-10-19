import uuid
from typing import TYPE_CHECKING, List

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, OrgScopedMixin, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.score import Score


class ScoringEngine(Base, UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, SoftDeleteMixin):
    """Scoring engine metadata container."""

    __tablename__ = "engines"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    active_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Relationships
    organization: Mapped["Organization"] = relationship("Organization", back_populates="engines")
    params: Mapped[List["ScoringEngineParam"]] = relationship(
        "ScoringEngineParam",
        back_populates="engine",
        cascade="all, delete-orphan",
        order_by="desc(ScoringEngineParam.version)",
    )


class ScoringEngineParam(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """Versioned parameter and weight sets for the 22-signal scoring engine."""

    __tablename__ = "engine_params"

    engine_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("engines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    weights: Mapped[dict] = mapped_column(JSONB, nullable=False)
    threshold_high: Mapped[float] = mapped_column(Float, default=75.0, nullable=False)
    threshold_medium: Mapped[float] = mapped_column(Float, default=50.0, nullable=False)
    threshold_low: Mapped[float] = mapped_column(Float, default=25.0, nullable=False)
    ideal_client_bonus: Mapped[float] = mapped_column(Float, default=0.0, server_default="0", nullable=False)

    # Relationships
    engine: Mapped["ScoringEngine"] = relationship("ScoringEngine", back_populates="params")
    scores: Mapped[List["Score"]] = relationship("Score", back_populates="engine_param")
