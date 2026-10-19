import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def admin_engine():
    """Privileged engine used solely for test setup and teardown."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from app.core.config import settings

    eng = create_async_engine(settings.migration_database_url, poolclass=NullPool)
    yield eng
    await eng.dispose()


@pytest.fixture(autouse=True)
async def cleanup_pool_and_redis():
    """Clean up engine pool and redis client connections after every test."""
    from app.db.session import engine
    from app.security.session_store import close_redis_client

    yield
    await engine.dispose()
    await close_redis_client()


@pytest.fixture(autouse=True)
def no_live_auto_drafts(monkeypatch):
    """Approving leads in tests must never queue real AI drafts. Tests that need it opt back in."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "AUTO_DRAFT_ON_APPROVAL", False)
