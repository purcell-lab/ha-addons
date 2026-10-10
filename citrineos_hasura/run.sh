#!/bin/bash
set -euo pipefail
umask 077
password="$(jq -er '.database_password | select(test("^[a-f0-9]{64}$"))' /data/options.json)"
host="$(jq -er '.database_host | select(test("^[a-z0-9][a-z0-9.-]*$"))' /data/options.json)"
export HASURA_GRAPHQL_ADMIN_SECRET
HASURA_GRAPHQL_ADMIN_SECRET="$(jq -er '.admin_secret | select(test("^[a-f0-9]{64}$"))' /data/options.json)"
export HASURA_GRAPHQL_DATABASE_URL="postgres://citrine:${password}@${host}:5432/citrine"
ready=false
for attempt in $(seq 1 90); do
  if (echo >/dev/tcp/"${host}"/5432) 2>/dev/null; then ready=true; break; fi
  sleep 2
done
if [ "$ready" != true ]; then echo "Database readiness timed out." >&2; exit 1; fi
exec gosu 1000:1000 graphql-engine serve
