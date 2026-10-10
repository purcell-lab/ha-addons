#!/bin/bash
set -euo pipefail
umask 077
export POSTGRES_PASSWORD
POSTGRES_PASSWORD="$(jq -er '.password | select(test("^[a-f0-9]{64}$"))' /data/options.json)" || {
  echo "A generated 64-hex database credential is required." >&2; exit 78;
}
# The upstream entrypoint drops to postgres and initialises only an empty PGDATA.
exec /usr/local/bin/docker-entrypoint.sh "$@"
