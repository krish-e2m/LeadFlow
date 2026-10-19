from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

from app.core.constants import ScoreBand, SignalCategory
from app.scoring.catalog import DEFAULT_SIGNAL_WEIGHTS, SIGNAL_CATEGORIES, SIGNAL_LABELS

# A prospect whose score clears the Qualified threshold on fewer signals than this is held in
# Review: a near-perfect score built from two or three data points is not evidence enough.
DEFAULT_MIN_SIGNALS_FOR_QUALIFIED = 6
DETECTED_THRESHOLD = 0.5


def normalize_weights(weights: Optional[Mapping[str, Any]]) -> Dict[str, float]:
    """
    Maps any stored weights onto exactly the canonical 22 signals. Missing or unparseable entries
    fall back to the catalog default and unknown keys are ignored, so an engine saved before
    validation existed can never shrink or pad the signal catalog.
    """
    normalized: Dict[str, float] = {}
    source = weights or {}
    for key, default in DEFAULT_SIGNAL_WEIGHTS.items():
        try:
            value = float(source.get(key, default))
        except (TypeError, ValueError):
            value = default
        if value != value or value < 0:  # NaN or negative
            value = default
        normalized[key] = value
    return normalized


def _coerce_value(raw: Any) -> Optional[float]:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value != value:
        return None
    return min(1.0, max(0.0, value))


def _coerce_value_weight(raw: Any) -> float:
    try:
        weight = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return weight if weight == weight and weight > 0 else 0.0


