import uuid
from typing import Any, Dict, Optional

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import RunStatus, RunType
from app.core.filter_catalog import (
    FilterValidationError,
    resolve_effective_search_params,
    validate_and_normalize_search_params,
)
from app.models.audience import Audience
from app.models.organization import Organization
from app.models.run import Run
from app.repositories.search_repo import SearchRepository
from app.services.quota_service import QuotaService


class SearchService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.search_repo = SearchRepository(session)

    async def initiate_search(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        name: str,
        query_params: Dict[str, Any],
        audience_id: Optional[uuid.UUID] = None,
        limit: int = 25,
    ) -> Run:
        """
        Creates search record and async Run entry, then enqueues task in ARQ worker.
        Enforces organization active status, audience resolution & validation,
        per-search limits, monthly ingestion quotas, and concurrent run limits.
        Combines persisted audience criteria with user overrides according to precedence.
        Returns the created Run object immediately with HTTP 202 semantics.
        """
        # 1. Validate Organization active status
        org_stmt = select(Organization).where(
            Organization.id == org_id, Organization.deleted_at.is_(None)
        )
        org = (await self.session.execute(org_stmt)).scalars().first()
        if not org or not org.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Organization is inactive or suspended. Cannot initiate new search.",
            )

        # 2. Resolve and validate audience & query parameters
        if audience_id is not None:
            aud_stmt = select(Audience).where(
                Audience.id == audience_id,
                Audience.org_id == org_id,
                Audience.deleted_at.is_(None),
            )
            audience = (await self.session.execute(aud_stmt)).scalars().first()
            if not audience:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Audience with ID {audience_id} not found in active organization.",
                )
            if not audience.is_active:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Audience '{audience.name}' is inactive and cannot be used for new searches.",
                )

            try:
                effective_query_params = resolve_effective_search_params(
                    audience.filters, query_params
                )
            except FilterValidationError as e:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Invalid search override parameters: {str(e)}",
                )
        else:
            try:
                effective_query_params = validate_and_normalize_search_params(query_params)
            except FilterValidationError as e:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Invalid search parameters: {str(e)}",
                )

        if not effective_query_params:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Search must contain at least one criteria (e.g., domains, locations, employee_ranges, or a valid audience).",
            )

        # 3. Check and reserve lead ingestion quotas (per-search & monthly)
        await QuotaService.check_and_reserve_lead_ingestion(org_id, limit, self.session)

        # 4. Check and reserve concurrent run quota
        await QuotaService.check_and_reserve_concurrent_run(org_id, self.session)

        # 5. Create Search record with effective criteria
        search = await self.search_repo.create(
            org_id=org_id,
            audience_id=audience_id,
            name=name,
            query_params=effective_query_params,
            created_by=user_id,
        )

        # 6. Create Run record
        run = Run(
            org_id=org_id,
            search_id=search.id,
            run_type=RunType.SEARCH,
            status=RunStatus.PENDING,
            progress_pct=0,
            items_total=limit,
            items_processed=0,
            items_succeeded=0,
            items_failed=0,
            error_details={},
        )
        self.session.add(run)
        await self.session.flush()

        # 7. Enqueue to ARQ background worker via Redis with effective criteria
        try:
            redis_pool = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
            await redis_pool.enqueue_job(
                "run_search_pipeline", str(run.id), str(org_id), limit, effective_query_params
            )
            await redis_pool.close()
        except Exception as e:
            # If dispatch fails, rollback concurrent quota and mark run FAILED immediately
            await QuotaService.release_concurrent_run(org_id)
            run.status = RunStatus.FAILED
            run.error_details = {"enqueue_error": f"Failed to dispatch to worker queue: {str(e)}"}
            await self.session.flush()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Worker queue dispatch failed: {str(e)}. Concurrent run reservation released.",
            )

        return run
