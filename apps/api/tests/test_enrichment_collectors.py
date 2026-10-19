import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from bs4 import BeautifulSoup
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.constants import ApprovalStatus, PipelineStatus, ScoreBand
from app.db.session import engine, tenant_session
from app.models.enrichment import Enrichment
from app.models.lead import Lead
from app.models.organization import Organization
from app.providers.crawler import WebCrawlerAdapter, is_safe_url
from app.providers.pagespeed import PageSpeedAdapter
from app.services.enrichment_service import EnrichmentService
from app.services.scoring_service import ScoringService


@pytest.fixture(autouse=True)
async def cleanup_pool():
    """Ensure all engine connections are cleanly disposed between test loops."""
    yield
    await engine.dispose()


@pytest.fixture
async def admin_engine():
    eng = create_async_engine(settings.migration_database_url, poolclass=NullPool)
    yield eng
    await eng.dispose()


def test_ssrf_url_validation_blocks_internal_and_metadata_destinations():
    """Verify crawler rejects localhost, internal private subnets, and cloud metadata IPs."""
    # Disallowed IPs and hostnames
    assert not is_safe_url("http://127.0.0.1/admin")
    assert not is_safe_url("https://127.0.0.1:8080")
    assert not is_safe_url("http://localhost:3000")
    assert not is_safe_url("http://169.254.169.254/latest/meta-data/")
    assert not is_safe_url("http://10.0.0.5/internal")
    assert not is_safe_url("https://192.168.1.1/router")
    assert not is_safe_url("http://172.16.0.10/")
    assert not is_safe_url("http://metadata.google.internal/computeMetadata/v1/")
    assert not is_safe_url("ftp://example.com/file")  # Scheme check

    # Allowed public domain
    assert is_safe_url("https://example.com")
    assert is_safe_url("https://google.com")


def test_crawler_configuration_and_limits():
    """Verify crawler limits: 8 pages max, 12.0s timeout, 4 concurrency, 5MB response cap."""
    crawler = WebCrawlerAdapter()
    assert crawler.MAX_PAGES == 8
    assert crawler.TIMEOUT_SECONDS == 12.0
    assert crawler.CONCURRENCY_LIMIT == 4
    assert crawler.MAX_RESPONSE_BYTES == 5 * 1024 * 1024


def test_hiring_signal_collector_semantics():
    """
    Verify hiring signal behavior:
    - Careers page with listings -> 1.0 (detected)
    - Careers page without listings -> 0.0 (not detected)
    - No careers page on domain -> None (unavailable; do NOT claim company is not hiring)
    """
    crawler = WebCrawlerAdapter()

    # Scenario 1: Careers page with active job openings
    pages_with_jobs = [
        {"url": "https://company.com", "html": "<html><body>Home</body></html>", "soup": None, "words": 300},
        {
            "url": "https://company.com/careers",
            "html": "<html><body><h1>Careers</h1><p>Open Positions</p><a href='/jobs/eng'>Apply Now</a></body></html>",
            "body_text": "Careers Open Positions Apply Now Senior Software Engineer",
            "soup": None,
            "words": 150,
        },
    ]
    for p in pages_with_jobs:
        p["soup"] = BeautifulSoup(p["html"], "html.parser")

    signals_with_jobs = crawler._evaluate_signals_across_pages(pages_with_jobs, ssl_valid=True, domain="company.com")
    assert signals_with_jobs["hiring"]["value"] == 1.0
    assert "active hiring detected" in signals_with_jobs["hiring"]["evidence"].lower()
    assert signals_with_jobs["hiring"]["source_url"] == "https://company.com/careers"

    # Scenario 2: Careers page found, but explicitly no openings
    pages_no_jobs = [
        {"url": "https://company.com", "html": "<html><body>Home</body></html>", "soup": None, "words": 300},
        {
            "url": "https://company.com/careers",
            "html": "<html><body><h1>Careers</h1><p>We have no current openings at this time.</p></body></html>",
            "body_text": "Careers We have no current openings at this time.",
            "soup": None,
            "words": 50,
        },
    ]
    for p in pages_no_jobs:
        p["soup"] = BeautifulSoup(p["html"], "html.parser")

    signals_no_jobs = crawler._evaluate_signals_across_pages(pages_no_jobs, ssl_valid=True, domain="company.com")
    assert signals_no_jobs["hiring"]["value"] == 0.0
    assert "no active job openings" in signals_no_jobs["hiring"]["evidence"].lower()

    # Scenario 3: No careers page anywhere on domain
    pages_without_careers = [
        {"url": "https://company.com", "html": "<html><body>Home</body></html>", "soup": None, "words": 300},
        {"url": "https://company.com/about", "html": "<html><body>About us</body></html>", "body_text": "About us", "soup": None, "words": 100},
    ]
    for p in pages_without_careers:
        p["soup"] = BeautifulSoup(p["html"], "html.parser")

    signals_no_careers = crawler._evaluate_signals_across_pages(pages_without_careers, ssl_valid=True, domain="company.com")
    # Must be None (unavailable) - never assume not hiring!
    assert signals_no_careers["hiring"]["value"] is None
    assert "no careers page detected" in signals_no_careers["hiring"]["evidence"].lower()


