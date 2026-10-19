from typing import Any, Dict

from arq.connections import RedisSettings

from app.core.config import settings
from app.core.logging import logger, setup_logging
from app.jobs.draft_tasks import generate_lead_draft
from app.jobs.search_tasks import run_search_pipeline


async def startup(ctx: Dict[str, Any]) -> None:
    """ARQ worker initialization hook with automatic stuck-run recovery."""
    setup_logging()
    logger.info("ARQ background worker starting up...")
    try:
        from sqlalchemy import text

        from app.db.session import AsyncSessionLocal
        from app.repositories.run_repo import RunRepository
        from app.services.quota_service import QuotaService

        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT set_config('leadflow.is_super_admin', 'true', true)"))
            repo = RunRepository(session)
            recovered = await repo.recover_stuck_runs(max_age_seconds=settings.ARQ_JOB_TIMEOUT)
            if recovered:
                logger.warning(
                    f"ARQ startup: recovered {len(recovered)} abandoned/stuck runs from previous worker session."
                )
                # Reconcile quotas for distinct affected organizations
                distinct_org_ids = {r.org_id for r in recovered}
                for org_id in distinct_org_ids:
                    await QuotaService.reconcile_concurrent_runs(org_id, session)
            await session.commit()
    except Exception as e:
        logger.error(f"Error during ARQ startup stuck-run recovery: {e}")


async def shutdown(ctx: Dict[str, Any]) -> None:
    """ARQ worker graceful termination hook."""
    logger.info("ARQ background worker shutting down...")


class WorkerSettings:
    """ARQ Worker configuration class."""

    functions = [run_search_pipeline, generate_lead_draft]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    max_jobs = settings.ARQ_MAX_JOBS
    health_check_interval = 30  # seconds; /readyz reads this heartbeat
    job_timeout = settings.ARQ_JOB_TIMEOUT
