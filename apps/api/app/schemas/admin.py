import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: Optional[uuid.UUID]
    actor_user_id: Optional[uuid.UUID]
    action: str
    entity_type: str
    entity_id: uuid.UUID
    changes: Dict[str, Any]
    ip_address: Optional[str]
    user_agent: Optional[str]
    created_at: datetime


class ProviderStatusResponse(BaseModel):
    name: str
    is_configured: bool
    is_healthy: bool
    status_message: str
    last_checked: datetime


class QuotaUsageDetail(BaseModel):
    used: int
    limit: int
    remaining: int
    period: str
    is_exceeded: bool = False


class UsageMetricsResponse(BaseModel):
    org_id: Optional[uuid.UUID]
    total_searches_run: int
    total_leads_sourced: int
    total_contacts_revealed: int
    total_ai_drafts_generated: int
    total_crm_syncs: int
    credits_used: int
    credits_limit: int

    monthly_leads: Optional[QuotaUsageDetail] = None
    leads_per_search_limit: int = 500
    concurrent_runs: Optional[QuotaUsageDetail] = None
    daily_contact_reveals: Optional[QuotaUsageDetail] = None
    daily_draft_generation: Optional[QuotaUsageDetail] = None
    monthly_llm_usage_usd: Optional[float] = 0.0
    monthly_llm_ceiling_usd: Optional[float] = None
    llm_provider_configured: bool = False
    status_flags: Dict[str, Any] = {}
    quotas: Optional[Dict[str, Any]] = None


class SystemHealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    database: str
    redis: str
    providers_online: int
    providers_total: int


class TestEmailRequest(BaseModel):
    to_email: str
    subject: Optional[str] = "LeadFlow Resend Test Email"


class TestEmailResponse(BaseModel):
    success: bool
    message: str
    message_id: Optional[str] = None
    to: str
    from_email: str

