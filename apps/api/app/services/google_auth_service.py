import re
import secrets
import urllib.parse
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import httpx
from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.constants import UserRole
from app.db.session import AsyncSessionLocal
from app.models.engine import ScoringEngine, ScoringEngineParam
from app.models.organization import Organization
from app.models.user import User
from app.scoring.catalog import DEFAULT_SIGNAL_WEIGHTS
from app.security.passwords import hash_password
from app.security.session_store import get_redis_client


class GoogleUserProfile(BaseModel):
    sub: str
    email: str
    email_verified: bool = False
    name: Optional[str] = None
    picture: Optional[str] = None


class GoogleAuthService:
    GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
    GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
    GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"

    @classmethod
    def check_configuration(cls) -> None:
        """Validates that Google OAuth credentials are configured."""
        if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail=(
                    "Google OAuth is not configured. Please supply GOOGLE_CLIENT_ID and "
                    "GOOGLE_CLIENT_SECRET in your environment settings."
                ),
            )

    @classmethod
    async def create_authorization_url(
        cls,
        redirect_uri: Optional[str] = None,
        return_url: Optional[str] = None,
    ) -> Tuple[str, str]:
        """
        Generates a Google OAuth 2.0 authorization URL with a secure random state.
        Stores the state in Redis with a 10-minute expiry to prevent OAuth CSRF.
        """
        cls.check_configuration()

        state = secrets.token_urlsafe(32)
        effective_redirect = redirect_uri or settings.GOOGLE_REDIRECT_URI

        # Store state in Redis with optional return URL
        redis_client = get_redis_client()
        state_data = return_url or "/dashboard"
        await redis_client.set(f"leadflow:oauth_state:{state}", state_data, ex=600)

        params = {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": effective_redirect,
            "response_type": "code",
            "scope": "openid email profile",
            "access_type": "offline",
            "state": state,
            "prompt": "select_account",
        }
        url = f"{cls.GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"
        return url, state

    @classmethod
    async def validate_state(cls, state: str) -> Optional[str]:
        """Validates OAuth state against Redis and returns the stored return_url if valid."""
        redis_client = get_redis_client()
        key = f"leadflow:oauth_state:{state}"
        stored = await redis_client.get(key)
        if not stored:
            return None
        await redis_client.delete(key)
        return stored if isinstance(stored, str) else stored.decode("utf-8")

    @classmethod
    async def exchange_code_for_profile(
        cls,
        code: str,
        redirect_uri: Optional[str] = None,
    ) -> GoogleUserProfile:
        """Exchanges authorization code for tokens and retrieves verified user profile."""
        cls.check_configuration()
        effective_redirect = redirect_uri or settings.GOOGLE_REDIRECT_URI

        async with httpx.AsyncClient(timeout=10.0) as client:
            token_response = await client.post(
                cls.GOOGLE_TOKEN_URL,
                data={
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": effective_redirect,
                },
                headers={"Accept": "application/json"},
            )

            if token_response.status_code != 200:
                detail = "Failed to exchange authorization code with Google."
                try:
                    err_json = token_response.json()
                    if "error_description" in err_json:
                        detail = f"Google OAuth error: {err_json['error_description']}"
                except Exception:
                    pass
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=detail,
                )

            token_data = token_response.json()
            access_token = token_data.get("access_token")

            # Fetch user info using access token
            userinfo_response = await client.get(
                cls.GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if userinfo_response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to retrieve user profile from Google.",
                )

            userinfo = userinfo_response.json()

        if not userinfo.get("email"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Google account did not provide an email address.",
            )

        return GoogleUserProfile(
            sub=str(userinfo.get("sub")),
            email=userinfo.get("email").strip().lower(),
            email_verified=bool(userinfo.get("email_verified", False)),
            name=userinfo.get("name"),
            picture=userinfo.get("picture"),
        )

    @classmethod
    async def verify_id_token_credential(cls, id_token: str) -> GoogleUserProfile:
        """
        Validates Google ID token credential (from Google Identity Services popup / One-Tap).
        """
        cls.check_configuration()

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{cls.GOOGLE_TOKENINFO_URL}?id_token={urllib.parse.quote(id_token)}"
            )
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired Google identity token.",
                )

            data = resp.json()

        # Validate audience if client ID is configured
        if settings.GOOGLE_CLIENT_ID and data.get("aud") != settings.GOOGLE_CLIENT_ID:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Google token audience mismatch.",
            )

        if not data.get("email"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Google credential does not contain an email address.",
            )

        return GoogleUserProfile(
            sub=str(data.get("sub")),
            email=data.get("email").strip().lower(),
            email_verified=data.get("email_verified") in (True, "true"),
            name=data.get("name"),
            picture=data.get("picture"),
        )

    @classmethod
    async def authenticate_or_provision_user(
        cls,
        profile: GoogleUserProfile,
    ) -> Tuple[User, Optional[str], bool]:
        """
        Resolves or provisions a user for the verified Google profile.
        Returns: (user, org_name, is_new_registration)
        """
        if not profile.email_verified:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Your Google email address is not verified by Google.",
            )

        clean_email = profile.email

        async with AsyncSessionLocal() as session:
            # Bypass RLS to find user across tenants by email or google_id
            await session.execute(
                text(
                    "SELECT set_config('leadflow.auth_context', 'true', true), "
                    "set_config('leadflow.is_super_admin', 'false', true), "
                    "set_config('leadflow.current_org_id', '', true)"
                )
            )

            stmt = (
                select(User)
                .options(selectinload(User.organization))
                .where(
                    (User.email == clean_email) | (User.google_id == profile.sub),
                    User.deleted_at.is_(None),
                )
            )
            user = (await session.execute(stmt)).scalars().first()

            if user:
                # User already exists - check status
                if not user.is_active:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="User account is deactivated.",
                    )

                if user.role != UserRole.SUPER_ADMIN and user.organization:
                    if not user.organization.is_active or user.organization.deleted_at is not None:
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="Organization is suspended or deactivated. Access denied.",
                        )

                # Link google_id and update avatar/name if missing
                changed = False
                if not user.google_id:
                    user.google_id = profile.sub
                    changed = True
                if profile.picture and user.avatar_url != profile.picture:
                    user.avatar_url = profile.picture
                    changed = True
                if profile.name and not user.full_name:
                    user.full_name = profile.name
                    changed = True

                user.last_login_at = datetime.now(timezone.utc)
                await session.commit()

                org_name = user.organization.name if user.organization else None
                return user, org_name, False

            # User does NOT exist: Auto-provision new organization and org_admin user
            org_id = uuid.uuid4()
            user_id = uuid.uuid4()

            display_name = profile.name.strip() if profile.name else clean_email.split("@")[0].title()
            clean_org_name = f"{display_name}'s Workspace"
            base_slug = re.sub(r"[^a-z0-9]+", "-", clean_org_name.lower()).strip("-")
            slug = f"{base_slug[:80]}-{uuid.uuid4().hex[:6]}"

            # Set tenant session variable to new org_id so RLS check passes
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
                hashed_password=hash_password(f"oauth_{uuid.uuid4().hex}!SecureDisabled#"),
                full_name=display_name,
                role=UserRole.ORG_ADMIN,
                is_active=True,
                must_reset_password=False,
                last_login_at=datetime.now(timezone.utc),
                google_id=profile.sub,
                avatar_url=profile.picture,
            )
            session.add(new_user)
            await session.flush()

            # Initialize Default B2B ICP Engine for new tenant
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
            return new_user, clean_org_name, True
