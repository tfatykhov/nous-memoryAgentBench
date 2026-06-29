#!/usr/bin/env bash
# Provision a fresh, isolated nous memory database for the MAB harness.
#
# nous verifies its schemas exist (it will NOT create them) and then applies
# sql/migrations/* itself on startup (tracked in nous_system.schema_migrations).
# So we create an empty DB and apply ONLY sql/init.sql; nous migrates the rest.
#
# Usage:
#   scripts/provision_eval_db.sh [DB_NAME] [PG_CONTAINER] [NOUS_REPO]
# Defaults: nous_mab  nous-eval-scratch  ../nous
set -euo pipefail

DB_NAME="${1:-nous_mab}"
CONTAINER="${2:-nous-eval-scratch}"
NOUS_REPO="${3:-../nous}"
PG_USER="${PG_USER:-nous}"

echo ">> (re)creating database '$DB_NAME' in container '$CONTAINER'"
docker exec "$CONTAINER" dropdb -U "$PG_USER" --if-exists "$DB_NAME"
docker exec "$CONTAINER" createdb -U "$PG_USER" "$DB_NAME"

echo ">> applying $NOUS_REPO/sql/init.sql (schemas + base tables)"
docker exec -i "$CONTAINER" psql -q -v ON_ERROR_STOP=1 -U "$PG_USER" -d "$DB_NAME" \
  < "$NOUS_REPO/sql/init.sql"

echo ">> done. nous will apply sql/migrations/* on first startup."
echo ">> point the harness at it with:  MAB_DB_NAME=$DB_NAME"
