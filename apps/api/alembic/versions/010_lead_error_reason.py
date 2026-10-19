"""Add leads.error_reason for the "error" pipeline stage.

Revision ID: 010_lead_error_reason
Revises: 009_add_google_auth_fields
Create Date: 2026-10-19 16:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "010_lead_error_reason"
down_revision: Union[str, None] = "009_add_google_auth_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("error_reason", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("leads", "error_reason")
