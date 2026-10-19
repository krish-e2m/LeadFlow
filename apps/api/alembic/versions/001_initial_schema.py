"""Initial LeadFlow schema migration with 14 tables and RLS policies

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-10-12 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Organizations
    op.create_table(
        "orgs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), unique=True, nullable=False),
        sa.Column("plan", sa.String(50), server_default="starter", nullable=False),
        sa.Column("settings", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_orgs_slug", "orgs", ["slug"])

    # 2. Users
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orgs.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=True),
        sa.Column("role", sa.String(50), server_default="client_viewer", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_org_id", "users", ["org_id"])
    op.create_index("ix_users_email", "users", ["email"])

    # 3. Audiences
    op.create_table(
        "audiences",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orgs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("filters", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_audiences_org_id", "audiences", ["org_id"])

    # 4. Engines
    op.create_table(
        "engines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orgs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("active_version", sa.Integer(), server_default="1", nullable=False),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_engines_org_id", "engines", ["org_id"])

    # 5. Engine Params
    op.create_table(
        "engine_params",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "engine_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("engines.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("weights", postgresql.JSONB(), nullable=False),
        sa.Column("threshold_high", sa.Float(), server_default="75.0", nullable=False),
        sa.Column("threshold_medium", sa.Float(), server_default="50.0", nullable=False),
        sa.Column("threshold_low", sa.Float(), server_default="25.0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_engine_params_engine_id", "engine_params", ["engine_id"])

    # 6. Searches
    op.create_table(
        "searches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orgs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "audience_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("audiences.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("query_params", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
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
    op.create_index("ix_searches_org_id", "searches", ["org_id"])

    # 7. Leads
    op.create_table(
        "leads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orgs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "search_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("searches.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("domain", sa.String(255), nullable=False),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("industry", sa.String(100), nullable=True),
        sa.Column("country", sa.String(100), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("employee_count", sa.Integer(), nullable=True),
        sa.Column("pipeline_status", sa.String(50), server_default="sourced", nullable=False),
        sa.Column("score_band", sa.String(50), server_default="unscored", nullable=False),
        sa.Column("approval_status", sa.String(50), server_default="pending", nullable=False),
        sa.Column(
            "approved_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_leads_org_id", "leads", ["org_id"])
    op.create_index("ix_leads_domain", "leads", ["domain"])

    # 8. Enrichments
    op.create_table(
        "enrichments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orgs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "lead_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("leads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("payload", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("provider_provenance", postgresql.JSONB(), server_default="{}", nullable=False),
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
    op.create_index("ix_enrichments_lead_id", "enrichments", ["lead_id"])
    op.create_index("ix_enrichments_org_id", "enrichments", ["org_id"])

    # 9. Scores
    op.create_table(
        "scores",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orgs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "lead_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("leads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "enrichment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enrichments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "engine_param_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("engine_params.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("overall_score", sa.Float(), nullable=False),
        sa.Column("score_band", sa.String(50), nullable=False),
        sa.Column("website_subscore", sa.Float(), nullable=True),
        sa.Column("marketing_subscore", sa.Float(), nullable=True),
        sa.Column("signal_details", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
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
    op.create_index("ix_scores_lead_id", "scores", ["lead_id"])
    op.create_index("ix_scores_org_id", "scores", ["org_id"])

    # 10. Contacts
    op.create_table(
        "contacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orgs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "lead_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("leads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("first_name", sa.String(100), nullable=True),
        sa.Column("last_name", sa.String(100), nullable=True),
        sa.Column("title", sa.String(200), nullable=True),
        sa.Column("linkedin_url", sa.String(500), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("is_revealed", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("revealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "revealed_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
    op.create_index("ix_contacts_lead_id", "contacts", ["lead_id"])
    op.create_index("ix_contacts_org_id", "contacts", ["org_id"])

    # 11. Drafts
    op.create_table(
        "drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orgs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "lead_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("leads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "contact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("contacts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("model_used", sa.String(100), nullable=False),
        sa.Column("audit_citations", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("approval_status", sa.String(50), server_default="pending", nullable=False),
        sa.Column(
            "approved_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
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
    op.create_index("ix_drafts_lead_id", "drafts", ["lead_id"])
    op.create_index("ix_drafts_org_id", "drafts", ["org_id"])

    # 12. CRM Syncs
    op.create_table(
        "crm_syncs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orgs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "lead_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("leads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "draft_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("drafts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("crm_provider", sa.String(50), server_default="hubspot", nullable=False),
        sa.Column("crm_contact_id", sa.String(100), nullable=True),
        sa.Column("crm_company_id", sa.String(100), nullable=True),
        sa.Column("crm_engagement_id", sa.String(100), nullable=True),
        sa.Column("sync_status", sa.String(50), server_default="pending", nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
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
    op.create_index("ix_crm_syncs_lead_id", "crm_syncs", ["lead_id"])
    op.create_index("ix_crm_syncs_org_id", "crm_syncs", ["org_id"])

    # 13. Runs
    op.create_table(
        "runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orgs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "search_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("searches.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("run_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), server_default="pending", nullable=False),
        sa.Column("progress_pct", sa.Integer(), server_default="0", nullable=False),
        sa.Column("items_total", sa.Integer(), server_default="0", nullable=False),
        sa.Column("items_processed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("items_succeeded", sa.Integer(), server_default="0", nullable=False),
        sa.Column("items_failed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_details", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
    op.create_index("ix_runs_org_id", "runs", ["org_id"])

    # 14. Audit Log
    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orgs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("changes", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_audit_log_org_id", "audit_log", ["org_id"])
    op.create_index("ix_audit_log_action", "audit_log", ["action"])

    # Enable and Force Row-Level Security (RLS) on tenant-scoped tables with direct org_id
    tenant_tables = [
        "users",
        "audiences",
        "engines",
        "searches",
        "leads",
        "enrichments",
        "scores",
        "contacts",
        "drafts",
        "crm_syncs",
        "runs",
        "audit_log",
    ]
    for tbl in tenant_tables:
        op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {tbl} FORCE ROW LEVEL SECURITY;")
        op.execute(f"""
            CREATE POLICY {tbl}_tenant_isolation_policy ON {tbl}
            FOR ALL
            USING (
                current_setting('leadflow.is_super_admin', true) = 'true'
                OR org_id = NULLIF(current_setting('leadflow.current_org_id', true), '')::uuid
            )
            WITH CHECK (
                current_setting('leadflow.is_super_admin', true) = 'true'
                OR org_id = NULLIF(current_setting('leadflow.current_org_id', true), '')::uuid
            );
        """)

    # Organizations table RLS (primary key is id)
    op.execute("ALTER TABLE orgs ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE orgs FORCE ROW LEVEL SECURITY;")
    op.execute("""
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
    """)

    # Engine params table RLS (inherited tenant ownership through engines.org_id)
    op.execute("ALTER TABLE engine_params ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE engine_params FORCE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY engine_params_tenant_isolation_policy ON engine_params
        FOR ALL
        USING (
            current_setting('leadflow.is_super_admin', true) = 'true'
            OR EXISTS (
                SELECT 1 FROM engines
                WHERE engines.id = engine_params.engine_id
                AND engines.org_id = NULLIF(current_setting('leadflow.current_org_id', true), '')::uuid
            )
        )
        WITH CHECK (
            current_setting('leadflow.is_super_admin', true) = 'true'
            OR EXISTS (
                SELECT 1 FROM engines
                WHERE engines.id = engine_params.engine_id
                AND engines.org_id = NULLIF(current_setting('leadflow.current_org_id', true), '')::uuid
            )
        );
    """)

    # Grant DML permissions on all tables and sequences to least-privilege runtime role leadflow_app
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO leadflow_app;")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO leadflow_app;")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS engine_params_tenant_isolation_policy ON engine_params;")
    op.execute("DROP POLICY IF EXISTS orgs_tenant_isolation_policy ON orgs;")
    for tbl in [
        "runs",
        "crm_syncs",
        "drafts",
        "contacts",
        "scores",
        "enrichments",
        "leads",
        "searches",
        "engines",
        "audiences",
        "users",
        "audit_log",
    ]:
        op.execute(f"DROP POLICY IF EXISTS {tbl}_tenant_isolation_policy ON {tbl};")

    op.drop_table("audit_log")
    op.drop_table("runs")
    op.drop_table("crm_syncs")
    op.drop_table("drafts")
    op.drop_table("contacts")
    op.drop_table("scores")
    op.drop_table("enrichments")
    op.drop_table("leads")
    op.drop_table("searches")
    op.drop_table("engine_params")
    op.drop_table("engines")
    op.drop_table("audiences")
    op.drop_table("users")
    op.drop_table("orgs")
