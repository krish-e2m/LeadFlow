import uuid
from typing import Any, Dict

from sqlalchemy import or_, select

from app.core.constants import (
    ApprovalStatus,
    CrmSyncStatus,
    PipelineStatus,
    RunStatus,
)
from app.core.logging import logger
from app.db.session import tenant_session
from app.models.contact import Contact
from app.models.crm_sync import CrmSync
from app.models.lead import Lead
from app.models.organization import Organization
from app.providers.hubspot import normalize_domain
from app.providers.manager import provider_manager
from app.repositories.run_repo import RunRepository
from app.security.tenant import set_current_tenant
from app.services.enrichment_service import EnrichmentService
from app.services.quota_service import QuotaService
from app.services.scoring_service import ScoringService


async def run_search_pipeline(
    ctx: Dict[str, Any], run_id_str: str, org_id_str: str, limit: int, query_params: Dict[str, Any]
) -> Dict[str, Any]:
    """
    ARQ Background Task: Coordinates discovery, enrichment, and scoring across prospects.
    Revalidates organization authorization before running and guarantees concurrent run
    quota release in all termination paths.
    """
    run_id = uuid.UUID(run_id_str)
    org_id = uuid.UUID(org_id_str)

    logger.info(f"Starting async search pipeline for run_id={run_id}, limit={limit}")
    set_current_tenant(org_id)

    try:
        # Revalidate organization authorization in worker
        search_id = None
        async with tenant_session(org_id) as session:
            org_stmt = select(Organization).where(
                Organization.id == org_id, Organization.deleted_at.is_(None)
            )
            org = (await session.execute(org_stmt)).scalars().first()
            if not org or not org.is_active:
                logger.warning(f"Aborting run {run_id}: organization {org_id} is inactive or deleted.")
                run_repo = RunRepository(session)
                await run_repo.update_progress(
                    run_id,
                    progress_pct=0,
                    status=RunStatus.FAILED,
                    error_details={"org_error": "Organization is suspended or offboarded."},
                )
                await session.commit()
                return {"status": "failed", "error": "Organization suspended or offboarded"}

            run_repo = RunRepository(session)
            run_obj = await run_repo.get_by_id(run_id)
            if run_obj:
                search_id = run_obj.search_id
            await run_repo.update_progress(run_id, progress_pct=5, status=RunStatus.RUNNING)
            await session.commit()

        sourced_prospects = []

        # 1. Discovery Stage: Direct domains input or Hunter discovery
        try:
            domains = query_params.get("domains") or []
            if domains and isinstance(domains, list) and len(domains) > 0:
                for d in domains[:limit]:
                    clean_d = d.strip().replace("https://", "").replace("http://", "").split("/")[0]
                    if clean_d:
                        sourced_prospects.append(
                            {
                                "company_name": clean_d.split(".")[0].capitalize(),
                                "domain": clean_d,
                                "industry": "Direct Input",
                                "country": None,
                                "city": None,
                                "employee_count": None,
                            }
                        )
            elif (
                query_params.get("locations")
                or query_params.get("employee_ranges")
                or query_params.get("verticals")
                or query_params.get("industries")
                or query_params.get("keywords")
            ) and provider_manager.hunter.is_configured():
                hunter_res = await provider_manager.hunter.search_organizations(
                    query_params, limit=limit
                )
                sourced_prospects = hunter_res.get("organizations", [])
            elif provider_manager.hunter.is_configured():
                hunter_res = await provider_manager.hunter.search_organizations(
                    query_params, limit=limit
                )
                sourced_prospects = hunter_res.get("organizations", [])
            else:
                sourced_prospects = []
        except Exception as e:
            logger.error(f"Discovery stage failed: {str(e)}")
            async with tenant_session(org_id) as session:
                run_repo = RunRepository(session)
                await run_repo.update_progress(
                    run_id,
                    progress_pct=10,
                    status=RunStatus.FAILED,
                    error_details={"discovery_error": str(e)},
                )
                await session.commit()
            return {"status": "failed", "error": str(e)}

        # Post-discovery downstream exclusions: exclude_domains
        exclude_domains = query_params.get("exclude_domains") or []
        if isinstance(exclude_domains, list) and exclude_domains and sourced_prospects:
            normalized_excluded = {
                d.strip().lower().replace("https://", "").replace("http://", "").split("/")[0]
                for d in exclude_domains
                if isinstance(d, str) and d.strip()
            }
            sourced_prospects = [
                p
                for p in sourced_prospects
                if p.get("domain", "").strip().lower() not in normalized_excluded
            ]

        # Post-discovery downstream exclusions: exclude_existing_crm
        exclude_existing_crm = bool(query_params.get("exclude_existing_crm", False))
        if exclude_existing_crm and sourced_prospects:
            async with tenant_session(org_id) as session:
                crm_synced_stmt = (
                    select(Lead.domain)
                    .outerjoin(CrmSync, CrmSync.lead_id == Lead.id)
                    .where(
                        Lead.org_id == org_id,
                        Lead.deleted_at.is_(None),
                        or_(
                            Lead.pipeline_status == PipelineStatus.SYNCED,
                            CrmSync.sync_status == CrmSyncStatus.SUCCESS,
                        ),
                    )
                )
                crm_synced_domains = set((await session.execute(crm_synced_stmt)).scalars().all())
                crm_synced_domains = {d.strip().lower() for d in crm_synced_domains if d}
                sourced_prospects = [
                    p
                    for p in sourced_prospects
                    if p.get("domain", "").strip().lower() not in crm_synced_domains
                ]

        # Also skip companies that already exist in HubSpot (one search request per 100 domains)
        if exclude_existing_crm and sourced_prospects and provider_manager.hubspot.is_configured():
            try:
                in_hubspot = await provider_manager.hubspot.find_existing_company_domains(
                    [p.get("domain", "") for p in sourced_prospects]
                )
                if in_hubspot:
                    sourced_prospects = [
                        p for p in sourced_prospects if normalize_domain(p.get("domain", "")) not in in_hubspot
                    ]
            except Exception as hs_err:
                logger.warning(f"HubSpot existing-company check skipped: {hs_err}")

        # Post-discovery downstream exclusions: exclude_verticals
        exclude_verticals = query_params.get("exclude_verticals") or []
        if isinstance(exclude_verticals, list) and exclude_verticals and sourced_prospects:
            norm_exclude_v = [v.strip().lower() for v in exclude_verticals if isinstance(v, str) and v.strip()]
            if norm_exclude_v:
                filtered_prospects = []
                for p in sourced_prospects:
                    p_ind = (p.get("industry") or "").strip().lower()
                    p_keywords = [str(k).strip().lower() for k in p.get("keywords", []) if str(k).strip()]
                    is_excluded = any(
                        (ex_v in p_ind or p_ind in ex_v or any(ex_v in kw or kw in ex_v for kw in p_keywords))
                        for ex_v in norm_exclude_v
                        if (p_ind or p_keywords)
                    )
                    if not is_excluded:
                        filtered_prospects.append(p)
                sourced_prospects = filtered_prospects

        # Post-discovery downstream filtering: verticals & vertical_match (OR vs AND)
        verticals = query_params.get("verticals") or query_params.get("industries") or []
        vertical_match = str(query_params.get("vertical_match") or "or").strip().lower()
        if isinstance(verticals, list) and verticals and sourced_prospects:
            norm_verticals = [v.strip().lower() for v in verticals if isinstance(v, str) and v.strip()]
            if norm_verticals:
                matched_prospects = []
                for p in sourced_prospects:
                    p_ind = (p.get("industry") or "").strip().lower()
                    p_keywords = [str(k).strip().lower() for k in p.get("keywords", []) if str(k).strip()]

                    def _matches_term(v_term: str) -> bool:
                        return bool(
                            (p_ind and (v_term in p_ind or p_ind in v_term))
                            or any(v_term in kw or kw in v_term for kw in p_keywords)
                        )

                    if vertical_match == "and":
                        if all(_matches_term(v) for v in norm_verticals):
                            matched_prospects.append(p)
                    else:
                        if not p_ind and not p_keywords:
                            matched_prospects.append(p)
                        elif any(_matches_term(v) for v in norm_verticals):
                            matched_prospects.append(p)
                sourced_prospects = matched_prospects

        total_prospects = len(sourced_prospects)
        if total_prospects == 0:
            async with tenant_session(org_id) as session:
                run_repo = RunRepository(session)
                await run_repo.update_progress(
                    run_id,
                    progress_pct=100,
                    status=RunStatus.COMPLETED,
                    items_processed=0,
                    items_succeeded=0,
                    items_failed=0,
                )
                await session.commit()
            return {"status": "completed", "items_processed": 0}

        succeeded = 0
        failed = 0

        # 2. Sequential / Batch Processing: Ingest Lead -> Enrich -> Score
        for idx, prospect in enumerate(sourced_prospects):
            domain = prospect["domain"]
            try:
                async with tenant_session(org_id) as session:
                    # Upsert or fetch lead
                    lead_stmt = select(Lead).where(
                        Lead.org_id == org_id, Lead.domain == domain, Lead.deleted_at.is_(None)
                    )
                    lead = (await session.execute(lead_stmt)).scalars().first()

                    if not lead:
                        lead = Lead(
                            org_id=org_id,
                            search_id=search_id,
                            domain=domain,
                            company_name=prospect.get("company_name", domain),
                            industry=prospect.get("industry"),
                            country=prospect.get("country"),
                            city=prospect.get("city"),
                            employee_count=prospect.get("employee_count"),
                            pipeline_status=PipelineStatus.SOURCED,
                            score_band=None,
                            approval_status=ApprovalStatus.PENDING,
                        )
                        session.add(lead)
                        await session.flush()
                    elif not lead.search_id and search_id:
                        lead.search_id = search_id

                    # Ingest sample contact placeholder with fault isolation (Hunter)
                    contacts_data = []
                    target_roles = query_params.get("target_roles") or None
                    if provider_manager.hunter.is_configured():
                        try:
                            contacts_data = await provider_manager.hunter.search_contacts_for_lead(
                                domain, titles=target_roles
                            )
                        except Exception as ce:
                            logger.warning(f"Hunter contact search skipped for {domain}: {str(ce)}")

                    for c_data in contacts_data[:2]:
                        # Emails are masked (e.g. j***@acme.com) until reveal, so different people can
                        # share the same masked value; de-duplicate on identity, not on the masked email.
                        c_stmt = select(Contact).where(Contact.lead_id == lead.id)
                        if c_data.get("first_name") or c_data.get("last_name"):
                            c_stmt = c_stmt.where(
                                Contact.first_name == c_data.get("first_name"),
                                Contact.last_name == c_data.get("last_name"),
                            )
                        else:
                            c_stmt = c_stmt.where(Contact.email == c_data["email"])
                        if not (await session.execute(c_stmt)).scalars().first():
                            contact = Contact(
                                org_id=org_id,
                                lead_id=lead.id,
                                first_name=c_data.get("first_name"),
                                last_name=c_data.get("last_name"),
                                title=c_data.get("title"),
                                linkedin_url=c_data.get("linkedin_url"),
                                email=c_data.get("email"),
                                is_revealed=False,
                            )
                            session.add(contact)

                    # Enrichment & Scoring
                    enrichment_service = EnrichmentService(session)
                    enrichment = await enrichment_service.enrich_lead(lead)

                    scoring_service = ScoringService(session)
                    await scoring_service.score_lead(lead, enrichment=enrichment)

                    await session.commit()
                    succeeded += 1

            except Exception as e:
                logger.error(f"Failed processing lead {domain}: {str(e)}")
                failed += 1

            # Calculate progress
            pct = 10 + int(((idx + 1) / total_prospects) * 85)
            async with tenant_session(org_id) as session:
                run_repo = RunRepository(session)
                await run_repo.update_progress(
                    run_id,
                    progress_pct=pct,
                    items_processed=idx + 1,
                    items_succeeded=succeeded,
                    items_failed=failed,
                )
                await session.commit()

        # 3. Complete Run
        async with tenant_session(org_id) as session:
            run_repo = RunRepository(session)
            await run_repo.update_progress(
                run_id,
                progress_pct=100,
                status=RunStatus.COMPLETED,
                items_processed=total_prospects,
                items_succeeded=succeeded,
                items_failed=failed,
            )
            await session.commit()

            logger.info(
                f"Finished search pipeline run_id={run_id}: {succeeded} succeeded, {failed} failed."
            )
            return {
                "status": "completed",
                "items_processed": total_prospects,
                "succeeded": succeeded,
                "failed": failed,
            }
    finally:
        # Guarantee release of concurrent run reservation and lead quota reconciliation under all conditions
        await QuotaService.release_concurrent_run(org_id)
        try:
            async with tenant_session(org_id) as session:
                await QuotaService.reconcile_lead_ingestion(org_id, session)
        except Exception as q_err:
            logger.warning(f"Failed to reconcile lead quota on search completion for org {org_id}: {q_err}")
