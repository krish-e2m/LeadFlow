import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.core.constants import RunStatus
from app.models.run import Run
from app.repositories.base import BaseRepository


class RunRepository(BaseRepository[Run]):
    def __init__(self, session):
        super().__init__(Run, session)

    async def update_progress(
        self,
        run_id: uuid.UUID,
        progress_pct: int,
        status: Optional[RunStatus] = None,
        items_processed: Optional[int] = None,
        items_succeeded: Optional[int] = None,
        items_failed: Optional[int] = None,
        error_details: Optional[Dict[str, Any]] = None,
    ) -> Optional[Run]:
        run = await self.get_by_id(run_id)
        if not run:
            return None

        run.progress_pct = min(max(progress_pct, 0), 100)
        if status:
            run.status = status
            if status == RunStatus.RUNNING and not run.started_at:
                run.started_at = datetime.now(timezone.utc)
            elif status in [RunStatus.COMPLETED, RunStatus.FAILED]:
                run.completed_at = datetime.now(timezone.utc)

        if items_processed is not None:
            run.items_processed = items_processed
        if items_succeeded is not None:
            run.items_succeeded = items_succeeded
        if items_failed is not None:
            run.items_failed = items_failed
        if error_details:
            run.error_details = error_details

        await self.session.flush()
        return run

    async def recover_stuck_runs(
        self, max_age_seconds: int = 3600, org_id: Optional[uuid.UUID] = None
    ) -> list[Run]:
        """
        Detects and transitions abandoned or stuck runs to FAILED state.
        Ensures worker crashes or timeouts do not leave runs permanently PENDING/RUNNING,
        avoiding duplicate work execution and leaking concurrent run allocations.
        """
        from datetime import timedelta

        from sqlalchemy import or_, select

        threshold = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
        stmt = select(Run).where(
            Run.status.in_([RunStatus.PENDING, RunStatus.RUNNING]),
            or_(
                (Run.started_at.is_not(None) & (Run.started_at < threshold)),
                (Run.started_at.is_(None) & (Run.created_at < threshold)),
            ),
        )
        if org_id:
            stmt = stmt.where(Run.org_id == org_id)

        res = await self.session.execute(stmt)
        stuck_runs = list(res.scalars().all())
        now = datetime.now(timezone.utc)
        for r in stuck_runs:
            r.status = RunStatus.FAILED
            r.completed_at = now
            r.error_details = {
                "error": "Run timed out or was interrupted by worker restart.",
                "recovered_at": now.isoformat(),
                "timeout_threshold_seconds": max_age_seconds,
            }
        if stuck_runs:
            await self.session.flush()
        return stuck_runs
