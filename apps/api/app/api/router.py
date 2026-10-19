from fastapi import APIRouter

from app.api.v1 import (
    access_requests,
    admin,
    audiences,
    auth,
    contacts,
    crm,
    drafts,
    engines,
    leads,
    runs,
    searches,
    users,
)

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth.router)
api_router.include_router(access_requests.router)
api_router.include_router(users.router)
api_router.include_router(searches.router)
api_router.include_router(runs.router)
api_router.include_router(leads.router)
api_router.include_router(audiences.router)
api_router.include_router(engines.router)
api_router.include_router(contacts.router)
api_router.include_router(contacts.lead_contacts_router)
api_router.include_router(drafts.router)
api_router.include_router(crm.router)
api_router.include_router(admin.router)
