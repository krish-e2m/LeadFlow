# LeadFlow Security & Multi-Tenancy Architecture

## 1. Multi-Tenant Isolation Model

LeadFlow utilizes a Defense-in-Depth multi-tenancy model to guarantee zero data leakage between organizations.

```text
Layer 1: JWT Claims Validation (Validates user identity and assigned org_id)
   |
Layer 2: FastAPI Dependency Injection (Injects validated tenant context into request)
   |
Layer 3: Repository Query Scoping (Automatically binds WHERE org_id = :org_id)
   |
Layer 4: PostgreSQL Row-Level Security (Enforced in database engine via SET LOCAL)
```

---

## 2. Role-Based Access Control (RBAC) Matrix

LeadFlow defines three discrete roles:
1. `super_admin`: Platform administrator with cross-tenant visibility, provider provisioning, and global system analytics.
2. `org_admin`: Organization manager with full read/write permissions within their tenant, team member management, and scoring engine configuration.
3. `client_viewer`: Restricted read-only stakeholder with access to approved leads and sanitized client portal summaries, with zero ability to mutate data or trigger credits.

### Permission Matrix

| Operation | `super_admin` | `org_admin` | `client_viewer` |
| :--- | :---: | :---: | :---: |
| **Manage Organizations & System** | Yes | No | No |
| **Manage Provider Credentials** | Yes | No | No |
| **View System Audit Logs** | All Orgs | Own Org | No |
| **Create/Edit Audiences (ICP)** | Yes | Yes | No |
| **Configure Scoring Engine Weights** | Yes | Yes | No |
| **Trigger Asynchronous Searches** | Yes | Yes | No |
| **View Leads & Scoring Breakdown** | Yes | Yes | Read-Only (Approved only) |
| **Approve / Reject Lead Gate** | Yes | Yes | No |
| **Reveal Contact Info (Spend Gate)** | Yes | Yes | No |
| **Generate AI Outreach Draft** | Yes | Yes | No |
| **Approve / Reject AI Draft Gate** | Yes | Yes | No |
| **Synchronize to HubSpot CRM** | Yes | Yes | No |

---

## 3. PostgreSQL Row-Level Security (RLS) Policies

All tenant-scoped tables (`users`, `audiences`, `engines`, `engine_params`, `searches`, `leads`, `enrichments`, `scores`, `contacts`, `drafts`, `crm_syncs`, `runs`, `audit_log`) enforce RLS policies:

```sql
-- Example for leads table
ALTER TABLE leads ENABLE ROW LEVEL SECURITY;

CREATE POLICY lead_tenant_isolation ON leads
FOR ALL
USING (
  current_setting('leadflow.is_super_admin', true) = 'true'
  OR org_id = NULLIF(current_setting('leadflow.current_org_id', true), '')::uuid
)
WITH CHECK (
  current_setting('leadflow.is_super_admin', true) = 'true'
  OR org_id = NULLIF(current_setting('leadflow.current_org_id', true), '')::uuid
);
```

When the FastAPI backend initiates a database session:
```python
await db_session.execute(
    text("SET LOCAL leadflow.current_org_id = :org_id"),
    {"org_id": str(current_user.org_id)}
)
```

---

## 4. Spend Safety & Action Authorization Gates

Lead intelligence APIs can consume significant credits. LeadFlow implements hard programmatic guardrails:

1. **Lead Approval Gate**:
   - `Lead.approval_status` must equal `approved` before any AI draft generation can be initiated.
   - Attempting to generate a draft for an unapproved lead returns HTTP 400 `LEAD_NOT_APPROVED`.

2. **Contact Reveal Gate**:
   - Raw emails and phone numbers are masked in all standard query responses (`m***@company.com`).
   - Unmasking requires an explicit `POST /api/v1/contacts/{id}/reveal` request.
   - Every reveal action logs the operator ID, timestamp, and consumes an organization reveal quota credit.

3. **Draft Approval Gate**:
   - `Draft.approval_status` must equal `approved` before CRM synchronization can occur.
   - Attempting to synchronize an unapproved draft returns HTTP 400 `DRAFT_NOT_APPROVED`.
