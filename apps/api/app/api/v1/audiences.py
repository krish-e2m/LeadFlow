import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.filter_catalog import FilterValidationError, validate_and_normalize_filters
from app.db.session import get_db
from app.models.audience import Audience
from app.providers.manager import provider_manager
from app.providers.openrouter import (
    OpenRouterAuthenticationError,
    OpenRouterConfigurationError,
    OpenRouterParsingError,
    OpenRouterRateLimitError,
    OpenRouterTimeoutError,
    OpenRouterValidationError,
)
from app.schemas.audience import (
    AudienceCreate,
    AudienceResponse,
    GenerateAIAudienceRequest,
    GeneratedAIAudienceResponse,
)
from app.security.rbac import AuthenticatedUser, require_org_admin

router = APIRouter(prefix="/audiences", tags=["ICP Audiences"])


@router.get("", response_model=List[AudienceResponse])
async def list_audiences(
    current_user: AuthenticatedUser = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db),
):
    """Lists saved ICP audiences for the organization."""
    stmt = (
        select(Audience)
        .where(Audience.org_id == current_user.org_id, Audience.deleted_at.is_(None))
        .order_by(Audience.created_at.desc())
    )
    res = await db.execute(stmt)
    return list(res.scalars().all())


@router.post("/generate-ai-criteria", response_model=GeneratedAIAudienceResponse)
@router.post("/ai-propose", response_model=GeneratedAIAudienceResponse)
async def generate_ai_icp_criteria(
    req: GenerateAIAudienceRequest,
    current_user: AuthenticatedUser = Depends(require_org_admin),
):
    """
    Parses a natural language brief using OpenRouter frontier LLMs into structured,
    catalog-validated ICP audience filters (canonical verticals, locations, exclusions,
    and matching modes) with an evidence-grounded AI rationale.
    Supports route alias /ai-propose as documented in the specification.
    """
    if not req.prompt or not req.prompt.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Prompt cannot be empty.",
        )

    try:
        res = await provider_manager.openrouter.generate_icp_criteria(
            req.prompt, allow_offline_heuristic=bool(req.allow_offline_heuristic)
        )
        return res
    except OpenRouterConfigurationError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"OpenRouter is unconfigured: {str(e)}",
        )
    except OpenRouterAuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OpenRouter authentication error: {str(e)}",
        )
    except OpenRouterRateLimitError as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"OpenRouter rate limit: {str(e)}",
        )
    except OpenRouterTimeoutError as e:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"OpenRouter request timed out: {str(e)}",
        )
    except (OpenRouterParsingError, OpenRouterValidationError) as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OpenRouter response validation error: {str(e)}",
        )
    except FilterValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"ICP filter validation failed: {str(e)}",
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        safe_err = str(e)
        if provider_manager.openrouter.api_key:
            safe_err = safe_err.replace(provider_manager.openrouter.api_key, "[REDACTED]")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate ICP criteria: {safe_err}",
        )


@router.post("", response_model=AudienceResponse, status_code=status.HTTP_201_CREATED)
async def create_audience(
    req: AudienceCreate,
    current_user: AuthenticatedUser = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db),
):
    """Creates a new Ideal Customer Profile (ICP) filter set with catalog validation."""
    try:
        normalized_filters = validate_and_normalize_filters(req.filters)
    except FilterValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Filter validation error: {str(e)}",
        )

    audience = Audience(
        org_id=current_user.org_id,
        name=req.name,
        description=req.description or "",
        filters=normalized_filters,
        ai_rationale=req.ai_rationale,
        version=1,
    )
    db.add(audience)
    await db.flush()
    await db.commit()
    return audience


@router.get("/{audience_id}", response_model=AudienceResponse)
async def get_audience(
    audience_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db),
):
    """Retrieves an ICP audience by ID."""
    stmt = select(Audience).where(
        Audience.id == audience_id,
        Audience.org_id == current_user.org_id,
        Audience.deleted_at.is_(None),
    )
    audience = (await db.execute(stmt)).scalars().first()
    if not audience:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audience not found.")
    return audience
