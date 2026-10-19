   -- Run this ONCE against your Neon database before first deploy — paste into Neon's console SQL
   -- editor, or: psql "<your neon connection string>" -f infra/scripts/neon-init.sql
   --
   -- Neon's default role (shown on your connection details page) is the admin/superuser-equivalent
   -- role — use it for POSTGRES_ADMIN_URL. This script creates the second, restricted role the app
   -- actually runs as at runtime (DATABASE_URL / DATABASE_APP_URL), matching the dev setup's
   -- leadflow_admin / leadflow_app split (see infra/docker/init-db.sql).
   --
   -- Replace REPLACE_WITH_REAL_PASSWORD below with a real generated password (openssl rand -hex 24)
   -- before running this, then use that same password in DATABASE_URL / DATABASE_APP_URL.
   
   CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
   CREATE EXTENSION IF NOT EXISTS "pgcrypto";
   
   DO
   $do$
   BEGIN
      IF NOT EXISTS (
         SELECT FROM pg_catalog.pg_roles
         WHERE  rolname = 'leadflow_app') THEN
         CREATE ROLE leadflow_app WITH LOGIN PASSWORD '001fefcbf6fa389358475d50ae4b61aa277c83ff0193d7ce';
      ELSE
         ALTER ROLE leadflow_app WITH LOGIN PASSWORD '001fefcbf6fa389358475d50ae4b61aa277c83ff0193d7ce';
      END IF;
   END
   $do$;
   
   GRANT ALL ON SCHEMA public TO CURRENT_USER;
   GRANT USAGE ON SCHEMA public TO leadflow_app;
   ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO leadflow_app;
   ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO leadflow_app;
   
   -- RLS tenant isolation is evaluated using: current_setting('leadflow.current_org_id', true)
   -- (the app sets this per-request/per-job — nothing further to configure here; the policies
   -- themselves are created by Alembic migrations, run separately after this script).
