# LeadFlow REST API Documentation

## 1. Overview & Authentication

All API endpoints reside under `/api/v1`. Communication is strictly JSON over HTTPS.

### Authentication
Include the JWT Bearer token in the `Authorization` header:
```http
Authorization: Bearer <jwt_access_token>
```
The token contains the user's `sub` (User ID), `org_id` (Organization ID), and `role` (`super_admin`, `org_admin`, or `client_viewer`).

---

## 2. Asynchronous Job & HTTP 202 Contract

Heavy operations (Discovery, Bulk Enrichment, Batch Scoring, CRM Sync) execute asynchronously via ARQ.

### Initiating a Search Job
`POST /api/v1/searches`

**Request:**
```json
{
  "name": "B2B SaaS Q4 Discovery",
  "audience_id": "a1b2c3d4-0000-0000-0000-000000000000",
  "limit": 50,
  "filters": {
    "locations": ["United States"],
    "industries": ["Computer Software", "Internet"],
    "min_employees": 20
  }
}
```

**Response: `202 Accepted`**
```json
{
  "run_id": "9f8e7d6c-1111-2222-3333-444455556666",
  "status": "pending",
  "message": "Search job accepted and enqueued.",
  "poll_url": "/api/v1/runs/9f8e7d6c-1111-2222-3333-444455556666"
}
```

### Polling Run Progress
`GET /api/v1/runs/{run_id}`

**Response: `200 OK`**
```json
{
  "id": "9f8e7d6c-1111-2222-3333-444455556666",
  "run_type": "search",
  "status": "running",
  "progress_pct": 65,
  "items_total": 50,
  "items_processed": 32,
  "items_succeeded": 30,
  "items_failed": 2,
  "started_at": "2026-10-12T10:00:00Z",
  "completed_at": null
}
```

---

## 3. Core Endpoint Catalog

### Authentication & Account
- `POST /api/v1/auth/login`: Exchange email + password for access and refresh tokens.
- `POST /api/v1/auth/refresh`: Refresh expired access token.
- `POST /api/v1/auth/forgot-password`: Trigger Resend password recovery email.
- `POST /api/v1/auth/reset-password`: Complete password reset with one-time token.

### Leads & Pipeline
- `GET /api/v1/leads`: Paginated list of leads with score band, pipeline status, and approval status filters.
- `GET /api/v1/leads/{id}`: Detailed view of a single lead including score breakdown, enrichments, contacts, and drafts.
- `PATCH /api/v1/leads/{id}/approval`: **Human Approval Gate** - set approval to `approved` or `rejected`.
- `POST /api/v1/leads/{id}/rescore`: Re-run the 22-signal scoring engine against existing enrichment data.

### Contacts & Reveal Safety Gate
- `GET /api/v1/leads/{id}/contacts`: List contacts for a lead (unrevealed emails/phones are masked as `j***@domain.com`).
- `POST /api/v1/contacts/{id}/reveal`: Explicit human confirmation to spend credits and unmask contact details.

### AI Draft Studio
- `POST /api/v1/leads/{id}/drafts`: Generate customized outreach draft using OpenRouter AI. **Enforces lead must be `approved` first**.
- `GET /api/v1/leads/{id}/drafts`: List generated drafts for a lead.
- `PATCH /api/v1/drafts/{id}/approval`: **Draft Approval Gate** - approve or reject draft outreach copy.

### CRM Sync (HubSpot)
- `POST /api/v1/leads/{id}/sync-crm`: Idempotently push lead and draft to HubSpot. **Enforces draft must be `approved` first**.
- `GET /api/v1/leads/{id}/sync-status`: Query HubSpot synchronization status and object IDs.

### ICP Audiences & Scoring Engines
- `GET /api/v1/audiences` & `POST /api/v1/audiences`: Manage ICP filter definitions.
- `GET /api/v1/engines` & `POST /api/v1/engines`: Manage scoring engine profiles.
- `POST /api/v1/engines/{id}/params`: Save a new versioned weights definition for the 22 signals.

### Administration & Super Admin
- `GET /api/v1/admin/orgs`: List all organizations (`super_admin` only).
- `POST /api/v1/admin/orgs`: Provision a new organization.
- `GET /api/v1/admin/providers`: Check configuration & connectivity of all 8 external providers.
- `GET /api/v1/admin/audit-logs`: Query global or tenant audit history.
- `GET /api/v1/admin/usage`: Review credit and API spend statistics.

---

## 4. Error Responses
Standard RFC 7807 problem details format:
```json
{
  "detail": "Lead must be approved by an operator before generating an outreach draft.",
  "error_code": "LEAD_NOT_APPROVED",
  "status_code": 400
}
```