def ranked_findings(signal_details: Mapping[str, Any], limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Detected, enabled signals ordered by how much they move the score (weight x value), so the
    explanation and the outreach draft lead with the strongest pain points rather than catalog order.
    Works on stored Score.signal_details, including rows written before signals could be disabled.
    """
    findings = []
    for key, item in signal_details.items():
        if key.startswith("_") or not isinstance(item, dict):
            continue
        value = _coerce_value(item.get("value"))
        weight = _coerce_value_weight(item.get("weight"))
        if value is None or value < DETECTED_THRESHOLD or weight <= 0 or item.get("enabled") is False:
            continue
        findings.append(
            {
                "signal": key,
                "label": item.get("label") or SIGNAL_LABELS.get(key, key),
                "finding": item.get("evidence"),
                "weight": weight,
                "impact": round(weight * value, 3),
            }
        )
    findings.sort(key=lambda f: (f["impact"], f["weight"]), reverse=True)
    return findings[:limit] if limit else findings


@dataclass
class SignalEvaluationResult:
    key: str
    label: str
    category: SignalCategory
    weight: float
    value: Optional[float]  # 0.0 (not detected) .. 1.0 (detected), or None (unavailable)
    status: str  # "detected", "not_detected", "unavailable" or "disabled"
    evidence: Optional[str]
    provider: Optional[str]
    is_available: bool
    source_url: Optional[str] = None

    @property
    def enabled(self) -> bool:
        return self.weight > 0


@dataclass
class ScoringResult:
    overall_score: Optional[float]  # 0.0 to 100.0, or None if no available signals
    score_band: Optional[ScoreBand]  # ScoreBand.QUALIFIED, REVIEW, DISQUALIFIED, or None
    website_subscore: Optional[float]
    marketing_subscore: Optional[float]
    available_signals_count: int
    available_signals_ratio: str  # e.g. "18/22"
    signal_details: Dict[str, Any]
    explanation: str


def _weighted_pct(signals: List[SignalEvaluationResult]) -> Optional[float]:
    total_weight = sum(s.weight for s in signals)
    if total_weight <= 0:
        return None
    return round(sum(s.weight * (s.value or 0.0) for s in signals) / total_weight * 100.0, 1)


class ScoringEngineCore:
    """
    Canonical 22-signal scoring engine.
    - Weighted mean over enabled signals that have data; unavailable signals are skipped, never
      scored as zero. A weight of 0 disables a signal: it is shown but never counted.
    - Ideal-client bonus only when BOTH the website and marketing groups score strongly.
    - Bands: qualified >= threshold_high, review >= threshold_medium, else disqualified; null when
      nothing could be scored.
    """

    def __init__(
        self,
        weights: Optional[Mapping[str, Any]] = None,
        threshold_high: float = 75.0,
        threshold_medium: float = 50.0,
        threshold_low: float = 25.0,
        ideal_client_bonus: float = 0.0,
        ideal_client_group_threshold: float = 50.0,
        min_signals_for_qualified: int = DEFAULT_MIN_SIGNALS_FOR_QUALIFIED,
    ):
        self.weights = normalize_weights(weights)
        self.threshold_high = threshold_high
        self.threshold_medium = threshold_medium
        self.threshold_low = threshold_low
        self.ideal_client_bonus = max(0.0, ideal_client_bonus or 0.0)
        self.ideal_client_group_threshold = ideal_client_group_threshold
        self.min_signals_for_qualified = max(0, int(min_signals_for_qualified or 0))

    def _evaluate_signal(self, key: str, weight: float, raw_item: Any) -> SignalEvaluationResult:
        evidence = provider = source_url = None
        if isinstance(raw_item, dict):
            value = _coerce_value(raw_item.get("value"))
            evidence = raw_item.get("evidence")
            provider = raw_item.get("provider")
            source_url = raw_item.get("source_url")
        else:
            value = _coerce_value(raw_item)

        is_available = value is not None
        if weight <= 0:
            status = "disabled"
        elif not is_available:
            status = "unavailable"
        elif value >= DETECTED_THRESHOLD:
            status = "detected"
        else:
            status = "not_detected"

        return SignalEvaluationResult(
            key=key,
            label=SIGNAL_LABELS.get(key, key),
            category=SIGNAL_CATEGORIES.get(key, SignalCategory.WEBSITE),
            weight=weight,
            value=value,
            status=status,
            evidence=evidence,
            provider=provider,
            is_available=is_available,
            source_url=source_url,
        )

    def evaluate(self, raw_signals: Mapping[str, Any]) -> ScoringResult:
        """
        raw_signals maps signal keys to {"value", "evidence", "provider", "source_url"} dicts or bare
        0.0-1.0 numbers. Keys outside the catalog are ignored.
        """
        evaluated = [self._evaluate_signal(k, w, raw_signals.get(k)) for k, w in self.weights.items()]

        enabled = [s for s in evaluated if s.enabled]
        scorable = [s for s in enabled if s.is_available]
        total_signals = len(enabled)
        available_count = len(scorable)
        available_ratio = f"{available_count}/{total_signals}"

        details_map: Dict[str, Any] = {
            s.key: {
                "label": s.label,
                "category": s.category.value,
                "weight": s.weight,
                "enabled": s.enabled,
                "value": s.value,
                "status": s.status,
                "evidence": s.evidence,
                "provider": s.provider,
                "is_available": s.is_available,
                "source_url": s.source_url,
            }
            for s in evaluated
        }
        metadata: Dict[str, Any] = {
            "available_signals_count": available_count,
            "available_signals_ratio": available_ratio,
            "total_signals": total_signals,
            "catalog_signals": len(evaluated),
            "disabled_signals_count": len(evaluated) - total_signals,
            "fired_signals_count": sum(1 for s in scorable if (s.value or 0.0) >= DETECTED_THRESHOLD),
            "ideal_client_bonus": self.ideal_client_bonus,
        }

        if not scorable:
            for s in evaluated:
                if s.status == "unavailable" and not s.evidence:
                    details_map[s.key]["evidence"] = "Signal data unavailable or collector unconfigured"
            metadata.update({"ideal_client": False, "ideal_client_bonus_applied": 0.0, "low_coverage": False})
            details_map["_metadata"] = metadata
            reason = (
                "Every signal is disabled in this engine, so nothing can be scored."
                if not enabled
                else "No audit signals available: none could be collected for this prospect, so it was not scored."
            )
            return ScoringResult(
                overall_score=None,
                score_band=None,
                website_subscore=None,
                marketing_subscore=None,
                available_signals_count=0,
                available_signals_ratio=available_ratio,
                signal_details=details_map,
                explanation=reason,
            )

        website_subscore = _weighted_pct([s for s in scorable if s.category == SignalCategory.WEBSITE])
        marketing_subscore = _weighted_pct([s for s in scorable if s.category == SignalCategory.MARKETING])
        base_score = _weighted_pct(scorable) or 0.0

        # Ideal client = BOTH groups score strongly: the "new website AND marketing" client.
        ideal_client = (
            website_subscore is not None
            and marketing_subscore is not None
            and website_subscore >= self.ideal_client_group_threshold
            and marketing_subscore >= self.ideal_client_group_threshold
        )
        bonus_applied = self.ideal_client_bonus if ideal_client else 0.0
        overall_score = round(min(100.0, max(0.0, base_score + bonus_applied)), 1)

        if overall_score >= self.threshold_high:
            score_band = ScoreBand.QUALIFIED
        elif overall_score >= self.threshold_medium:
            score_band = ScoreBand.REVIEW
        else:
            score_band = ScoreBand.DISQUALIFIED

        low_coverage = available_count < min(self.min_signals_for_qualified, total_signals)
        held_for_review = score_band == ScoreBand.QUALIFIED and low_coverage
        if held_for_review:
            score_band = ScoreBand.REVIEW

        top = ranked_findings(details_map, limit=5)
        metadata.update(
            {
                "ideal_client": ideal_client,
                "ideal_client_bonus_applied": bonus_applied,
                "low_coverage": low_coverage,
                "held_for_review": held_for_review,
                "top_findings": [f["signal"] for f in top],
            }
        )
        details_map["_metadata"] = metadata

        opp_text = (
            "\n".join(f"- {f['label']}: {f['finding'] or 'detected'}" for f in top)
            if top
            else "No pain-point signals detected on the available evidence."
        )
        coverage_note = (
            f"\nHeld in Review: the score clears the Qualified bar but only {available_count} signals had data "
            f"(at least {self.min_signals_for_qualified} needed to auto-qualify)."
            if held_for_review
            else ""
        )
        explanation = (
            f"Overall Score: {overall_score}/100 ({score_band.value.upper()}). "
            f"Evaluated on {available_ratio} available signals "
            f"(Website: {website_subscore if website_subscore is not None else 'N/A'}, "
            f"Marketing: {marketing_subscore if marketing_subscore is not None else 'N/A'})."
            f"{coverage_note}\n"
            f"Primary Pain Points / Opportunities:\n{opp_text}"
        )

        return ScoringResult(
            overall_score=overall_score,
            score_band=score_band,
            website_subscore=website_subscore,
            marketing_subscore=marketing_subscore,
            available_signals_count=available_count,
            available_signals_ratio=available_ratio,
            signal_details=details_map,
            explanation=explanation,
        )
