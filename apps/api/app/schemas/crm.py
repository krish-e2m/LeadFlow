import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.core.constants import CrmSyncStatus


class CrmSyncRequest(BaseModel):
    draft_id: Optional[uuid.UUID] = None
    crm_provider: str = "hubspot"


class CrmSyncResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    lead_id: uuid.UUID
    draft_id: Optional[uuid.UUID]
    crm_provider: str
    crm_contact_id: Optional[str]
    crm_company_id: Optional[str]
    crm_engagement_id: Optional[str]
    sync_status: CrmSyncStatus
    retry_count: int
    error_message: Optional[str]
    synced_at: Optional[datetime]
    created_at: datetime
    # True when this call found an existing sync for the same draft and did not call HubSpot again.
    already_synced: bool = False
    crm_company_url: Optional[str] = None
    crm_contact_url: Optional[str] = None
