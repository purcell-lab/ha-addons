#!/usr/bin/env bash
# OCPP phase of the Imatra lab end to end (called by imatra_server/tests/e2e.sh
# with the Imatra App, the station and the EV running on network imatra-lab).
# For each OCPP version: the bridge App against a mock CSMS; a 10 A profile
# Accepted only after the device confirmed it, 3 A Rejected, a clear Accepted,
# the transaction Started and Ended.
set -euo pipefail
HERE=$(cd "$(dirname "$0")/.." && pwd)
: "${KEY:?}" "${API:?}" "${WORK:?}"
BRIDGE=imatra-ocpp-app:ci
SUMMARY=${GITHUB_STEP_SUMMARY:-/dev/null}
log()  { echo "[ocpp] $*"; }
fail() { echo "[ocpp] FAIL: $*" >&2; docker logs --tail 80 bridge 2>&1 | sed 's/^/[bridge] /'; docker logs csms 2>&1 | tail -40 | sed 's/^/[csms] /'; exit 1; }
cleanup() { docker rm -f bridge csms >/dev/null 2>&1 || true; }
trap cleanup EXIT

arch=$(uname -m); case "$arch" in x86_64) arch=amd64 ;; aarch64|arm64) arch=aarch64 ;; esac
docker build -q --build-arg BUILD_ARCH="$arch" -t "$BRIDGE" "$HERE" >/dev/null
log "bridge image built"

wait_csms() { # jq-condition seconds what
  for _ in $(seq 1 "$2"); do
    docker logs csms 2>/dev/null | grep '^{' | jq -se "$1" >/dev/null 2>&1 && { log "ok: $3"; return 0; }
    sleep 1
  done
  fail "$3 (not within $2 s)"
}

for version in ocpp2.1 ocpp2.0.1; do
  cleanup
  docker run -d --name csms --network imatra-lab -e CSMS_VERSIONS="$version" \
    -v "$HERE/tests/mock_csms.py:/mock_csms.py:ro" --entrypoint python "$BRIDGE" /mock_csms.py >/dev/null
  mkdir -p "$WORK/bridge-$version"
  # imatra_url empty: the bridge finds the server App by its Supervisor name.
  jq -n --arg key "$KEY" '{csms_url: "ws://csms:9000/ocpp", csms_password: "", imatra_url: "", imatra_api_key: $key,
    devices: ["dev-01"], station_id_prefix: "IMATRA-", confirm_timeout_s: 10, default_duration_s: 3600,
    voltage_v: 230, phases: 3}' > "$WORK/bridge-$version/options.json"
  since=$(curl -fsS -H "X-API-Key: $KEY" "$API/events?cursor=0&limit=1000" | jq '.next_cursor')
  while :; do  # the newest cursor
    nxt=$(curl -fsS -H "X-API-Key: $KEY" "$API/events?cursor=$since&limit=1000" | jq '.next_cursor')
    [ "$nxt" = "$since" ] && break; since=$nxt
  done
  docker run -d --init --name bridge --hostname ci0000ab-imatra-ocpp --network imatra-lab \
    -v "$WORK/bridge-$version:/data" "$BRIDGE" >/dev/null

  wait_csms "map(select(.event == \"boot\" and .version == \"$version\" and .station == \"IMATRA-dev-01\")) | length > 0" 60 "$version: boot accepted as IMATRA-dev-01"
  wait_csms 'map(select(.event == "tx" and .type == "Started")) | length > 0' 90 "$version: transaction Started at plug-in"
  wait_csms 'map(select(.event == "clear")) | length > 0' 60 "$version: profile commands answered"
  lines=$(docker logs csms 2>/dev/null | grep '^{')
  jq -se 'map(select(.event == "set_profile" and .amps == 10 and .status == "Accepted")) | length == 1' <<<"$lines" >/dev/null \
    || fail "$version: 10 A not Accepted: $(jq -sc 'map(select(.event == "set_profile"))' <<<"$lines")"
  jq -se 'map(select(.event == "set_profile" and .amps == 3 and .status == "Rejected" and .reason == "BelowMinimum")) | length == 1' <<<"$lines" >/dev/null \
    || fail "$version: 3 A not Rejected BelowMinimum"
  jq -se 'map(select(.event == "clear" and .status == "Accepted")) | length == 1' <<<"$lines" >/dev/null || fail "$version: clear"
  info=$(jq -sr 'map(select(.event == "set_profile" and .amps == 10))[0].info // ""' <<<"$lines")
  log "ok: $version: 10 A Accepted after device confirmation; 3 A Rejected BelowMinimum; clear Accepted"
  # Imatra's own record: the 10 A limit from the bridge, applied by the device.
  curl -fsS -H "X-API-Key: $KEY" "$API/events?cursor=$since&limit=1000&types=limit.changed,limit.applied&device=dev-01" \
    | jq -e '[.events[] | select(.type == "limit.changed" and .data.limit_a == 10)] | length > 0' >/dev/null \
    || fail "$version: no 10 A limit.changed in the Imatra feed"
  log "ok: $version: Imatra feed shows the 10 A limit"
  wait_csms 'map(select(.event == "tx" and .type == "Ended" and .stopped == "EVDisconnected")) | length > 0' 90 "$version: transaction Ended (EVDisconnected)"
  docker logs bridge 2>&1 | grep -qF "$KEY" && fail "the Imatra key appears in the bridge log"
  echo "$version: 10 A accepted ($info)" >> "$SUMMARY"
done
log "PASSED"
