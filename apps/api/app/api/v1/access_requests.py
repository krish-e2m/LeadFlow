import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.constants import ApprovalStatus, UserRole
from app.db.session import get_db
from app.models.access_request import AccessRequest
from app.models.user import User
from app.providers.manager import provider_manager
from app.schemas.access_request import (
    AccessRequestReject,
    AccessRequestResponse,
)
from app.security.rbac import AuthenticatedUser, require_org_admin
from app.services.audit_service import AuditService

router = APIRouter(prefix="/access-requests", tags=["Access Requests"])


@router.get("", response_model=List[AccessRequestResponse])
async def list_access_requests(
    status_filter: Optional[str] = Query(None, alias="status"),
    current_user: AuthenticatedUser = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    List access requests scoped by role:
    - Super Admins see all requests (or org_admin / pending requests).
    - Org Admins only see client_viewer requests for their assigned organization.
    """
    stmt = (
        select(AccessRequest)
        .options(selectinload(AccessRequest.organization))
        .order_by(AccessRequest.created_at.desc())
    )

    if not current_user.is_super_admin:
        # Defense-in-depth on top of DB RLS
        stmt = stmt.where(
            AccessRequest.org_id == current_user.org_id,
            AccessRequest.requested_role == UserRole.CLIENT_VIEWER.value,
        )

    if status_filter:
        stmt = stmt.where(AccessRequest.status == status_filter.lower())

    results = (await db.execute(stmt)).scalars().all()

    return [
        AccessRequestResponse(
            id=req.id,
            org_id=req.org_id,
            org_name=req.organization.name if req.organization else None,
            email=req.email,
            full_name=req.full_name,
            requested_role=req.requested_role,
            status=req.status,
            rejection_reason=req.rejection_reason,
            reviewed_by=req.reviewed_by,
            reviewed_at=req.reviewed_at,
            created_at=req.created_at,
            updated_at=req.updated_at,
        )
        for req in results
    ]


@router.post("/{request_id}/approve", response_model=AccessRequestResponse)
async def approve_access_request(
    request_id: uuid.UUID,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Approves an access request:
    - org_admin requests can ONLY be approved by Super Admins.
    - client_viewer requests can be approved by Org Admins of that org or Super Admins.
    - Atomically provisions/activates the user account with the requested role.
    - Race-safe via row locking (with_for_update).
    """
    stmt = (
        select(AccessRequest)
        .options(selectinload(AccessRequest.organization))
        .where(AccessRequest.id == request_id)
        .with_for_update()
    )
    access_req = (await db.execute(stmt)).scalars().first()

    if not access_req:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Access request not found.",
        )

    if access_req.status != ApprovalStatus.PENDING.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Access request has already been {access_req.status}.",
        )

    # Permission verification
    if access_req.requested_role == UserRole.ORG_ADMIN.value:
        if not current_user.is_super_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Organization Admins cannot approve Org Admin access requests. Super Admin approval is required.",
            )
    elif access_req.requested_role == UserRole.CLIENT_VIEWER.value:
        if not current_user.is_super_admin and current_user.org_id != access_req.org_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cross-tenant access request approval denied.",
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown requested role: {access_req.requested_role}",
        )

    # Provision or activate user account
    user_stmt = select(User).where(User.email == access_req.email, User.deleted_at.is_(None))
    existing_user = (await db.execute(user_stmt)).scalars().first()

    if existing_user:
        existing_user.org_id = access_req.org_id
        existing_user.role = UserRole(access_req.requested_role)
        existing_user.is_active = True
        if access_req.hashed_password:
            existing_user.hashed_password = access_req.hashed_password
        if access_req.full_name:
            existing_user.full_name = access_req.full_name
    else:
        new_user = User(
            id=uuid.uuid4(),
            org_id=access_req.org_id,
            email=access_req.email,
            hashed_password=access_req.hashed_password,
            full_name=access_req.full_name,
            role=UserRole(access_req.requested_role),
            is_active=True,
            must_reset_password=False,
        )
        db.add(new_user)

    # Update access request status
    access_req.status = ApprovalStatus.APPROVED.value
    access_req.reviewed_by = current_user.id
    access_req.reviewed_at = datetime.now(timezone.utc)

    audit_service = AuditService(db)
    await audit_service.log_action(
        action="access_request.approved",
        entity_type="access_request",
        entity_id=access_req.id,
        changes={
            "status": "approved",
            "requested_role": access_req.requested_role,
            "org_id": str(access_req.org_id),
        },
        org_id=access_req.org_id,
        actor_user_id=current_user.id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    await db.commit()

    # Dispatch email notification to applicant via Resend (fire-and-forget / non-blocking)
    try:
        await provider_manager.resend.send_access_request_decision(
            applicant_email=access_req.email,
            applicant_name=access_req.full_name,
            org_name=access_req.organization.name if access_req.organization else "LeadFlow",
            approved=True,
            role=access_req.requested_role,
        )
    except Exception:
        pass

    return AccessRequestResponse(
        id=access_req.id,
        org_id=access_req.org_id,
        org_name=access_req.organization.name if access_req.organization else None,
        email=access_req.email,
        full_name=access_req.full_name,
        requested_role=access_req.requested_role,
        status=access_req.status,
        rejection_reason=access_req.rejection_reason,
        reviewed_by=access_req.reviewed_by,
        reviewed_at=access_req.reviewed_at,
        created_at=access_req.created_at,
        updated_at=access_req.updated_at,
    )


@router.post("/{request_id}/reject", response_model=AccessRequestResponse)
async def reject_access_request(
    request_id: uuid.UUID,
    payload: Optional[AccessRequestReject] = None,
    request: Request = None,
    current_user: AuthenticatedUser = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Rejects an access request:
    - org_admin requests can ONLY be rejected by Super Admins.
    - client_viewer requests can be rejected by Org Admins of that org or Super Admins.
    - Race-safe via row locking (with_for_update).
    """
    stmt = (
        select(AccessRequest)
        .options(selectinload(AccessRequest.organization))
        .where(AccessRequest.id == request_id)
        .with_for_update()
    )
    access_req = (await db.execute(stmt)).scalars().first()

    if not access_req:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Access request not found.",
        )

    if access_req.status != ApprovalStatus.PENDING.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Access request has already been {access_req.status}.",
        )

    # Permission verification
    if access_req.requested_role == UserRole.ORG_ADMIN.value:
        if not current_user.is_super_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Organization Admins cannot reject Org Admin access requests. Super Admin approval is required.",
            )
    elif access_req.requested_role == UserRole.CLIENT_VIEWER.value:
        if not current_user.is_super_admin and current_user.org_id != access_req.org_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cross-tenant access request rejection denied.",
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown requested role: {access_req.requested_role}",
        )

    reason = payload.rejection_reason if payload and payload.rejection_reason else None
    access_req.status = ApprovalStatus.REJECTED.value
    access_req.rejection_reason = reason
    access_req.reviewed_by = current_user.id
    access_req.reviewed_at = datetime.now(timezone.utc)

    audit_service = AuditService(db)
    await audit_service.log_action(
        action="access_request.rejected",
        entity_type="access_request",
        entity_id=access_req.id,
        changes={
            "status": "rejected",
            "reason": reason,
            "requested_role": access_req.requested_role,
            "org_id": str(access_req.org_id),
        },
        org_id=access_req.org_id,
        actor_user_id=current_user.id,
        ip_address=request.client.host if request and request.client else None,
        user_agent=request.headers.get("user-agent") if request else None,
    )

    await db.commit()

    # Dispatch email notification to applicant via Resend (fire-and-forget / non-blocking)
    try:
        await provider_manager.resend.send_access_request_decision(
            applicant_email=access_req.email,
            applicant_name=access_req.full_name,
            org_name=access_req.organization.name if access_req.organization else "LeadFlow",
            approved=False,
            role=access_req.requested_role,
            rejection_reason=reason,
        )
    except Exception:
        pass

    return AccessRequestResponse(
        id=access_req.id,
        org_id=access_req.org_id,
        org_name=access_req.organization.name if access_req.organization else None,
        email=access_req.email,
        full_name=access_req.full_name,
        requested_role=access_req.requested_role,
        status=access_req.status,
        rejection_reason=access_req.rejection_reason,
        reviewed_by=access_req.reviewed_by,
        reviewed_at=access_req.reviewed_at,
        created_at=access_req.created_at,
        updated_at=access_req.updated_at,
    )