@pytest.mark.asyncio
async def test_enrichment_cache_reuse_and_ttl(admin_engine):
    """Verify that valid cached enrichment in Redis prevents repeated external crawling."""
    mock_redis = AsyncMock()
    cached_data = {
        "payload": {
            "legacy_platform": {"value": 1.0, "evidence": "Drupal 7", "provider": "web_crawler", "source_url": "https://cached-domain.com"},
            "no_ssl": {"value": 0.0, "evidence": "HTTPS valid", "provider": "web_crawler", "source_url": "https://cached-domain.com"},
        },
        "provenance": {"domain": "cached-domain.com", "collectors": {"crawler": {"status_code": 200}}},
    }
    mock_redis.get.return_value = json.dumps(cached_data)

    admin_session_maker = async_sessionmaker(bind=admin_engine, class_=AsyncSession, expire_on_commit=False)
    org_id = uuid.uuid4()
    org_slug = f"cache-org-{org_id.hex[:6]}"

    async with admin_session_maker() as admin_s:
        org = Organization(id=org_id, name="Cache Org", slug=org_slug)
        admin_s.add(org)
        await admin_s.commit()

    try:
        async with tenant_session(org_id) as session:
            lead = Lead(
                org_id=org_id,
                domain="cached-domain.com",
                company_name="Cached Company",
                pipeline_status=PipelineStatus.SOURCED,
            )
            session.add(lead)
            await session.flush()

            service = EnrichmentService(session, redis_client=mock_redis)
            enrichment = await service.enrich_lead(lead)
            await session.commit()

            # Verified cache hit
            assert mock_redis.get.called
            assert enrichment.provider_provenance["from_cache"] is True
            assert enrichment.payload["legacy_platform"]["value"] == 1.0
            assert lead.pipeline_status == PipelineStatus.ENRICHED
    finally:
        async with admin_session_maker() as admin_s:
            await admin_s.execute(text("DELETE FROM orgs WHERE id = :oid"), {"oid": org_id})
            await admin_s.commit()


