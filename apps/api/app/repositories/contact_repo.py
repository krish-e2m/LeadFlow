import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select

from app.models.contact import Contact
from app.repositories.base import BaseRepository


class ContactRepository(BaseRepository[Contact]):
    def __init__(self, session):
        super().__init__(Contact, session)

    async def list_by_lead(self, lead_id: uuid.UUID, org_id: uuid.UUID) -> List[Contact]:
        stmt = (
            select(Contact)
            .where(Contact.lead_id == lead_id, Contact.org_id == org_id)
            .order_by(Contact.created_at.desc())
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def mark_revealed(
        self,
        contact_id: uuid.UUID,
        org_id: uuid.UUID,
        revealed_by: uuid.UUID,
        unmasked_email: Optional[str] = None,
        unmasked_phone: Optional[str] = None,
    ) -> Optional[Contact]:
        contact = await self.get_by_id(contact_id, org_id=org_id)
        if not contact:
            return None

        contact.is_revealed = True
        contact.revealed_by = revealed_by
        contact.revealed_at = datetime.now(timezone.utc)
        if unmasked_email:
            contact.email = unmasked_email
        if unmasked_phone:
            contact.phone = unmasked_phone

        await self.session.flush()
        return contact
