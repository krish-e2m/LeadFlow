from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.providers.hunter import HunterAdapter, parse_location_for_hunter
from app.providers.manager import provider_manager


@pytest.mark.asyncio
async def test_hunter_unconfigured_behavior():
    """Verify adapter gracefully handles unconfigured state without throwing exceptions."""
    adapter = HunterAdapter()
    adapter.api_key = ""

    assert not adapter.is_configured()
    status = await adapter.check_health()
    assert not status.is_configured
    assert not status.is_healthy
    assert "not configured" in status.status_message.lower()

    # Graceful degradation
    enrich = await adapter.enrich_organization("example.com")
    assert enrich is None

    contacts = await adapter.search_contacts_for_lead("example.com")
    assert contacts == []


@pytest.mark.asyncio
async def test_hunter_health_check_success():
    """Verify health check successfully parses Hunter /account response."""
    adapter = HunterAdapter()
    adapter.api_key = "test_hunter_key_123"

    mock_resp = {
        "data": {
            "first_name": "Test",
            "last_name": "User",
            "email": "test@leadflow.local",
            "plan_name": "Free",
            "requests": {
                "searches": {"used": 5, "available": 25},
                "verifications": {"used": 2, "available": 50},
            },
        }
    }

    mock_http_response = httpx.Response(
        status_code=200,
        json=mock_resp,
        request=httpx.Request("GET", "https://api.hunter.io/v2/account"),
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_http_response
        status = await adapter.check_health()

        assert status.is_configured
        assert status.is_healthy
        assert "Free" in status.status_message
        assert "5/25" in status.status_message


@pytest.mark.asyncio
async def test_hunter_enrich_organization():
    """Verify company enrichment parses domain-search response."""
    adapter = HunterAdapter()
    adapter.api_key = "test_hunter_key_123"

    mock_resp = {
        "data": {
            "domain": "stripe.com",
            "organization": "Stripe",
            "industry": "Financial Services",
            "country": "US",
            "city": "South San Francisco",
            "state": "California",
            "linkedin": "https://www.linkedin.com/company/stripe",
            "twitter": "stripe",
            "technologies": [{"name": "react"}, {"name": "aws"}],
        }
    }

    mock_http_response = httpx.Response(
        status_code=200,
        json=mock_resp,
        request=httpx.Request("GET", "https://api.hunter.io/v2/domain-search"),
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_http_response
        enrichment = await adapter.enrich_organization("stripe.com")

        assert enrichment is not None
        assert enrichment["company_name"] == "Stripe"
        assert enrichment["domain"] == "stripe.com"
        assert enrichment["industry"] == "Financial Services"
        assert enrichment["country"] == "US"
        assert "react" in enrichment["technologies"]


@pytest.mark.asyncio
async def test_hunter_search_contacts_masked():
    """Verify contact discovery masks emails until explicit reveal."""
    adapter = HunterAdapter()
    adapter.api_key = "test_hunter_key_123"

    mock_resp = {
        "data": {
            "domain": "stripe.com",
            "emails": [
                {
                    "value": "patrick@stripe.com",
                    "first_name": "Patrick",
                    "last_name": "Collison",
                    "position": "CEO",
                    "linkedin": "https://www.linkedin.com/in/patrickcollison",
                    "phone_number": "+14155551234",
                    "confidence": 98,
                }
            ],
        }
    }

    mock_http_response = httpx.Response(
        status_code=200,
        json=mock_resp,
        request=httpx.Request("GET", "https://api.hunter.io/v2/domain-search"),
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_http_response
        contacts = await adapter.search_contacts_for_lead("stripe.com")

        assert len(contacts) == 1
        contact = contacts[0]
        assert contact["first_name"] == "Patrick"
        assert contact["last_name"] == "Collison"
        assert contact["title"] == "CEO"
        assert contact["email"] == "p***@stripe.com"
        assert not contact["is_revealed"]


@pytest.mark.asyncio
async def test_hunter_reveal_contact_details():
    """Verify contact reveal unmasks direct email and phone."""
    adapter = HunterAdapter()
    adapter.api_key = "test_hunter_key_123"

    finder_resp = {
        "data": {
            "first_name": "Patrick",
            "last_name": "Collison",
            "email": "patrick@stripe.com",
            "score": 98,
            "phone_number": "+14155551234",
        }
    }

    verifier_resp = {
        "data": {
            "result": "deliverable",
            "score": 98,
            "email": "patrick@stripe.com",
        }
    }

    mock_finder_http = httpx.Response(
        status_code=200,
        json=finder_resp,
        request=httpx.Request("GET", "https://api.hunter.io/v2/email-finder"),
    )
    mock_verifier_http = httpx.Response(
        status_code=200,
        json=verifier_resp,
        request=httpx.Request("GET", "https://api.hunter.io/v2/email-verifier"),
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = [mock_finder_http, mock_verifier_http]
        revealed = await adapter.reveal_contact_details(
            domain="stripe.com",
            first_name="Patrick",
            last_name="Collison",
        )

        assert revealed["email"] == "patrick@stripe.com"
        assert revealed["phone"] == "+14155551234"
        assert revealed["verification_status"] == "deliverable"
        assert revealed["provider"] == "hunter"


def test_hunter_registered_in_provider_manager():
    """Verify hunter adapter is registered in the global ProviderManager."""
    assert "hunter" in provider_manager._adapters
    assert provider_manager.hunter is not None
    assert provider_manager.hunter.name == "hunter"


@pytest.mark.asyncio
async def test_hunter_health_check_restricted_account():
    """Verify health check marks is_healthy=False when account is restricted."""
    adapter = HunterAdapter()
    adapter.api_key = "test_hunter_key_123"

    mock_acc_resp = httpx.Response(
        status_code=200,
        json={"data": {"plan_name": "Free", "requests": {"searches": {"used": 0, "available": 50}}}},
        request=httpx.Request("GET", "https://api.hunter.io/v2/account"),
    )
    mock_probe_resp = httpx.Response(
        status_code=429,
        json={"errors": [{"id": "restricted_account", "code": 429, "details": "restricted"}]},
        request=httpx.Request("GET", "https://api.hunter.io/v2/domain-search"),
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = [mock_acc_resp, mock_probe_resp]
        status = await adapter.check_health()

        assert status.is_configured
        assert not status.is_healthy
        assert "restricted" in status.status_message.lower()


def test_parse_location_for_hunter():
    """Verify location parser maps country codes and preserves cities without false USA fallbacks."""
    # Country ISO mapping
    assert parse_location_for_hunter("United States") == {"country": "US"}
    assert parse_location_for_hunter("India") == {"country": "IN"}
    assert parse_location_for_hunter("United Kingdom") == {"country": "GB"}

    # Known Indian cities - must NOT map to United States
    v_loc = parse_location_for_hunter("Vadodara")
    assert v_loc["city"] == "Vadodara"
    assert v_loc["country"] == "IN"

    ah_loc = parse_location_for_hunter("Ahmedabad, Gujarat, India")
    assert ah_loc["city"] == "Ahmedabad"
    assert ah_loc["country"] == "IN"

    # Known US cities
    sf_loc = parse_location_for_hunter("San Francisco, CA")
    assert sf_loc["city"] == "San Francisco"
    assert sf_loc["country"] == "US"

    # Unknown city: must keep city name and NOT invent US country code
    unk_loc = parse_location_for_hunter("SomeUnlistedCity")
    assert unk_loc["city"] == "SomeUnlistedCity"
    assert "country" not in unk_loc or unk_loc["country"] != "US"


@pytest.mark.asyncio
async def test_hunter_discover_companies_request_mapping():
    """Verify Hunter Discover translates ICP criteria into POST /discover payload."""
    adapter = HunterAdapter()
    adapter.api_key = "test_hunter_key_123"

    criteria = {
        "locations": ["Ahmedabad, Gujarat, India"],
        "verticals": ["Computer Software", "FinTech"],
        "exclude_verticals": ["Gambling"],
        "employee_ranges": ["11-50", "51-200"],
        "keywords": ["AI", "Cloud"],
        "technologies": ["React", "Python"],
        "query": "Software development firms",
    }

    captured_json = {}
    captured_headers = {}

    async def mock_discover_post(url, headers, json):
        nonlocal captured_json, captured_headers
        captured_json = json
        captured_headers = headers
        return httpx.Response(
            status_code=200,
            json={
                "data": {
                    "companies": [
                        {
                            "name": "CloudCo India",
                            "domain": "cloudco.in",
                            "industry": "Computer Software",
                            "headquarters_location": {
                                "city": "Ahmedabad",
                                "state": "Gujarat",
                                "country": "IN",
                            },
                            "headcount": "11-50",
                            "technologies": ["React", "Python"],
                            "linkedin_url": "https://linkedin.com/company/cloudco",
                            "description": "Enterprise cloud systems",
                            "year_founded": 2018,
                            "job_openings": 2,
                        }
                    ],
                    "total": 1,
                },
                "meta": {"results": 1, "limit": 25, "page": 1},
            },
            request=httpx.Request("POST", "https://api.hunter.io/v2/discover"),
        )

    with patch("httpx.AsyncClient.post", side_effect=mock_discover_post):
        res = await adapter.discover_companies(criteria, limit=25)
        assert res["total"] == 1
        assert len(res["organizations"]) == 1
        org = res["organizations"][0]
        assert org["company_name"] == "CloudCo India"
        assert org["domain"] == "cloudco.in"
        assert org["city"] == "Ahmedabad"
        assert org["country"] == "IN"
        assert org["hiring_intent"] is True

        # Verify translated parameters in request
        assert captured_headers["X-API-KEY"] == "test_hunter_key_123"
        filters = captured_json["filters"]
        assert filters["headquarters_location"]["city"] == "Ahmedabad"
        assert filters["headquarters_location"]["country"] == "IN"
        assert filters["industry"]["include"] == ["Computer Software", "FinTech"]
        assert filters["industry"]["exclude"] == ["Gambling"]
        assert filters["headcount"] == ["11-50", "51-200"]
        assert filters["keywords"]["include"] == ["AI", "Cloud"]
        assert filters["technologies"] == ["React", "Python"]
        assert captured_json["query"] == "Software development firms"


@pytest.mark.asyncio
async def test_hunter_discover_companies_data_list_format():
    """Verify Hunter Discover parses real Hunter.io API format where 'data' is a list of companies."""
    adapter = HunterAdapter()
    adapter.api_key = "test_hunter_key_123"

    mock_resp = httpx.Response(
        status_code=200,
        json={
            "data": [
                {
                    "domain": "amazon.com",
                    "organization": "Amazon",
                    "emails_count": {"personal": 361943, "generic": 3104, "total": 365047},
                },
                {
                    "domain": "cisco.com",
                    "organization": "Cisco",
                    "emails_count": {"personal": 94479, "generic": 2160, "total": 96639},
                },
            ],
            "meta": {"results": 527149, "limit": 2, "offset": 0},
        },
        request=httpx.Request("POST", "https://api.hunter.io/v2/discover"),
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        res = await adapter.discover_companies({"query": "software"}, limit=2)
        assert res["total"] == 527149
        assert len(res["organizations"]) == 2
        assert res["organizations"][0]["company_name"] == "Amazon"
        assert res["organizations"][0]["domain"] == "amazon.com"
        assert res["organizations"][1]["company_name"] == "Cisco"
        assert res["organizations"][1]["domain"] == "cisco.com"


@pytest.mark.asyncio

async def test_hunter_discover_plan_restricted_raises_error():
    """Verify Hunter Discover raises truthful error on plan restrictions (HTTP 403)."""
    adapter = HunterAdapter()
    adapter.api_key = "test_hunter_key_123"

    mock_resp = httpx.Response(
        status_code=403,
        json={"errors": [{"id": "restricted_account", "code": 403, "details": "Discover endpoint restricted on Free plan"}]},
        request=httpx.Request("POST", "https://api.hunter.io/v2/discover"),
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        with pytest.raises(RuntimeError) as exc_info:
            await adapter.discover_companies({"locations": ["India"]})

        assert "restricted" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_hunter_company_find_enrichment_and_fallback():
    """Verify company enrichment uses GET /companies/find and falls back to /domain-search."""
    adapter = HunterAdapter()
    adapter.api_key = "test_hunter_key_123"

    mock_company_resp = httpx.Response(
        status_code=200,
        json={
            "data": {
                "name": "Stripe",
                "legal_name": "Stripe, Inc.",
                "domain": "stripe.com",
                "industry": "Financial Services",
                "sector": "Information Technology",
                "description": "Financial infrastructure for the internet",
                "tags": ["FinTech", "SaaS"],
                "employees_count": 8000,
                "location": {"city": "South San Francisco", "state": "CA", "country": "US"},
                "phone_number": "+18889262289",
                "technologies": ["AWS", "Ruby"],
                "year_founded": 2010,
                "funding": {"total_raised": 8700000000},
            }
        },
        request=httpx.Request("GET", "https://api.hunter.io/v2/companies/find"),
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_company_resp
        enrichment = await adapter.enrich_company("stripe.com")

        assert enrichment is not None
        assert enrichment["company_name"] == "Stripe"
        assert enrichment["legal_name"] == "Stripe, Inc."
        assert enrichment["employee_count"] == 8000
        assert enrichment["country"] == "US"
        assert enrichment["year_founded"] == 2010
        assert "AWS" in enrichment["technologies"]
        assert enrichment["provider"] == "hunter_company_find"


@pytest.mark.asyncio
async def test_hunter_email_finder_and_verifier():
    """Verify Email Finder and Verifier endpoints."""
    adapter = HunterAdapter()
    adapter.api_key = "test_hunter_key_123"

    finder_resp = httpx.Response(
        status_code=200,
        json={
            "data": {
                "first_name": "John",
                "last_name": "Doe",
                "email": "john@example.com",
                "score": 95,
                "position": "CTO",
                "phone_number": "+1234567890",
            }
        },
        request=httpx.Request("GET", "https://api.hunter.io/v2/email-finder"),
    )
    verifier_resp = httpx.Response(
        status_code=200,
        json={
            "data": {
                "result": "deliverable",
                "score": 95,
                "email": "john@example.com",
                "status": "valid",
            }
        },
        request=httpx.Request("GET", "https://api.hunter.io/v2/email-verifier"),
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = finder_resp
        found = await adapter.find_email("example.com", first_name="John", last_name="Doe")
        assert found["email"] == "john@example.com"
        assert found["score"] == 95

        mock_get.return_value = verifier_resp
        verified = await adapter.verify_email("john@example.com")
        assert verified["result"] == "deliverable"
        assert verified["score"] == 95


@pytest.mark.asyncio
async def test_hunter_person_and_combined_enrichment():
    """Verify Person and Combined Enrichment endpoints."""
    adapter = HunterAdapter()
    adapter.api_key = "test_hunter_key_123"

    person_resp = httpx.Response(
        status_code=200,
        json={
            "data": {
                "first_name": "Dustin",
                "last_name": "Moskovitz",
                "position": "CEO",
                "company": {"name": "Asana", "domain": "asana.com"},
                "location": {"city": "San Francisco", "country": "US"},
            }
        },
        request=httpx.Request("GET", "https://api.hunter.io/v2/people/find"),
    )

    combined_resp = httpx.Response(
        status_code=200,
        json={
            "data": {
                "person": {"first_name": "Dustin"},
                "company": {"name": "Asana"},
            }
        },
        request=httpx.Request("GET", "https://api.hunter.io/v2/combined/find"),
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = person_resp
        person = await adapter.enrich_person("dustin@asana.com")
        assert person["company_name"] == "Asana"
        assert person["job_title"] == "CEO"

        mock_get.return_value = combined_resp
        combined = await adapter.enrich_combined("dustin@asana.com")
        assert "person" in combined
        assert "company" in combined


@pytest.mark.asyncio
async def test_hunter_domain_finder():
    """Verify Domain Finder resolves domain from company name."""
    adapter = HunterAdapter()
    adapter.api_key = "test_hunter_key_123"

    mock_resp = httpx.Response(
        status_code=200,
        json={"data": {"domain": "stripe.com"}},
        request=httpx.Request("GET", "https://api.hunter.io/v2/companies/find"),
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        domain = await adapter.find_domain_for_company("Stripe")
        assert domain == "stripe.com"


@pytest.mark.asyncio
async def test_hunter_get_usage():
    """Verify usage retrieval parses requests and calls."""
    adapter = HunterAdapter()
    adapter.api_key = "test_hunter_key_123"

    mock_resp = httpx.Response(
        status_code=200,
        json={
            "data": {
                "plan_name": "Starter",
                "plan_level": 1,
                "reset_date": "2026-11-01",
                "requests": {"searches": {"used": 10, "available": 500}},
            }
        },
        request=httpx.Request("GET", "https://api.hunter.io/v2/account"),
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        usage = await adapter.get_usage()
        assert usage["plan_name"] == "Starter"
        assert usage["reset_date"] == "2026-11-01"
        assert usage["requests"]["searches"]["used"] == 10


def test_apollo_completely_absent_from_provider_manager():
    """Verify Apollo has been completely excised from active provider registry."""
    assert "apollo" not in provider_manager._adapters
    assert not hasattr(provider_manager, "apollo")
    assert "hunter" in provider_manager._adapters

