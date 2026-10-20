import re
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.constants import ApprovalStatus, UserRole
from app.core.logging import logger
from app.db.session import AsyncSessionLocal, auth_session, get_db
from app.models.access_request import AccessRequest
from app.models.engine import ScoringEngine, ScoringEngineParam
from app.models.organization import Organization
from app.models.user import User
from app.providers.manager import provider_manager
from app.schemas.access_request import (
    AccessRequestCreate,
    AccessRequestResponse,
    PublicOrganizationItem,
)
from app.schemas.auth import (
    AuthUserResponse,
    ChangePasswordRequest,
    GoogleAuthUrlResponse,
    GoogleTokenRequest,
    LoginRequest,
    LoginResponse,
    PasswordResetConfirm,
    PasswordResetRequest,
    RefreshTokenRequest,
    SignupRequest,
)
from app.scoring.catalog import DEFAULT_SIGNAL_WEIGHTS
from app.security.csrf import set_csrf_cookie
from app.security.jwt import create_access_token, create_refresh_token, decode_token
from app.security.passwords import hash_password, verify_password
from app.security.rbac import AuthenticatedUser, get_current_user
from app.security.session_store import SessionStore
from app.services.audit_service import AuditService
from app.services.google_auth_service import GoogleAuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _set_auth_cookies(
    response: Response,
    access_token: str,
    refresh_token: str,
) -> str:
    """Sets hardened HttpOnly session cookies and CSRF cookie on response. Returns the CSRF token
    value so the caller can also hand it to the frontend in the JSON body (see AuthUserResponse)."""
    response.set_cookie(
        key=settings.COOKIE_ACCESS_NAME,
        value=access_token,
        httponly=True,
        samesite=settings.COOKIE_SAMESITE,
        secure=settings.is_cookie_secure,
        domain=settings.COOKIE_DOMAIN,
        path="/",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    response.set_cookie(
        key=settings.COOKIE_REFRESH_NAME,
        value=refresh_token,
        httponly=True,
        samesite=settings.COOKIE_SAMESITE,
        secure=settings.is_cookie_secure,
        domain=settings.COOKIE_DOMAIN,
        path="/api/v1/auth",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
    )
    return set_csrf_cookie(response)


def _clear_auth_cookies(response: Response) -> None:
    """Clears all session authentication cookies."""
    response.delete_cookie(
        key=settings.COOKIE_ACCESS_NAME,
        path="/",
        domain=settings.COOKIE_DOMAIN,
    )
    response.delete_cookie(
        key=settings.COOKIE_REFRESH_NAME,
        path="/api/v1/auth",
        domain=settings.COOKIE_DOMAIN,
    )
    response.delete_cookie(
        key=settings.COOKIE_CSRF_NAME,
        path="/",
        domain=settings.COOKIE_DOMAIN,
    )


@router.post("/signup", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    payload: SignupRequest,
    response: Response,
):
    """
    Public organization & user onboarding endpoint:
    - Creates a new tenant organization.
    - Creates the initial organization administrator user account.
    - Initializes the tenant's default 22-signal scoring profile.
    - Establishes a secure HttpOnly session with access and refresh tokens.
    """
    if len(payload.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters long.",
        )
    clean_org_name = payload.organization_name.strip()
    if not clean_org_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization name is required.",
        )
    clean_email = payload.email.strip().lower()

    # Generate slug from organization name
    base_slug = re.sub(r"[^a-z0-9]+", "-", clean_org_name.lower()).strip("-")
    if not base_slug:
        base_slug = "org"
    slug = f"{base_slug[:80]}-{uuid.uuid4().hex[:6]}"

    org_id = uuid.uuid4()
    user_id = uuid.uuid4()

    async with AsyncSessionLocal() as session:
        # Check email uniqueness with auth_context bypass
        await session.execute(
            text(
                "SELECT set_config('leadflow.auth_context', 'true', true), "
                "set_config('leadflow.is_super_admin', 'false', true), "
                "set_config('leadflow.current_org_id', '', true)"
            )
        )
        existing = (
            await session.execute(
                select(User).where(User.email == clean_email, User.deleted_at.is_(None))
            )
        ).scalars().first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An account with this email address already exists. Please sign in instead.",
            )

        # Set tenant session variable to new org_id so RLS check passes for orgs and tenant tables
        await session.execute(
            text(
                "SELECT set_config('leadflow.current_org_id', :org_id, true), "
                "set_config('leadflow.auth_context', 'true', true), "
                "set_config('leadflow.is_super_admin', 'false', true)"
            ),
            {"org_id": str(org_id)},
        )

        new_org = Organization(
            id=org_id,
            name=clean_org_name,
            slug=slug,
            plan="starter",
            settings={},
            is_active=True,
        )
        session.add(new_org)
        await session.flush()

        new_user = User(
            id=user_id,
            org_id=org_id,
            email=clean_email,
            hashed_password=hash_password(payload.password),
            full_name=payload.full_name.strip() if payload.full_name else None,
            role=UserRole.ORG_ADMIN,
            is_active=True,
            must_reset_password=False,
            last_login_at=datetime.now(timezone.utc),
        )
        session.add(new_user)
        await session.flush()

        # Initialize Default B2B ICP Engine for tenant
        default_engine = ScoringEngine(
            org_id=org_id,
            name="Default B2B ICP Engine",
            description="Standard 22-signal weighted lead scoring profile",
            active_version=1,
        )
        session.add(default_engine)
        await session.flush()

        engine_param = ScoringEngineParam(
            engine_id=default_engine.id,
            version=1,
            weights=dict(DEFAULT_SIGNAL_WEIGHTS),
            threshold_high=75.0,
            threshold_medium=50.0,
            threshold_low=25.0,
        )
        session.add(engine_param)

        await session.commit()

    # Session establishment
    access_token = create_access_token(
        subject=str(user_id),
        org_id=str(org_id),
        role=UserRole.ORG_ADMIN.value,
        email=clean_email,
        must_reset_password=False,
    )

    refresh_token = create_refresh_token(
        subject=str(user_id),
        org_id=str(org_id),
    )

    ref_payload = decode_token(refresh_token, expected_type="refresh")
    await SessionStore.register_refresh_token(
        user_id=str(user_id),
        jti=ref_payload["jti"],
        family_id=ref_payload["family"],
    )

    csrf_token = _set_auth_cookies(response, access_token, refresh_token)

    return LoginResponse(
        user=AuthUserResponse(
            id=user_id,
            email=clean_email,
            full_name=new_user.full_name,
            role=UserRole.ORG_ADMIN.value,
            org_id=org_id,
            org_name=clean_org_name,
            must_reset_password=False,
            csrf_token=csrf_token,
        ),
        message="Registration successful! Welcome to LeadFlow.",
    )


