import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict

from app.core.constants import RunStatus, RunType


class RunAcceptedResponse(BaseModel):
    """HTTP 202 Accepted response for queued background jobs."""

    run_id: uuid.UUID
    status: RunStatus
    message: str
    poll_url: str


class RunResponse(BaseModel):
    """Polling response payload reporting real-time task progress."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    search_id: Optional[uuid.UUID]
    run_type: RunType
    status: RunStatus
    progress_pct: int
    items_total: int
    items_processed: int
    items_succeeded: int
    items_failed: int
    error_details: Dict[str, Any]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime
