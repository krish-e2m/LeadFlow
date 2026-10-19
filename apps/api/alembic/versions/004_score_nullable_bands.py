"""Make score columns nullable for unscored leads.

Revision ID: 004_score_nullable_bands
Revises: 003_auth_context_policy
Create Date: 2026-10-13 10:45:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '004_score_nullable_bands'
down_revision: Union[str, None] = '003_auth_context_policy'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Allow NULL for overall_score in scores table when no signals are available
    op.alter_column('scores', 'overall_score', existing_type=sa.Float(), nullable=True)

    # 2. Allow NULL for score_band in scores table when unscored
    op.alter_column('scores', 'score_band', existing_type=sa.String(50), nullable=True)

    # 3. Allow NULL for score_band in leads table and remove 'unscored' default constraint
    op.alter_column('leads', 'score_band', existing_type=sa.String(50), nullable=True, server_default=None)


def downgrade() -> None:
    op.alter_column('leads', 'score_band', existing_type=sa.String(50), nullable=False, server_default='unscored')
    op.alter_column('scores', 'score_band', existing_type=sa.String(50), nullable=False)
    op.alter_column('scores', 'overall_score', existing_type=sa.Float(), nullable=False)
