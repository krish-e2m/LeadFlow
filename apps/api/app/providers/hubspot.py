import asyncio
import html
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Set

import httpx

from app.core.config import settings
from app.core.logging import logger
from app.providers.base import BaseProviderAdapter, ProviderStatus

HUBSPOT_BASE_URL = "https://api.hubapi.com"

# HubSpot-defined association type ids (default labels) used for notes.
NOTE_TO_CONTACT = 202
NOTE_TO_COMPANY = 190

# Free-plan rules this adapter follows:
#  * Standard CRM objects and properties only (contacts, companies, notes). No custom properties,
#    custom objects, deals, workflows or sequences, which need a paid tier.
#  * One private-app token. Free/Starter private apps allow 100 requests per 10 seconds and
#    250,000 per day, so a sync spends at most ~7 requests and a 429 is retried once.
#  * Existing CRM data is never overwritten: only empty properties are filled in.
COMPANY_PROPERTIES = ["name", "domain", "city", "country", "numberofemployees"]
CONTACT_PROPERTIES = ["email", "firstname", "lastname", "jobtitle"]
MAX_RETRY_AFTER_SECONDS = 10
SEARCH_IN_LIMIT = 100  # HubSpot accepts at most 100 values in an IN filter


class HubSpotError(RuntimeError):
    """A HubSpot API call failed. `status_code` is None for transport errors."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


def normalize_domain(value: str) -> str:
    """Lower-cases and strips scheme, path and a leading www so domains match HubSpot's `domain` property."""
    clean = (value or "").strip().lower()
    for prefix in ("https://", "http://"):
        if clean.startswith(prefix):
            clean = clean[len(prefix):]
    clean = clean.split("/")[0].split(":")[0]
    return clean[4:] if clean.startswith("www.") else clean


def record_url(portal_id: str, object_type_id: str, record_id: Optional[str]) -> Optional[str]:
    """Deep link to a HubSpot record (contacts are 0-1, companies are 0-2). None when the portal is unknown."""
    if not portal_id or not record_id:
        return None
    return f"https://app.hubspot.com/contacts/{portal_id.strip()}/record/{object_type_id}/{record_id}"