@router.get("/organizations", response_model=List[PublicOrganizationItem])
async def list_public_organizations():
    """
    Public listing of active organizations for role selection and access requests.
    Only returns id, name, and slug of non-deleted, active organizations.
    """
    async with auth_session() as db:
        stmt = (
            select(Organization.id, Organization.name, Organization.slug)
            .where(Organization.is_active.is_(True), Organization.deleted_at.is_(None))
            .order_by(Organization.name.asc())
        )
        result = await db.execute(stmt)
        return [
            PublicOrganizationItem(id=row.id, name=row.name, slug=row.slug)
            for row in result.all()
        ]


@router.post("/access-requests", response_model=AccessRequestResponse, status_code=status.HTTP_201_CREATED)
async def submit_access_request(
    payload: AccessRequestCreate,
    request: Request,
):
    """
    Submits a role-selection and organization access request:
    - org_admin requests route to Super Admin approval.
    - client_viewer requests route to Organization Admin approval.
    - super_admin requests are rejected.
    """
    clean_email = payload.email.strip().lower()
    clean_role = payload.requested_role.strip().lower()

    if clean_role not in (UserRole.ORG_ADMIN.value, UserRole.CLIENT_VIEWER.value):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid requested role. Allowed roles: org_admin, client_viewer.",
        )

    if len(payload.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters long.",
        )

    async with auth_session() as db:
        # Check org exists and is active
        org_stmt = select(Organization).where(
            Organization.id == payload.org_id,
            Organization.is_active.is_(True),
            Organization.deleted_at.is_(None),
        )
        org = (await db.execute(org_stmt)).scalars().first()
        if not org:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Selected organization not found or inactive.",
            )

        # Check if user already exists
        user_stmt = select(User).where(User.email == clean_email, User.deleted_at.is_(None))
        existing_user = (await db.execute(user_stmt)).scalars().first()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An active account with this email address already exists. Please log in directly.",
            )

        # Check for duplicate pending requests for this (email, org_id, requested_role)
        pending_stmt = select(AccessRequest).where(
            AccessRequest.email == clean_email,
            AccessRequest.org_id == payload.org_id,
            AccessRequest.requested_role == clean_role,
            AccessRequest.status == ApprovalStatus.PENDING.value,
        )
        existing_request = (await db.execute(pending_stmt)).scalars().first()
        if existing_request:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A pending access request already exists for this email, organization, and role.",
            )

        new_request = AccessRequest(
            id=uuid.uuid4(),
            org_id=payload.org_id,
            email=clean_email,
            full_name=payload.full_name.strip() if payload.full_name else clean_email.split("@")[0],
            hashed_password=hash_password(payload.password),
            requested_role=clean_role,
            status=ApprovalStatus.PENDING.value,
        )
        db.add(new_request)
        await db.flush()

        audit_service = AuditService(db)
        await audit_service.log_action(
            action="access_request.submitted",
            entity_type="access_request",
            entity_id=new_request.id,
            changes={
                "email": clean_email,
                "requested_role": clean_role,
                "org_id": str(payload.org_id),
            },
            org_id=payload.org_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        await db.commit()

        return AccessRequestResponse(
            id=new_request.id,
            org_id=new_request.org_id,
            org_name=org.name,
            email=new_request.email,
            full_name=new_request.full_name,
            requested_role=new_request.requested_role,
            status=new_request.status,
            rejection_reason=new_request.rejection_reason,
            reviewed_by=new_request.reviewed_by,
            reviewed_at=new_request.reviewed_at,
            created_at=new_request.created_at,
            updated_at=new_request.updated_at,
        )


@router.post("/login", response_model=LoginResponse)
async def login(
    credentials: LoginRequest,
    response: Response,
):
    """
    Authenticates user credentials and establishes an HttpOnly cookie session.
    Registers refresh token in Redis and never returns reusable raw tokens in the JSON payload.
    """
    async with auth_session() as db:
        stmt = (
            select(User)
            .options(selectinload(User.organization))
            .where(User.email == credentials.email.lower(), User.deleted_at.is_(None))
        )
        user = (await db.execute(stmt)).scalars().first()

        if not user:
            # Check if there is an access request for this applicant
            req_stmt = (
                select(AccessRequest)
                .where(AccessRequest.email == credentials.email.lower())
                .order_by(AccessRequest.created_at.desc())
            )
            latest_req = (await db.execute(req_stmt)).scalars().first()
            if (
                latest_req
                and latest_req.hashed_password
                and verify_password(credentials.password, latest_req.hashed_password)
            ):
                if latest_req.status == ApprovalStatus.PENDING.value:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Your access request is currently pending administrative approval. You will be able to log in once approved.",
                    )
                elif latest_req.status == ApprovalStatus.REJECTED.value:
                    reason = f": {latest_req.rejection_reason}" if latest_req.rejection_reason else "."
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"Your access request was rejected{reason}",
                    )

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not verify_password(credentials.password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="User account is deactivated."
            )

        if user.role != UserRole.SUPER_ADMIN and user.organization:
            if not user.organization.is_active or user.organization.deleted_at is not None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Organization is suspended or deactivated. Access denied.",
                )

        user.last_login_at = datetime.now(timezone.utc)
        await db.commit()

        user_id = user.id
        org_id = user.org_id
        role_val = user.role.value
        email_val = user.email
        must_reset = user.must_reset_password
        org_name = user.organization.name if user.organization else None
        full_name = user.full_name

    access_token = create_access_token(
        subject=str(user_id),
        org_id=str(org_id) if org_id else None,
        role=role_val,
        email=email_val,
        must_reset_password=must_reset,
    )

    refresh_token = create_refresh_token(
        subject=str(user_id),
        org_id=str(org_id) if org_id else None,
    )

    ref_payload = decode_token(refresh_token, expected_type="refresh")
    await SessionStore.register_refresh_token(
        user_id=str(user_id),
        jti=ref_payload["jti"],
        family_id=ref_payload["family"],
    )

    csrf_token = _set_auth_cookies(response, access_token, refresh_token)

    return LoginResponse(
        user=AuthUserResponse(
            id=user_id,
            email=email_val,
            full_name=full_name,
            role=role_val,
            org_id=org_id,
            org_name=org_name,
            must_reset_password=must_reset,
            csrf_token=csrf_token,
        ),
        message="Authentication successful",
    )


@router.post("/refresh", response_model=LoginResponse)
async def refresh_session(
    request: Request,
    response: Response,
    payload: Optional[RefreshTokenRequest] = None,
):
    """
    Rotates the refresh token and issues a new access token via HttpOnly cookies.
    Detects token reuse: reusing an already-rotated token invalidates the entire session family.
    """
    raw_refresh = request.cookies.get(settings.COOKIE_REFRESH_NAME)
    if not raw_refresh and payload and payload.refresh_token:
        raw_refresh = payload.refresh_token

    if not raw_refresh:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token missing from cookie or request payload.",
        )

    try:
        decoded = decode_token(raw_refresh, expected_type="refresh")
    except Exception:
        _clear_auth_cookies(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token.",
        )

    user_id_str = decoded.get("sub")
    old_jti = decoded.get("jti")
    family_id = decoded.get("family", old_jti)

    # Perform refresh token rotation with reuse detection in Redis
    new_jti = str(uuid.uuid4())
    success, reason = await SessionStore.rotate_refresh_token(
        user_id=user_id_str,
        old_jti=old_jti,
        family_id=family_id,
        new_jti=new_jti,
    )

    if not success:
        _clear_auth_cookies(response)
        if reason == "REUSE_DETECTED":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token reuse detected. All sessions in this family terminated.",
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token expired or invalid.",
        )

    user_id = uuid.UUID(user_id_str)
    async with auth_session() as db:
        stmt = (
            select(User)
            .options(selectinload(User.organization))
            .where(User.id == user_id, User.deleted_at.is_(None))
        )
        user = (await db.execute(stmt)).scalars().first()

        if not user or not user.is_active:
            _clear_auth_cookies(response)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account inactive or deleted.",
            )

        if user.role != UserRole.SUPER_ADMIN and user.organization:
            if not user.organization.is_active or user.organization.deleted_at is not None:
                _clear_auth_cookies(response)
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Organization is suspended or deactivated. Access denied.",
                )

        u_id = user.id
        u_org_id = user.org_id
        u_role = user.role.value
        u_email = user.email
        u_must_reset = user.must_reset_password
        u_full_name = user.full_name
        u_org_name = user.organization.name if user.organization else None

    new_access = create_access_token(
        subject=str(u_id),
        org_id=str(u_org_id) if u_org_id else None,
        role=u_role,
        email=u_email,
        must_reset_password=u_must_reset,
    )

    new_refresh = create_refresh_token(
        subject=str(u_id),
        org_id=str(u_org_id) if u_org_id else None,
        token_id=new_jti,
        family_id=family_id,
    )

    csrf_token = _set_auth_cookies(response, new_access, new_refresh)

    return LoginResponse(
        user=AuthUserResponse(
            id=u_id,
            email=u_email,
            full_name=u_full_name,
            role=u_role,
            org_id=u_org_id,
            org_name=u_org_name,
            must_reset_password=u_must_reset,
            csrf_token=csrf_token,
        ),
        message="Session refreshed successfully",
    )


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    current_user: Optional[AuthenticatedUser] = Depends(get_current_user),
):
    """
    Revokes the current session and tokens in Redis, and clears all session cookies.
    """
    _clear_auth_cookies(response)

    if current_user and current_user.jti:
        await SessionStore.revoke_access_token(current_user.jti)

    raw_refresh = request.cookies.get(settings.COOKIE_REFRESH_NAME)
    if raw_refresh:
        try:
            ref_payload = decode_token(raw_refresh, expected_type="refresh")
            await SessionStore.revoke_refresh_token(
                user_id=ref_payload["sub"], jti=ref_payload["jti"]
            )
        except Exception:
            pass

    return {"message": "Successfully logged out."}


