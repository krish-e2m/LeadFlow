import uuid
from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.scoring.catalog import DEFAULT_SIGNAL_WEIGHTS, validate_engine_weights


class SignalWeightConfig(BaseModel):
    weights: Dict[str, float] = Field(default_factory=lambda: dict(DEFAULT_SIGNAL_WEIGHTS))
    threshold_high: float = Field(default=75.0, ge=0.0, le=100.0)
    threshold_medium: float = Field(default=50.0, ge=0.0, le=100.0)
    # Accepted for backward compatibility with stored param rows; the scoring engine only reads
    # threshold_high/threshold_medium (see scoring/engine.py) — there is no separate "low" band,
    # just qualified / review / disqualified. Kept bounded rather than removed to avoid a migration.
    threshold_low: float = Field(default=25.0, ge=0.0, le=100.0)
    ideal_client_bonus: float = Field(default=0.0, ge=0.0, le=100.0)

    @field_validator("weights")
    @classmethod
    def _validate_weights(cls, v: Dict[str, float]) -> Dict[str, float]:
        try:
            return validate_engine_weights(v)
        except ValueError as e:
            raise ValueError(str(e))

    @model_validator(mode="after")
    def _validate_threshold_order(self) -> "SignalWeightConfig":
        if self.threshold_medium > self.threshold_high:
            raise ValueError("threshold_medium (Review from) must not exceed threshold_high (Qualified from).")
        if self.threshold_low > self.threshold_medium:
            raise ValueError("threshold_low must not exceed threshold_medium.")
        return self


class EngineParamResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    engine_id: uuid.UUID
    version: int
    weights: Dict[str, float]
    threshold_high: float
    threshold_medium: float
    threshold_low: float
    ideal_client_bonus: float = 0.0
    created_at: datetime


class EngineCreate(BaseModel):
    name: str
    description: Optional[str] = ""
    initial_weights: Optional[Dict[str, float]] = None

    @field_validator("initial_weights")
    @classmethod
    def _validate_initial_weights(cls, v: Optional[Dict[str, float]]) -> Optional[Dict[str, float]]:
        if v is None:
            return None
        try:
            return validate_engine_weights(v)
        except ValueError as e:
            raise ValueError(str(e))


class GenerateEngineWeightsRequest(BaseModel):
    prompt: str
    allow_offline_heuristic: Optional[bool] = False


class GeneratedEngineWeightsResponse(BaseModel):
    weights: Dict[str, float]
    threshold_high: float
    threshold_medium: float
    threshold_low: float = 25.0
    ideal_client_bonus: float = 0.0
    ai_rationale: str
    model_used: Optional[str] = "ai"
    generated_at: Optional[str] = None


class EngineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    description: str
    active_version: int
    params: Optional[List[EngineParamResponse]] = None
    created_at: datetime
    updated_at: datetime
