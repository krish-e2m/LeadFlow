import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from redis.asyncio import Redis, from_url
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.constants import PipelineStatus
from app.core.logging import logger
from app.models.enrichment import Enrichment
from app.models.lead import Lead
from app.providers.manager import provider_manager
from app.scoring.catalog import DEFAULT_SIGNAL_WEIGHTS

ENRICHMENT_CACHE_TTL_SECONDS = 168 * 3600  # 168 hours = 7 days
# Bump when collector output changes so payloads cached by older, buggier collectors are never reused
# (v2: Firecrawl now supplies rawHtml, so <head>-based signals are no longer misreported).
ENRICHMENT_CACHE_VERSION = "v2"


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
        - Uses Redis 168-hour cache to avoid redundant external collection.
        - Isolates collector failures so one collector's error does not block others.
        - Unconfigured paid providers (PageSpeed, DataForSEO, Places) return None without breaking flow.
        - Stores immutable versioned Enrichment record with provider provenance.
        """
        lead.pipeline_status = PipelineStatus.ENRICHING
        await self.session.flush()

        clean_domain = lead.domain.strip().lower()
        cache_key = f"leadflow:enrichment:cache:{ENRICHMENT_CACHE_VERSION}:{clean_domain}"

        # 1. Check Redis 168-hour enrichment cache
        redis = await self._get_redis()
        cached_payload = None
        if redis:
            try:
                cached_raw = await redis.get(cache_key)
                if cached_raw:
                    cached_data = json.loads(cached_raw)
                    cached_payload = cached_data.get("payload")
                    cached_provenance = cached_data.get("provenance", {})
                    cached_provenance["from_cache"] = True
                    cached_provenance["retrieved_from_cache_at"] = datetime.now(timezone.utc).isoformat()

                    # Save new Enrichment record using cached payload
                    return await self._persist_enrichment(
                        lead, cached_payload, cached_provenance
                    )
            except Exception as e:
                logger.warning(f"Error reading from Redis enrichment cache: {str(e)}")

        # 2. Concurrent Collector Execution with Fault Isolation
        crawl_task = provider_manager.crawler.crawl_domain(lead.domain)
        pagespeed_task = provider_manager.pagespeed.audit_url(lead.domain)
        places_task = provider_manager.places.fetch_place_signals(lead.company_name, lead.domain)
        dataforseo_task = provider_manager.dataforseo.fetch_seo_signals(lead.domain)
        serpapi_task = provider_manager.serpapi.fetch_review_signals(
            lead.company_name, lead.domain, location=lead.city or lead.country
        )

        # Primary organization enricher: Hunter.io Company Enrichment
        if provider_manager.hunter.is_configured():
            org_task = provider_manager.hunter.enrich_company(lead.domain)
        else:
            async def _noop_enrich():
                return None
            org_task = _noop_enrich()

        (
            crawl_res,
            pagespeed_res,
            places_res,
            dataforseo_res,
            org_res,
            serpapi_res,
        ) = await asyncio.gather(
            crawl_task,
            pagespeed_task,
            places_task,
            dataforseo_task,
            org_task,
            serpapi_task,
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
        # Merge Crawler signals
        if isinstance(crawl_res, dict) and not isinstance(crawl_res, Exception):
            aggregated_signals.update(crawl_res.get("signals", {}))
            provenance["collectors"]["crawler"] = crawl_res.get("provenance", {})
        else:
            err = str(crawl_res)
            provenance["collectors"]["crawler"] = {"error": err, "status": "failed"}

        # Merge PageSpeed signals
        if isinstance(pagespeed_res, dict) and not isinstance(pagespeed_res, Exception):
            for k, sig_data in pagespeed_res.get("signals", {}).items():
                if sig_data.get("value") is not None or k not in aggregated_signals:
                    aggregated_signals[k] = sig_data
            provenance["collectors"]["pagespeed"] = pagespeed_res.get("provenance", {})
        else:
            provenance["collectors"]["pagespeed"] = {"error": str(pagespeed_res), "status": "failed"}

        # Merge SerpApi Google Maps Review signals (Primary reputation provider)
        if isinstance(serpapi_res, dict) and not isinstance(serpapi_res, Exception):
            serpapi_sig = serpapi_res.get("signals", {}).get("low_review_rating")
            if serpapi_sig and serpapi_sig.get("value") is not None:
                aggregated_signals["low_review_rating"] = serpapi_sig
            provenance["collectors"]["serpapi"] = serpapi_res.get("provenance", {})
        else:
            provenance["collectors"]["serpapi"] = (
                {"error": str(serpapi_res), "status": "failed"}
                if isinstance(serpapi_res, Exception)
                else {"status": "skipped"}
            )

        # Merge Google Places signals (Fallback if SerpApi did not populate rating)
        if isinstance(places_res, dict) and not isinstance(places_res, Exception):
            for k, sig_data in places_res.get("signals", {}).items():
                if sig_data.get("value") is not None or k not in aggregated_signals:
                    aggregated_signals[k] = sig_data
            provenance["collectors"]["places"] = places_res.get("provenance", {})
        else:
            provenance["collectors"]["places"] = {"error": str(places_res), "status": "failed"}

        # Merge DataForSEO signals
        if isinstance(dataforseo_res, dict) and not isinstance(dataforseo_res, Exception):
            for k, sig_data in dataforseo_res.get("signals", {}).items():
                if sig_data.get("value") is not None or k not in aggregated_signals:
                    aggregated_signals[k] = sig_data
            provenance["collectors"]["dataforseo"] = dataforseo_res.get("provenance", {})
        else:
            provenance["collectors"]["dataforseo"] = {"error": str(dataforseo_res), "status": "failed"}

        # Merge Organization Data (Hunter Company Enrichment)
        provider_name = "hunter"
        if isinstance(org_res, dict) and not isinstance(org_res, Exception):
            provenance["collectors"][provider_name] = org_res
            if not lead.employee_count and org_res.get("employee_count"):
                lead.employee_count = org_res["employee_count"]
            if not lead.industry and org_res.get("industry"):
                lead.industry = org_res["industry"]
            if not lead.country and org_res.get("country"):
                lead.country = org_res["country"]
            if not lead.city and org_res.get("city"):
                lead.city = org_res["city"]
            if (not lead.company_name or lead.company_name == lead.domain) and org_res.get("company_name"):
                lead.company_name = org_res["company_name"]
        else:
            provenance["collectors"][provider_name] = (
                {"error": str(org_res), "status": "failed"}
                if isinstance(org_res, Exception)
                else {"status": "skipped"}
            )

        # Ensure all 22 canonical signals exist in payload
        for sig_key in DEFAULT_SIGNAL_WEIGHTS.keys():
            if sig_key not in aggregated_signals:
                aggregated_signals[sig_key] = {
                    "value": None,
                    "evidence": "Signal collector unconfigured or skipped",
                    "provider": None,
                    "is_available": False,
                }

        # 4. Cache in Redis (168-hour TTL) if collection produced valid data
        if redis and isinstance(crawl_res, dict):
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
        return await self._persist_enrichment(lead, aggregated_signals, provenance)

    async def _persist_enrichment(
        self, lead: Lead, payload: Dict[str, Any], provenance: Dict[str, Any]
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

        lead.pipeline_status = PipelineStatus.ENRICHED
        await self.session.flush()
        return enrichment
