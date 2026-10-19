import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.db.session import AsyncSessionLocal, engine, tenant_session


@pytest.fixture(autouse=True)
async def cleanup_engine_pool():
    yield
    await engine.dispose()


@pytest.fixture
async def admin_engine():
    """Privileged engine used solely for test setup and teardown."""
    eng = create_async_engine(settings.migration_database_url, poolclass=NullPool)
    yield eng
    await eng.dispose()


@pytest.fixture
async def test_tenants(admin_engine):
    """
    Creates two isolated test organizations and cleans them up after test completion.
    Uses admin connection so RLS doesn't block setup/teardown.
    """
    org_a_id = uuid.uuid4()
    org_b_id = uuid.uuid4()
    slug_a = f"test-sec-a-{org_a_id.hex[:8]}"
    slug_b = f"test-sec-b-{org_b_id.hex[:8]}"

    admin_session_factory = async_sessionmaker(
        bind=admin_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with admin_session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO orgs (id, name, slug, plan, is_active) VALUES "
                "(:id_a, 'Security Test Org A', :slug_a, 'starter', true), "
                "(:id_b, 'Security Test Org B', :slug_b, 'starter', true)"
            ),
            {
                "id_a": org_a_id,
                "slug_a": slug_a,
                "id_b": org_b_id,
                "slug_b": slug_b,
            },
        )
        await session.commit()

    yield {
        "org_a_id": org_a_id,
        "slug_a": slug_a,
        "org_b_id": org_b_id,
        "slug_b": slug_b,
    }

    # Cleanup test data using admin privileges
    async with admin_session_factory() as session:
        await session.execute(
            text("DELETE FROM orgs WHERE id IN (:id_a, :id_b)"),
            {"id_a": org_a_id, "id_b": org_b_id},
        )
        await session.commit()


@pytest.mark.asyncio
async def test_runtime_role_is_least_privilege():
    """Verify runtime role is leadflow_app, is NOT superuser, and has NO BYPASSRLS."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                "SELECT rolname, rolsuper, rolbypassrls "
                "FROM pg_roles WHERE rolname = current_user"
            )
        )
        row = result.fetchone()
        assert row is not None, "Could not fetch current_user from pg_roles"
        rolname, rolsuper, rolbypassrls = row
        assert rolname == "leadflow_app"
        assert rolsuper is False, "leadflow_app must NOT be a superuser"
        assert rolbypassrls is False, "leadflow_app must NOT have BYPASSRLS"


@pytest.mark.asyncio
async def test_runtime_role_cannot_modify_schema():
    """Verify runtime user cannot execute DDL / schema modification in public schema."""
    async with AsyncSessionLocal() as session:
        with pytest.raises((ProgrammingError, DBAPIError)) as exc_info:
            await session.execute(text("CREATE TABLE public._sec_test_probe (id int)"))
            await session.commit()

        error_message = str(exc_info.value).lower()
        assert (
            "permission denied" in error_message
            or "insufficientprivilege" in error_message
        ), f"Unexpected error message: {exc_info.value}"


@pytest.mark.asyncio
async def test_migration_applied_and_rls_enforced_on_all_tables():
    """Verify Alembic migration revision is 001_initial_schema and all 14 tables enforce RLS."""
    expected_tables = {
        "orgs",
        "users",
        "audiences",
        "engines",
        "engine_params",
        "searches",
        "leads",
        "enrichments",
        "scores",
        "contacts",
        "drafts",
        "crm_syncs",
        "runs",
        "audit_log",
        "access_requests",
    }

    async with AsyncSessionLocal() as session:
        # Check Alembic version
        ver_res = await session.execute(text("SELECT version_num FROM alembic_version"))
        version = ver_res.scalar()
        assert version in (
            "003_auth_context_policy",
            "004_score_nullable_bands",
            "005_access_requests",
            "006_add_audience_ai_rationale",
            "007_engine_ideal_client_bonus",
            "008_crm_sync_idempotency_key",
            "009_add_google_auth_fields",
            "010_lead_error_reason",
        )

        # Check existing domain tables
        tables_res = await session.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
            )
        )
        existing_tables = {row[0] for row in tables_res.fetchall()}
        assert expected_tables.issubset(existing_tables), (
            f"Missing domain tables: {expected_tables - existing_tables}"
        )

        # Check RLS and FORCE RLS on all domain tables
        rls_res = await session.execute(
            text(
                "SELECT relname, relrowsecurity, relforcerowsecurity "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND relname = ANY(:tables)"
            ),
            {"tables": list(expected_tables)},
        )
        rls_info = {row[0]: (row[1], row[2]) for row in rls_res.fetchall()}
        for table in expected_tables:
            assert table in rls_info, f"Table {table} not found in pg_class"
            has_rls, has_force_rls = rls_info[table]
            assert has_rls is True, f"Table {table} missing row security"
            assert has_force_rls is True, f"Table {table} missing FORCE row security"


@pytest.mark.asyncio
async def test_tenant_isolation_prevents_cross_tenant_reads(test_tenants, admin_engine):
    """Verify Tenant A cannot read Tenant B's protected records."""
    org_a = test_tenants["org_a_id"]
    org_b = test_tenants["org_b_id"]

    # Seed data for Org B using admin session
    admin_session_factory = async_sessionmaker(
        bind=admin_engine, class_=AsyncSession, expire_on_commit=False
    )
    b_lead_id = uuid.uuid4()
    async with admin_session_factory() as admin_sess:
        await admin_sess.execute(
            text(
                "INSERT INTO leads (id, org_id, company_name, domain) "
                "VALUES (:id, :org_id, 'Tenant B Secret Corp', 'secret-b.com')"
            ),
            {"id": b_lead_id, "org_id": org_b},
        )
        await admin_sess.commit()

    # Query as Tenant A via runtime tenant_session
    async with tenant_session(org_id=org_a) as sess_a:
        res = await sess_a.execute(text("SELECT id, company_name FROM leads WHERE id = :id"), {"id": b_lead_id})
        rows = res.fetchall()
        assert len(rows) == 0, "Tenant A was able to read Tenant B's lead!"

    # Query as Tenant B via runtime tenant_session to confirm row is visible to owner
    async with tenant_session(org_id=org_b) as sess_b:
        res = await sess_b.execute(text("SELECT id, company_name FROM leads WHERE id = :id"), {"id": b_lead_id})
        rows = res.fetchall()
        assert len(rows) == 1, "Tenant B was unable to read its own lead"


