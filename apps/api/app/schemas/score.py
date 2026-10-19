import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict

from app.core.constants import ScoreBand


class SignalDetailItem(BaseModel):
    label: str
    category: str
    weight: float
    value: Optional[float]
    status: Optional[str] = None  # "detected" | "not_detected" | "unavailable"
    evidence: Optional[str]
    provider: Optional[str]
    is_available: bool


class ScoreResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    lead_id: uuid.UUID
    overall_score: Optional[float] = None
    score_band: Optional[ScoreBand] = None
    website_subscore: Optional[float] = None
    marketing_subscore: Optional[float] = None
    signal_details: Dict[str, Any]
    explanation: Optional[str] = None
    created_at: datetime
