from datetime import datetime, timezone

from app.core.config import settings
from app.providers.base import BaseProviderAdapter, ProviderStatus


class SuperMemoryAdapter(BaseProviderAdapter):
    """Optional SuperMemory integration for long-term account and domain memory context."""

    def __init__(self):
        super().__init__("supermemory")
        self.api_key = settings.SUPERMEMORY_API_KEY
        self.enabled = settings.SUPERMEMORY_ENABLED

    def is_configured(self) -> bool:
        return bool(self.enabled and self.api_key and len(self.api_key.strip()) > 0)

    async def check_health(self) -> ProviderStatus:
        if not self.is_configured():
            return ProviderStatus(
                name=self.name,
                is_configured=False,
                is_healthy=False,
                status_message="SuperMemory optional provider is disabled or unconfigured.",
                last_checked=datetime.now(timezone.utc),
            )
        return ProviderStatus(
            name=self.name,
            is_configured=True,
            is_healthy=True,
            status_message="SuperMemory configured and ready.",
            last_checked=datetime.now(timezone.utc),
        )