@pytest.mark.asyncio
async def test_tenant_isolation_prevents_cross_tenant_writes(test_tenants):
    """Verify Tenant A cannot insert or update records with Tenant B's org_id."""
    org_a = test_tenants["org_a_id"]
    org_b = test_tenants["org_b_id"]

    # Attempt cross-tenant insert from Tenant A session
    async with tenant_session(org_id=org_a) as sess_a:
        with pytest.raises((ProgrammingError, DBAPIError)) as exc_info:
            await sess_a.execute(
                text(
                    "INSERT INTO leads (id, org_id, company_name, domain) "
                    "VALUES (:id, :org_id, 'Malicious Tenant A Insert', 'bad.com')"
                ),
                {"id": uuid.uuid4(), "org_id": org_b},
            )
            await sess_a.flush()

        assert "row-level security" in str(exc_info.value).lower(), (
            f"Expected RLS policy violation on cross-tenant insert: {exc_info.value}"
        )


@pytest.mark.asyncio
async def test_inherited_tenant_isolation_for_engine_params(test_tenants, admin_engine):
    """Verify engine_params inherits tenant boundary from parent engines table."""
    org_a = test_tenants["org_a_id"]
    org_b = test_tenants["org_b_id"]

    # Create engines for Org A and Org B
    admin_session_factory = async_sessionmaker(
        bind=admin_engine, class_=AsyncSession, expire_on_commit=False
    )
    engine_b_id = uuid.uuid4()
    param_b_id = uuid.uuid4()
    async with admin_session_factory() as admin_sess:
        await admin_sess.execute(
            text(
                "INSERT INTO engines (id, org_id, name, active_version) "
                "VALUES (:id, :org_id, 'Engine B', 1)"
            ),
            {"id": engine_b_id, "org_id": org_b},
        )
        await admin_sess.execute(
            text(
                "INSERT INTO engine_params (id, engine_id, version, weights, threshold_high, threshold_medium, threshold_low) "
                "VALUES (:id, :engine_id, 1, '{\"weight\": 1.0}', 75.0, 50.0, 25.0)"
            ),
            {"id": param_b_id, "engine_id": engine_b_id},
        )
        await admin_sess.commit()

    # Query engine_params as Tenant A
    async with tenant_session(org_id=org_a) as sess_a:
        res = await sess_a.execute(
            text("SELECT id FROM engine_params WHERE id = :id"), {"id": param_b_id}
        )
        assert len(res.fetchall()) == 0, "Tenant A was able to read Tenant B's engine_params!"

        # Attempt to insert engine_param for Engine B under Tenant A context
        with pytest.raises((ProgrammingError, DBAPIError)) as exc_info:
            await sess_a.execute(
                text(
                    "INSERT INTO engine_params (id, engine_id, version, weights, threshold_high, threshold_medium, threshold_low) "
                    "VALUES (:id, :engine_id, 2, '{\"weight\": 2.0}', 75.0, 50.0, 25.0)"
                ),
                {"id": uuid.uuid4(), "engine_id": engine_b_id},
            )
            await sess_a.flush()

        assert "row-level security" in str(exc_info.value).lower(), (
            f"Expected RLS policy violation on engine_params insert: {exc_info.value}"
        )


