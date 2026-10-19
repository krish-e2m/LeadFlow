import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class SearchCreate(BaseModel):
    name: str
    audience_id: Optional[uuid.UUID] = None
    query_params: Dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(default=25, ge=1, le=500)


class SearchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    audience_id: Optional[uuid.UUID]
    name: str
    query_params: Dict[str, Any]
    created_by: uuid.UUID
    created_at: datetime
