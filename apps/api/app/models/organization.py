from typing import TYPE_CHECKING, List

from sqlalchemy import Boolean, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.audience import Audience
    from app.models.engine import ScoringEngine
    from app.models.lead import Lead
    from app.models.user import User


class Organization(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """Multi-tenant organization boundary."""

    __tablename__ = "orgs"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    plan: Mapped[str] = mapped_column(String(50), default="starter", nullable=False)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    users: Mapped[List["User"]] = relationship(
        "User", back_populates="organization", cascade="all, delete-orphan"
    )
    audiences: Mapped[List["Audience"]] = relationship(
        "Audience", back_populates="organization", cascade="all, delete-orphan"
    )
    engines: Mapped[List["ScoringEngine"]] = relationship(
        "ScoringEngine", back_populates="organization", cascade="all, delete-orphan"
    )
    leads: Mapped[List["Lead"]] = relationship(
        "Lead", back_populates="organization", cascade="all, delete-orphan"
    )
