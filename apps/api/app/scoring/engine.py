from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.core.constants import ScoreBand, SignalCategory
from app.scoring.catalog import DEFAULT_SIGNAL_WEIGHTS, SIGNAL_CATEGORIES, SIGNAL_LABELS


@dataclass
class SignalEvaluationResult:
    key: str
    label: str
    category: SignalCategory
    weight: float
    value: Optional[float]  # 0.0 (not detected), 1.0 (detected), or None (unavailable)
    status: str  # "detected", "not_detected", or "unavailable"
    evidence: Optional[str]
    provider: Optional[str]
    is_available: bool
    source_url: Optional[str] = None


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


class ScoringEngineCore:
    """
    Canonical 22-Signal Scoring Engine implementation.
    Evaluates prospect enrichment payloads against configurable weights.
    Strictly excludes unavailable (None) signals from the scoring denominator.
    Canonical score bands: 'qualified', 'review', 'disqualified', or null for unscored.
    """

    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        threshold_high: float = 75.0,
        threshold_medium: float = 50.0,
        threshold_low: float = 25.0,
        ideal_client_bonus: float = 0.0,
        ideal_client_group_threshold: float = 50.0,
    ):
        self.weights = weights or dict(DEFAULT_SIGNAL_WEIGHTS)
        self.threshold_high = threshold_high
        self.threshold_medium = threshold_medium
        self.threshold_low = threshold_low
        self.ideal_client_bonus = max(0.0, ideal_client_bonus)
        self.ideal_client_group_threshold = ideal_client_group_threshold

    def evaluate(self, raw_signals: Dict[str, Any]) -> ScoringResult:
        """
        Calculates normalized scoring results over raw signal inputs.

        Args:
            raw_signals: Dictionary where keys are signal keys and values are either:
                         - dict: {"value": float|None, "evidence": str, "provider": str, "source_url": str}
                         - float: 0.0 to 1.0 (or None)
        """
        evaluated_signals: List[SignalEvaluationResult] = []

        for key, weight in self.weights.items():
            category = SIGNAL_CATEGORIES.get(key, SignalCategory.WEBSITE)
            label = SIGNAL_LABELS.get(key, key)

            raw_item = raw_signals.get(key)
            val: Optional[float] = None
            evidence: Optional[str] = None
            provider: Optional[str] = None
            source_url: Optional[str] = None

            if isinstance(raw_item, dict):
                val = raw_item.get("value")
                evidence = raw_item.get("evidence")
                provider = raw_item.get("provider")
                source_url = raw_item.get("source_url")
            elif isinstance(raw_item, (int, float)):
                val = float(raw_item)
            elif raw_item is None:
                val = None

            is_available = val is not None

            # Determine explicit detection status
            if not is_available:
                status = "unavailable"
            elif val >= 0.5:
                status = "detected"
            else:
                status = "not_detected"

            evaluated_signals.append(
                SignalEvaluationResult(
                    key=key,
                    label=label,
                    category=category,
                    weight=weight,
                    value=val,
                    status=status,
                    evidence=evidence,
                    provider=provider,
                    is_available=is_available,
                    source_url=source_url,
                )
            )

        # Separate into categories
        website_avail = [
            s for s in evaluated_signals if s.category == SignalCategory.WEBSITE and s.is_available
        ]
        marketing_avail = [
            s
            for s in evaluated_signals
            if s.category == SignalCategory.MARKETING and s.is_available
        ]
        all_avail = [s for s in evaluated_signals if s.is_available]

        total_signals = len(self.weights)
        available_count = len(all_avail)
        available_ratio = f"{available_count}/{total_signals}"

        # If no signals are available, score must be null (do not assign 0.0)
        if not all_avail:
            details_map: Dict[str, Any] = {}
            for s in evaluated_signals:
                details_map[s.key] = {
                    "label": s.label,
                    "category": s.category.value,
                    "weight": s.weight,
                    "value": None,
                    "status": "unavailable",
                    "evidence": s.evidence or "Signal data unavailable or collector unconfigured",
                    "provider": s.provider,
                    "is_available": False,
                    "source_url": s.source_url,
                }
            details_map["_metadata"] = {
                "available_signals_count": 0,
                "available_signals_ratio": f"0/{total_signals}",
                "total_signals": total_signals,
                "fired_signals_count": 0,
            }

            return ScoringResult(
                overall_score=None,
                score_band=None,
                website_subscore=None,
                marketing_subscore=None,
                available_signals_count=0,
                available_signals_ratio=f"0/{total_signals}",
                signal_details=details_map,
                explanation="Prospect has not been enriched yet; no audit signals available for scoring.",
            )

        # Calculate Website Subscore
        website_subscore: Optional[float] = None
        if website_avail:
            w_sum = sum(s.weight * (s.value or 0.0) for s in website_avail)
            w_total = sum(s.weight for s in website_avail)
            website_subscore = round((w_sum / w_total) * 100.0, 1) if w_total > 0 else 0.0

        # Calculate Marketing Subscore
        marketing_subscore: Optional[float] = None
        if marketing_avail:
            m_sum = sum(s.weight * (s.value or 0.0) for s in marketing_avail)
            m_total = sum(s.weight for s in marketing_avail)
            marketing_subscore = round((m_sum / m_total) * 100.0, 1) if m_total > 0 else 0.0

        # Calculate Normalized Overall Score
        total_weighted_sum = sum(s.weight * (s.value or 0.0) for s in all_avail)
        total_weight = sum(s.weight for s in all_avail)
        base_score = round((total_weighted_sum / total_weight) * 100.0, 1) if total_weight > 0 else 0.0

        # Ideal client = BOTH the website and marketing groups score strongly. The configured
        # bonus is applied only in that case (a prospect who needs just one of the two services
        # is not the "new website AND marketing" client the engine is built to surface).
        ideal_client = (
            website_subscore is not None
            and marketing_subscore is not None
            and website_subscore >= self.ideal_client_group_threshold
            and marketing_subscore >= self.ideal_client_group_threshold
        )
        bonus_applied = self.ideal_client_bonus if (ideal_client and self.ideal_client_bonus > 0.0) else 0.0
        overall_score = round(min(100.0, max(0.0, base_score + bonus_applied)), 1)

        # Determine Canonical Score Band:
        # qualified: >= threshold_high (default 75.0)
        # review: >= threshold_medium (default 50.0)
        # disqualified: < threshold_medium
        if overall_score >= self.threshold_high:
            score_band = ScoreBand.QUALIFIED
        elif overall_score >= self.threshold_medium:
            score_band = ScoreBand.REVIEW
        else:
            score_band = ScoreBand.DISQUALIFIED

        # Build signal details payload
        details_map = {}
        top_opportunities: List[str] = []

        for s in evaluated_signals:
            details_map[s.key] = {
                "label": s.label,
                "category": s.category.value,
                "weight": s.weight,
                "value": s.value,
                "status": s.status,
                "evidence": s.evidence,
                "provider": s.provider,
                "is_available": s.is_available,
                "source_url": s.source_url,
            }
            if s.is_available and s.value is not None and s.value >= 0.7:
                desc = s.evidence if s.evidence else f"High signal on {s.label}"
                top_opportunities.append(f"- {s.label}: {desc}")

        fired_count = len([s for s in all_avail if s.value is not None and s.value >= 0.5])
        details_map["_metadata"] = {
            "available_signals_count": available_count,
            "available_signals_ratio": available_ratio,
            "total_signals": total_signals,
            "fired_signals_count": fired_count,
            "ideal_client_bonus": self.ideal_client_bonus,
            "ideal_client": ideal_client,
            "ideal_client_bonus_applied": bonus_applied,
        }

        # Construct explanation
        opp_text = (
            "\n".join(top_opportunities[:5])
            if top_opportunities
            else "Standard baseline score across verified signals."
        )
        explanation = (
            f"Overall Score: {overall_score}/100 ({score_band.value.upper()}). "
            f"Evaluated on {available_ratio} available signals "
            f"(Website: {website_subscore if website_subscore is not None else 'N/A'}, "
            f"Marketing: {marketing_subscore if marketing_subscore is not None else 'N/A'}).\n"
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
