import secrets
from typing import Optional
from urllib.parse import urlparse

from fastapi import HTTPException, Request, Response, status

from app.core.config import settings
from app.core.logging import logger

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
EXEMPT_PATHS = {
    "/api/v1/auth/login",
    "/api/v1/auth/signup",
    "/api/v1/auth/refresh",
    "/api/v1/auth/forgot-password",
    "/api/v1/auth/reset-password",
    "/healthz",
    "/livez",
    "/readyz",
    "/docs",
    "/openapi.json",
    "/redoc",
}


def generate_csrf_token() -> str:
    """Generates a cryptographically secure anti-CSRF token."""
    return secrets.token_urlsafe(32)


def set_csrf_cookie(response: Response, csrf_token: Optional[str] = None) -> str:
    """Sets the anti-CSRF cookie on the HTTP response."""
    token = csrf_token or generate_csrf_token()
    response.set_cookie(
        key=settings.COOKIE_CSRF_NAME,
        value=token,
        httponly=False,  # Accessible to frontend JavaScript to read and set in X-CSRF-Token header
        samesite=settings.COOKIE_SAMESITE,
        secure=settings.is_cookie_secure,
        domain=settings.COOKIE_DOMAIN,
        path="/",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    return token


def validate_csrf(request: Request) -> None:
    """
    Validates CSRF protection on state-changing requests using cookie authentication.
    Verifies trusted origin and double-submit anti-CSRF token matching.
    """
    if request.method in SAFE_METHODS:
        return

    path = request.url.path
    if path in EXEMPT_PATHS:
        return

    # If request is authenticated via Bearer header, browser CSRF is not applicable
    auth_header = request.headers.get("authorization")
    cookie_token = request.cookies.get(settings.COOKIE_ACCESS_NAME)

    if not cookie_token and auth_header and auth_header.startswith("Bearer "):
        return

    # Only enforce if request relies on cookie authentication
    if not cookie_token:
        return

    # 1. Origin / Referer Validation
    origin = request.headers.get("origin")
    referer = request.headers.get("referer")
    source_origin = None

    if origin:
        source_origin = origin.rstrip("/")
    elif referer:
        parsed = urlparse(referer)
        source_origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")

    allowed_origins = {o.rstrip("/") for o in settings.BACKEND_CORS_ORIGINS}

    if not source_origin or source_origin not in allowed_origins:
        logger.warning(f"CSRF rejected: untrusted or missing origin '{source_origin}'")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF validation failed: untrusted or missing request origin.",
        )

    # 2. Double-Submit Anti-CSRF Token Validation
    csrf_cookie = request.cookies.get(settings.COOKIE_CSRF_NAME)
    csrf_header = request.headers.get("x-csrf-token")

    if not csrf_cookie or not csrf_header:
        logger.warning("CSRF rejected: missing CSRF cookie or X-CSRF-Token header.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF protection token missing.",
        )

    if not secrets.compare_digest(csrf_cookie, csrf_header):
        logger.warning("CSRF rejected: token mismatch.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF protection token mismatch.",
        )
