"""Add Google OAuth fields (google_id, avatar_url) to users table.

Revision ID: 009_add_google_auth_fields
Revises: 008_crm_sync_idempotency_key
Create Date: 2026-10-16 16:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "009_add_google_auth_fields"
down_revision: Union[str, None] = "008_crm_sync_idempotency_key"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("google_id", sa.String(length=255), nullable=True))
    op.create_index("ix_users_google_id", "users", ["google_id"], unique=True)
    op.add_column("users", sa.Column("avatar_url", sa.String(length=1024), nullable=True))


def downgrade() -> None:
    op.drop_index("ix_users_google_id", table_name="users")
    op.drop_column("users", "avatar_url")
    op.drop_column("users", "google_id")
