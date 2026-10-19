
from app.core.constants import ScoreBand
from app.scoring.catalog import DEFAULT_SIGNAL_WEIGHTS
from app.scoring.engine import ScoringEngineCore


def test_22_signals_catalog_exact_weights():
    """Verify that all exact 22 signals and required weights are configured."""
    expected_weights = {
        # Website signals (10)
        "legacy_platform": 1.5,
        "slow_site": 1.3,
        "old_design": 1.0,
        "weak_ctas": 1.0,
        "not_mobile_friendly": 0.8,
        "no_ssl": 1.2,
        "thin_content": 0.7,
        "no_analytics": 0.6,
        "accessibility": 0.6,
        "no_live_chat": 0.5,
        # Marketing signals (12)
        "poor_seo": 1.4,
        "poor_aeo_geo": 1.0,
        "low_domain_trust": 0.6,
        "stale_blog": 1.1,
        "no_press": 0.7,
        "no_case_studies": 0.8,
        "no_video": 0.5,
        "weak_social": 0.9,
        "weak_email_capture": 0.6,
        "ppc_spend": 1.2,
        "hiring": 1.1,
        "low_review_rating": 0.8,
    }

    assert len(DEFAULT_SIGNAL_WEIGHTS) == 22
    for key, weight in expected_weights.items():
        assert key in DEFAULT_SIGNAL_WEIGHTS
        assert DEFAULT_SIGNAL_WEIGHTS[key] == weight


def test_missing_data_skipped_never_zeroed():
    """
    Verify rule: Missing data must be represented as None and skipped during scoring,
    never converted into a zero score or reducing the denominator.
    """
    engine = ScoringEngineCore()

    # Scenario: Only 2 signals present, both 1.0 (high opportunity)
    raw_signals_partial = {
        "slow_site": {"value": 1.0, "evidence": "FCP > 4s", "provider": "pagespeed"},
        "legacy_platform": {"value": 1.0, "evidence": "Drupal 7", "provider": "crawler"},
        # All other 20 signals are missing/None
    }
    result = engine.evaluate(raw_signals_partial)

    # Since all available signals are 1.0, normalized score MUST be 100.0, NOT penalized by missing signals
    assert result.overall_score == 100.0
    assert result.score_band == ScoreBand.QUALIFIED
    assert result.website_subscore == 100.0
    assert result.marketing_subscore is None  # No marketing signals available
    assert result.available_signals_count == 2
    assert result.available_signals_ratio == "2/22"

    # Check that skipped signals are preserved with is_available = False and status = "unavailable"
    assert result.signal_details["poor_seo"]["value"] is None
    assert result.signal_details["poor_seo"]["is_available"] is False
    assert result.signal_details["poor_seo"]["status"] == "unavailable"


def test_all_unavailable_signals_produces_null_score():
    """
    Verify rule 5: If no signals are available, the numeric score must be null;
    do not assign zero. Score band must be null/None.
    """
    engine = ScoringEngineCore()
    raw_empty = {}
    result = engine.evaluate(raw_empty)

    assert result.overall_score is None
    assert result.score_band is None
    assert result.website_subscore is None
    assert result.marketing_subscore is None
    assert result.available_signals_count == 0
    assert result.available_signals_ratio == "0/22"
    assert "no audit signals available" in result.explanation.lower()


def test_fired_versus_nonfired_contribution():
    """
    Verify rule:
    - Fired signals (1.0) contribute weight to numerator and denominator.
    - Non-fired signals (0.0) contribute 0.0 to numerator, but their weight is in the denominator.
    - Unavailable signals (None) are excluded completely from denominator.
    """
    engine = ScoringEngineCore()

    raw_signals = {
        # Website signals (weight: 1.5 + 1.3 = 2.8)
        "legacy_platform": {
            "value": 1.0,
            "evidence": "Old CMS",
            "provider": "crawler",
        },  # 1.5 * 1.0 = 1.5
        "slow_site": {
            "value": 0.0,
            "evidence": "Fast site",
            "provider": "pagespeed",
        },  # 1.3 * 0.0 = 0.0
        # Marketing signals (weight: 1.2 + 1.1 = 2.3)
        "ppc_spend": {
            "value": 1.0,
            "evidence": "Active ads",
            "provider": "crawler",
        },  # 1.2 * 1.0 = 1.2
        "hiring": {
            "value": 0.0,
            "evidence": "No open jobs",
            "provider": "crawler",
        },  # 1.1 * 0.0 = 0.0
        # Other 18 signals missing
    }
    result = engine.evaluate(raw_signals)

    # Website: 1.5 / 2.8 = ~53.6%
    assert result.website_subscore == 53.6
    # Marketing: 1.2 / 2.3 = ~52.2%
    assert result.marketing_subscore == 52.2
    # Overall: (1.5 + 1.2) / (2.8 + 2.3) = 2.7 / 5.1 = ~52.9%
    assert result.overall_score == 52.9
    # 52.9 is between threshold_medium (50.0) and threshold_high (75.0) -> REVIEW
    assert result.score_band == ScoreBand.REVIEW
    assert result.available_signals_count == 4
    assert result.available_signals_ratio == "4/22"


