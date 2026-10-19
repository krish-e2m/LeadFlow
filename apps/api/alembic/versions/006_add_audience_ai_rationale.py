"""Add ai_rationale column to audiences table

Revision ID: 006_add_audience_ai_rationale
Revises: 005_access_requests
Create Date: 2026-10-15 13:40:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "006_add_audience_ai_rationale"
down_revision: Union[str, None] = "005_access_requests"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("audiences", sa.Column("ai_rationale", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("audiences", "ai_rationale")
