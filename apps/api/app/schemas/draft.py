import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict

from app.core.constants import DraftApprovalStatus


class DraftGenerateRequest(BaseModel):
    contact_id: Optional[uuid.UUID] = None
    model: Optional[str] = None
    custom_instructions: Optional[str] = None


class DraftUpdate(BaseModel):
    subject: Optional[str] = None
    body: Optional[str] = None


class DraftApprovalUpdate(BaseModel):
    approval_status: DraftApprovalStatus


class DraftResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    lead_id: uuid.UUID
    contact_id: Optional[uuid.UUID]
    subject: str
    body: str
    model_used: str
    audit_citations: Union[Dict[str, Any], List[Any], Any]
    approval_status: DraftApprovalStatus
    approved_by: Optional[uuid.UUID]
    approved_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class DraftSendResponse(BaseModel):
    draft_id: uuid.UUID
    recipient: str
    subject: str
    message_id: Optional[str] = None
    status: str = "sent"
    sent_at: datetime
