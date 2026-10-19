import uuid
from contextvars import ContextVar
from typing import Optional

# Async context variable for the currently active tenant organization
_current_tenant_org_id: ContextVar[Optional[uuid.UUID]] = ContextVar(
    "current_tenant_org_id", default=None
)
_is_super_admin_context: ContextVar[bool] = ContextVar("is_super_admin_context", default=False)


def set_current_tenant(org_id: Optional[uuid.UUID], is_super_admin: bool = False) -> None:
    """Set the current tenant context for the active async task."""
    _current_tenant_org_id.set(org_id)
    _is_super_admin_context.set(is_super_admin)


def get_current_tenant() -> Optional[uuid.UUID]:
    """Retrieve the current tenant organization ID from context."""
    return _current_tenant_org_id.get()


def is_super_admin_request() -> bool:
    """Check if the current request context is running with super admin privileges."""
    return _is_super_admin_context.get()
