import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.models.engine import ScoringEngine, ScoringEngineParam
from app.providers.manager import provider_manager
from app.providers.openrouter import (
    OpenRouterAuthenticationError,
    OpenRouterConfigurationError,
    OpenRouterParsingError,
    OpenRouterRateLimitError,
    OpenRouterTimeoutError,
    OpenRouterValidationError,
)
from app.schemas.engine import (
    EngineCreate,
    EngineParamResponse,
    EngineResponse,
    GeneratedEngineWeightsResponse,
    GenerateEngineWeightsRequest,
    SignalWeightConfig,
)
from app.scoring.catalog import DEFAULT_SIGNAL_WEIGHTS
from app.security.rbac import AuthenticatedUser, require_org_admin

router = APIRouter(prefix="/engines", tags=["Scoring Engines"])


@router.post("/ai-propose", response_model=GeneratedEngineWeightsResponse)
async def generate_ai_engine_weights(
    req: GenerateEngineWeightsRequest,
    current_user: AuthenticatedUser = Depends(require_org_admin),
):
    """
    Parses an ideal-client brief into a proposed set of 22-signal weights, score-band thresholds
    and an ideal-client bonus via OpenRouter. Pure proposal: never spends Apollo credits, never
    auto-saves — the operator reviews and edits before publishing a new engine version
    (docs/poc.md 8.2: engines path, "AI never auto-runs searches or spends Apollo credits").
    """
    if not req.prompt or not req.prompt.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Prompt cannot be empty.")

    try:
        return await provider_manager.openrouter.generate_engine_weights(
            req.prompt, allow_offline_heuristic=bool(req.allow_offline_heuristic)
        )
    except OpenRouterConfigurationError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"OpenRouter is unconfigured: {str(e)}")
    except OpenRouterAuthenticationError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"OpenRouter authentication error: {str(e)}")
    except OpenRouterRateLimitError as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=f"OpenRouter rate limit: {str(e)}")
    except OpenRouterTimeoutError as e:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=f"OpenRouter request timed out: {str(e)}")
    except (OpenRouterParsingError, OpenRouterValidationError) as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"OpenRouter response validation error: {str(e)}")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        safe_err = str(e)
        if provider_manager.openrouter.api_key:
            safe_err = safe_err.replace(provider_manager.openrouter.api_key, "[REDACTED]")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to generate engine weights: {safe_err}")


@router.get("", response_model=List[EngineResponse])
async def list_engines(
    current_user: AuthenticatedUser = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db),
):
    """Lists configured scoring engine profiles and active version pointers."""
    stmt = (
        select(ScoringEngine)
        .where(ScoringEngine.org_id == current_user.org_id, ScoringEngine.deleted_at.is_(None))
        .options(selectinload(ScoringEngine.params))
        .order_by(ScoringEngine.created_at.asc())
    )
    res = await db.execute(stmt)
    return list(res.scalars().all())


@router.post("", response_model=EngineResponse, status_code=status.HTTP_201_CREATED)
async def create_engine(
    req: EngineCreate,
    current_user: AuthenticatedUser = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db),
):
    """Provisions a new scoring engine with default 22-signal weights."""
    engine = ScoringEngine(
        org_id=current_user.org_id,
        name=req.name,
        description=req.description or "",
        active_version=1,
    )
    db.add(engine)
    await db.flush()

    weights = req.initial_weights or dict(DEFAULT_SIGNAL_WEIGHTS)
    param = ScoringEngineParam(
        engine_id=engine.id,
        version=1,
        weights=weights,
        threshold_high=75.0,
        threshold_medium=50.0,
        threshold_low=25.0,
    )
    db.add(param)
    await db.flush()
    # Stay inside the request transaction: its tenant (RLS) context is transaction-local, so a
    # refresh after commit() would run without it and find no rows.
    await db.refresh(engine, attribute_names=["params"])
    return engine


@router.post("/{engine_id}/params", response_model=EngineParamResponse)
async def update_engine_params(
    engine_id: uuid.UUID,
    config: SignalWeightConfig,
    current_user: AuthenticatedUser = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Publishes a new versioned set of signal weights for the 22 scoring engine metrics.
    Preserves historical runs using prior versions.
    """
    stmt = select(ScoringEngine).where(
        ScoringEngine.id == engine_id,
        ScoringEngine.org_id == current_user.org_id,
        ScoringEngine.deleted_at.is_(None),
    )
    engine = (await db.execute(stmt)).scalars().first()
    if not engine:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Scoring engine not found."
        )

    v_stmt = select(func.max(ScoringEngineParam.version)).where(
        ScoringEngineParam.engine_id == engine.id
    )
    current_max_v = (await db.execute(v_stmt)).scalar_one() or 0
    new_version = current_max_v + 1

    param = ScoringEngineParam(
        engine_id=engine.id,
        version=new_version,
        weights=config.weights,
        threshold_high=config.threshold_high,
        threshold_medium=config.threshold_medium,
        threshold_low=config.threshold_low,
        ideal_client_bonus=config.ideal_client_bonus,
    )
    db.add(param)
    engine.active_version = new_version
    await db.flush()
    return param
