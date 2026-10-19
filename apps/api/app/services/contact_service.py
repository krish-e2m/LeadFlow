import uuid
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import ApprovalStatus
from app.core.logging import logger
from app.models.contact import Contact
from app.models.lead import Lead
from app.models.organization import Organization
from app.providers.manager import provider_manager
from app.repositories.contact_repo import ContactRepository
from app.services.quota_service import QuotaService

# Contacts stored per company when discovering people on demand.
DISCOVER_LIMIT = 5


def is_real_email(value: Optional[str]) -> bool:
    """True for a deliverable-looking address, False for masked placeholders such as j***@acme.com."""
    return bool(value and "@" in value and "*" not in value)


def display_name(contact: Contact) -> str:
    return " ".join(p for p in [contact.first_name, contact.last_name] if p) or "this contact"


class ContactService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.contact_repo = ContactRepository(session)

    async def _require_active_org(self, org_id: uuid.UUID) -> None:
        org_stmt = select(Organization).where(Organization.id == org_id, Organization.deleted_at.is_(None))
        org = (await self.session.execute(org_stmt)).scalars().first()
        if not org or not org.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Organization is inactive or suspended. Cannot reveal contact details.",
            )

    async def _get_lead(self, lead_id: uuid.UUID, org_id: uuid.UUID) -> Lead:
        lead_stmt = select(Lead).where(Lead.id == lead_id, Lead.org_id == org_id, Lead.deleted_at.is_(None))
        lead = (await self.session.execute(lead_stmt)).scalars().first()
        if not lead:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found.")
        return lead

    @staticmethod
    def _require_approved(lead: Lead) -> None:
        if lead.approval_status != ApprovalStatus.APPROVED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Workflow Policy Violation: Lead must be approved by an operator before revealing contact details.",
            )

    @staticmethod
    def _require_hunter() -> None:
        if not provider_manager.hunter.is_configured():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Contact lookup needs Hunter.io. Set HUNTER_API_KEY and HUNTER_ENABLED=true, then try again.",
            )

    async def _contacts_for_lead(self, lead_id: uuid.UUID, org_id: uuid.UUID) -> List[Contact]:
        stmt = (
            select(Contact)
            .where(Contact.lead_id == lead_id, Contact.org_id == org_id)
            .order_by(Contact.created_at.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def reveal_contact(
        self,
        contact_id: uuid.UUID,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Contact:
        """
        Gated action: reveals the verified work email (and phone when Hunter has one) for a contact.

        - The parent lead must be approved, and the daily reveal quota is reserved first.
        - If Hunter can't return a real email, the reservation is released and the contact stays
          masked, so a failed lookup never counts as a reveal.
        """
        await self._require_active_org(org_id)

        contact = await self.contact_repo.get_by_id(contact_id, org_id=org_id)
        if not contact:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found.")

        lead = await self._get_lead(contact.lead_id, org_id)
        self._require_approved(lead)

        if contact.is_revealed:
            return contact  # Already revealed: no second charge

        self._require_hunter()
        await QuotaService.check_and_reserve_contact_reveal(org_id, self.session)

        try:
            revealed = await provider_manager.hunter.reveal_contact_details(
                domain=lead.domain,
                first_name=contact.first_name,
                last_name=contact.last_name,
                email=contact.email,
            )
        except Exception as exc:
            await QuotaService.release_contact_reveal(org_id)
            logger.warning(f"Hunter reveal failed for contact {contact.id}: {exc}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Hunter.io couldn't complete the lookup for {display_name(contact)}. Nothing was revealed; try again shortly.",
            )

        email = revealed.get("email")
        if not is_real_email(email):
            await QuotaService.release_contact_reveal(org_id)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Hunter.io has no verified email for {display_name(contact)} at {lead.domain}. Nothing was revealed.",
            )

        contact.email = email
        if revealed.get("phone"):
            contact.phone = revealed["phone"]
        contact.is_revealed = True
        contact.revealed_by = user_id
        contact.revealed_at = datetime.now(timezone.utc)
        await self.session.flush()
        return contact

    async def discover_contacts(self, lead_id: uuid.UUID, org_id: uuid.UUID) -> Tuple[List[Contact], int]:
        """
        Finds decision-makers at the lead's domain with Hunter (one Hunter search) and stores the new
        ones masked. Returns all of the lead's contacts and how many were added.
        """
        await self._require_active_org(org_id)
        lead = await self._get_lead(lead_id, org_id)
        self._require_hunter()

        found = await provider_manager.hunter.search_contacts_for_lead(lead.domain, limit=DISCOVER_LIMIT)
        existing = await self._contacts_for_lead(lead.id, org_id)
        seen = {
            ((c.first_name or "").lower(), (c.last_name or "").lower()) if (c.first_name or c.last_name) else (c.email or "")
            for c in existing
        }

        created = 0
        for person in found:
            first, last = person.get("first_name"), person.get("last_name")
            key = ((first or "").lower(), (last or "").lower()) if (first or last) else (person.get("email") or "")
            if key in seen:
                continue
            seen.add(key)
            self.session.add(
                Contact(
                    org_id=org_id,
                    lead_id=lead.id,
                    first_name=first,
                    last_name=last,
                    title=person.get("title"),
                    linkedin_url=person.get("linkedin_url"),
                    email=person.get("email"),
                    is_revealed=False,
                )
            )
            created += 1

        await self.session.flush()
        return await self._contacts_for_lead(lead.id, org_id), created

    async def reveal_primary_contact(
        self, lead_id: uuid.UUID, org_id: uuid.UUID, user_id: uuid.UUID
    ) -> Tuple[Contact, bool, int]:
        """
        One-click company reveal: reveals the top contact at an approved lead. If no people are stored
        yet, they are discovered first. Returns (contact, already_revealed, contacts_discovered).
        """
        await self._require_active_org(org_id)
        lead = await self._get_lead(lead_id, org_id)
        self._require_approved(lead)

        contacts = await self._contacts_for_lead(lead.id, org_id)
        discovered = 0
        if not contacts:
            contacts, discovered = await self.discover_contacts(lead.id, org_id)
        if not contacts:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Hunter.io didn't find any people at {lead.domain}.",
            )

        target = next((c for c in contacts if not c.is_revealed), None)
        if target is None:
            return contacts[0], True, discovered

        return await self.reveal_contact(target.id, org_id, user_id), False, discovered
