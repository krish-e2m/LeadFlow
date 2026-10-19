import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from app.core.filter_catalog import validate_and_normalize_filters


class AudienceCreate(BaseModel):
    name: str
    description: Optional[str] = ""
    filters: Dict[str, Any]
    ai_rationale: Optional[str] = None

    @field_validator("filters", mode="after")
    @classmethod
    def validate_filters(cls, v: Any) -> Dict[str, Any]:
        return validate_and_normalize_filters(v)


class AudienceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    filters: Optional[Dict[str, Any]] = None
    ai_rationale: Optional[str] = None
    is_active: Optional[bool] = None

    @field_validator("filters", mode="after")
    @classmethod
    def validate_filters(cls, v: Any) -> Optional[Dict[str, Any]]:
        if v is not None:
            return validate_and_normalize_filters(v)
        return v


class AudienceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    description: str
    filters: Dict[str, Any]
    ai_rationale: Optional[str] = None
    version: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class GenerateAIAudienceRequest(BaseModel):
    prompt: str
    allow_offline_heuristic: Optional[bool] = False


class GeneratedAIAudienceResponse(BaseModel):
    name: str
    description: str
    ai_rationale: str
    filters: Dict[str, Any]
    model_used: Optional[str] = "ai"
    generated_at: Optional[str] = None
