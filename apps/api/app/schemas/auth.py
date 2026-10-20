import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    organization_name: str
    full_name: Optional[str] = None


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    refresh_token: str
    expires_in: int


class TokenPayload(BaseModel):
    sub: str
    org_id: Optional[str] = None
    role: str
    exp: int


class RefreshTokenRequest(BaseModel):
    refresh_token: Optional[str] = None


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class AuthUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: Optional[str] = None
    role: str
    org_id: Optional[uuid.UUID] = None
    org_name: Optional[str] = None
    must_reset_password: bool = False
    avatar_url: Optional[str] = None
    # The frontend and API are on different domains in production, so JS on the frontend can never
    # read the CSRF cookie directly (document.cookie is strictly same-origin) -- it must be handed
    # the token value here and sent back as the X-CSRF-Token header instead.
    csrf_token: Optional[str] = None


class LoginResponse(BaseModel):
    user: AuthUserResponse
    message: str = "Authentication successful"


class GoogleAuthUrlResponse(BaseModel):
    url: str
    state: str


class GoogleTokenRequest(BaseModel):
    credential: str  # Google ID token (JWT)
