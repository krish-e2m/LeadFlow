import uuid
from datetime import datetime
from typing import Any, Dict

from pydantic import BaseModel, ConfigDict


class EnrichmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    lead_id: uuid.UUID
    version: int
    payload: Dict[str, Any]
    provider_provenance: Dict[str, Any]
    created_at: datetime