def test_canonical_score_bands_enforced():
    """Verify threshold evaluation for canonical score bands: qualified, review, disqualified."""
    # Qualified: >= 75.0
    engine_std = ScoringEngineCore(threshold_high=75.0, threshold_medium=50.0, threshold_low=25.0)
    high_signals = {"legacy_platform": {"value": 1.0}, "no_ssl": {"value": 1.0}}
    assert engine_std.evaluate(high_signals).score_band == ScoreBand.QUALIFIED

    # Review: 50.0 <= score < 75.0
    mid_signals = {"legacy_platform": {"value": 1.0}, "slow_site": {"value": 0.0}}  # 1.5 / 2.8 = 53.6%
    assert engine_std.evaluate(mid_signals).score_band == ScoreBand.REVIEW

    # Disqualified: < 50.0
    low_signals = {
        "legacy_platform": {"value": 0.0},  # weight 1.5
        "no_ssl": {"value": 0.0},           # weight 1.2
        "weak_ctas": {"value": 1.0},        # weight 1.0 (1.0 / 3.7 = ~27.0%)
    }
    assert engine_std.evaluate(low_signals).score_band == ScoreBand.DISQUALIFIED


def test_ideal_client_bonus_behavior():
    """
    Verify the ideal-client rule: the configured bonus applies only when BOTH the website and the
    marketing groups score strongly; it stays inactive when 0.0 and is clamped to 100.0.
    """
    both_groups = {
        "legacy_platform": {"value": 0.6},  # website group, weighted score 60
        "poor_seo": {"value": 0.6},         # marketing group, weighted score 60
    }
    website_only = {"legacy_platform": {"value": 0.5}}  # no marketing evidence -> not an ideal client

    # Bonus configured at 0.0 is inactive
    res_no = ScoringEngineCore(ideal_client_bonus=0.0).evaluate(both_groups)
    assert res_no.overall_score == 60.0

    # Both groups strong -> bonus applied
    res_bonus = ScoringEngineCore(ideal_client_bonus=10.0).evaluate(both_groups)
    assert res_bonus.overall_score == 70.0
    assert res_bonus.signal_details["_metadata"]["ideal_client"] is True
    assert res_bonus.signal_details["_metadata"]["ideal_client_bonus_applied"] == 10.0

    # Only one group present -> no bonus
    res_single = ScoringEngineCore(ideal_client_bonus=10.0).evaluate(website_only)
    assert res_single.overall_score == 50.0
    assert res_single.signal_details["_metadata"]["ideal_client"] is False

    # One group strong, the other weak -> no bonus
    lopsided = {"legacy_platform": {"value": 1.0}, "poor_seo": {"value": 0.1}}
    res_lopsided = ScoringEngineCore(ideal_client_bonus=10.0).evaluate(lopsided)
    assert res_lopsided.signal_details["_metadata"]["ideal_client_bonus_applied"] == 0.0

    # Clamping at 100.0
    maxed = {"legacy_platform": {"value": 1.0}, "poor_seo": {"value": 1.0}}
    res_over = ScoringEngineCore(ideal_client_bonus=20.0).evaluate(maxed)
    assert res_over.overall_score == 100.0


def test_canonical_scoring_integrity_and_exclusion_of_supplemental_signals():
    """
    Verify Task 2:
    - Only the 22 canonical signals defined in DEFAULT_SIGNAL_WEIGHTS contribute to scoring.
    - Supplemental or extraneous signals (e.g. low_traffic, no_pricing_page, social_subscore)
      are strictly excluded and never counted in denominator or available count.
    - Only website_subscore (10 signals) and marketing_subscore (12 signals) exist.
    - Available signals count strictly reflects canonical signals.
    - Collector provenance and evidence are preserved in details payload.
    """
    engine = ScoringEngineCore()
    assert len(engine.weights) == 22

    # Inject canonical signals plus non-canonical supplemental signals
    raw_payload = {
        # Canonical Website Signals (2 available)
        "slow_site": {"value": 1.0, "evidence": "Lighthouse FCP > 3.0s", "provider": "pagespeed"},
        "legacy_platform": {"value": 0.0, "evidence": "Modern Next.js detected", "provider": "crawler"},
        # Canonical Marketing Signals (1 available)
        "poor_seo": {"value": 1.0, "evidence": "Missing meta description", "provider": "crawler"},
        # Supplemental / Non-canonical indicators (MUST BE IGNORED by engine)
        "low_traffic": {"value": 1.0, "evidence": "Under 5k visits", "provider": "semrush"},
        "no_pricing_page": {"value": 1.0, "evidence": "No pricing link found", "provider": "crawler"},
        "social_subscore": 50.0,
    }

    result = engine.evaluate(raw_payload)

    # Available count must be exactly 3 (only canonical signals: slow_site, legacy_platform, poor_seo)
    assert result.available_signals_count == 3
    assert result.available_signals_ratio == "3/22"

    # Total evaluated metadata must be 22
    assert result.signal_details["_metadata"]["total_signals"] == 22
    assert result.signal_details["_metadata"]["available_signals_count"] == 3

    # Non-canonical signals must NOT be present in signal_details keys
    assert "low_traffic" not in result.signal_details
    assert "no_pricing_page" not in result.signal_details
    assert "social_subscore" not in result.signal_details

    # Resulting score only computes canonical weights:
    # Website: (1.3 * 1.0 + 1.5 * 0.0) / (1.3 + 1.5) = 1.3 / 2.8 = ~46.4%
    assert result.website_subscore == 46.4
    # Marketing: (1.4 * 1.0) / 1.4 = 100.0%
    assert result.marketing_subscore == 100.0
    # Overall: (1.3 + 1.4) / (2.8 + 1.4) = 2.7 / 4.2 = ~64.3%
    assert result.overall_score == 64.3

    # Collector provenance is preserved
    assert result.signal_details["slow_site"]["provider"] == "pagespeed"
    assert result.signal_details["slow_site"]["evidence"] == "Lighthouse FCP > 3.0s"
    assert result.signal_details["poor_seo"]["provider"] == "crawler"
