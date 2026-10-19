"""Add idempotency key to CRM sync records.

Revision ID: 008_crm_sync_idempotency_key
Revises: 007_engine_ideal_client_bonus
Create Date: 2026-10-15 19:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '008_crm_sync_idempotency_key'
down_revision: Union[str, None] = '007_engine_ideal_client_bonus'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('crm_syncs', sa.Column('idempotency_key', sa.String(length=160), nullable=True))
    op.create_index('ix_crm_syncs_idempotency_key', 'crm_syncs', ['idempotency_key'])


def downgrade() -> None:
    op.drop_index('ix_crm_syncs_idempotency_key', table_name='crm_syncs')
    op.drop_column('crm_syncs', 'idempotency_key')
