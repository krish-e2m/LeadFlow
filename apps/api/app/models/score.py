import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Enum as SAEnum
from sqlalchemy import Float, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import ScoreBand
from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.engine import ScoringEngineParam
    from app.models.enrichment import Enrichment
    from app.models.lead import Lead


class Score(Base, UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin):
    """Historical scoring outputs derived from 22-signal engine evaluation."""

    __tablename__ = "scores"

    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    enrichment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("enrichments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    engine_param_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("engine_params.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    overall_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    score_band: Mapped[Optional[ScoreBand]] = mapped_column(
        SAEnum(
            ScoreBand,
            name="score_band_enum",
            native_enum=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=True,
        index=True,
    )
    website_subscore: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    marketing_subscore: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    signal_details: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    explanation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    lead: Mapped["Lead"] = relationship("Lead", back_populates="scores")
    enrichment: Mapped["Enrichment"] = relationship("Enrichment", back_populates="scores")
    engine_param: Mapped["ScoringEngineParam"] = relationship(
        "ScoringEngineParam", back_populates="scores"
    )