@router.get("/me", response_model=AuthUserResponse)
async def get_current_user_profile(
    request: Request,
    response: Response,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns verified user profile and active organization context.
    Super admin can dynamically switch organizations using X-Organization-Id header.

    Also hands back the CSRF token value: the frontend runs on a different domain than this API in
    production, so its JavaScript can never read the CSRF cookie directly (document.cookie is
    strictly same-origin) -- this is how it learns the value to echo back as X-CSRF-Token on
    state-changing requests. Re-issues the cookie if it's missing for any reason (e.g. this is the
    first request after a Google OAuth redirect landed without one, which shouldn't normally happen
    but must never leave the frontend permanently unable to make any state-changing request).
    """
    org_name = None
    if current_user.org_id:
        stmt = select(Organization.name).where(Organization.id == current_user.org_id)
        org_name = (await db.execute(stmt)).scalar()

    csrf_token = request.cookies.get(settings.COOKIE_CSRF_NAME) or set_csrf_cookie(response)

    return AuthUserResponse(
        id=current_user.id,
        email=current_user.email or "",
        role=current_user.role.value,
        org_id=current_user.org_id,
        org_name=org_name,
        must_reset_password=current_user.must_reset_password,
        csrf_token=csrf_token,
    )


@router.post("/change-password")
async def change_password(
    req: ChangePasswordRequest,
    response: Response,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Changes password for the currently authenticated user.
    Clears forced password reset and invalidates all existing sessions in Redis.
    """
    if len(req.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be at least 8 characters long.",
        )

    stmt = select(User).where(User.id == current_user.id)
    user = (await db.execute(stmt)).scalars().first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    if not verify_password(req.old_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect current password.",
        )

    user.hashed_password = hash_password(req.new_password)
    user.must_reset_password = False
    await db.commit()

    # Invalidate all prior sessions/tokens in Redis
    await SessionStore.invalidate_all_user_sessions(str(user.id))

    # Issue a fresh session with must_reset_password=False
    new_access = create_access_token(
        subject=str(user.id),
        org_id=str(user.org_id) if user.org_id else None,
        role=user.role.value,
        email=user.email,
        must_reset_password=False,
    )
    new_refresh = create_refresh_token(
        subject=str(user.id),
        org_id=str(user.org_id) if user.org_id else None,
    )
    ref_payload = decode_token(new_refresh, expected_type="refresh")
    await SessionStore.register_refresh_token(
        user_id=str(user.id),
        jti=ref_payload["jti"],
        family_id=ref_payload["family"],
    )
    _set_auth_cookies(response, new_access, new_refresh)

    return {"message": "Password changed successfully. Prior sessions invalidated."}


