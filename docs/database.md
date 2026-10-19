# LeadFlow Database Architecture & RLS Security

## 1. Relational Schema & Entity Relationship Model

LeadFlow utilizes PostgreSQL 16 with UUID primary keys and strict tenant scoping across 14 relational tables.

```text
                  +-------------------+
                  |   organizations   |
                  +-------------------+
                     | 1           1 |
          +----------+               +----------+
          | N                                   | N
+-------------------+                 +-------------------+
|       users       |                 |     audiences     |
+-------------------+                 +-------------------+
          | 1                                   | 1
          | audit/actors                        | N
+-------------------+                 +-------------------+
|     audit_log     |                 |     searches      |
+-------------------+                 +-------------------+
                                                | 1
                                                | N
                                      +-------------------+
                                      |       runs        |
                                      +-------------------+
                                                | 1
                                                | N
+-------------------+ 1             N +-------------------+
|      engines      |-----------------|       leads       |
+-------------------+                 +-------------------+
          | 1                                   | 1
          | N                         +---------+---------+
+-------------------+                 | 1       | 1       | 1
|   engine_params   |                 | N       | N       | N
+-------------------+       +-------------+ +-------+ +---------+
                            | enrichments | |scores | |contacts |
                            +-------------+ +-------+ +---------+
                                                | 1       | 1
                                                | N       | N
                                            +---------------+
                                            |    drafts     |
                                            +---------------+
                                                    | 1
                                                    | N
                                            +---------------+
                                            |   crm_syncs   |
                                            +---------------+
```

---

## 2. Table Specifications

### 1. `orgs` (Organizations)
Multi-tenant root container.
- `id` (UUID, PK)
- `name` (VARCHAR, Not Null)
- `slug` (VARCHAR, Unique, Not Null)
- `plan` (VARCHAR, Default 'starter')
- `settings` (JSONB, Default {})
- `is_active` (BOOLEAN, Default True)
- `created_at`, `updated_at`, `deleted_at`

### 2. `users`
Tenant-scoped authentication and RBAC accounts.
- `id` (UUID, PK)
- `org_id` (UUID, FK -> orgs.id, Nullable only for global super_admin)
- `email` (VARCHAR, Unique, Not Null)
- `hashed_password` (VARCHAR, Not Null)
- `full_name` (VARCHAR)
- `role` (ENUM: `super_admin`, `org_admin`, `client_viewer`)
- `is_active` (BOOLEAN, Default True)
- `last_login_at` (TIMESTAMPTZ)
- `created_at`, `updated_at`, `deleted_at`

### 3. `audiences`
Versioned Ideal Customer Profile (ICP) filter sets.
- `id` (UUID, PK)
- `org_id` (UUID, FK -> orgs.id, Not Null)
- `name` (VARCHAR, Not Null)
- `description` (TEXT)
- `filters` (JSONB, Not Null) - e.g. `{ "locations": ["US"], "industries": ["B2B SaaS"], "headcount_min": 20 }`
- `version` (INTEGER, Default 1)
- `is_active` (BOOLEAN, Default True)
- `created_at`, `updated_at`, `deleted_at`

### 4. `engines`
Scoring engine configurations.
- `id` (UUID, PK)
- `org_id` (UUID, FK -> orgs.id, Not Null)
- `name` (VARCHAR, Not Null)
- `description` (TEXT)
- `active_version` (INTEGER, Default 1)
- `created_at`, `updated_at`, `deleted_at`

### 5. `engine_params`
Versioned signal weight parameter definitions.
- `id` (UUID, PK)
- `engine_id` (UUID, FK -> engines.id, Not Null)
- `version` (INTEGER, Not Null)
- `weights` (JSONB, Not Null) - Exact weights for all 22 website and marketing signals
- `threshold_high` (FLOAT, Default 75.0)
- `threshold_medium` (FLOAT, Default 50.0)
- `threshold_low` (FLOAT, Default 25.0)
- `created_at`

### 6. `searches`
Lead sourcing requests linked to audiences.
- `id` (UUID, PK)
- `org_id` (UUID, FK -> orgs.id, Not Null)
- `audience_id` (UUID, FK -> audiences.id, Nullable)
- `name` (VARCHAR, Not Null)
- `query_params` (JSONB, Not Null)
- `created_by` (UUID, FK -> users.id, Not Null)
- `created_at`, `updated_at`

### 7. `leads`
Prospect companies sourced and evaluated.
- `id` (UUID, PK)
- `org_id` (UUID, FK -> orgs.id, Not Null)
- `search_id` (UUID, FK -> searches.id, Nullable)
- `domain` (VARCHAR, Not Null)
- `company_name` (VARCHAR, Not Null)
- `industry` (VARCHAR)
- `country` (VARCHAR)
- `city` (VARCHAR)
- `employee_count` (INTEGER)
- `pipeline_status` (ENUM: `sourced`, `enriching`, `enriched`, `scoring`, `scored`, `approved`, `disqualified`, `drafting`, `drafted`, `synced`)
- `score_band` (ENUM: `high`, `medium`, `low`, `disqualified`, `unscored`)
- `approval_status` (ENUM: `pending`, `approved`, `rejected`)
- `approved_by` (UUID, FK -> users.id, Nullable)
- `approved_at` (TIMESTAMPTZ, Nullable)
- `created_at`, `updated_at`, `deleted_at`

### 8. `enrichments`
Raw audit data and provider provenance stored as JSONB.
- `id` (UUID, PK)
- `org_id` (UUID, FK -> orgs.id, Not Null)
- `lead_id` (UUID, FK -> leads.id, Not Null)
- `version` (INTEGER, Default 1)
- `payload` (JSONB, Not Null) - Structured website crawl, PageSpeed metrics, SEO data
- `provider_provenance` (JSONB, Not Null) - Timestamps, status, and API sources
- `created_at`

