import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.router import api_router
from app.core.config import settings
from app.core.logging import logger, setup_logging
from app.db.session import engine
from app.security.csrf import validate_csrf
from app.security.session_store import close_redis_client, get_redis_client


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan context manager for startup and graceful shutdown."""
    setup_logging()
    logger.info(f"Initializing {settings.APP_NAME} ({settings.ENVIRONMENT} mode)...")

    # Verify database connectivity
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("PostgreSQL database connection verified.")
    except Exception as e:
        logger.warning(f"Database connection warning at startup: {e}")

    yield

    logger.info(f"Shutting down {settings.APP_NAME}...")
    await engine.dispose()
    await close_redis_client()


WORKER_HEARTBEAT_KEY = "arq:queue:health-check"
IS_PRODUCTION = settings.ENVIRONMENT.lower() == "production"

app = FastAPI(
    title=settings.APP_NAME,
    description="Multi-Tenant B2B Lead Intelligence, Scoring, and Outreach Orchestration Platform",
    version="0.1.0",
    lifespan=lifespan,
    # OpenAPI/Swagger are disabled in production.
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
)

# Configure Cross-Origin Resource Sharing (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_correlation_and_headers_middleware(request: Request, call_next):
    """
    Attaches a unique X-Request-ID to incoming requests and outgoing responses
    for end-to-end tracing and observability, along with operational headers.
    """
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if IS_PRODUCTION:
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    if request.url.path in ("/healthz", "/livez", "/readyz"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


@app.middleware("http")
async def csrf_origin_middleware(request: Request, call_next):
    """Enforces strict origin validation and anti-CSRF token verification on cookie sessions."""
    try:
        validate_csrf(request)
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    response = await call_next(request)
    return response


# Mount REST API Routers
app.include_router(api_router)


# Liveness and Readiness Health Probes
@app.get("/healthz", tags=["Health Checks"])
async def health_check():
    """Simple liveness probe."""
    return {"status": "healthy", "version": "0.1.0", "app": settings.APP_NAME}


@app.get("/livez", tags=["Health Checks"])
async def liveness_probe():
    """Kubernetes liveness probe."""
    return {"status": "alive"}


@app.get("/readyz", tags=["Health Checks"])
async def readiness_probe():
    """
    Readiness probe: PostgreSQL and Redis must be reachable (503 otherwise).
    The ARQ worker heartbeat is reported but does not fail readiness of the API itself.
    """
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database connectivity check failed: {str(e)}",
        )

    worker = "unknown"
    try:
        redis = get_redis_client()
        await redis.ping()
        # ARQ refreshes this key every health_check_interval seconds while a worker is alive.
        worker = "up" if await redis.exists(WORKER_HEARTBEAT_KEY) else "down"
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Redis connectivity check failed: {str(e)}",
        )
    return {"status": "ready", "database": "connected", "redis": "connected", "worker": worker}


@app.get("/", tags=["Root"])
async def root():
    return {
        "app": settings.APP_NAME,
        "version": "0.1.0",
        "docs": "/docs",
        "api_v1": "/api/v1",
        "environment": settings.ENVIRONMENT,
    }
