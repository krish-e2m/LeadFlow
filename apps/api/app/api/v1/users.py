import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import UserRole
from app.db.session import get_db
from app.models.organization import Organization
from app.models.user import User
from app.schemas.user import UserCreate, UserResponse, UserUpdate
from app.security.passwords import hash_password
from app.security.rbac import AuthenticatedUser, require_org_admin
from app.security.session_store import SessionStore
from app.services.audit_service import AuditService

router = APIRouter(prefix="/users", tags=["User Management"])


@router.get("", response_model=List[UserResponse])
async def list_users(
    skip: int = 0,
    limit: int = 50,
    org_id: Optional[uuid.UUID] = Query(None, description="Super admin only: filter by organization"),
    current_user: AuthenticatedUser = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Lists users within the authorized organization.
    - Super admins can list across organizations or filter by a specific tenant.
    - Org admins can only list users belonging to their own organization.
    - Client viewers are rejected with 403 Forbidden.
    """
    stmt = select(User).where(User.deleted_at.is_(None))

    if current_user.role == UserRole.SUPER_ADMIN:
        target_org = org_id or current_user.org_id
        if target_org:
            stmt = stmt.where(User.org_id == target_org)
    else:
        # Org admin strictly scoped to own organization
        stmt = stmt.where(User.org_id == current_user.org_id)

    stmt = stmt.order_by(User.created_at.desc()).offset(skip).limit(limit)
    res = await db.execute(stmt)
    return list(res.scalars().all())


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Retrieves an individual user account within the authorized organization.
    Enforces tenant boundaries for org admins.
    """
    stmt = select(User).where(User.id == user_id, User.deleted_at.is_(None))
    user = (await db.execute(stmt)).scalars().first()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    if current_user.role != UserRole.SUPER_ADMIN:
        if user.org_id != current_user.org_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found in authorized organization.",
            )

    return user


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    current_user: AuthenticatedUser = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Provisions a new organization user account.
    - Prevents privilege escalation: org admins cannot grant super_admin privileges.
    - Strictly derives organization ownership from verified auth for org admins.
    - Sets initial forced-password-reset flag.
    - Hashes password securely.
    """
    # 1. Tenant & role resolution
    if current_user.role == UserRole.SUPER_ADMIN:
        target_org_id = payload.org_id or current_user.org_id
        assigned_role = payload.role
    else:
        # Org admins cannot grant super_admin privileges
        if payload.role == UserRole.SUPER_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Organization administrators cannot grant super_admin privileges.",
            )
        target_org_id = current_user.org_id
        assigned_role = payload.role

    # 2. Validate organization if assigned
    if target_org_id:
        org_stmt = select(Organization).where(
            Organization.id == target_org_id, Organization.deleted_at.is_(None)
        )
        target_org = (await db.execute(org_stmt)).scalars().first()
        if not target_org or not target_org.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Target organization is inactive or does not exist.",
            )

    # 3. Check email uniqueness
    existing_stmt = select(User).where(
        User.email == payload.email.lower(), User.deleted_at.is_(None)
    )
    if (await db.execute(existing_stmt)).scalars().first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email address already exists.",
        )

    # 4. Construct user record
    new_user = User(
        org_id=target_org_id,
        email=payload.email.lower(),
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role=assigned_role,
        is_active=True,
        must_reset_password=payload.must_reset_password
        if payload.must_reset_password is not None
        else True,
    )
    db.add(new_user)
    await db.flush()

    # 5. Record audit log
    audit_service = AuditService(db)
    await audit_service.log_action(
        action="user.create",
        entity_type="user",
        entity_id=new_user.id,
        changes={
            "email": new_user.email,
            "role": new_user.role.value,
            "org_id": str(target_org_id) if target_org_id else None,
            "must_reset_password": new_user.must_reset_password,
        },
        org_id=target_org_id,
        actor_user_id=current_user.id,
    )
    await db.commit()
    return new_user


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    current_user: AuthenticatedUser = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Updates user attributes (role, active status, name, password reset requirement).
    - Prevents privilege escalation: org admins cannot promote to super_admin or modify super_admins.
    - Prevents cross-organization mutations.
    - Invalidates active sessions in Redis when deactivating a user.
    """
    stmt = select(User).where(User.id == user_id, User.deleted_at.is_(None))
    user = (await db.execute(stmt)).scalars().first()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    if current_user.role != UserRole.SUPER_ADMIN:
        if user.org_id != current_user.org_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found in authorized organization.",
            )
        # Org admin cannot modify a super_admin
        if user.role == UserRole.SUPER_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Organization administrators cannot modify super_admin accounts.",
            )
        # Org admin cannot elevate role to super_admin
        if payload.role == UserRole.SUPER_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Privilege escalation denied: cannot assign super_admin role.",
            )

    changes = {}

    if payload.full_name is not None and payload.full_name != user.full_name:
        changes["full_name"] = {"from": user.full_name, "to": payload.full_name}
        user.full_name = payload.full_name

    if payload.role is not None and payload.role != user.role:
        changes["role"] = {"from": user.role.value, "to": payload.role.value}
        user.role = payload.role

    if payload.must_reset_password is not None and payload.must_reset_password != user.must_reset_password:
        changes["must_reset_password"] = {
            "from": user.must_reset_password,
            "to": payload.must_reset_password,
        }
        user.must_reset_password = payload.must_reset_password

    if payload.is_active is not None and payload.is_active != user.is_active:
        changes["is_active"] = {"from": user.is_active, "to": payload.is_active}
        user.is_active = payload.is_active
        if not payload.is_active:
            # Terminate all active sessions upon deactivation
            await SessionStore.invalidate_all_user_sessions(str(user.id))

    await db.flush()

    if changes:
        audit_service = AuditService(db)
        await audit_service.log_action(
            action="user.update",
            entity_type="user",
            entity_id=user.id,
            changes=changes,
            org_id=user.org_id,
            actor_user_id=current_user.id,
        )

    await db.commit()
    return user


@router.delete("/{user_id}", status_code=status.HTTP_200_OK)
async def delete_user(
    user_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Soft-deletes a user account.
    - Org admins can only delete users in their own organization.
    - Prevents deleting super_admins by non-super_admins.
    - Invalidates all sessions immediately.
    """
    stmt = select(User).where(User.id == user_id, User.deleted_at.is_(None))
    user = (await db.execute(stmt)).scalars().first()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    if current_user.role != UserRole.SUPER_ADMIN:
        if user.org_id != current_user.org_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found in authorized organization.",
            )
        if user.role == UserRole.SUPER_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot delete super_admin account.",
            )

    now = datetime.now(timezone.utc)
    user.is_active = False
    user.deleted_at = now
    await db.flush()

    # Terminate active sessions
    await SessionStore.invalidate_all_user_sessions(str(user.id))

    audit_service = AuditService(db)
    await audit_service.log_action(
        action="user.delete",
        entity_type="user",
        entity_id=user.id,
        changes={"deleted_at": now.isoformat()},
        org_id=user.org_id,
        actor_user_id=current_user.id,
    )
    await db.commit()

    return {"message": "User successfully deactivated and soft-deleted."}
