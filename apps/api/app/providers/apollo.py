"""
DEPRECATED: Apollo.io provider adapter has been retired and deactivated.
All active company discovery, contact reveals, and organization enrichment have migrated to Hunter.io.
This module is retained strictly as an inactive stub to prevent import crashes and raises RuntimeError if invoked.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.providers.base import BaseProviderAdapter, ProviderStatus


class ApolloAdapter(BaseProviderAdapter):
    """Deprecated: Apollo is no longer an active provider in LeadFlow."""

    def __init__(self):
        super().__init__("apollo")

    def is_configured(self) -> bool:
        return False

    async def check_health(self) -> ProviderStatus:
        return ProviderStatus(
            name=self.name,
            is_configured=False,
            is_healthy=False,
            status_message="Apollo provider is retired and disabled. Migrated to Hunter.io.",
            last_checked=datetime.now(timezone.utc),
        )

    async def enrich_organization(self, domain: str) -> Optional[Dict[str, Any]]:
        raise RuntimeError("Apollo is deprecated and disabled. Use HunterAdapter.enrich_company instead.")

    async def search_organizations(
        self, filters: Dict[str, Any], limit: int = 25, page: int = 1
    ) -> Dict[str, Any]:
        raise RuntimeError("Apollo is deprecated and disabled. Use HunterAdapter.discover_companies instead.")

    async def search_contacts_for_lead(
        self, domain: str, titles: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        raise RuntimeError("Apollo is deprecated and disabled. Use HunterAdapter.search_contacts_for_lead instead.")

    async def reveal_contact_details(self, apollo_person_id: str) -> Dict[str, Any]:
        raise RuntimeError("Apollo is deprecated and disabled. Use HunterAdapter.reveal_contact_details instead.")
