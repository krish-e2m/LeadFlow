import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Integer
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import RunStatus, RunType
from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.search import Search


class Run(Base, UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin):
    """Execution state tracking for long-running asynchronous ARQ jobs."""

    __tablename__ = "runs"

    search_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("searches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    run_type: Mapped[RunType] = mapped_column(
        SAEnum(RunType, name="run_type_enum", native_enum=False), nullable=False, index=True
    )
    status: Mapped[RunStatus] = mapped_column(
        SAEnum(RunStatus, name="run_status_enum", native_enum=False),
        default=RunStatus.PENDING,
        nullable=False,
        index=True,
    )
    progress_pct: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    items_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    items_processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    items_succeeded: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    items_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_details: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    search: Mapped[Optional["Search"]] = relationship("Search", back_populates="runs")