@pytest.mark.asyncio
async def test_collector_failure_isolation(admin_engine):
    """Verify that a crawler failure does not block or destroy another collector's output."""
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None  # Cache miss

    admin_session_maker = async_sessionmaker(bind=admin_engine, class_=AsyncSession, expire_on_commit=False)
    org_id = uuid.uuid4()
    org_slug = f"iso-org-{org_id.hex[:6]}"

    async with admin_session_maker() as admin_s:
        org = Organization(id=org_id, name="Isolate Org", slug=org_slug)
        admin_s.add(org)
        await admin_s.commit()

    try:
        async with tenant_session(org_id) as session:
            lead = Lead(
                org_id=org_id,
                domain="fail-test.com",
                company_name="Fail Test Co",
                pipeline_status=PipelineStatus.SOURCED,
            )
            session.add(lead)
            await session.flush()

            with patch("app.providers.manager.provider_manager.crawler.crawl_domain", side_effect=Exception("Network Timeout")), \
                 patch("app.providers.manager.provider_manager.pagespeed.audit_url", new_callable=AsyncMock, return_value={"signals": {}, "provenance": {"status": "ok"}}), \
                 patch("app.providers.manager.provider_manager.places.fetch_place_signals", new_callable=AsyncMock, return_value={"signals": {}, "provenance": {"status": "ok"}}), \
                 patch("app.providers.manager.provider_manager.dataforseo.fetch_seo_signals", new_callable=AsyncMock, return_value={"signals": {}, "provenance": {"status": "ok"}}), \
                 patch("app.providers.manager.provider_manager.serpapi.fetch_review_signals", new_callable=AsyncMock, return_value={"signals": {}, "provenance": {"status": "ok"}}), \
                 patch("app.providers.manager.provider_manager.hunter.enrich_company", new_callable=AsyncMock, return_value={"company_name": "Fail Test Co"}):
                service = EnrichmentService(session, redis_client=mock_redis)
                enrichment = await service.enrich_lead(lead)
                await session.commit()

                assert enrichment.provider_provenance["collectors"]["crawler"]["status"] == "failed"
                assert "Network Timeout" in enrichment.provider_provenance["collectors"]["crawler"]["error"]
                # All 22 canonical signals still exist in payload
                assert len(enrichment.payload) >= 22
                assert enrichment.payload["legacy_platform"]["value"] is None
                assert lead.pipeline_status == PipelineStatus.ENRICHED
    finally:
        async with admin_session_maker() as admin_s:
            await admin_s.execute(text("DELETE FROM orgs WHERE id = :oid"), {"oid": org_id})
            await admin_s.commit()


@pytest.mark.asyncio
async def test_rescoring_preserves_pipeline_status_and_history(admin_engine):
    """
    Verify rule:
    1. Rescoring creates a new Score record (snapshot).
    2. Rescoring does not re-enrich or alter original evidence.
    3. Rescoring does not reset an approved or disqualified lead to SCORED.
    """
    admin_session_maker = async_sessionmaker(bind=admin_engine, class_=AsyncSession, expire_on_commit=False)
    org_id = uuid.uuid4()
    org_slug = f"rescore-org-{org_id.hex[:6]}"

    async with admin_session_maker() as admin_s:
        org = Organization(id=org_id, name="Rescore Org", slug=org_slug)
        admin_s.add(org)
        await admin_s.commit()

    try:
        lead_id = None
        score_1_id = None
        async with tenant_session(org_id) as session:
            lead = Lead(
                org_id=org_id,
                domain="approved-lead.com",
                company_name="Approved Co",
                pipeline_status=PipelineStatus.APPROVED,
                approval_status=ApprovalStatus.APPROVED,
            )
            session.add(lead)
            await session.flush()
            lead_id = lead.id

            enrichment = Enrichment(
                org_id=org_id,
                lead_id=lead.id,
                version=1,
                payload={
                    "legacy_platform": {"value": 1.0, "weight": 1.5, "evidence": "Legacy CMS", "provider": "web_crawler"},
                    "no_ssl": {"value": 1.0, "weight": 1.2, "evidence": "No SSL", "provider": "web_crawler"},
                },
                provider_provenance={"collectors": {}},
            )
            session.add(enrichment)
            await session.flush()

            scoring_service = ScoringService(session)
            score_1 = await scoring_service.score_lead(lead, enrichment=enrichment)
            score_1_id = score_1.id

            assert score_1.overall_score == 100.0
            assert score_1.score_band == ScoreBand.QUALIFIED
            # Verified pipeline status was NOT changed back to SCORED (remains APPROVED!)
            assert lead.pipeline_status == PipelineStatus.APPROVED

        # Second transaction: simulates POST /leads/{id}/rescore endpoint in separate tenant session
        async with tenant_session(org_id) as rescore_session:
            lead_stmt = select(Lead).where(Lead.id == lead_id)
            lead_to_rescore = (await rescore_session.execute(lead_stmt)).scalars().first()
            assert lead_to_rescore is not None

            rescore_service = ScoringService(rescore_session)
            score_2 = await rescore_service.score_lead(lead_to_rescore)

            assert score_2.id != score_1_id  # New snapshot created
            assert score_2.overall_score == 100.0
            assert score_2.score_band == ScoreBand.QUALIFIED
            # Verified pipeline status preserved on rescore
            assert lead_to_rescore.pipeline_status == PipelineStatus.APPROVED
    finally:
        async with admin_session_maker() as admin_s:
            await admin_s.execute(text("DELETE FROM orgs WHERE id = :oid"), {"oid": org_id})
            await admin_s.commit()


