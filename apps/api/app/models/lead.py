import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import ApprovalStatus, PipelineStatus, ScoreBand
from app.db.base import Base, OrgScopedMixin, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.contact import Contact
    from app.models.crm_sync import CrmSync
    from app.models.draft import Draft
    from app.models.enrichment import Enrichment
    from app.models.organization import Organization
    from app.models.score import Score
    from app.models.search import Search
    from app.models.user import User


class Lead(Base, UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, SoftDeleteMixin):
    """Company prospect tracked through discovery, scoring, approval, and CRM sync."""

    __tablename__ = "leads"

    search_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("searches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    domain: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    industry: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    employee_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # State Tracking
    pipeline_status: Mapped[PipelineStatus] = mapped_column(
        SAEnum(PipelineStatus, name="pipeline_status_enum", native_enum=False),
        default=PipelineStatus.SOURCED,
        nullable=False,
        index=True,
    )
    score_band: Mapped[Optional[ScoreBand]] = mapped_column(
        SAEnum(
            ScoreBand,
            name="score_band_enum",
            native_enum=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=None,
        nullable=True,
        index=True,
    )
    approval_status: Mapped[ApprovalStatus] = mapped_column(
        SAEnum(ApprovalStatus, name="approval_status_enum", native_enum=False),
        default=ApprovalStatus.PENDING,
        nullable=False,
        index=True,
    )
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    organization: Mapped["Organization"] = relationship("Organization", back_populates="leads")
    search: Mapped[Optional["Search"]] = relationship("Search", back_populates="leads")
    approver: Mapped[Optional["User"]] = relationship("User")
    enrichments: Mapped[List["Enrichment"]] = relationship(
        "Enrichment",
        back_populates="lead",
        cascade="all, delete-orphan",
        order_by="desc(Enrichment.version)",
    )
    scores: Mapped[List["Score"]] = relationship(
        "Score",
        back_populates="lead",
        cascade="all, delete-orphan",
        order_by="desc(Score.created_at)",
    )
    contacts: Mapped[List["Contact"]] = relationship(
        "Contact", back_populates="lead", cascade="all, delete-orphan"
    )
    drafts: Mapped[List["Draft"]] = relationship(
        "Draft", back_populates="lead", cascade="all, delete-orphan"
    )
    crm_syncs: Mapped[List["CrmSync"]] = relationship(
        "CrmSync", back_populates="lead", cascade="all, delete-orphan"
    )