### 9. `scores`
Historical scoring outputs calculated from enrichments.
- `id` (UUID, PK)
- `org_id` (UUID, FK -> orgs.id, Not Null)
- `lead_id` (UUID, FK -> leads.id, Not Null)
- `enrichment_id` (UUID, FK -> enrichments.id, Not Null)
- `engine_param_id` (UUID, FK -> engine_params.id, Not Null)
- `overall_score` (FLOAT, Not Null) - 0.0 to 100.0
- `score_band` (VARCHAR, Not Null) - 'HIGH', 'MEDIUM', 'LOW', 'DISQUALIFIED'
- `website_subscore` (FLOAT)
- `marketing_subscore` (FLOAT)
- `signal_details` (JSONB, Not Null) - Detailed 22 signal scores, weights, values, and evidence
- `explanation` (TEXT)
- `created_at`

### 10. `contacts`
Decision-makers discovered at the prospect company.
- `id` (UUID, PK)
- `org_id` (UUID, FK -> orgs.id, Not Null)
- `lead_id` (UUID, FK -> leads.id, Not Null)
- `first_name` (VARCHAR)
- `last_name` (VARCHAR)
- `title` (VARCHAR)
- `linkedin_url` (VARCHAR)
- `email` (VARCHAR) - Masked until `is_revealed` is true
- `phone` (VARCHAR) - Masked until `is_revealed` is true
- `is_revealed` (BOOLEAN, Default False)
- `revealed_at` (TIMESTAMPTZ, Nullable)
- `revealed_by` (UUID, FK -> users.id, Nullable)
- `created_at`, `updated_at`

### 11. `drafts`
AI-generated personalized outreach copy.
- `id` (UUID, PK)
- `org_id` (UUID, FK -> orgs.id, Not Null)
- `lead_id` (UUID, FK -> leads.id, Not Null)
- `contact_id` (UUID, FK -> contacts.id, Nullable)
- `subject` (VARCHAR, Not Null)
- `body` (TEXT, Not Null)
- `model_used` (VARCHAR, Not Null)
- `audit_citations` (JSONB) - Concrete findings cited in the draft
- `approval_status` (ENUM: `pending`, `approved`, `rejected`)
- `approved_by` (UUID, FK -> users.id, Nullable)
- `approved_at` (TIMESTAMPTZ, Nullable)
- `created_at`, `updated_at`

### 12. `crm_syncs`
Idempotent synchronization records for external CRM (HubSpot).
- `id` (UUID, PK)
- `org_id` (UUID, FK -> orgs.id, Not Null)
- `lead_id` (UUID, FK -> leads.id, Not Null)
- `draft_id` (UUID, FK -> drafts.id, Nullable)
- `crm_provider` (VARCHAR, Default 'hubspot')
- `crm_contact_id` (VARCHAR)
- `crm_company_id` (VARCHAR)
- `crm_engagement_id` (VARCHAR)
- `sync_status` (ENUM: `pending`, `success`, `failed`)
- `retry_count` (INTEGER, Default 0)
- `error_message` (TEXT)
- `synced_at` (TIMESTAMPTZ)
- `created_at`

### 13. `runs`
Asynchronous batch job tracking for ARQ tasks.
- `id` (UUID, PK)
- `org_id` (UUID, FK -> orgs.id, Not Null)
- `run_type` (ENUM: `search`, `enrichment`, `scoring`, `crm_sync`)
- `status` (ENUM: `pending`, `running`, `completed`, `failed`)
- `progress_pct` (INTEGER, Default 0)
- `items_total` (INTEGER, Default 0)
- `items_processed` (INTEGER, Default 0)
- `items_succeeded` (INTEGER, Default 0)
- `items_failed` (INTEGER, Default 0)
- `error_details` (JSONB)
- `started_at` (TIMESTAMPTZ)
- `completed_at` (TIMESTAMPTZ)
- `created_at`, `updated_at`

### 14. `audit_log`
Comprehensive immutable security and operation log.
- `id` (UUID, PK)
- `org_id` (UUID, FK -> orgs.id, Nullable)
- `actor_user_id` (UUID, FK -> users.id, Nullable)
- `action` (VARCHAR, Not Null) - e.g. `lead.approve`, `contact.reveal`, `draft.generate`, `crm.sync`
- `entity_type` (VARCHAR, Not Null)
- `entity_id` (UUID, Not Null)
- `changes` (JSONB)
- `ip_address` (VARCHAR)
- `user_agent` (VARCHAR)
- `created_at` (TIMESTAMPTZ, Default NOW())

---

## 3. PostgreSQL Row-Level Security (RLS) Implementation

To guarantee data isolation across organizations:

1. **Session Tenant Variable**:
   In each database transaction, the FastAPI session sets:
   ```sql
   SET LOCAL leadflow.current_org_id = '<current_org_uuid>';
   ```
2. **Row-Level Security Policies**:
   Each tenant-scoped table enables RLS:
   ```sql
   ALTER TABLE leads ENABLE ROW LEVEL SECURITY;
   
   CREATE POLICY lead_tenant_isolation_policy ON leads
   FOR ALL
   USING (
     org_id = NULLIF(current_setting('leadflow.current_org_id', true), '')::uuid
     OR current_setting('leadflow.is_super_admin', true) = 'true'
   );
   ```
3. **Database Roles**:
   - `leadflow_admin`: Privileged owner role used strictly for Alembic schema migrations.
   - `leadflow_app`: Unprivileged runtime role subject to RLS enforcement.
