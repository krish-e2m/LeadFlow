import uuid
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.core.constants import ApprovalStatus, PipelineStatus, ScoreBand
from app.schemas.contact import ContactResponse
from app.schemas.draft import DraftResponse
from app.schemas.enrichment import EnrichmentResponse
from app.schemas.score import ScoreResponse


class LeadCreate(BaseModel):
    domain: str
    company_name: str
    industry: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    employee_count: Optional[int] = None
    search_id: Optional[uuid.UUID] = None


class LeadApprovalUpdate(BaseModel):
    approval_status: ApprovalStatus
    manual_override: Optional[bool] = False
    override_reason: Optional[str] = None


class LeadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    search_id: Optional[uuid.UUID]
    domain: str
    company_name: str
    industry: Optional[str]
    country: Optional[str]
    city: Optional[str]
    employee_count: Optional[int]
    pipeline_status: PipelineStatus
    score_band: Optional[ScoreBand] = None
    approval_status: ApprovalStatus
    approved_by: Optional[uuid.UUID]
    approved_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    # Latest overall score (list responses), why the lead is in the "error" stage, and whether
    # it is archived.
    overall_score: Optional[float] = None
    error_reason: Optional[str] = None
    archived_at: Optional[datetime] = Field(default=None, validation_alias="deleted_at")
    # Approval responses only: what happened to the automatic email draft
    # (queued, exists, disabled, not_configured or unavailable).
    auto_draft: Optional[str] = None


class LeadDetailResponse(LeadResponse):
    scores: List[ScoreResponse] = []
    enrichments: List[EnrichmentResponse] = []
    contacts: List[ContactResponse] = []
    drafts: List[DraftResponse] = []


class BulkActionType(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    ARCHIVE = "archive"
    UNARCHIVE = "unarchive"
    RESCORE = "rescore"


class BulkLeadActionRequest(BaseModel):
    action: BulkActionType
    lead_ids: List[uuid.UUID]
    engine_id: Optional[uuid.UUID] = None


class BulkItemResult(BaseModel):
    lead_id: uuid.UUID
    success: bool
    status: Optional[str] = None
    error: Optional[str] = None


class BulkLeadActionResponse(BaseModel):
    action: str
    total_requested: int
    total_succeeded: int
    # Bulk approve only: email drafts queued for the newly approved leads.
    drafts_queued: int = 0
    total_failed: int
    results: List[BulkItemResult]
    # Bulk rescore only: band counts of the re-scored leads before and after, e.g.
    # {"before": {"qualified": 3, "review": 5}, "after": {"qualified": 4, "review": 4}}.
    band_changes: Optional[Dict[str, Dict[str, int]]] = None
