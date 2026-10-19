import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class AccessRequestCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, description="Initial password for account upon approval")
    org_id: uuid.UUID
    requested_role: str = Field(..., description="Canonical role: org_admin or client_viewer")
    full_name: Optional[str] = Field(None, max_length=255)


class AccessRequestReject(BaseModel):
    rejection_reason: Optional[str] = Field(None, max_length=500)


class AccessRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    org_name: Optional[str] = None
    email: str
    full_name: Optional[str] = None
    requested_role: str
    status: str
    rejection_reason: Optional[str] = None
    reviewed_by: Optional[uuid.UUID] = None
    reviewed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class PublicOrganizationItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
