#!/bin/bash
set -euo pipefail
umask 077
password="$(jq -er '.database_password | select(test("^[a-f0-9]{64}$"))' /data/options.json)"
host="$(jq -er '.database_host | select(test("^[a-z0-9][a-z0-9.-]*$"))' /data/options.json)"
export HASURA_GRAPHQL_ADMIN_SECRET
HASURA_GRAPHQL_ADMIN_SECRET="$(jq -er '.admin_secret | select(test("^[a-f0-9]{64}$"))' /data/options.json)"
export HASURA_GRAPHQL_DATABASE_URL="postgres://citrine:${password}@${host}:5432/citrine"
exec setpriv --reuid=1000 --regid=1000 --clear-groups graphql-engine serve
