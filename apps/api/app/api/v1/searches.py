from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.repositories.search_repo import SearchRepository
from app.schemas.run import RunAcceptedResponse
from app.schemas.search import SearchCreate, SearchResponse
from app.security.rbac import AuthenticatedUser, require_org_admin
from app.services.search_service import SearchService

router = APIRouter(prefix="/searches", tags=["Searches & Discovery"])


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=RunAcceptedResponse)
async def create_search(
    req: SearchCreate,
    current_user: AuthenticatedUser = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Submits a new asynchronous lead discovery search.
    Returns HTTP 202 Accepted with a unique Run ID for frontend progress polling.
    """
    search_service = SearchService(db)
    run = await search_service.initiate_search(
        org_id=current_user.org_id,
        user_id=current_user.id,
        name=req.name,
        query_params=req.query_params,
        audience_id=req.audience_id,
        limit=req.limit,
    )
    await db.commit()

    return RunAcceptedResponse(
        run_id=run.id,
        status=run.status,
        message="Search job accepted and queued for background processing.",
        poll_url=f"/api/v1/runs/{run.id}",
    )


@router.get("", response_model=List[SearchResponse])
async def list_searches(
    skip: int = 0,
    limit: int = 20,
    current_user: AuthenticatedUser = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db),
):
    """Lists past searches for the active tenant organization."""
    repo = SearchRepository(db)
    return await repo.list_by_org(current_user.org_id, skip=skip, limit=limit)
