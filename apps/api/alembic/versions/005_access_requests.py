"""Create access_requests table with RLS and permissions

Revision ID: 005_access_requests
Revises: 004_score_nullable_bands
Create Date: 2026-10-14 17:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "005_access_requests"
down_revision: Union[str, None] = "004_score_nullable_bands"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create access_requests table
    op.create_table(
        "access_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orgs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=True),
        sa.Column("requested_role", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), server_default="pending", nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column(
            "reviewed_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # 2. Indexes
    op.create_index("ix_access_requests_org_id", "access_requests", ["org_id"])
    op.create_index("ix_access_requests_email", "access_requests", ["email"])
    op.create_index("ix_access_requests_status", "access_requests", ["status"])
    op.execute(
        "CREATE UNIQUE INDEX uq_access_requests_pending ON access_requests (email, org_id, requested_role) WHERE status = 'pending';"
    )

    # 3. Row-Level Security
    op.execute("ALTER TABLE access_requests ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE access_requests FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY access_requests_tenant_isolation_policy ON access_requests
        FOR ALL
        USING (
            current_setting('leadflow.is_super_admin', true) = 'true'
            OR current_setting('leadflow.auth_context', true) = 'true'
            OR (
                org_id = NULLIF(current_setting('leadflow.current_org_id', true), '')::uuid
                AND requested_role = 'client_viewer'
            )
        )
        WITH CHECK (
            current_setting('leadflow.is_super_admin', true) = 'true'
            OR current_setting('leadflow.auth_context', true) = 'true'
            OR (
                org_id = NULLIF(current_setting('leadflow.current_org_id', true), '')::uuid
                AND requested_role = 'client_viewer'
            )
        );
        """
    )

    # 4. Update orgs RLS policy to permit public listing and lookups during auth_context
    op.execute("DROP POLICY IF EXISTS orgs_tenant_isolation_policy ON orgs;")
    op.execute(
        """
        CREATE POLICY orgs_tenant_isolation_policy ON orgs
        FOR ALL
        USING (
            current_setting('leadflow.is_super_admin', true) = 'true'
            OR current_setting('leadflow.auth_context', true) = 'true'
            OR id = NULLIF(current_setting('leadflow.current_org_id', true), '')::uuid
        )
        WITH CHECK (
            current_setting('leadflow.is_super_admin', true) = 'true'
            OR current_setting('leadflow.auth_context', true) = 'true'
            OR id = NULLIF(current_setting('leadflow.current_org_id', true), '')::uuid
        );
        """
    )

    # 5. Update audit_log RLS policy to permit recording audit events during auth_context
    op.execute("DROP POLICY IF EXISTS audit_log_tenant_isolation_policy ON audit_log;")
    op.execute(
        """
        CREATE POLICY audit_log_tenant_isolation_policy ON audit_log
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

    # 6. Grants to least-privilege runtime role leadflow_app
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON access_requests TO leadflow_app;")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS audit_log_tenant_isolation_policy ON audit_log;")
    op.execute(
        """
        CREATE POLICY audit_log_tenant_isolation_policy ON audit_log
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
    op.execute("DROP POLICY IF EXISTS orgs_tenant_isolation_policy ON orgs;")
    op.execute(
        """
        CREATE POLICY orgs_tenant_isolation_policy ON orgs
        FOR ALL
        USING (
            current_setting('leadflow.is_super_admin', true) = 'true'
            OR id = NULLIF(current_setting('leadflow.current_org_id', true), '')::uuid
        )
        WITH CHECK (
            current_setting('leadflow.is_super_admin', true) = 'true'
            OR id = NULLIF(current_setting('leadflow.current_org_id', true), '')::uuid
        );
        """
    )
    op.execute("DROP POLICY IF EXISTS access_requests_tenant_isolation_policy ON access_requests;")
    op.execute("DROP INDEX IF EXISTS uq_access_requests_pending;")
    op.drop_index("ix_access_requests_status", table_name="access_requests")
    op.drop_index("ix_access_requests_email", table_name="access_requests")
    op.drop_index("ix_access_requests_org_id", table_name="access_requests")
    op.drop_table("access_requests")
