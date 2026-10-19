import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import or_, select

from app.core.config import settings
from app.core.constants import (
    POST_REVIEW_STATUSES,
    ApprovalStatus,
    CrmSyncStatus,
    PipelineStatus,
    RunStatus,
    ScoreBand,
)
from app.core.logging import logger
from app.db.session import tenant_session
from app.models.contact import Contact
from app.models.crm_sync import CrmSync
from app.models.enrichment import Enrichment
from app.models.lead import Lead
from app.models.organization import Organization
from app.providers.hubspot import normalize_domain
from app.providers.manager import provider_manager
from app.repositories.run_repo import RunRepository
from app.security.tenant import set_current_tenant
from app.services.enrichment_service import (
    ENRICHMENT_CACHE_TTL_SECONDS,
    EnrichmentService,
    coerce_employee_count,
)
from app.services.quota_service import QuotaService
from app.services.scoring_service import ScoringService

# Contacts are looked up (one Hunter Domain Search credit each) only for leads worth contacting.
CONTACT_LOOKUP_BANDS = {ScoreBand.QUALIFIED, ScoreBand.REVIEW}
MAX_RECORDED_FAILURES = 50

SUCCEEDED, FAILED, SKIPPED = "succeeded", "failed", "skipped"


def _clean_domain(raw: str) -> str:
    d = (raw or "").strip().lower().replace("https://", "").replace("http://", "")
    return d.split("/")[0].split("?")[0].split("#")[0].strip(".")


def _clip(value: Any, length: int) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text[:length] if text else None