@router.post("/forgot-password")
async def forgot_password(req: PasswordResetRequest):
    """Triggers secure password reset email via Resend."""
    async with auth_session() as db:
        user = (await db.execute(select(User).where(User.email == req.email.lower()))).scalars().first()
        if user:
            reset_token = create_access_token(
                subject=str(user.id),
                role=user.role.value,
                expires_delta=timedelta(hours=1),
            )
            await provider_manager.resend.send_password_reset_email(user.email, reset_token)

    # Always return 200 to prevent email enumeration
    return {
        "message": "If this email exists in our system, password reset instructions have been sent."
    }


@router.post("/reset-password")
async def reset_password(req: PasswordResetConfirm):
    """Confirms password reset token, updates password, and invalidates all existing sessions."""
    if len(req.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be at least 8 characters long.",
        )

    try:
        payload = decode_token(req.token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token.",
        )

    user_id = uuid.UUID(payload.get("sub"))
    async with auth_session() as db:
        user = (await db.execute(select(User).where(User.id == user_id))).scalars().first()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

        user.hashed_password = hash_password(req.new_password)
        user.must_reset_password = False
        await db.commit()

    # Invalidate all prior sessions in Redis
    await SessionStore.invalidate_all_user_sessions(str(user_id))

    return {"message": "Password reset successful. You may now log in with your new password."}


@router.get("/google/url", response_model=GoogleAuthUrlResponse)
async def get_google_auth_url(return_url: Optional[str] = None):
    """
    Generates a secure Google OAuth 2.0 authorization URL with anti-CSRF state token.
    State is stored in Redis for 10 minutes.
    """
    url, state = await GoogleAuthService.create_authorization_url(return_url=return_url)
    return GoogleAuthUrlResponse(url=url, state=state)


