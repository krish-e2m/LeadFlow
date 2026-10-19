"""Add configurable ideal-client bonus to scoring engine parameter sets.

Revision ID: 007_engine_ideal_client_bonus
Revises: 006_add_audience_ai_rationale
Create Date: 2026-10-15 17:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '007_engine_ideal_client_bonus'
down_revision: Union[str, None] = '006_add_audience_ai_rationale'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'engine_params',
        sa.Column('ideal_client_bonus', sa.Float(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    op.drop_column('engine_params', 'ideal_client_bonus')
