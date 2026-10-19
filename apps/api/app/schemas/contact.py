import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, model_validator


class ContactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    lead_id: uuid.UUID
    first_name: Optional[str]
    last_name: Optional[str]
    title: Optional[str]
    linkedin_url: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    is_revealed: bool
    revealed_at: Optional[datetime]
    created_at: datetime

    @model_validator(mode="after")
    def mask_unrevealed_pii(self) -> "ContactResponse":
        if not self.is_revealed:
            # Phone number is strictly redacted before explicit reveal
            self.phone = None
            # Email is masked (e.g. b***@domain.com) before explicit reveal
            if self.email:
                if "***" not in self.email and "@" in self.email:
                    prefix, domain = self.email.split("@", 1)
                    self.email = f"{prefix[:1]}***@{domain}"
                elif "***" not in self.email:
                    self.email = "***"
        return self


class ContactRevealRequest(BaseModel):
    confirm_credit_spend: bool = True


class ContactRevealResponse(BaseModel):
    contact: ContactResponse
    credits_remaining: Optional[int] = None
    message: str
    # Company-level reveal only: the top contact was already revealed, so nothing was spent.
    already_revealed: bool = False
    # Company-level reveal only: people found with Hunter because none were stored yet.
    contacts_discovered: int = 0


class ContactDiscoverResponse(BaseModel):
    contacts: List[ContactResponse]
    created: int
    message: str
