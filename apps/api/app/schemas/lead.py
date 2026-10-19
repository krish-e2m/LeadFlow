import uuid
from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict

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
