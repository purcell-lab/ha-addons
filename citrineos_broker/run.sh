#!/bin/bash
set -euo pipefail
umask 077
export RABBITMQ_DEFAULT_PASS
RABBITMQ_DEFAULT_PASS="$(jq -er '.password | select(test("^[a-f0-9]{64}$"))' /data/options.json)" || {
  echo "A generated 64-hex broker credential is required." >&2; exit 78;
}
mkdir -p /data/mnesia
chown -R rabbitmq:rabbitmq /data/mnesia
export RABBITMQ_SERVER_ADDITIONAL_ERL_ARGS="+S 2:2"
exec /usr/local/bin/docker-entrypoint.sh "$@"
