import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr

from app.core.constants import UserRole


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: Optional[str] = None
    role: UserRole = UserRole.CLIENT_VIEWER
    org_id: Optional[uuid.UUID] = None
    must_reset_password: Optional[bool] = True


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    must_reset_password: Optional[bool] = None


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: Optional[uuid.UUID]
    email: str
    full_name: Optional[str]
    role: UserRole
    is_active: bool
    must_reset_password: bool
    last_login_at: Optional[datetime]
    created_at: datetime
