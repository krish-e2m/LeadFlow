import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import RunStatus
from app.db.session import get_db
from app.models.run import Run
from app.repositories.run_repo import RunRepository
from app.schemas.run import RunResponse
from app.security.rbac import AuthenticatedUser, require_authenticated
from app.services.quota_service import QuotaService

router = APIRouter(prefix="/runs", tags=["Job Runs & Polling"])


@router.get("", response_model=List[RunResponse])
async def list_runs(
    status: Optional[RunStatus] = Query(None, description="Filter runs by status"),
    limit: int = Query(20, ge=1, le=100, description="Max runs to return"),
    current_user: AuthenticatedUser = Depends(require_authenticated),
    db: AsyncSession = Depends(get_db),
):
    """Lists recent asynchronous job runs for the active organization."""
    stmt = select(Run)
    if not current_user.is_super_admin:
        stmt = stmt.where(Run.org_id == current_user.org_id)
    if status:
        stmt = stmt.where(Run.status == status)
    stmt = stmt.order_by(Run.created_at.desc()).limit(limit)

    res = await db.execute(stmt)
    return list(res.scalars().all())


@router.get("/{run_id}", response_model=RunResponse)
async def get_run_status(
    run_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_authenticated),
    db: AsyncSession = Depends(get_db),
):
    """
    Polls the status and progress of an asynchronous job run.
    Allows frontend clients to display live percent completion and counters.
    Safely transitions runs exceeding system execution timeouts to FAILED.
    """
    repo = RunRepository(db)
    run = await repo.get_by_id(
        run_id, org_id=current_user.org_id if not current_user.is_super_admin else None
    )
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")

    # Check for stuck/abandoned run during polling
    if run.status in [RunStatus.PENDING, RunStatus.RUNNING]:
        now = datetime.now(timezone.utc)
        ref_time = run.started_at or run.created_at
        if ref_time and (now - ref_time).total_seconds() > (settings.ARQ_JOB_TIMEOUT + 60):
            run.status = RunStatus.FAILED
            run.completed_at = now
            run.error_details = {
                "error": "Job timed out and was automatically recovered.",
                "timeout_threshold_seconds": settings.ARQ_JOB_TIMEOUT,
            }
            await db.flush()
            await QuotaService.release_concurrent_run(run.org_id)
            await db.commit()

    return run