@pytest.mark.asyncio
async def test_missing_tenant_context_fails_closed(test_tenants, admin_engine):
    """Verify queries fail closed (0 rows returned) when tenant context is empty or missing."""
    org_a = test_tenants["org_a_id"]

    admin_session_factory = async_sessionmaker(
        bind=admin_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with admin_session_factory() as admin_sess:
        await admin_sess.execute(
            text(
                "INSERT INTO audiences (id, org_id, name, filters) "
                "VALUES (:id, :org_id, 'Confidential Audience', '{\"industry\": \"tech\"}')"
            ),
            {"id": uuid.uuid4(), "org_id": org_a},
        )
        await admin_sess.commit()

    # Query with no tenant context configured
    async with AsyncSessionLocal() as session:
        # Default session sets leadflow.current_org_id = ''
        await session.execute(
            text("SELECT set_config('leadflow.current_org_id', '', true), set_config('leadflow.is_super_admin', 'false', true)")
        )

        res = await session.execute(text("SELECT id, name FROM audiences"))
        rows = res.fetchall()
        assert len(rows) == 0, "Missing tenant context exposed audience rows!"

        # Insertion without tenant context must fail RLS
        with pytest.raises((ProgrammingError, DBAPIError)):
            await session.execute(
                text(
                    "INSERT INTO audiences (id, org_id, name, filters) "
                    "VALUES (:id, :org_id, 'Hacked Audience', '{}')"
                ),
                {"id": uuid.uuid4(), "org_id": org_a},
            )
            await session.flush()


@pytest.mark.asyncio
async def test_connection_reuse_does_not_leak_tenant_context(test_tenants):
    """Verify transaction-local tenant context (set_config is_local=true) does not persist across transactions."""
    org_a = test_tenants["org_a_id"]
    from app.db.session import engine as runtime_engine

    # Check out a raw connection from pool
    async with runtime_engine.connect() as conn:
        # Transaction 1: Set tenant context for Tenant A
        async with conn.begin():
            await conn.execute(
                text("SELECT set_config('leadflow.current_org_id', :org_id, true)"),
                {"org_id": str(org_a)},
            )
            ctx_val = (await conn.execute(text("SELECT current_setting('leadflow.current_org_id', true)"))).scalar()
            assert ctx_val == str(org_a)

        # Transaction 2 on same connection without setting context
        async with conn.begin():
            reused_ctx = (await conn.execute(text("SELECT current_setting('leadflow.current_org_id', true)"))).scalar()
            # is_local=true causes it to reset after transaction commit
            assert reused_ctx == "" or reused_ctx is None, (
                f"Tenant context leaked across transactions: {reused_ctx}"
            )


@pytest.mark.asyncio
async def test_super_admin_context_can_read_all_tenants(test_tenants, admin_engine):
    """Verify super-admin context (leadflow.is_super_admin = 'true') can read cross-tenant data."""
    org_a = test_tenants["org_a_id"]
    org_b = test_tenants["org_b_id"]

    # Query with super admin flag set
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("SELECT set_config('leadflow.is_super_admin', 'true', true), set_config('leadflow.current_org_id', '', true)")
        )

        res = await session.execute(
            text("SELECT id FROM orgs WHERE id IN (:id_a, :id_b)"),
            {"id_a": org_a, "id_b": org_b},
        )
        rows = res.fetchall()
        assert len(rows) == 2, "Super admin context was unable to read both tenant organizations"
