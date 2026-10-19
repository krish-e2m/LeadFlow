import asyncio
from typing import Dict, List

from app.providers.base import BaseProviderAdapter, ProviderStatus
from app.providers.crawler import WebCrawlerAdapter
from app.providers.dataforseo import DataForSEOAdapter
from app.providers.firecrawl import FirecrawlAdapter
from app.providers.hubspot import HubSpotAdapter
from app.providers.hunter import HunterAdapter
from app.providers.openrouter import OpenRouterAdapter
from app.providers.pagespeed import PageSpeedAdapter
from app.providers.places import GooglePlacesAdapter
from app.providers.resend import ResendAdapter
from app.providers.serpapi import SerpApiAdapter
from app.providers.supermemory import SuperMemoryAdapter


class ProviderManager:
    """Central registry and health manager for all external provider integrations."""

    def __init__(self):
        self.crawler = WebCrawlerAdapter()
        self.pagespeed = PageSpeedAdapter()
        self.hunter = HunterAdapter()
        self.openrouter = OpenRouterAdapter()
        self.hubspot = HubSpotAdapter()
        self.places = GooglePlacesAdapter()
        self.dataforseo = DataForSEOAdapter()
        self.resend = ResendAdapter()
        self.supermemory = SuperMemoryAdapter()
        self.firecrawl = FirecrawlAdapter()
        self.serpapi = SerpApiAdapter()

        self._adapters: Dict[str, BaseProviderAdapter] = {
            "web_crawler": self.crawler,
            "google_pagespeed": self.pagespeed,
            "hunter": self.hunter,
            "openrouter": self.openrouter,
            "hubspot": self.hubspot,
            "google_places": self.places,
            "dataforseo": self.dataforseo,
            "resend": self.resend,
            "supermemory": self.supermemory,
            "firecrawl": self.firecrawl,
            "serpapi": self.serpapi,
        }

    async def get_all_provider_statuses(self) -> List[ProviderStatus]:
        """Runs health checks concurrently across all external adapters."""
        tasks = [adapter.check_health() for adapter in self._adapters.values()]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        statuses: List[ProviderStatus] = []
        for name, res in zip(self._adapters.keys(), results):
            if isinstance(res, Exception):
                statuses.append(
                    ProviderStatus(
                        name=name,
                        is_configured=self._adapters[name].is_configured(),
                        is_healthy=False,
                        status_message=f"Check exception: {str(res)}",
                    )
                )
            else:
                statuses.append(res)
        return statuses


provider_manager = ProviderManager()
