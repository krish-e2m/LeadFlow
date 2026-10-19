import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.models.contact import Contact
from app.schemas.contact import (
    ContactDiscoverResponse,
    ContactResponse,
    ContactRevealRequest,
    ContactRevealResponse,
)
from app.security.rbac import AuthenticatedUser, require_org_admin
from app.services.audit_service import AuditService
from app.services.contact_service import ContactService, display_name

router = APIRouter(prefix="/contacts", tags=["Contacts & Spend Gates"])
lead_contacts_router = APIRouter(prefix="/leads", tags=["Contacts & Spend Gates"])


async def _reveals_remaining(db: AsyncSession, org_id: uuid.UUID) -> int:
    now = datetime.now(timezone.utc)
    start_of_day = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    used_today = (
        await db.execute(
            select(func.count(Contact.id)).where(
                Contact.org_id == org_id,
                Contact.is_revealed.is_(True),
                Contact.revealed_at >= start_of_day,
            )
        )
    ).scalar_one()
    return max(0, settings.QUOTA_CONTACT_REVEALS_PER_DAY - used_today)


async def _audit_reveal(db: AsyncSession, contact: Contact, user: AuthenticatedUser) -> None:
    await AuditService(db).log_action(
        action="contact.reveal",
        entity_type="contact",
        entity_id=contact.id,
        changes={"revealed": True, "lead_id": str(contact.lead_id)},
        org_id=user.org_id,
        actor_user_id=user.id,
    )


@router.post("/{contact_id}/reveal", response_model=ContactRevealResponse)
async def reveal_contact_details(
    contact_id: uuid.UUID,
    payload: ContactRevealRequest,
    current_user: AuthenticatedUser = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Explicit spend gate: reveals one contact's verified work email and phone.
    Requires an approved lead and records an audit event.
    """
    service = ContactService(db)
    revealed_contact = await service.reveal_contact(
        contact_id=contact_id,
        org_id=current_user.org_id,
        user_id=current_user.id,
    )
    await _audit_reveal(db, revealed_contact, current_user)

    return ContactRevealResponse(
        contact=ContactResponse.model_validate(revealed_contact),
        credits_remaining=await _reveals_remaining(db, current_user.org_id),
        message="Contact details successfully revealed.",
    )


@lead_contacts_router.post("/{lead_id}/reveal-contact", response_model=ContactRevealResponse)
async def reveal_company_contact(
    lead_id: uuid.UUID,
    payload: ContactRevealRequest,
    current_user: AuthenticatedUser = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    One-click company reveal: reveals the top decision-maker at an approved lead.
    People are looked up with Hunter first when none are stored. Uses one reveal credit.
    """
    service = ContactService(db)
    contact, already_revealed, discovered = await service.reveal_primary_contact(
        lead_id=lead_id, org_id=current_user.org_id, user_id=current_user.id
    )
    if discovered:
        await AuditService(db).log_action(
            action="contact.discover",
            entity_type="lead",
            entity_id=lead_id,
            changes={"created": discovered},
            org_id=current_user.org_id,
            actor_user_id=current_user.id,
        )
    if not already_revealed:
        await _audit_reveal(db, contact, current_user)

    name = display_name(contact)
    return ContactRevealResponse(
        contact=ContactResponse.model_validate(contact),
        credits_remaining=await _reveals_remaining(db, current_user.org_id),
        message=(
            f"{name} was already revealed. Open the lead's contacts to reveal someone else."
            if already_revealed
            else f"Revealed {name}."
        ),
        already_revealed=already_revealed,
        contacts_discovered=discovered,
    )


@lead_contacts_router.post("/{lead_id}/contacts/discover", response_model=ContactDiscoverResponse)
async def discover_lead_contacts(
    lead_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_org_admin),
    db: AsyncSession = Depends(get_db),
):
    """Looks up decision-makers at the lead's domain with Hunter (one search) and stores them masked."""
    service = ContactService(db)
    contacts, created = await service.discover_contacts(lead_id=lead_id, org_id=current_user.org_id)
    await AuditService(db).log_action(
        action="contact.discover",
        entity_type="lead",
        entity_id=lead_id,
        changes={"created": created},
        org_id=current_user.org_id,
        actor_user_id=current_user.id,
    )
    if created:
        message = f"Found {created} new {'person' if created == 1 else 'people'}."
    elif contacts:
        message = "No new people found. The ones already listed are all Hunter has."
    else:
        message = "Hunter.io didn't find any people at this domain."
    return ContactDiscoverResponse(
        contacts=[ContactResponse.model_validate(c) for c in contacts],
        created=created,
        message=message,
    )