def _dedupe(prospects: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Leads are unique per domain; the same company twice in one run would race on insert."""
    seen = set()
    unique = []
    for p in prospects:
        domain = _clean_domain(p.get("domain", ""))
        if domain and domain not in seen:
            seen.add(domain)
            unique.append({**p, "domain": domain})
    return unique


async def _update_run(run_id: uuid.UUID, org_id: uuid.UUID, **fields: Any) -> None:
    async with tenant_session(org_id) as session:
        await RunRepository(session).update_progress(run_id, **fields)
        await session.commit()


def _fresh_enrichment(enrichment: Optional[Enrichment]) -> bool:
    """A recent enrichment of a reachable site can be re-scored instead of re-collected."""
    if enrichment is None or enrichment.created_at is None:
        return False
    age = datetime.now(timezone.utc) - enrichment.created_at
    crawler = ((enrichment.provider_provenance or {}).get("collectors") or {}).get("crawler") or {}
    return age < timedelta(seconds=ENRICHMENT_CACHE_TTL_SECONDS) and crawler.get("reachable") is True


async def _attach_contacts(session, lead: Lead, org_id: uuid.UUID, target_roles: Optional[List[str]]) -> None:
    has_contacts = (
        await session.execute(select(Contact.id).where(Contact.lead_id == lead.id).limit(1))
    ).first()
    if has_contacts:
        return
    try:
        contacts_data = await provider_manager.hunter.search_contacts_for_lead(lead.domain, titles=target_roles)
    except Exception as ce:
        logger.warning(f"Hunter contact search skipped for {lead.domain}: {str(ce)}")
        return

    seen = set()
    for c_data in contacts_data[:2]:
        # Emails are masked (j***@acme.com) until reveal, so de-duplicate on identity instead.
        identity = (c_data.get("first_name"), c_data.get("last_name")) if (
            c_data.get("first_name") or c_data.get("last_name")
        ) else c_data.get("email")
        if identity in seen:
            continue
        seen.add(identity)
        session.add(
            Contact(
                org_id=org_id,
                lead_id=lead.id,
                first_name=c_data.get("first_name"),
                last_name=c_data.get("last_name"),
                title=c_data.get("title"),
                linkedin_url=c_data.get("linkedin_url"),
                email=c_data.get("email"),
                is_revealed=False,
            )
        )


async def _process_prospect(
    org_id: uuid.UUID,
    search_id: Optional[uuid.UUID],
    prospect: Dict[str, Any],
    target_roles: Optional[List[str]],
) -> Tuple[str, Optional[str]]:
    """
    Ingest -> enrich -> score one company. Returns (outcome, failure_reason).
    The lead row is committed before enrichment so a failure can be recorded on it ("error" stage)
    instead of the company silently disappearing, and so a retried job resumes rather than repays.
    """
    domain = prospect["domain"]

    async with tenant_session(org_id) as session:
        lead = (
            await session.execute(
                select(Lead).where(Lead.org_id == org_id, Lead.domain == domain, Lead.deleted_at.is_(None))
            )
        ).scalars().first()

        if lead is not None and lead.pipeline_status in POST_REVIEW_STATUSES:
            # Already approved, rejected, drafted or synced: a new search must not reset it.
            if not lead.search_id and search_id:
                lead.search_id = search_id
            return SKIPPED, None

        if lead is None:
            lead = Lead(
                org_id=org_id,
                search_id=search_id,
                domain=domain,
                company_name=_clip(prospect.get("company_name"), 255) or domain,
                industry=_clip(prospect.get("industry"), 100),
                country=_clip(prospect.get("country"), 100),
                city=_clip(prospect.get("city"), 100),
                employee_count=coerce_employee_count(prospect.get("employee_count")),
                pipeline_status=PipelineStatus.SOURCED,
                score_band=None,
                approval_status=ApprovalStatus.PENDING,
            )
            session.add(lead)
            await session.flush()
        elif not lead.search_id and search_id:
            lead.search_id = search_id

        lead_id = lead.id
        latest = (
            await session.execute(
                select(Enrichment).where(Enrichment.lead_id == lead_id).order_by(Enrichment.version.desc()).limit(1)
            )
        ).scalars().first()
        reusable_enrichment_id = latest.id if _fresh_enrichment(latest) else None

    try:
        async with tenant_session(org_id) as session:
            lead = await session.get(Lead, lead_id)
            if reusable_enrichment_id is not None:
                enrichment = await session.get(Enrichment, reusable_enrichment_id)
            else:
                enrichment = await EnrichmentService(session).enrich_lead(lead)

            score = await ScoringService(session).score_lead(lead, enrichment=enrichment)

            if score.overall_score is None:
                crawler = ((enrichment.provider_provenance or {}).get("collectors") or {}).get("crawler") or {}
                reason = crawler.get("error") or "No audit signals could be collected for this website."
                lead.pipeline_status = PipelineStatus.ERROR
                lead.error_reason = _clip(reason, 500)
                return FAILED, reason

            if score.score_band in CONTACT_LOOKUP_BANDS and provider_manager.hunter.is_configured():
                await _attach_contacts(session, lead, org_id, target_roles)
        return SUCCEEDED, None

    except Exception as e:
        reason = f"{type(e).__name__}: {str(e)}"[:500]
        logger.error(f"Failed processing lead {domain}: {reason}")
        try:
            async with tenant_session(org_id) as session:
                lead = await session.get(Lead, lead_id)
                if lead is not None and lead.pipeline_status not in POST_REVIEW_STATUSES:
                    lead.pipeline_status = PipelineStatus.ERROR
                    lead.error_reason = reason
        except Exception as mark_err:
            logger.warning(f"Could not record error state for lead {domain}: {mark_err}")
        return FAILED, reason


def _apply_vertical_filters(prospects: List[Dict[str, Any]], query_params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Post-discovery vertical include/exclude. Hunter Discover already filtered by industry and usually
    returns no industry data, so a prospect without industry/keywords can't be judged here and is kept.
    """
    def terms(p: Dict[str, Any]) -> Tuple[str, List[str]]:
        p_ind = (p.get("industry") or "").strip().lower()
        p_keywords = [str(k).strip().lower() for k in (p.get("keywords") or []) if str(k).strip()]
        return p_ind, p_keywords

    def matches(p_ind: str, p_keywords: List[str], term: str) -> bool:
        return bool(
            (p_ind and (term in p_ind or p_ind in term))
            or any(term in kw or kw in term for kw in p_keywords)
        )

    exclude_verticals = query_params.get("exclude_verticals") or []
    norm_exclude = [v.strip().lower() for v in exclude_verticals if isinstance(v, str) and v.strip()]
    if norm_exclude:
        kept = []
        for p in prospects:
            p_ind, p_keywords = terms(p)
            if not any(matches(p_ind, p_keywords, ex) for ex in norm_exclude):
                kept.append(p)
        prospects = kept

    verticals = query_params.get("verticals") or query_params.get("industries") or []
    vertical_match = str(query_params.get("vertical_match") or "or").strip().lower()
    norm_verticals = [v.strip().lower() for v in verticals if isinstance(v, str) and v.strip()] if isinstance(verticals, list) else []
    if norm_verticals:
        kept = []
        for p in prospects:
            p_ind, p_keywords = terms(p)
            if not p_ind and not p_keywords:
                kept.append(p)
            elif vertical_match == "and":
                if all(matches(p_ind, p_keywords, v) for v in norm_verticals):
                    kept.append(p)
            elif any(matches(p_ind, p_keywords, v) for v in norm_verticals):
                kept.append(p)
        prospects = kept
    return prospects


async def run_search_pipeline(
    ctx: Dict[str, Any], run_id_str: str, org_id_str: str, limit: int, query_params: Dict[str, Any]
) -> Dict[str, Any]:
    """
    ARQ Background Task: Coordinates discovery, enrichment, and scoring across prospects.
    Revalidates organization authorization before running and guarantees concurrent run
    quota release in all termination paths. Leads are processed in parallel
    (SEARCH_LEAD_CONCURRENCY), and an interrupted run (job timeout, worker shutdown) is marked failed
    rather than left "running".
    """
    run_id = uuid.UUID(run_id_str)
    org_id = uuid.UUID(org_id_str)
    finished = False

    logger.info(f"Starting async search pipeline for run_id={run_id}, limit={limit}")
    set_current_tenant(org_id)

    try:
        # Revalidate organization authorization in worker
        search_id = None
        async with tenant_session(org_id) as session:
            org = (
                await session.execute(
                    select(Organization).where(Organization.id == org_id, Organization.deleted_at.is_(None))
                )
            ).scalars().first()
            run_repo = RunRepository(session)
            if not org or not org.is_active:
                logger.warning(f"Aborting run {run_id}: organization {org_id} is inactive or deleted.")
                await run_repo.update_progress(
                    run_id,
                    progress_pct=0,
                    status=RunStatus.FAILED,
                    error_details={"org_error": "Organization is suspended or offboarded."},
                )
                await session.commit()
                finished = True
                return {"status": "failed", "error": "Organization suspended or offboarded"}

            run_obj = await run_repo.get_by_id(run_id)
            if run_obj:
                search_id = run_obj.search_id
            await run_repo.update_progress(run_id, progress_pct=5, status=RunStatus.RUNNING)
            await session.commit()

        # 1. Discovery Stage: direct domains, or Hunter Discover (free)
        try:
            domains = query_params.get("domains") or []
            if isinstance(domains, list) and domains:
                sourced_prospects = []
                for d in domains[:limit]:
                    clean_d = _clean_domain(d)
                    if clean_d:
                        sourced_prospects.append(
                            {
                                "company_name": clean_d.split(".")[0].capitalize(),
                                "domain": clean_d,
                                "industry": None,
                                "country": None,
                                "city": None,
                                "employee_count": None,
                            }
                        )
            elif provider_manager.hunter.is_configured():
                hunter_res = await provider_manager.hunter.search_organizations(query_params, limit=limit)
                sourced_prospects = hunter_res.get("organizations", [])
            else:
                sourced_prospects = []
        except Exception as e:
            logger.error(f"Discovery stage failed: {str(e)}")
            await _update_run(
                run_id, org_id, progress_pct=10, status=RunStatus.FAILED, error_details={"discovery_error": str(e)}
            )
            finished = True
            return {"status": "failed", "error": str(e)}

        sourced_prospects = _dedupe(sourced_prospects)

        # Post-discovery exclusions: explicit domains
        exclude_domains = query_params.get("exclude_domains") or []
        if isinstance(exclude_domains, list) and exclude_domains and sourced_prospects:
            excluded = {_clean_domain(d) for d in exclude_domains if isinstance(d, str) and d.strip()}
            sourced_prospects = [p for p in sourced_prospects if p["domain"] not in excluded]

        # Post-discovery exclusions: companies already synced to the CRM
        if bool(query_params.get("exclude_existing_crm", False)) and sourced_prospects:
            async with tenant_session(org_id) as session:
                crm_synced_stmt = (
                    select(Lead.domain)
                    .outerjoin(CrmSync, CrmSync.lead_id == Lead.id)
                    .where(
                        Lead.org_id == org_id,
                        Lead.deleted_at.is_(None),
                        or_(Lead.pipeline_status == PipelineStatus.SYNCED, CrmSync.sync_status == CrmSyncStatus.SUCCESS),
                    )
                )
                synced = {_clean_domain(d) for d in (await session.execute(crm_synced_stmt)).scalars().all() if d}
            sourced_prospects = [p for p in sourced_prospects if p["domain"] not in synced]

            if sourced_prospects and provider_manager.hubspot.is_configured():
                try:
                    in_hubspot = await provider_manager.hubspot.find_existing_company_domains(
                        [p["domain"] for p in sourced_prospects]
                    )
                    if in_hubspot:
                        sourced_prospects = [p for p in sourced_prospects if normalize_domain(p["domain"]) not in in_hubspot]
                except Exception as hs_err:
                    logger.warning(f"HubSpot existing-company check skipped: {hs_err}")

        sourced_prospects = _apply_vertical_filters(sourced_prospects, query_params)[:limit]

        total_prospects = len(sourced_prospects)
        if total_prospects == 0:
            await _update_run(
                run_id, org_id, progress_pct=100, status=RunStatus.COMPLETED,
                items_processed=0, items_succeeded=0, items_failed=0,
            )
            finished = True
            return {"status": "completed", "items_processed": 0}

        # 2. Ingest -> Enrich -> Score, several leads at a time
        target_roles = query_params.get("target_roles") or None
        counts = {SUCCEEDED: 0, FAILED: 0, SKIPPED: 0}
        failures: Dict[str, str] = {}
        progress_lock = asyncio.Lock()
        semaphore = asyncio.Semaphore(max(1, settings.SEARCH_LEAD_CONCURRENCY))

        async def handle(prospect: Dict[str, Any]) -> None:
            async with semaphore:
                outcome, reason = await _process_prospect(org_id, search_id, prospect, target_roles)
            async with progress_lock:
                counts[outcome] += 1
                if reason and len(failures) < MAX_RECORDED_FAILURES:
                    failures[prospect["domain"]] = reason
                processed = sum(counts.values())
                try:
                    await _update_run(
                        run_id,
                        org_id,
                        progress_pct=10 + int(processed / total_prospects * 85),
                        items_processed=processed,
                        items_succeeded=counts[SUCCEEDED] + counts[SKIPPED],
                        items_failed=counts[FAILED],
                    )
                except Exception as progress_err:
                    logger.warning(f"Progress update failed for run {run_id}: {progress_err}")

        await asyncio.gather(*(handle(p) for p in sourced_prospects))

        # 3. Complete Run
        details: Dict[str, Any] = {}
        if failures:
            details["failed_leads"] = failures
        if counts[SKIPPED]:
            details["already_reviewed_skipped"] = counts[SKIPPED]
        await _update_run(
            run_id,
            org_id,
            progress_pct=100,
            status=RunStatus.COMPLETED,
            items_processed=total_prospects,
            items_succeeded=counts[SUCCEEDED] + counts[SKIPPED],
            items_failed=counts[FAILED],
            error_details=details or None,
        )
        finished = True

        logger.info(
            f"Finished search pipeline run_id={run_id}: {counts[SUCCEEDED]} scored, "
            f"{counts[SKIPPED]} already reviewed, {counts[FAILED]} failed."
        )
        return {
            "status": "completed",
            "items_processed": total_prospects,
            "succeeded": counts[SUCCEEDED],
            "skipped": counts[SKIPPED],
            "failed": counts[FAILED],
        }
    finally:
        if not finished:
            # Job timeout, worker shutdown or an unexpected error: never leave the run "running",
            # which would block the org's concurrent-run and monthly quota until a worker restart.
            try:
                await _update_run(
                    run_id,
                    org_id,
                    progress_pct=100,
                    status=RunStatus.FAILED,
                    error_details={"error": "The search was interrupted (job timeout, worker shutdown or crash)."},
                )
            except Exception as mark_err:
                logger.warning(f"Could not mark interrupted run {run_id} as failed: {mark_err}")
        await QuotaService.release_concurrent_run(org_id)
        try:
            async with tenant_session(org_id) as session:
                await QuotaService.reconcile_lead_ingestion(org_id, session)
        except Exception as q_err:
            logger.warning(f"Failed to reconcile lead quota on search completion for org {org_id}: {q_err}")
