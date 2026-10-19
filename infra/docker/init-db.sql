-- ==============================================================================
-- LeadFlow PostgreSQL 16 Initialization Script
-- Configures roles, extensions, and schema security
-- ==============================================================================

-- 1. Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 2. Create runtime application role with restricted privileges if not exists
DO
$do$
BEGIN
   IF NOT EXISTS (
      SELECT FROM pg_catalog.pg_roles
      WHERE  rolname = 'leadflow_app') THEN
      CREATE ROLE leadflow_app WITH LOGIN PASSWORD 'leadflow_app_password';
   END IF;
END
$do$;

-- 3. Grant schema permissions to application user
GRANT ALL ON SCHEMA public TO leadflow_admin;
GRANT USAGE ON SCHEMA public TO leadflow_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO leadflow_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO leadflow_app;

-- 4. Enable RLS configuration parameter
-- RLS tenant isolation is evaluated using: current_setting('leadflow.current_org_id', true)
COMMENT ON DATABASE leadflow IS 'LeadFlow Multi-Tenant Lead Intelligence Platform';
