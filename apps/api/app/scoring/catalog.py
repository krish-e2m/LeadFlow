from typing import Dict

from app.core.constants import SignalCategory

# Sane bounds for a per-signal weight multiplier. Defaults range 0.5-1.5; this leaves headroom for
# a deliberate emphasis/de-emphasis without letting one signal swamp the other 21.
MIN_SIGNAL_WEIGHT = 0.0
MAX_SIGNAL_WEIGHT = 5.0

# Mandatory 22 Signal Definitions and Weights
# Website signals:
# legacy_platform 1.5, slow_site 1.3, old_design 1.0, weak_ctas 1.0, not_mobile_friendly 0.8,
# no_ssl 1.2, thin_content 0.7, no_analytics 0.6, accessibility 0.6, no_live_chat 0.5.
# Marketing signals:
# poor_seo 1.4, poor_aeo_geo 1.0, low_domain_trust 0.6, stale_blog 1.1, no_press 0.7,
# no_case_studies 0.8, no_video 0.5, weak_social 0.9, weak_email_capture 0.6,
# ppc_spend 1.2, hiring 1.1, low_review_rating 0.8.

DEFAULT_SIGNAL_WEIGHTS: Dict[str, float] = {
    # Website Signals (10)
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
    # Marketing Signals (12)
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

SIGNAL_CATEGORIES: Dict[str, SignalCategory] = {
    "legacy_platform": SignalCategory.WEBSITE,
    "slow_site": SignalCategory.WEBSITE,
    "old_design": SignalCategory.WEBSITE,
    "weak_ctas": SignalCategory.WEBSITE,
    "not_mobile_friendly": SignalCategory.WEBSITE,
    "no_ssl": SignalCategory.WEBSITE,
    "thin_content": SignalCategory.WEBSITE,
    "no_analytics": SignalCategory.WEBSITE,
    "accessibility": SignalCategory.WEBSITE,
    "no_live_chat": SignalCategory.WEBSITE,
    "poor_seo": SignalCategory.MARKETING,
    "poor_aeo_geo": SignalCategory.MARKETING,
    "low_domain_trust": SignalCategory.MARKETING,
    "stale_blog": SignalCategory.MARKETING,
    "no_press": SignalCategory.MARKETING,
    "no_case_studies": SignalCategory.MARKETING,
    "no_video": SignalCategory.MARKETING,
    "weak_social": SignalCategory.MARKETING,
    "weak_email_capture": SignalCategory.MARKETING,
    "ppc_spend": SignalCategory.MARKETING,
    "hiring": SignalCategory.MARKETING,
    "low_review_rating": SignalCategory.MARKETING,
}

def validate_engine_weights(weights: Dict[str, float]) -> Dict[str, float]:
    """
    Normalizes a (possibly partial or sloppy) weights payload into exactly the 22 canonical
    signal keys. Unknown keys are dropped rather than rejected, so a stray key from a careless
    client never silently shrinks the "N of 22 signals" denominator in the scoring engine.
    Missing keys fall back to the catalog default; out-of-range or non-numeric values are rejected
    outright, since those are more likely a mistake than a deliberate choice.

    Raises ValueError with a clear message on bad input.
    """
    if not isinstance(weights, dict):
        raise ValueError("weights must be an object of signal_key -> weight.")

    normalized: Dict[str, float] = dict(DEFAULT_SIGNAL_WEIGHTS)
    for key in DEFAULT_SIGNAL_WEIGHTS:
        if key not in weights:
            continue
        raw = weights[key]
        try:
            value = float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"Weight for '{key}' must be a number, got {raw!r}.")
        if value != value:  # NaN
            raise ValueError(f"Weight for '{key}' cannot be NaN.")
        if value < MIN_SIGNAL_WEIGHT or value > MAX_SIGNAL_WEIGHT:
            raise ValueError(
                f"Weight for '{key}' must be between {MIN_SIGNAL_WEIGHT} and {MAX_SIGNAL_WEIGHT}, got {value}."
            )
        normalized[key] = value

    if sum(normalized.values()) <= 0.0:
        raise ValueError("At least one signal must have a weight above 0, or nothing can ever score.")

    return normalized


SIGNAL_LABELS: Dict[str, str] = {
    "legacy_platform": "Outdated CMS / Platform",
    "slow_site": "Slow Page Speed Performance",
    "old_design": "Outdated Design Patterns",
    "weak_ctas": "Weak / Missing Conversion CTAs",
    "not_mobile_friendly": "Poor Mobile Optimization",
    "no_ssl": "Missing / Insecure SSL Certificate",
    "thin_content": "Thin Homepage Content",
    "no_analytics": "Missing Web Analytics / Tracking",
    "accessibility": "Accessibility Deficiencies",
    "no_live_chat": "No Live Chat Widget",
    "poor_seo": "Weak Organic SEO Structure",
    "poor_aeo_geo": "Missing Schema & GEO/AEO Data",
    "low_domain_trust": "Low Domain Authority / Trust",
    "stale_blog": "Inactive / Stale Blog (>12mo)",
    "no_press": "No Media / Press Coverage",
    "no_case_studies": "No Case Studies / Social Proof",
    "no_video": "Absence of Video Marketing",
    "weak_social": "Inactive / Missing Social Presence",
    "weak_email_capture": "No Lead Capture / Newsletter Form",
    "ppc_spend": "Active Paid Search (PPC) Spend",
    "hiring": "Active Hiring / Open Positions",
    "low_review_rating": "Sub-par Review Rating (<3.8 Stars)",
}
