import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import CrmSyncStatus
from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.draft import Draft
    from app.models.lead import Lead


class CrmSync(Base, UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin):
    """Idempotent sync record tracking CRM object mapping, status, and retries."""

    __tablename__ = "crm_syncs"

    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    draft_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drafts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    crm_provider: Mapped[str] = mapped_column(String(50), default="hubspot", nullable=False)
    # "<provider>:<lead_id>:<draft_id>": the same lead and draft never creates a second CRM note.
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(160), nullable=True, index=True)
    crm_contact_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    crm_company_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    crm_engagement_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    sync_status: Mapped[CrmSyncStatus] = mapped_column(
        SAEnum(CrmSyncStatus, name="crm_sync_status_enum", native_enum=False),
        default=CrmSyncStatus.PENDING,
        nullable=False,
        index=True,
    )
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    lead: Mapped["Lead"] = relationship("Lead", back_populates="crm_syncs")
    draft: Mapped[Optional["Draft"]] = relationship("Draft", back_populates="crm_syncs")
