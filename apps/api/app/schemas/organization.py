import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict


class OrgCreate(BaseModel):
    name: str
    slug: str
    plan: str = "starter"
    settings: Optional[Dict[str, Any]] = None


class OrgUpdate(BaseModel):
    name: Optional[str] = None
    plan: Optional[str] = None
    settings: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None


class OrgResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    plan: str
    settings: Dict[str, Any]
    is_active: bool
    created_at: datetime
    deleted_at: Optional[datetime] = None


class OperatorAccessUpdate(BaseModel):
    enabled: bool
