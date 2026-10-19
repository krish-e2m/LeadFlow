"""Queues an AI email draft for leads right after an operator approves them."""

import uuid
from typing import Dict, Iterable, List

from arq import create_pool
from arq.connections import RedisSettings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import DraftApprovalStatus
from app.core.logging import logger
from app.models.draft import Draft
from app.providers.manager import provider_manager

# Outcome reported to the UI for each approved lead.
QUEUED = "queued"  # a worker is writing the draft
EXISTS = "exists"  # the lead already has a draft, nothing queued
DISABLED = "disabled"  # AUTO_DRAFT_ON_APPROVAL is off
NOT_CONFIGURED = "not_configured"  # OpenRouter has no API key
UNAVAILABLE = "unavailable"  # the worker queue (Redis) couldn't be reached

DRAFT_JOB = "generate_lead_draft"


async def leads_with_open_drafts(session: AsyncSession, lead_ids: Iterable[uuid.UUID]) -> set:
    """Leads that already have a pending or approved draft. Rejected drafts don't count."""
    ids = list(lead_ids)
    if not ids:
        return set()
    stmt = select(Draft.lead_id).where(
        Draft.lead_id.in_(ids), Draft.approval_status != DraftApprovalStatus.REJECTED
    )
    return set((await session.execute(stmt)).scalars().all())


class AutoDraftPlan:
    """Per-lead outcome decided inside the approval transaction, plus the leads still to queue."""

    def __init__(self, outcome: Dict[uuid.UUID, str], to_queue: List[uuid.UUID]):
        self.outcome = outcome
        self.to_queue = to_queue


async def plan_auto_drafts(session: AsyncSession, lead_ids: Iterable[uuid.UUID]) -> AutoDraftPlan:
    """
    Decides which approved leads need a draft. Call it BEFORE committing the approval: the request's
    row-level-security context is transaction-local, so queries after the commit can't see the org's drafts.
    """
    ids = list(dict.fromkeys(lead_ids))
    if not ids:
        return AutoDraftPlan({}, [])
    if not settings.AUTO_DRAFT_ON_APPROVAL:
        return AutoDraftPlan({lid: DISABLED for lid in ids}, [])
    if not provider_manager.openrouter.is_configured():
        return AutoDraftPlan({lid: NOT_CONFIGURED for lid in ids}, [])

    with_drafts = await leads_with_open_drafts(session, ids)
    return AutoDraftPlan({lid: EXISTS for lid in with_drafts}, [lid for lid in ids if lid not in with_drafts])


async def dispatch_auto_drafts(org_id: uuid.UUID, plan: AutoDraftPlan) -> Dict[uuid.UUID, str]:
    """
    Queues one draft job per planned lead. Call it AFTER the approval is committed so the worker sees
    the approved state. Approving is the operator action that authorizes the draft's LLM spend; the
    daily draft quota still applies inside the job.
    """
    outcome = dict(plan.outcome)
    if not plan.to_queue:
        return outcome
    try:
        pool = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
        try:
            for lid in plan.to_queue:
                await pool.enqueue_job(DRAFT_JOB, str(lid), str(org_id))
                outcome[lid] = QUEUED
        finally:
            await pool.close()
    except Exception as exc:
        logger.warning(f"Could not queue auto drafts for org {org_id}: {exc}")
        for lid in plan.to_queue:
            outcome.setdefault(lid, UNAVAILABLE)
    return outcome
