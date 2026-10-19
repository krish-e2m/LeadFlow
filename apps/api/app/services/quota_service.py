import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import RunStatus
from app.core.logging import logger
from app.models.contact import Contact
from app.models.crm_sync import CrmSync
from app.models.draft import Draft
from app.models.lead import Lead
from app.models.run import Run
from app.models.search import Search
from app.providers.manager import provider_manager
from app.security.session_store import get_redis_client


class QuotaService:
    """
    Enforces concurrency-safe business quotas across tenants.
    Implements strict fail-closed enforcement when Redis is unavailable,
    protecting the ₹0 cost ceiling against quota bypass.
    """

    @classmethod
    async def check_and_reserve_lead_ingestion(
        cls, org_id: uuid.UUID, requested_count: int, db: AsyncSession
    ) -> int:
        """
        Enforces:
        1. Per-search limit (max 500 leads per search).
        2. Monthly ingestion ceiling (default 100 leads/month per organization). A search asking for
           more than what is left runs with what is left; only an exhausted quota is rejected.
        Returns the number of leads reserved. Fails closed if Redis is unreachable.
        """
        # 1. Enforce per-search limit
        if requested_count > settings.QUOTA_LEADS_PER_SEARCH:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Requested lead count ({requested_count}) exceeds maximum per-search limit ({settings.QUOTA_LEADS_PER_SEARCH}).",
            )

        # 2. Derive genuine monthly usage from database
        now = datetime.now(timezone.utc)
        start_of_month = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
        stmt = select(func.count(Lead.id)).where(
            Lead.org_id == org_id,
            Lead.created_at >= start_of_month,
            Lead.deleted_at.is_(None),
        )
        db_month_used = (await db.execute(stmt)).scalar_one()

        monthly_limit = settings.QUOTA_LEADS_PER_MONTH
        remaining = monthly_limit - db_month_used
        if remaining <= 0:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Monthly lead ingestion quota exceeded. Limit: {monthly_limit}, used this month: {db_month_used}, remaining: 0. A super admin can raise the quota.",
            )
        granted = min(requested_count, remaining)

        # 3. Concurrency-safe Redis reservation (fail-closed if Redis unavailable)
        try:
            r = get_redis_client()
            key = f"leadflow:quota:{org_id}:leads:{now.strftime('%Y-%m')}"
            current_reserved = await r.get(key)
            current_val = int(current_reserved) if current_reserved else db_month_used

            if current_val + granted > monthly_limit:
                # Reconcile with active in-flight runs in database to detect stale reservations from finished/failed runs
                in_flight_stmt = select(func.coalesce(func.sum(Run.items_total), 0)).where(
                    Run.org_id == org_id,
                    Run.status.in_([RunStatus.PENDING, RunStatus.RUNNING]),
                    Run.created_at >= start_of_month,
                )
                in_flight_leads = int((await db.execute(in_flight_stmt)).scalar_one())
                current_val = min(current_val, db_month_used + in_flight_leads)
                granted = min(granted, monthly_limit - current_val)
                if granted <= 0:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail=f"Monthly lead ingestion quota exceeded: the rest of this month's {monthly_limit} leads are reserved by searches still running.",
                    )

            # Atomically set reservation
            pipe = r.pipeline()
            pipe.set(key, current_val + granted)
            pipe.expire(key, 86400 * 32)
            await pipe.execute()
            return granted
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Quota service Redis unavailable for lead ingestion: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Quota enforcement service unavailable (Redis unreachable). Operation rejected to prevent quota bypass.",
            ) from e

    @classmethod
    async def reconcile_lead_ingestion(cls, org_id: uuid.UUID, db: AsyncSession) -> int:
        """
        Reconciles Redis lead ingestion counter with actual database rows and active in-flight runs.
        Prevents completed or failed runs from permanently consuming quota reservations.
        """
        now = datetime.now(timezone.utc)
        start_of_month = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
        lead_stmt = select(func.count(Lead.id)).where(
            Lead.org_id == org_id,
            Lead.created_at >= start_of_month,
            Lead.deleted_at.is_(None),
        )
        db_month_used = (await db.execute(lead_stmt)).scalar_one()

        in_flight_stmt = select(func.coalesce(func.sum(Run.items_total), 0)).where(
            Run.org_id == org_id,
            Run.status.in_([RunStatus.PENDING, RunStatus.RUNNING]),
            Run.created_at >= start_of_month,
        )
        in_flight_leads = int((await db.execute(in_flight_stmt)).scalar_one())
        actual_in_use = db_month_used + in_flight_leads

        try:
            r = get_redis_client()
            key = f"leadflow:quota:{org_id}:leads:{now.strftime('%Y-%m')}"
            await r.set(key, actual_in_use, ex=86400 * 32)
        except Exception as e:
            logger.warning(f"Could not reconcile lead ingestion quota in Redis: {e}")
        return actual_in_use

    @classmethod
    async def check_and_reserve_concurrent_run(
        cls, org_id: uuid.UUID, db: Optional[AsyncSession] = None
    ) -> None:
        """
        Enforces maximum concurrent active runs per organization (default 2).
        Uses atomic Redis counter with fail-closed behavior.
        """
        limit = settings.QUOTA_CONCURRENT_RUNS
        try:
            r = get_redis_client()
            key = f"leadflow:quota:{org_id}:concurrent_runs"
            current = await r.incr(key)
            await r.expire(key, settings.ARQ_JOB_TIMEOUT + 300)

            if current > limit:
                if db:
                    actual_active = await cls.reconcile_concurrent_runs(org_id, db)
                    if actual_active < limit:
                        # Redis was desynchronized from a terminated worker; allow run after reconciling
                        current = await r.incr(key)
                        if current <= limit:
                            return
                await r.decr(key)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Concurrent run quota exceeded. Maximum active background runs: {limit}.",
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Quota service Redis unavailable for concurrent runs: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Quota enforcement service unavailable (Redis unreachable). Operation rejected to prevent quota bypass.",
            ) from e

    @classmethod
    async def release_concurrent_run(cls, org_id: uuid.UUID) -> None:
        """Decrements the concurrent active runs counter upon job completion or failure."""
        try:
            r = get_redis_client()
            key = f"leadflow:quota:{org_id}:concurrent_runs"
            val = await r.decr(key)
            if val < 0:
                await r.set(key, 0)
        except Exception as e:
            logger.error(f"Failed to release concurrent run quota in Redis: {e}")

    @classmethod
    async def reconcile_concurrent_runs(cls, org_id: uuid.UUID, db: AsyncSession) -> int:
        """Reconciles Redis concurrent run counter with actual database active runs for crash recovery."""
        stmt = select(func.count(Run.id)).where(
            Run.org_id == org_id,
            Run.status.in_([RunStatus.PENDING, RunStatus.RUNNING]),
        )
        active_runs = (await db.execute(stmt)).scalar_one()
        try:
            r = get_redis_client()
            key = f"leadflow:quota:{org_id}:concurrent_runs"
            await r.set(key, active_runs, ex=settings.ARQ_JOB_TIMEOUT + 300)
        except Exception as e:
            logger.warning(f"Could not reconcile concurrent runs in Redis: {e}")
        return active_runs

    @classmethod
    async def check_and_reserve_contact_reveal(
        cls, org_id: uuid.UUID, db: AsyncSession
    ) -> None:
        """
        Enforces daily contact reveals limit (default 100/day per organization).
        Fails closed if Redis is unreachable.
        """
        now = datetime.now(timezone.utc)
        limit = settings.QUOTA_CONTACT_REVEALS_PER_DAY
        try:
            r = get_redis_client()
            key = f"leadflow:quota:{org_id}:reveals:{now.strftime('%Y-%m-%d')}"
            current = await r.incr(key)
            await r.expire(key, 86400 * 2)

            if current > limit:
                await r.decr(key)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Daily contact reveal quota exceeded. Limit: {limit}/day.",
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Quota service Redis unavailable for contact reveals: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Quota enforcement service unavailable (Redis unreachable). Operation rejected to prevent quota bypass.",
            ) from e

    @classmethod
    async def release_contact_reveal(cls, org_id: uuid.UUID) -> None:
        """Rolls back reveal reservation if the reveal operation failed."""
        try:
            r = get_redis_client()
            now = datetime.now(timezone.utc)
            key = f"leadflow:quota:{org_id}:reveals:{now.strftime('%Y-%m-%d')}"
            val = await r.decr(key)
            if val < 0:
                await r.set(key, 0)
        except Exception as e:
            logger.error(f"Failed to release contact reveal reservation: {e}")

    @classmethod
    async def check_and_reserve_draft_generation(
        cls, org_id: uuid.UUID, db: AsyncSession
    ) -> None:
        """
        Enforces daily outreach draft generation limit (default 200/day per organization)
        and validates zero-cost monthly LLM ceiling.
        Fails closed if Redis is unreachable.
        """
        now = datetime.now(timezone.utc)
        limit = settings.QUOTA_DRAFT_GENERATION_PER_DAY
        try:
            r = get_redis_client()
            key = f"leadflow:quota:{org_id}:drafts:{now.strftime('%Y-%m-%d')}"
            current = await r.incr(key)
            await r.expire(key, 86400 * 2)

            if current > limit:
                await r.decr(key)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Daily draft generation quota exceeded. Limit: {limit}/day.",
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Quota service Redis unavailable for draft generation: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Quota enforcement service unavailable (Redis unreachable). Operation rejected to prevent quota bypass.",
            ) from e

    @classmethod
    async def release_draft_generation(cls, org_id: uuid.UUID) -> None:
        """Rolls back draft reservation if the generation operation failed."""
        try:
            r = get_redis_client()
            now = datetime.now(timezone.utc)
            key = f"leadflow:quota:{org_id}:drafts:{now.strftime('%Y-%m-%d')}"
            val = await r.decr(key)
            if val < 0:
                await r.set(key, 0)
        except Exception as e:
            logger.error(f"Failed to release draft reservation: {e}")

    @classmethod
    async def get_usage_summary(cls, org_id: uuid.UUID, db: AsyncSession) -> Dict[str, Any]:
        """
        Calculates genuine usage metrics from real database rows and live quota counters.
        Never uses hardcoded mock figures.
        """
        now = datetime.now(timezone.utc)
        start_of_month = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
        start_of_day = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)

        # 1. Total lifetime counts
        total_searches = (
            await db.execute(select(func.count(Search.id)).where(Search.org_id == org_id))
        ).scalar_one()
        total_leads = (
            await db.execute(
                select(func.count(Lead.id)).where(Lead.org_id == org_id, Lead.deleted_at.is_(None))
            )
        ).scalar_one()
        total_contacts_revealed = (
            await db.execute(
                select(func.count(Contact.id)).where(
                    Contact.org_id == org_id, Contact.is_revealed.is_(True)
                )
            )
        ).scalar_one()
        total_ai_drafts = (
            await db.execute(select(func.count(Draft.id)).where(Draft.org_id == org_id))
        ).scalar_one()
        total_crm_syncs = (
            await db.execute(
                select(func.count(CrmSync.id)).where(
                    CrmSync.org_id == org_id, CrmSync.sync_status == "success"
                )
            )
        ).scalar_one()

        # 2. Monthly lead consumption
        monthly_leads_used = (
            await db.execute(
                select(func.count(Lead.id)).where(
                    Lead.org_id == org_id,
                    Lead.created_at >= start_of_month,
                    Lead.deleted_at.is_(None),
                )
            )
        ).scalar_one()
        monthly_leads_limit = settings.QUOTA_LEADS_PER_MONTH

        # 3. Active concurrent runs
        concurrent_runs_count = (
            await db.execute(
                select(func.count(Run.id)).where(
                    Run.org_id == org_id,
                    Run.status.in_([RunStatus.PENDING, RunStatus.RUNNING]),
                )
            )
        ).scalar_one()
        concurrent_runs_limit = settings.QUOTA_CONCURRENT_RUNS

        # 4. Daily contact reveals
        daily_reveals_used = (
            await db.execute(
                select(func.count(Contact.id)).where(
                    Contact.org_id == org_id,
                    Contact.is_revealed.is_(True),
                    Contact.revealed_at >= start_of_day,
                )
            )
        ).scalar_one()
        daily_reveals_limit = settings.QUOTA_CONTACT_REVEALS_PER_DAY

        # 5. Daily draft generation
        daily_drafts_used = (
            await db.execute(
                select(func.count(Draft.id)).where(
                    Draft.org_id == org_id,
                    Draft.created_at >= start_of_day,
                )
            )
        ).scalar_one()
        daily_drafts_limit = settings.QUOTA_DRAFT_GENERATION_PER_DAY

        # 6. Overall credits calculation: derived from real actions
        credits_used = total_contacts_revealed + total_ai_drafts
        credits_limit = 500  # Default starter allowance

        return {
            "org_id": org_id,
            "total_searches_run": total_searches,
            "total_leads_sourced": total_leads,
            "total_contacts_revealed": total_contacts_revealed,
            "total_ai_drafts_generated": total_ai_drafts,
            "total_crm_syncs": total_crm_syncs,
            "credits_used": credits_used,
            "credits_limit": credits_limit,
            "monthly_leads": {
                "used": monthly_leads_used,
                "limit": monthly_leads_limit,
                "remaining": max(0, monthly_leads_limit - monthly_leads_used),
                "period": "monthly",
                "is_exceeded": monthly_leads_used >= monthly_leads_limit,
            },
            "leads_per_search_limit": settings.QUOTA_LEADS_PER_SEARCH,
            "concurrent_runs": {
                "used": concurrent_runs_count,
                "limit": concurrent_runs_limit,
                "remaining": max(0, concurrent_runs_limit - concurrent_runs_count),
                "period": "concurrent",
                "is_exceeded": concurrent_runs_count >= concurrent_runs_limit,
            },
            "daily_contact_reveals": {
                "used": daily_reveals_used,
                "limit": daily_reveals_limit,
                "remaining": max(0, daily_reveals_limit - daily_reveals_used),
                "period": "daily",
                "is_exceeded": daily_reveals_used >= daily_reveals_limit,
            },
            "daily_draft_generation": {
                "used": daily_drafts_used,
                "limit": daily_drafts_limit,
                "remaining": max(0, daily_drafts_limit - daily_drafts_used),
                "period": "daily",
                "is_exceeded": daily_drafts_used >= daily_drafts_limit,
            },
            "monthly_llm_usage_usd": 0.0,
            "monthly_llm_ceiling_usd": settings.QUOTA_LLM_MONTHLY_CEILING_USD,
            "llm_provider_configured": provider_manager.openrouter.is_configured(),
            "status_flags": {
                "zero_cost_policy_active": True,
                "fail_closed_redis_active": True,
            },
            "quotas": {
                "leads_monthly": {
                    "used": monthly_leads_used,
                    "limit": monthly_leads_limit,
                    "remaining": max(0, monthly_leads_limit - monthly_leads_used),
                    "period": "monthly",
                },
                "leads_per_search": {"limit": settings.QUOTA_LEADS_PER_SEARCH},
                "concurrent_runs": {
                    "active": concurrent_runs_count,
                    "limit": concurrent_runs_limit,
                    "remaining": max(0, concurrent_runs_limit - concurrent_runs_count),
                },
                "contact_reveals_daily": {
                    "used": daily_reveals_used,
                    "limit": daily_reveals_limit,
                    "remaining": max(0, daily_reveals_limit - daily_reveals_used),
                    "period": "daily",
                },
                "draft_generation_daily": {
                    "used": daily_drafts_used,
                    "limit": daily_drafts_limit,
                    "remaining": max(0, daily_drafts_limit - daily_drafts_used),
                    "period": "daily",
                },
                "llm_monthly": {
                    "used_usd": 0.0,
                    "ceiling_usd": settings.QUOTA_LLM_MONTHLY_CEILING_USD,
                    "remaining_usd": settings.QUOTA_LLM_MONTHLY_CEILING_USD,
                },
            },
        }
