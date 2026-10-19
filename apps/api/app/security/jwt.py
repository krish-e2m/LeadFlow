import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import jwt

from app.core.config import settings


def create_access_token(
    subject: str,
    org_id: Optional[str] = None,
    role: str = "org_admin",
    email: Optional[str] = None,
    must_reset_password: bool = False,
    token_id: Optional[str] = None,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Generate a signed JWT access token containing subject, org_id, role, jti, and claims."""
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    jti = token_id or str(uuid.uuid4())
    to_encode: Dict[str, Any] = {
        "sub": subject,
        "jti": jti,
        "org_id": org_id,
        "role": role,
        "email": email,
        "must_reset_password": must_reset_password,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "type": "access",
    }
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(
    subject: str,
    org_id: Optional[str] = None,
    token_id: Optional[str] = None,
    family_id: Optional[str] = None,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Generate a signed JWT refresh token with unique jti and family tracking for rotation."""
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    jti = token_id or str(uuid.uuid4())
    to_encode: Dict[str, Any] = {
        "sub": subject,
        "jti": jti,
        "org_id": org_id,
        "family": family_id or jti,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "type": "refresh",
    }
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str, expected_type: Optional[str] = None) -> Dict[str, Any]:
    """Decode and validate a signed JWT token against current signing key and algorithm."""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["exp", "iat", "sub", "type"]},
        )
        if expected_type and payload.get("type") != expected_type:
            raise ValueError(f"Invalid token type: expected {expected_type}, got {payload.get('type')}")
        return payload
    except jwt.PyJWTError as e:
        raise ValueError(f"Invalid token: {str(e)}") from e
