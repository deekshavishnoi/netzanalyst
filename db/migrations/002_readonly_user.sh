#!/bin/bash
# Creates the read-only role used by the MCP server.
# Runs automatically on first container start (docker-entrypoint-initdb.d).
# The MCP server must NEVER use the owner role.
set -euo pipefail

RO_PASSWORD="${POSTGRES_RO_PASSWORD:?POSTGRES_RO_PASSWORD must be set}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'netzanalyst_ro') THEN
        CREATE ROLE netzanalyst_ro LOGIN PASSWORD '${RO_PASSWORD}';
    ELSE
        ALTER ROLE netzanalyst_ro PASSWORD '${RO_PASSWORD}';
    END IF;
END
\$\$;

-- Connect + read, nothing else.
GRANT CONNECT ON DATABASE "$POSTGRES_DB" TO netzanalyst_ro;
GRANT USAGE   ON SCHEMA public           TO netzanalyst_ro;
GRANT SELECT  ON ALL TABLES IN SCHEMA public TO netzanalyst_ro;

-- Explicitly deny everything else, including on tables created later.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO netzanalyst_ro;
REVOKE CREATE ON SCHEMA public FROM netzanalyst_ro;

-- Belt and braces: a statement timeout on the role itself, so a runaway query
-- dies even if the MCP server's own timeout fails.
ALTER ROLE netzanalyst_ro SET statement_timeout = '15s';
ALTER ROLE netzanalyst_ro SET default_transaction_read_only = on;
SQL

echo "read-only role netzanalyst_ro ready"