def test_pagespeed_config_reads_without_exposing_secrets():
    """Verify PageSpeedAdapter loads configuration properly and does not expose secrets."""
    adapter = PageSpeedAdapter()
    assert adapter.name == "google_pagespeed"
    assert adapter.base_url == "https://pagespeedonline.googleapis.com/pagespeedonline/v5/runPagespeed"
    rep = repr(adapter)
    if adapter.api_key:
        assert adapter.api_key not in rep
    assert "BaseProviderAdapter" in rep or "PageSpeedAdapter" in rep or "google_pagespeed" in str(adapter)


@pytest.mark.asyncio
async def test_pagespeed_successful_response_mapping():
    """Verify that a successful Lighthouse mobile audit maps to canonical signals."""
    adapter = PageSpeedAdapter()
    adapter.api_key = "fake_test_key"

    fake_lighthouse_response = {
        "lighthouseResult": {
            "categories": {
                "performance": {"score": 0.42},
                "accessibility": {"score": 0.88},
                "seo": {"score": 0.95},
            },
            "audits": {
                "first-contentful-paint": {"displayValue": "3.8 s"},
                "largest-contentful-paint": {"displayValue": "4.2 s"},
                "total-blocking-time": {"displayValue": "650 ms"},
                "viewport": {"score": 1.0},
            },
        }
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = fake_lighthouse_response

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        result = await adapter.audit_url("example.com")

        # Verify call params
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args.kwargs
        assert call_kwargs["params"]["url"] == "https://example.com"
        assert call_kwargs["params"]["key"] == "fake_test_key"
        assert call_kwargs["params"]["strategy"] == "mobile"
        assert set(call_kwargs["params"]["category"]) == {"performance", "accessibility", "seo"}

        # Verify signal mapping
        signals = result["signals"]
        # slow_site: perf_score 0.42 < 0.5 -> 1.0 (slow site detected)
        assert signals["slow_site"]["value"] == 1.0
        assert "42/100" in signals["slow_site"]["evidence"]
        assert signals["slow_site"]["provider"] == "google_pagespeed"

        # not_mobile_friendly: viewport 1.0 >= 0.9 -> 0.0 (mobile friendly)
        assert signals["not_mobile_friendly"]["value"] == 0.0
        assert "Valid mobile viewport" in signals["not_mobile_friendly"]["evidence"]

        # accessibility: access_score 0.88 >= 0.6 -> 0.0 (good accessibility)
        assert signals["accessibility"]["value"] == 0.0
        assert "88/100" in signals["accessibility"]["evidence"]

        # Provenance metrics preserved
        provenance = result["provenance"]
        assert provenance["perf_score"] == 0.42
        assert provenance["access_score"] == 0.88
        assert provenance["fcp"] == "3.8 s"
        assert provenance["lcp"] == "4.2 s"
        assert provenance["tbt"] == "650 ms"


@pytest.mark.asyncio
async def test_pagespeed_missing_metrics_remain_unavailable():
    """Verify missing Lighthouse audits remain None and are never coerced to zero."""
    adapter = PageSpeedAdapter()
    adapter.api_key = "fake_test_key"

    empty_lighthouse_response = {
        "lighthouseResult": {
            "categories": {},
            "audits": {},
        }
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = empty_lighthouse_response

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        result = await adapter.audit_url("example.com")

        signals = result["signals"]
        assert signals["slow_site"]["value"] is None
        assert "unavailable" in signals["slow_site"]["evidence"].lower()

        assert signals["not_mobile_friendly"]["value"] is None
        assert "unavailable" in signals["not_mobile_friendly"]["evidence"].lower()

        assert signals["accessibility"]["value"] is None
        assert "unavailable" in signals["accessibility"]["evidence"].lower()


@pytest.mark.asyncio
async def test_pagespeed_http_errors_and_timeouts_redact_secrets():
    """Verify HTTP error status codes (400, 403, 429, 500) and timeouts are caught and redact secrets."""
    adapter = PageSpeedAdapter()
    secret_key = "super_secret_pagespeed_credential_123"
    adapter.api_key = secret_key

    # 1. HTTP 403 Forbidden with error message containing the key
    err_resp = MagicMock()
    err_resp.status_code = 403
    err_resp.json.return_value = {
        "error": {
            "code": 403,
            "message": f"API key {secret_key} has expired or is invalid.",
        }
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = err_resp
        res = await adapter.audit_url("example.com")

        assert res["signals"]["slow_site"]["value"] is None
        assert res["signals"]["not_mobile_friendly"]["value"] is None
        assert res["signals"]["accessibility"]["value"] is None
        assert secret_key not in res["provenance"]["error"]
        assert "[REDACTED]" in res["provenance"]["error"]
        assert secret_key not in res["signals"]["slow_site"]["evidence"]

    # 2. Timeout exception
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.ReadTimeout(f"Request timed out with key {secret_key}")
        res_timeout = await adapter.audit_url("example.com")

        assert res_timeout["signals"]["slow_site"]["value"] is None
        assert secret_key not in res_timeout["provenance"]["error"]
        assert "[REDACTED]" in res_timeout["provenance"]["error"]
        assert secret_key not in res_timeout["signals"]["slow_site"]["evidence"]


@pytest.mark.asyncio
async def test_enrichment_service_merges_pagespeed_and_crawler(admin_engine):
    """Verify EnrichmentService concurrently executes PageSpeed and merges signals into canonical payload."""
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None  # Cache miss

    admin_session_maker = async_sessionmaker(bind=admin_engine, class_=AsyncSession, expire_on_commit=False)
    org_id = uuid.uuid4()
    org_slug = f"ps-merge-{org_id.hex[:6]}"

    async with admin_session_maker() as admin_s:
        org = Organization(id=org_id, name="PageSpeed Merge Org", slug=org_slug)
        admin_s.add(org)
        await admin_s.commit()

    try:
        async with tenant_session(org_id) as session:
            lead = Lead(
                org_id=org_id,
                domain="merge-test.com",
                company_name="Merge Test Co",
                pipeline_status=PipelineStatus.SOURCED,
            )
            session.add(lead)
            await session.flush()

            mock_crawler_res = {
                "signals": {
                    "legacy_platform": {"value": 1.0, "evidence": "WordPress 4.9", "provider": "crawler"},
                    "no_ssl": {"value": 0.0, "evidence": "Valid SSL certificate", "provider": "crawler"},
                },
                "provenance": {"pages_scanned": 3},
            }
            mock_ps_res = {
                "signals": {
                    "slow_site": {"value": 1.0, "evidence": "Lighthouse score 35", "provider": "google_pagespeed"},
                    "not_mobile_friendly": {"value": 0.0, "evidence": "Valid viewport", "provider": "google_pagespeed"},
                    "accessibility": {"value": 0.0, "evidence": "Accessibility 85", "provider": "google_pagespeed"},
                },
                "provenance": {"perf_score": 0.35},
            }

            with patch("app.providers.manager.provider_manager.crawler.crawl_domain", new_callable=AsyncMock) as mock_crawl, \
                 patch("app.providers.manager.provider_manager.pagespeed.audit_url", new_callable=AsyncMock) as mock_ps:
                mock_crawl.return_value = mock_crawler_res
                mock_ps.return_value = mock_ps_res

                service = EnrichmentService(session, redis_client=mock_redis)
                enrichment = await service.enrich_lead(lead)
                await session.commit()

                # Verify both crawler and pagespeed signals are present in payload
                assert enrichment.payload["legacy_platform"]["value"] == 1.0
                assert enrichment.payload["no_ssl"]["value"] == 0.0
                assert enrichment.payload["slow_site"]["value"] == 1.0
                assert enrichment.payload["not_mobile_friendly"]["value"] == 0.0
                assert enrichment.payload["accessibility"]["value"] == 0.0
                assert enrichment.payload["slow_site"]["provider"] == "google_pagespeed"
                assert enrichment.provider_provenance["collectors"]["pagespeed"]["perf_score"] == 0.35
                assert lead.pipeline_status == PipelineStatus.ENRICHED
    finally:
        async with admin_session_maker() as admin_s:
            await admin_s.execute(text("DELETE FROM orgs WHERE id = :oid"), {"oid": org_id})
            await admin_s.commit()

