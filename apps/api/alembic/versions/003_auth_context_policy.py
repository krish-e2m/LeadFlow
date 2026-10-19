"""Update users tenant isolation policy with auth_context

Revision ID: 003_auth_context_policy
Revises: 002_add_must_reset_password
Create Date: 2026-10-12
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003_auth_context_policy"
down_revision: Union[str, None] = "002_add_must_reset_password"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP POLICY IF EXISTS users_tenant_isolation_policy ON users;")
    op.execute(
        """
        CREATE POLICY users_tenant_isolation_policy ON users
            FOR ALL
            USING (
                current_setting('leadflow.is_super_admin', true) = 'true'
                OR current_setting('leadflow.auth_context', true) = 'true'
                OR org_id = NULLIF(current_setting('leadflow.current_org_id', true), '')::uuid
            )
            WITH CHECK (
                current_setting('leadflow.is_super_admin', true) = 'true'
                OR current_setting('leadflow.auth_context', true) = 'true'
                OR org_id = NULLIF(current_setting('leadflow.current_org_id', true), '')::uuid
            );
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS users_tenant_isolation_policy ON users;")
    op.execute(
        """
        CREATE POLICY users_tenant_isolation_policy ON users
            FOR ALL
            USING (
                current_setting('leadflow.is_super_admin', true) = 'true'
                OR org_id = NULLIF(current_setting('leadflow.current_org_id', true), '')::uuid
            )
            WITH CHECK (
                current_setting('leadflow.is_super_admin', true) = 'true'
                OR org_id = NULLIF(current_setting('leadflow.current_org_id', true), '')::uuid
            );
        """
    )
