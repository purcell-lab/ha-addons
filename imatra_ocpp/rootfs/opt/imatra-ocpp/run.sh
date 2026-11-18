#!/usr/bin/env bash
# Starts the bridge from the App options. Never logged: the keys and passwords.
set -euo pipefail
OPT=${OPTIONS_FILE:-/data/options.json}
STATE=${STATE_DIR:-/data/bridge}
die() { echo "[imatra-ocpp] ERROR: $*" >&2; exit 1; }

[ -n "$(jq -r '.imatra_api_key // empty' "$OPT")" ] || die "set imatra_api_key (the Imatra App's operator_api_key)"
[ -n "$(jq -r '.csms_url // empty' "$OPT")" ] || die "set csms_url, e.g. ws://<repo>-citrineos-server:8082"
imatra_url=$(jq -r '.imatra_url // empty' "$OPT")
if [ -z "$imatra_url" ]; then
  # The Supervisor names App containers <repo hash>-<slug>; the server App is
  # in the same repository, so it is <repo hash>-imatra-server.
  host=$(hostname)
  [[ "$host" == *-imatra-ocpp ]] || die "set imatra_url (cannot derive it from host name '$host')"
  imatra_url="http://${host%-imatra-ocpp}-imatra-server:8080"
fi

mkdir -p "$STATE"
umask 077
jq --arg url "$imatra_url" --arg state "$STATE" '{
  csms_url, csms_password, imatra_url: $url, imatra_api_key, devices, station_id_prefix,
  confirm_timeout_s, default_duration_s, voltage_v, phases, state_dir: $state}' "$OPT" > "$STATE/config.json"
chown -R bridge "$STATE"
echo "[imatra-ocpp] imatra-ocpp $(cut -c1-7 /etc/imatra-ocpp-commit); Imatra at $imatra_url; CSMS $(jq -r .csms_url "$OPT"); prefix $(jq -r .station_id_prefix "$OPT")"
exec setpriv --reuid=bridge --regid=bridge --init-groups python -m imatra_ocpp "$STATE/config.json"
