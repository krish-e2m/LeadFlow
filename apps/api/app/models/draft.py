import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import DraftApprovalStatus
from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.contact import Contact
    from app.models.crm_sync import CrmSync
    from app.models.lead import Lead
    from app.models.user import User


class Draft(Base, UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin):
    """AI-generated personalized outreach copy with audit citations and human approval gate."""

    __tablename__ = "drafts"

    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contact_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    model_used: Mapped[str] = mapped_column(String(100), nullable=False)
    audit_citations: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    approval_status: Mapped[DraftApprovalStatus] = mapped_column(
        SAEnum(DraftApprovalStatus, name="draft_approval_status_enum", native_enum=False),
        default=DraftApprovalStatus.PENDING,
        nullable=False,
        index=True,
    )
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    lead: Mapped["Lead"] = relationship("Lead", back_populates="drafts")
    contact: Mapped[Optional["Contact"]] = relationship("Contact", back_populates="drafts")
    approver: Mapped[Optional["User"]] = relationship("User")
    crm_syncs: Mapped[List["CrmSync"]] = relationship("CrmSync", back_populates="draft")
