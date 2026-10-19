from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict


@dataclass
class ProviderStatus:
    name: str
    is_configured: bool
    is_healthy: bool
    status_message: str
    last_checked: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "is_configured": self.is_configured,
            "is_healthy": self.is_healthy,
            "status_message": self.status_message,
            "last_checked": self.last_checked.isoformat(),
        }


class BaseProviderAdapter(ABC):
    """Abstract base class for all third-party external integrations."""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def is_configured(self) -> bool:
        """Returns True if all required credentials and settings are present."""
        pass

    @abstractmethod
    async def check_health(self) -> ProviderStatus:
        """Performs a live connectivity and configuration check."""
        pass
