#!/usr/bin/env bash
# Create and initialise the local Postgres database for netzanalyst.
#
# Use this when running Postgres natively (e.g. `brew install postgresql@16`).
# If you use Docker instead, `docker compose up` does all of this for you via
# the init scripts in sql/ and you do not need this script.
#
#   ./scripts/setup-local-db.sh           # create, apply schema, create RO role
#   ./scripts/setup-local-db.sh --reset   # drop the database first
#
# Reads POSTGRES_* and passwords from .env.
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  echo "error: .env not found. Copy .env.example to .env and fill it in." >&2
  exit 1
fi
set -a; . ./.env; set +a

DB="${POSTGRES_DB:-netzanalyst}"
OWNER="${POSTGRES_USER:-netzanalyst}"
OWNER_PW="${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set in .env}"
RO_PW="${POSTGRES_RO_PASSWORD:?POSTGRES_RO_PASSWORD must be set in .env}"

if ! command -v psql >/dev/null 2>&1; then
  echo "error: psql not on PATH. For Homebrew Postgres 16:" >&2
  echo '  export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"' >&2
  exit 1
fi

if [[ "${1:-}" == "--reset" ]]; then
  echo "==> dropping database $DB"
  psql -d postgres -q -c "DROP DATABASE IF EXISTS \"$DB\";"
fi

echo "==> ensuring role $OWNER"
psql -d postgres -q -v ON_ERROR_STOP=1 <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$OWNER') THEN
    CREATE ROLE "$OWNER" LOGIN PASSWORD '$OWNER_PW' CREATEDB;
  ELSE
    ALTER ROLE "$OWNER" PASSWORD '$OWNER_PW';
  END IF;
END \$\$;
SQL

if ! psql -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$DB';" | grep -q 1; then
  echo "==> creating database $DB owned by $OWNER"
  createdb -O "$OWNER" "$DB"
fi

# Apply the schema AS THE OWNER, so the ingest role owns every table it has to
# write to. Applying it as a superuser instead leaves the tables owned by that
# superuser and the ingest fails with "permission denied for table generation".
echo "==> applying schema as $OWNER"
PGPASSWORD="$OWNER_PW" psql -h 127.0.0.1 -U "$OWNER" -d "$DB" -q -v ON_ERROR_STOP=1 -f sql/001_schema.sql

echo "==> creating read-only role netzanalyst_ro"
psql -d "$DB" -q -v ON_ERROR_STOP=1 <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'netzanalyst_ro') THEN
    CREATE ROLE netzanalyst_ro LOGIN PASSWORD '$RO_PW';
  ELSE
    ALTER ROLE netzanalyst_ro PASSWORD '$RO_PW';
  END IF;
END \$\$;
GRANT CONNECT ON DATABASE "$DB" TO netzanalyst_ro;
GRANT USAGE ON SCHEMA public TO netzanalyst_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO netzanalyst_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE "$OWNER" IN SCHEMA public GRANT SELECT ON TABLES TO netzanalyst_ro;
REVOKE CREATE ON SCHEMA public FROM netzanalyst_ro;
ALTER ROLE netzanalyst_ro SET statement_timeout = '15s';
ALTER ROLE netzanalyst_ro SET default_transaction_read_only = on;
SQL

echo "==> verifying the read-only role really is read-only"
if PGPASSWORD="$RO_PW" psql -h 127.0.0.1 -U netzanalyst_ro -d "$DB" -q -c \
     "CREATE TABLE should_not_exist (i int);" >/dev/null 2>&1; then
  echo "FAIL: netzanalyst_ro was able to create a table" >&2
  exit 1
fi
echo "    ok: writes are rejected"

echo
echo "Database $DB is ready. Next:"
echo "  python data/ingest/smard.py --from 2024-01-01 --to \$(date +%F)"