@router.get("/google/callback")
async def google_oauth_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    """
    Handles Google OAuth 2.0 authorization code callback:
    - Verifies anti-CSRF state from Redis
    - Exchanges code for profile with Google
    - Automatically provisions or logs in the user
    - Establishes HttpOnly session cookies
    - Redirects browser to frontend dashboard
    """
    # BACKEND_CORS_ORIGINS is a list of every allowed origin (order not meaningful, and index [0]
    # isn't necessarily the live app); GOOGLE_FRONTEND_REDIRECT_URL is the one setting that names
    # the actual frontend to send the browser back to.
    parsed_frontend = urllib.parse.urlparse(settings.GOOGLE_FRONTEND_REDIRECT_URL)
    frontend_base = (
        f"{parsed_frontend.scheme}://{parsed_frontend.netloc}" if parsed_frontend.netloc else "http://localhost:3000"
    )
    login_url = f"{frontend_base}/login"

    if error:
        err_param = urllib.parse.quote(f"Google login was cancelled or failed: {error}")
        return RedirectResponse(url=f"{login_url}?error={err_param}", status_code=status.HTTP_302_FOUND)

    if not code or not state:
        err_param = urllib.parse.quote("Missing OAuth authorization code or state parameter.")
        return RedirectResponse(url=f"{login_url}?error={err_param}", status_code=status.HTTP_302_FOUND)

    # Validate state against Redis
    return_path = await GoogleAuthService.validate_state(state)
    if return_path is None:
        err_param = urllib.parse.quote("Invalid or expired OAuth state. Please try logging in again.")
        return RedirectResponse(url=f"{login_url}?error={err_param}", status_code=status.HTTP_302_FOUND)

    try:
        profile = await GoogleAuthService.exchange_code_for_profile(code)
        user, org_name, _ = await GoogleAuthService.authenticate_or_provision_user(profile)
    except HTTPException as e:
        err_param = urllib.parse.quote(str(e.detail))
        return RedirectResponse(url=f"{login_url}?error={err_param}", status_code=status.HTTP_302_FOUND)
    except Exception as exc:
        # The user only sees a generic message; keep the cause in the server log.
        logger.exception(f"Google OAuth callback failed: {type(exc).__name__}")
        err_param = urllib.parse.quote("An unexpected error occurred during Google authentication.")
        return RedirectResponse(url=f"{login_url}?error={err_param}", status_code=status.HTTP_302_FOUND)

    # Establish session tokens
    access_token = create_access_token(
        subject=str(user.id),
        org_id=str(user.org_id) if user.org_id else None,
        role=user.role.value,
        email=user.email,
        must_reset_password=user.must_reset_password,
    )

    refresh_token = create_refresh_token(
        subject=str(user.id),
        org_id=str(user.org_id) if user.org_id else None,
    )

    ref_payload = decode_token(refresh_token, expected_type="refresh")
    await SessionStore.register_refresh_token(
        user_id=str(user.id),
        jti=ref_payload["jti"],
        family_id=ref_payload["family"],
    )

    # Prepare redirect
    target_url = f"{frontend_base}{return_path}" if return_path.startswith("/") else f"{frontend_base}/dashboard"
    response = RedirectResponse(url=target_url, status_code=status.HTTP_302_FOUND)
    _set_auth_cookies(response, access_token, refresh_token)
    return response


@router.post("/google/token", response_model=LoginResponse)
async def google_token_login(
    payload: GoogleTokenRequest,
    response: Response,
):
    """
    Validates Google ID Token from Google Identity Services (One-Tap / popup) and logs in or creates user.
    """
    profile = await GoogleAuthService.verify_id_token_credential(payload.credential)
    user, org_name, _ = await GoogleAuthService.authenticate_or_provision_user(profile)

    access_token = create_access_token(
        subject=str(user.id),
        org_id=str(user.org_id) if user.org_id else None,
        role=user.role.value,
        email=user.email,
        must_reset_password=user.must_reset_password,
    )

    refresh_token = create_refresh_token(
        subject=str(user.id),
        org_id=str(user.org_id) if user.org_id else None,
    )

    ref_payload = decode_token(refresh_token, expected_type="refresh")
    await SessionStore.register_refresh_token(
        user_id=str(user.id),
        jti=ref_payload["jti"],
        family_id=ref_payload["family"],
    )

    csrf_token = _set_auth_cookies(response, access_token, refresh_token)

    return LoginResponse(
        user=AuthUserResponse(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=user.role.value,
            org_id=user.org_id,
            org_name=org_name,
            must_reset_password=user.must_reset_password,
            avatar_url=user.avatar_url,
            csrf_token=csrf_token,
        ),
        message="Authentication successful",
    )
