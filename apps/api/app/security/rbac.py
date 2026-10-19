import uuid
from typing import List, Optional

from fastapi import Depends, HTTPException, Request, status

from app.core.config import settings
from app.core.constants import UserRole
from app.security.jwt import decode_token
from app.security.session_store import SessionStore
from app.security.tenant import set_current_tenant

PASSWORD_RESET_EXEMPT_PATHS = {
    "/api/v1/auth/change-password",
    "/api/v1/auth/me",
    "/api/v1/auth/logout",
}


class AuthenticatedUser:
    """Lightweight authenticated user context populated from validated JWT claims."""

    def __init__(
        self,
        user_id: uuid.UUID,
        org_id: Optional[uuid.UUID],
        role: UserRole,
        email: Optional[str] = None,
        must_reset_password: bool = False,
        jti: Optional[str] = None,
    ):
        self.id = user_id
        self.org_id = org_id
        self.role = role
        self.email = email
        self.must_reset_password = must_reset_password
        self.jti = jti

    @property
    def is_super_admin(self) -> bool:
        return self.role == UserRole.SUPER_ADMIN

    @property
    def is_org_admin(self) -> bool:
        return self.role in (UserRole.SUPER_ADMIN, UserRole.ORG_ADMIN)


def extract_token_from_request(request: Request) -> str:
    """Extracts JWT access token from Bearer Authorization header or HttpOnly session cookie."""
    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        if token:
            return token

    cookie_token = request.cookies.get(settings.COOKIE_ACCESS_NAME)
    if cookie_token:
        return cookie_token

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication credentials missing.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(request: Request) -> AuthenticatedUser:
    """
    Dependency validating the access token from Authorization header or HttpOnly cookie.
    Enforces token type, signature, expiry, revocation, tenant boundary, and forced password reset.
    """
    token = extract_token_from_request(request)

    try:
        payload = decode_token(token, expected_type="access")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token subject missing",
        )

    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed user ID in token",
        )

    access_jti = payload.get("jti")
    iat = payload.get("iat", 0)

    # Verify token revocation in Redis (fail-closed if Redis unavailable)
    if access_jti:
        is_revoked = await SessionStore.is_access_token_revoked(
            user_id=user_id_str, access_jti=access_jti, iat=iat
        )
        if is_revoked:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked or invalidated.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    token_org_id_str = payload.get("org_id")
    assigned_org_id = uuid.UUID(token_org_id_str) if token_org_id_str else None

    raw_role = payload.get("role", UserRole.CLIENT_VIEWER.value)
    try:
        role = UserRole(raw_role)
    except ValueError:
        role = UserRole.CLIENT_VIEWER

    must_reset_password = bool(payload.get("must_reset_password", False))

    # Enforce forced password reset: restricted users may only access password change/me/logout
    if must_reset_password:
        path = request.url.path
        if path not in PASSWORD_RESET_EXEMPT_PATHS:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Password reset required. You must change your password before accessing this resource.",
            )

    # Super admin organization switching support via X-Organization-Id header
    # X-Org-Context is the documented header; X-Organization-Id is kept as a legacy alias.
    requested_org_header = request.headers.get("x-org-context") or request.headers.get("x-organization-id")
    effective_org_id = assigned_org_id

    if role == UserRole.SUPER_ADMIN:
        if requested_org_header:
            try:
                effective_org_id = uuid.UUID(requested_org_header)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid X-Org-Context header format",
                )
    else:
        # Regular users cannot operate across or switch organizations
        if not assigned_org_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User must belong to an organization",
            )
        if requested_org_header and requested_org_header != str(assigned_org_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cross-tenant organization access denied.",
            )

        if effective_org_id and await SessionStore.is_org_suspended(str(effective_org_id)):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Organization is suspended or deactivated. Access denied.",
            )

    # Establish transaction-local tenant context for RLS evaluation
    set_current_tenant(effective_org_id, is_super_admin=(role == UserRole.SUPER_ADMIN))

    return AuthenticatedUser(
        user_id=user_id,
        org_id=effective_org_id,
        role=role,
        email=payload.get("email"),
        must_reset_password=must_reset_password,
        jti=access_jti,
    )


def require_roles(allowed_roles: List[UserRole]):
    """Dependency factory ensuring user holds one of the specified roles."""

    async def role_checker(
        current_user: AuthenticatedUser = Depends(get_current_user),
    ) -> AuthenticatedUser:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation requires one of the roles: {[r.value for r in allowed_roles]}",
            )
        return current_user

    return role_checker


# Role helper dependencies
require_super_admin = require_roles([UserRole.SUPER_ADMIN])
require_org_admin = require_roles([UserRole.SUPER_ADMIN, UserRole.ORG_ADMIN])
require_authenticated = get_current_user