class HubSpotAdapter(BaseProviderAdapter):
    """
    HubSpot CRM API adapter (free-plan compatible) for idempotent company and contact upsert
    and for logging the approved outreach draft as a note on the records.

    Private app scopes needed: crm.objects.contacts.read/write and crm.objects.companies.read/write.
    """

    def __init__(self):
        super().__init__("hubspot")
        self.access_token = settings.HUBSPOT_ACCESS_TOKEN
        self.portal_id = settings.HUBSPOT_PORTAL_ID
        self.enabled = settings.HUBSPOT_ENABLED
        self.base_url = HUBSPOT_BASE_URL

    def is_configured(self) -> bool:
        return bool(self.enabled and self.access_token and len(self.access_token.strip()) > 0)

    @property
    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"}

    def _redact(self, text: str) -> str:
        return text.replace(self.access_token, "[REDACTED]") if self.access_token else text

    @staticmethod
    def _error_detail(resp: httpx.Response) -> str:
        try:
            body = resp.json()
            return str(body.get("message") or body.get("error") or body)[:300]
        except Exception:
            return resp.text[:300]

    async def _request(self, client: httpx.AsyncClient, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """
        Sends one API request. A 429 is retried once after the advertised delay; every other
        non-2xx answer raises HubSpotError, so a failed call can never be mistaken for success.
        """
        url = f"{self.base_url}{path}"
        for attempt in (1, 2):
            try:
                resp = await client.request(method, url, headers=self._headers, **kwargs)
            except httpx.HTTPError as exc:
                raise HubSpotError(f"HubSpot request failed: {self._redact(str(exc)) or type(exc).__name__}") from exc

            if resp.status_code == 429 and attempt == 1:
                delay = min(float(resp.headers.get("Retry-After", "1") or 1), MAX_RETRY_AFTER_SECONDS)
                logger.warning(f"HubSpot rate limit hit on {path}; retrying in {delay:.1f}s")
                await asyncio.sleep(delay)
                continue
            break

        if resp.status_code >= 400:
            detail = self._redact(self._error_detail(resp))
            hint = ""
            if resp.status_code == 401:
                hint = " (the access token is invalid or expired)"
            elif resp.status_code == 403:
                hint = " (the private app is missing a required scope)"
            elif resp.status_code == 429:
                hint = " (rate limit still exceeded)"
            raise HubSpotError(f"HubSpot HTTP {resp.status_code}{hint}: {detail}", resp.status_code)
        return resp

    async def check_health(self) -> ProviderStatus:
        if not self.is_configured():
            return ProviderStatus(
                name=self.name,
                is_configured=False,
                is_healthy=False,
                status_message="HubSpot access token not configured or integration disabled.",
                last_checked=datetime.now(timezone.utc),
            )
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                await self._request(client, "GET", "/crm/v3/objects/contacts", params={"limit": 1})
                companies = await self._request(client, "GET", "/crm/v3/objects/companies", params={"limit": 1})
            portal = f" (portal {self.portal_id})" if self.portal_id else ""
            return ProviderStatus(
                name=self.name,
                is_configured=True,
                is_healthy=companies.status_code == 200,
                status_message=f"Connected to HubSpot CRM{portal}",
                last_checked=datetime.now(timezone.utc),
            )
        except HubSpotError as exc:
            return ProviderStatus(
                name=self.name,
                is_configured=True,
                is_healthy=False,
                status_message=str(exc),
                last_checked=datetime.now(timezone.utc),
            )

    # ------------------------------------------------------------------ lookups

    async def find_existing_company_domains(self, domains: Iterable[str]) -> Set[str]:
        """Returns the subset of `domains` that already exist as HubSpot companies (one request per 100 domains)."""
        wanted = sorted({normalize_domain(d) for d in domains if d})
        found: Set[str] = set()
        if not self.is_configured() or not wanted:
            return found

        async with httpx.AsyncClient(timeout=15.0) as client:
            for start in range(0, len(wanted), SEARCH_IN_LIMIT):
                chunk = wanted[start : start + SEARCH_IN_LIMIT]
                resp = await self._request(
                    client,
                    "POST",
                    "/crm/v3/objects/companies/search",
                    json={
                        "filterGroups": [{"filters": [{"propertyName": "domain", "operator": "IN", "values": chunk}]}],
                        "properties": ["domain"],
                        "limit": 100,
                    },
                )
                for row in resp.json().get("results", []):
                    domain = normalize_domain((row.get("properties") or {}).get("domain") or "")
                    if domain:
                        found.add(domain)
        return found

    async def _search_one(
        self, client: httpx.AsyncClient, object_type: str, prop: str, value: str, properties: List[str]
    ) -> Optional[Dict[str, Any]]:
        resp = await self._request(
            client,
            "POST",
            f"/crm/v3/objects/{object_type}/search",
            json={
                "filterGroups": [{"filters": [{"propertyName": prop, "operator": "EQ", "value": value}]}],
                "properties": properties,
                "limit": 1,
            },
        )
        results = resp.json().get("results", [])
        return results[0] if results else None

    @staticmethod
    def _blank_fields(existing: Dict[str, Any], desired: Dict[str, Any]) -> Dict[str, Any]:
        """Only the desired values whose HubSpot property is currently empty. Never overwrites CRM data."""
        current = existing.get("properties") or {}
        return {k: v for k, v in desired.items() if v not in (None, "") and not current.get(k)}

    # ------------------------------------------------------------------ upserts

    async def _upsert_company(
        self, client: httpx.AsyncClient, name: str, domain: str, extra: Dict[str, Any]
    ) -> Dict[str, Any]:
        desired = {"name": name, "domain": domain, **extra}
        existing = await self._search_one(client, "companies", "domain", domain, COMPANY_PROPERTIES)
        if existing:
            patch = self._blank_fields(existing, desired)
            if patch:
                await self._request(client, "PATCH", f"/crm/v3/objects/companies/{existing['id']}", json={"properties": patch})
            return {"id": existing["id"], "created": False}

        resp = await self._request(
            client,
            "POST",
            "/crm/v3/objects/companies",
            json={"properties": {k: v for k, v in desired.items() if v not in (None, "")}},
        )
        return {"id": resp.json()["id"], "created": True}

    async def _upsert_contact(self, client: httpx.AsyncClient, email: str, desired: Dict[str, Any]) -> Dict[str, Any]:
        email = email.strip().lower()
        existing = await self._search_one(client, "contacts", "email", email, CONTACT_PROPERTIES)
        if existing:
            patch = self._blank_fields(existing, desired)
            if patch:
                await self._request(client, "PATCH", f"/crm/v3/objects/contacts/{existing['id']}", json={"properties": patch})
            return {"id": existing["id"], "created": False}

        try:
            resp = await self._request(
                client,
                "POST",
                "/crm/v3/objects/contacts",
                json={"properties": {"email": email, **{k: v for k, v in desired.items() if v not in (None, "")}}},
            )
        except HubSpotError as exc:
            if exc.status_code != 409:
                raise
            # Created by someone else between our search and create: use that record.
            existing = await self._search_one(client, "contacts", "email", email, CONTACT_PROPERTIES)
            if not existing:
                raise
            return {"id": existing["id"], "created": False}
        return {"id": resp.json()["id"], "created": True}

    @staticmethod
    def build_note_body(draft_subject: Optional[str], draft_body: str, context_lines: Optional[List[str]]) -> str:
        """HTML note body. Every LeadFlow-supplied string is escaped, so draft text can never inject markup."""
        parts = [f"<b>LeadFlow approved draft: {html.escape(draft_subject or 'Outreach')}</b>"]
        if context_lines:
            parts.append("<br/>".join(html.escape(line) for line in context_lines))
        parts.append(html.escape(draft_body).replace("\n", "<br/>"))
        return "<br/><br/>".join(parts)

    async def sync_prospect(
        self,
        company_name: str,
        domain: str,
        contact_email: Optional[str],
        contact_first_name: Optional[str],
        contact_last_name: Optional[str],
        contact_title: Optional[str],
        draft_subject: Optional[str],
        draft_body: Optional[str],
        company_city: Optional[str] = None,
        company_country: Optional[str] = None,
        company_employees: Optional[int] = None,
        note_context: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Idempotently pushes the company (matched by domain) and, when an email is revealed, the
        contact (matched by email) to HubSpot, associates them, and logs the approved draft as a note.
        Raises HubSpotError if any step fails.
        """
        if not self.is_configured():
            raise RuntimeError("HubSpot CRM integration is disabled or access token is missing.")

        clean_domain = normalize_domain(domain)
        company_extra: Dict[str, Any] = {
            "city": company_city,
            "country": company_country,
            "numberofemployees": company_employees,
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            company = await self._upsert_company(client, company_name, clean_domain, company_extra)

            contact: Optional[Dict[str, Any]] = None
            if contact_email:
                contact = await self._upsert_contact(
                    client,
                    contact_email,
                    {"firstname": contact_first_name, "lastname": contact_last_name, "jobtitle": contact_title},
                )
                # Default (unlabeled) contact-to-company association; idempotent on HubSpot's side.
                await self._request(
                    client,
                    "PUT",
                    f"/crm/v4/objects/contacts/{contact['id']}/associations/default/companies/{company['id']}",
                )

            engagement_id: Optional[str] = None
            if draft_body:
                associations = [
                    {
                        "to": {"id": company["id"]},
                        "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": NOTE_TO_COMPANY}],
                    }
                ]
                if contact:
                    associations.append(
                        {
                            "to": {"id": contact["id"]},
                            "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": NOTE_TO_CONTACT}],
                        }
                    )
                note = await self._request(
                    client,
                    "POST",
                    "/crm/v3/objects/notes",
                    json={
                        "properties": {
                            "hs_timestamp": datetime.now(timezone.utc).isoformat(),
                            "hs_note_body": self.build_note_body(draft_subject, draft_body, note_context),
                        },
                        "associations": associations,
                    },
                )
                engagement_id = note.json().get("id")

        return {
            "crm_company_id": company["id"],
            "crm_contact_id": contact["id"] if contact else None,
            "crm_engagement_id": engagement_id,
            "company_created": company["created"],
            "contact_created": contact["created"] if contact else False,
            "company_url": record_url(self.portal_id, "0-2", company["id"]),
            "contact_url": record_url(self.portal_id, "0-1", contact["id"]) if contact else None,
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }
