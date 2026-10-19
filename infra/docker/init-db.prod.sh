#!/bin/sh
# Production-only Postgres init script. Unlike init-db.sql (dev, hardcoded dev password — never
# used here), this creates the restricted runtime role (leadflow_app) with the real
# POSTGRES_APP_PASSWORD from the environment, so the password in docker-compose.prod.yml's
# DATABASE_URL actually matches the role Postgres creates.
set -eu

: "${POSTGRES_APP_PASSWORD:?POSTGRES_APP_PASSWORD must be set for production init}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
  CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
  CREATE EXTENSION IF NOT EXISTS "pgcrypto";

  DO
  \$do\$
  BEGIN
     IF NOT EXISTS (
        SELECT FROM pg_catalog.pg_roles
        WHERE  rolname = 'leadflow_app') THEN
        CREATE ROLE leadflow_app WITH LOGIN PASSWORD '${POSTGRES_APP_PASSWORD}';
     ELSE
        ALTER ROLE leadflow_app WITH LOGIN PASSWORD '${POSTGRES_APP_PASSWORD}';
     END IF;
  END
  \$do\$;

  GRANT ALL ON SCHEMA public TO ${POSTGRES_USER};
  GRANT USAGE ON SCHEMA public TO leadflow_app;
  ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO leadflow_app;
  ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO leadflow_app;

  COMMENT ON DATABASE ${POSTGRES_DB} IS 'LeadFlow Multi-Tenant Lead Intelligence Platform';
EOSQL
