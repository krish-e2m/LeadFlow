import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.security.tenant import get_current_tenant, is_super_admin_request

# SQLAlchemy 2.0 Async Engine for application runtime (least privilege role)
engine = create_async_engine(
    settings.runtime_database_url,
    echo=(settings.ENVIRONMENT == "development" and settings.LOG_LEVEL == "DEBUG"),
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

# Async Session Factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency yielding a tenant-aware async database session.
    Configures PostgreSQL RLS session variables for the duration of the transaction.
    Guarantees transaction-local fail-closed defaults so pooled connections never leak context.
    """
    async with AsyncSessionLocal() as session:
        try:
            current_org_id = get_current_tenant()
            is_super = is_super_admin_request()

            if is_super:
                await session.execute(
                    text("SELECT set_config('leadflow.is_super_admin', 'true', true), set_config('leadflow.current_org_id', '', true), set_config('leadflow.auth_context', 'false', true)")
                )
            elif current_org_id:
                # Bind current organization ID into PostgreSQL session for RLS evaluation
                await session.execute(
                    text("SELECT set_config('leadflow.current_org_id', :org_id, true), set_config('leadflow.is_super_admin', 'false', true), set_config('leadflow.auth_context', 'false', true)"),
                    {"org_id": str(current_org_id)},
                )
            else:
                # Explicit fail-closed default for unauthenticated or non-tenant contexts
                await session.execute(
                    text("SELECT set_config('leadflow.is_super_admin', 'false', true), set_config('leadflow.current_org_id', '', true), set_config('leadflow.auth_context', 'false', true)")
                )

            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def tenant_session(
    org_id: Optional[uuid.UUID] = None,
) -> AsyncGenerator[AsyncSession, None]:
    """
    Async context manager yielding a tenant-aware database session.
    Configures PostgreSQL RLS session variables for worker jobs or background processes.
    Guarantees transaction-local fail-closed defaults so pooled connections never leak context.
    """
    effective_org = org_id or get_current_tenant()
    is_super = is_super_admin_request()

    async with AsyncSessionLocal() as session:
        try:
            if is_super:
                await session.execute(
                    text("SELECT set_config('leadflow.is_super_admin', 'true', true), set_config('leadflow.current_org_id', '', true), set_config('leadflow.auth_context', 'false', true)")
                )
            elif effective_org:
                await session.execute(
                    text("SELECT set_config('leadflow.current_org_id', :org_id, true), set_config('leadflow.is_super_admin', 'false', true), set_config('leadflow.auth_context', 'false', true)"),
                    {"org_id": str(effective_org)},
                )
            else:
                # Explicit fail-closed default
                await session.execute(
                    text("SELECT set_config('leadflow.is_super_admin', 'false', true), set_config('leadflow.current_org_id', '', true), set_config('leadflow.auth_context', 'false', true)")
                )

            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def auth_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Async context manager yielding a session specifically for credential lookups.
    Sets transaction-local leadflow.auth_context = 'true' for email-based user retrieval.
    """
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(
                text("SELECT set_config('leadflow.auth_context', 'true', true), set_config('leadflow.is_super_admin', 'false', true), set_config('leadflow.current_org_id', '', true)")
            )
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

