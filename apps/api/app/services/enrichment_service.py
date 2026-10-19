import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from redis.asyncio import Redis, from_url
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import POST_REVIEW_STATUSES, PipelineStatus
from app.core.logging import logger
from app.models.enrichment import Enrichment
from app.models.lead import Lead
from app.providers.manager import provider_manager
from app.scoring.catalog import DEFAULT_SIGNAL_WEIGHTS

ENRICHMENT_CACHE_TTL_SECONDS = 168 * 3600  # 168 hours = 7 days
# Bump when collector output changes so payloads cached by older, buggier collectors are never reused
# (v3: crawler signal fixes - homepage CTAs, analytics/chat vendors, JSON-LD, blog/press paths).
ENRICHMENT_CACHE_VERSION = "v3"


def coerce_employee_count(raw: Any) -> Optional[int]:
    """Hunter reports headcount as a number or a bracket such as "11-50" or "10000+"; keep the floor."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return int(raw) if raw >= 0 else None
    match = re.search(r"\d[\d,]*", str(raw))
    return int(match.group(0).replace(",", "")) if match else None


def _clip(value: Any, length: int) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text[:length] if text else None


def _skipped(reason: str) -> Dict[str, Any]:
    return {"signals": {}, "provenance": {"status": "skipped", "reason": reason}}


def _retrieve_result(task: "asyncio.Task[Any]") -> None:
    if not task.cancelled():
        task.exception()


class EnrichmentService:
    def __init__(self, session: AsyncSession, redis_client: Optional[Redis] = None):
        self.session = session
        self._redis = redis_client

    async def _get_redis(self) -> Optional[Redis]:
        if self._redis is None:
            try:
                self._redis = from_url(settings.REDIS_URL, decode_responses=True)
            except Exception as e:
                logger.warning(f"Could not connect to Redis for enrichment cache: {str(e)}")
                return None
        return self._redis

    async def enrich_lead(self, lead: Lead) -> Enrichment:
        """
        Gathers technical, performance, local, and SEO signals across independent collectors.
        - Redis 168-hour cache per domain avoids re-collecting (and re-paying for) the same site.
        - Free collectors (crawl, PageSpeed) run first; paid ones (SerpApi, Places, DataForSEO,
          Hunter) only once the crawl shows the site exists, so dead domains spend no credits.
        - Collector failures are isolated; unconfigured providers return None signals.
        - Leads a person already reviewed keep their pipeline status.
        """
        moves_pipeline = lead.pipeline_status not in POST_REVIEW_STATUSES
        if moves_pipeline:
            lead.pipeline_status = PipelineStatus.ENRICHING
            await self.session.flush()

        clean_domain = lead.domain.strip().lower()
        cache_key = f"leadflow:enrichment:cache:{ENRICHMENT_CACHE_VERSION}:{clean_domain}"

        # 1. Check Redis 168-hour enrichment cache
        redis = await self._get_redis()
        if redis:
            try:
                cached_raw = await redis.get(cache_key)
                if cached_raw:
                    cached_data = json.loads(cached_raw)
                    cached_payload = cached_data.get("payload")
                    cached_provenance = cached_data.get("provenance", {})
                    cached_provenance["from_cache"] = True
                    cached_provenance["retrieved_from_cache_at"] = datetime.now(timezone.utc).isoformat()
                    return await self._persist_enrichment(lead, cached_payload, cached_provenance, moves_pipeline)
            except Exception as e:
                logger.warning(f"Error reading from Redis enrichment cache: {str(e)}")

        # 2. Free collectors first. PageSpeed is the slow one (often 20-40s), so it keeps running
        # while the paid collectors work.
        crawl_task = asyncio.create_task(provider_manager.crawler.crawl_domain(lead.domain))
        pagespeed_task = asyncio.create_task(provider_manager.pagespeed.audit_url(lead.domain))
        try:
            crawl_res: Any = await crawl_task
        except Exception as e:
            crawl_res = e

        crawl_provenance = crawl_res.get("provenance", {}) if isinstance(crawl_res, dict) else {}
        site_unreachable = crawl_provenance.get("reachable") is False

        hunter_wanted = provider_manager.hunter.is_configured() and not (
            lead.industry and lead.employee_count and lead.country
        )

        if site_unreachable:
            pagespeed_task.cancel()
            pagespeed_task.add_done_callback(_retrieve_result)
            reason = "website unreachable; paid collectors skipped to save credits"
            pagespeed_res: Any = _skipped(reason)
            places_res: Any = _skipped(reason)
            dataforseo_res: Any = _skipped(reason)
            serpapi_res: Any = _skipped(reason)
            org_res: Any = None
        else:

            async def _no_org() -> None:
                return None

            org_coro = (
                provider_manager.hunter.enrich_company(lead.domain, allow_domain_search_fallback=False)
                if hunter_wanted
                else _no_org()
            )
            (pagespeed_res, places_res, dataforseo_res, org_res, serpapi_res) = await asyncio.gather(
                pagespeed_task,
                provider_manager.places.fetch_place_signals(lead.company_name, lead.domain),
                provider_manager.dataforseo.fetch_seo_signals(lead.domain),
                org_coro,
                provider_manager.serpapi.fetch_review_signals(
                    lead.company_name, lead.domain, location=lead.city or lead.country
                ),
                return_exceptions=True,
            )

        aggregated_signals: Dict[str, Any] = {}
        provenance: Dict[str, Any] = {
            "enriched_at": datetime.now(timezone.utc).isoformat(),
            "domain": clean_domain,
            "collectors": {},
            "from_cache": False,
        }

        # 3. Merge Collector Results
        if isinstance(crawl_res, dict):
            aggregated_signals.update(crawl_res.get("signals", {}))
            provenance["collectors"]["crawler"] = crawl_provenance
        else:
            provenance["collectors"]["crawler"] = {"error": str(crawl_res), "status": "failed"}

        if isinstance(pagespeed_res, dict):
            for k, sig_data in pagespeed_res.get("signals", {}).items():
                if sig_data.get("value") is not None or k not in aggregated_signals:
                    aggregated_signals[k] = sig_data
            provenance["collectors"]["pagespeed"] = pagespeed_res.get("provenance", {})
        else:
            provenance["collectors"]["pagespeed"] = {"error": str(pagespeed_res), "status": "failed"}

        # SerpApi Google Maps reviews are the primary reputation source
        if isinstance(serpapi_res, dict):
            serpapi_sig = serpapi_res.get("signals", {}).get("low_review_rating")
            if serpapi_sig and serpapi_sig.get("value") is not None:
                aggregated_signals["low_review_rating"] = serpapi_sig
            provenance["collectors"]["serpapi"] = serpapi_res.get("provenance", {})
        else:
            provenance["collectors"]["serpapi"] = {"error": str(serpapi_res), "status": "failed"}

        # Google Places fills the rating only if SerpApi did not
        if isinstance(places_res, dict):
            for k, sig_data in places_res.get("signals", {}).items():
                if sig_data.get("value") is not None or k not in aggregated_signals:
                    aggregated_signals[k] = sig_data
            provenance["collectors"]["places"] = places_res.get("provenance", {})
        else:
            provenance["collectors"]["places"] = {"error": str(places_res), "status": "failed"}

        if isinstance(dataforseo_res, dict):
            for k, sig_data in dataforseo_res.get("signals", {}).items():
                if sig_data.get("value") is not None or k not in aggregated_signals:
                    aggregated_signals[k] = sig_data
            provenance["collectors"]["dataforseo"] = dataforseo_res.get("provenance", {})
        else:
            provenance["collectors"]["dataforseo"] = {"error": str(dataforseo_res), "status": "failed"}

        # Organization firmographics (Hunter Company Enrichment)
        if isinstance(org_res, dict):
            provenance["collectors"]["hunter"] = org_res
            self._apply_firmographics(lead, org_res)
        elif isinstance(org_res, Exception):
            provenance["collectors"]["hunter"] = {"error": str(org_res), "status": "failed"}
        else:
            provenance["collectors"]["hunter"] = {
                "status": "skipped",
                "reason": "site unreachable"
                if site_unreachable
                else ("firmographics already known" if provider_manager.hunter.is_configured() else "unconfigured"),
            }

        # Ensure all 22 canonical signals exist in payload
        for sig_key in DEFAULT_SIGNAL_WEIGHTS.keys():
            if sig_key not in aggregated_signals:
                aggregated_signals[sig_key] = {
                    "value": None,
                    "evidence": "Signal collector unconfigured or skipped",
                    "provider": None,
                    "is_available": False,
                }

        # 4. Cache only real audits. A failed or blocked crawl must not pin "unreachable" on a
        # domain for a week when the outage was temporary.
        if redis and crawl_provenance.get("reachable") is True:
            try:
                cache_obj = {
                    "payload": aggregated_signals,
                    "provenance": provenance,
                    "cached_at": datetime.now(timezone.utc).isoformat(),
                }
                await redis.set(cache_key, json.dumps(cache_obj), ex=ENRICHMENT_CACHE_TTL_SECONDS)
            except Exception as e:
                logger.warning(f"Error saving to Redis enrichment cache: {str(e)}")

        # 5. Persist Enrichment Record
        return await self._persist_enrichment(lead, aggregated_signals, provenance, moves_pipeline)

    @staticmethod
    def _apply_firmographics(lead: Lead, org: Dict[str, Any]) -> None:
        """Fills blanks only, clipped to the column sizes so a long value can't fail the lead."""
        if not lead.employee_count:
            lead.employee_count = coerce_employee_count(org.get("employee_count"))
        if not lead.industry:
            lead.industry = _clip(org.get("industry"), 100)
        if not lead.country:
            lead.country = _clip(org.get("country"), 100)
        if not lead.city:
            lead.city = _clip(org.get("city"), 100)
        if (not lead.company_name or lead.company_name == lead.domain) and org.get("company_name"):
            lead.company_name = _clip(org["company_name"], 255) or lead.company_name

    async def _persist_enrichment(
        self, lead: Lead, payload: Dict[str, Any], provenance: Dict[str, Any], moves_pipeline: bool = True
    ) -> Enrichment:
        """Saves a new immutable versioned Enrichment record and advances pipeline status."""
        stmt = select(func.coalesce(func.max(Enrichment.version), 0)).where(
            Enrichment.lead_id == lead.id
        )
        latest_version = (await self.session.execute(stmt)).scalar_one()

        enrichment = Enrichment(
            org_id=lead.org_id,
            lead_id=lead.id,
            version=latest_version + 1,
            payload=payload,
            provider_provenance=provenance,
        )
        self.session.add(enrichment)

        if moves_pipeline:
            lead.pipeline_status = PipelineStatus.ENRICHED
        await self.session.flush()
        return enrichment
