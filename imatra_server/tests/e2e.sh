#!/usr/bin/env bash
# End to end for the Imatra App in CI (never on Home Assistant):
#   the App image as HA would run it (options in /data, /share mapped),
#   the Imatra test harness station and EV (fetched at run time by the
#   workflow into $HARNESS_DIR and built locally; never bundled or published:
#   PolyForm Internal Use 1.0.0), one ISO 15118-2 session with an operator
#   limit, a restart, and the network boundary.
#
#   HARNESS_DIR=/path/to/imatra.test_harness imatra_server/tests/e2e.sh
set -euo pipefail
HERE=$(cd "$(dirname "$0")/.." && pwd)
HARNESS_DIR=${HARNESS_DIR:?set HARNESS_DIR to the imatra.test_harness checkout}
WORK=${WORK:-$(mktemp -d)}
APP=imatra-app:ci
DEV=dev-01
API=http://127.0.0.1:18080/v1
SUMMARY=${GITHUB_STEP_SUMMARY:-/dev/null}

log()  { echo "[e2e] $*"; }
fail() { echo "[e2e] FAIL: $*" >&2; dump; exit 1; }
dump() {
  docker logs --tail 150 imatra 2>&1 | sed 's/^/[app] /' || true
  docker logs --tail 60 station 2>&1 | sed 's/^/[station] /' || true
  docker logs --tail 40 ev 2>&1 | sed 's/^/[ev] /' || true
}
KEY=$(openssl rand -hex 24)
api() { curl -fsS -H "X-API-Key: $KEY" -H 'Content-Type: application/json' "$@"; }
LAST=
wait_for() { # what url jq-condition [seconds]
  local what=$1 url=$2 cond=$3 secs=${4:-240}
  for _ in $(seq 1 "$secs"); do
    if LAST=$(api "$url" 2>/dev/null) && jq -e "$cond" >/dev/null 2>&1 <<<"$LAST"; then
      log "ok: $what"; return 0
    fi
    sleep 1
  done
  echo "[e2e] last response: $LAST" >&2
  fail "$what (not within ${secs}s)"
}

cleanup() {
  docker rm -f ev station imatra >/dev/null 2>&1 || true
  docker network rm v2g imatra-lab >/dev/null 2>&1 || true
}
trap cleanup EXIT
cleanup

# --- build -------------------------------------------------------------------
arch=$(uname -m); case "$arch" in x86_64) arch=amd64 ;; aarch64|arm64) arch=aarch64 ;; esac
start=$(date +%s)
docker build -q --build-arg BUILD_ARCH="$arch" -t "$APP" "$HERE" >/dev/null
echo "app_build_seconds=$(( $(date +%s) - start ))" >> "$SUMMARY"
docker build -q -t imatra-station:ci "$HARNESS_DIR/station" >/dev/null
docker build -q -t imatra-ev:ci "$HARNESS_DIR/ev" >/dev/null
log "images built ($arch)"

# --- the App, as the Supervisor would start it -----------------------------------
mkdir -p "$WORK/data" "$WORK/share"
jq -n --arg key "$KEY" --arg dev "$DEV" '{
  operator_api_key: $key, broker_dns: "mqtt", broker_ips: [],
  devices: [{id: $dev, type: "station", rules: "{\"topology\":\"integrated\"}"}],
  evse_max_current_a: 32, evse_phases: 3, evse_nominal_voltage_v: 230}' > "$WORK/data/options.json"
docker network create imatra-lab >/dev/null
docker network create --internal --ipv6 --subnet fd15:118::/64 v2g >/dev/null
run_app() {
  docker run -d --init --name imatra --hostname imatra-server --network imatra-lab --network-alias mqtt \
    -v "$WORK/data:/data" -v "$WORK/share:/share" -p 127.0.0.1:18080:8080 "$APP" >/dev/null
}
run_app
for _ in $(seq 1 240); do
  curl -fsS http://127.0.0.1:18080/health >/dev/null 2>&1 && break
  docker inspect -f '{{.State.Running}}' imatra 2>/dev/null | grep -q true || fail "the App stopped during start-up"
  sleep 1
done
curl -fsS http://127.0.0.1:18080/health >/dev/null || fail "gateway /health"
for _ in $(seq 1 60); do docker logs imatra 2>&1 | grep -q 'running: Imatra' && break; sleep 1; done
docker logs imatra 2>&1 | grep -q "device $DEV: registry entry published" || fail "registry entry for $DEV"
log "App started"
# Secrets never in the log.
pw=$(grep -h PASSWORD "$WORK/data/secrets.env" 2>/dev/null || sudo grep -h PASSWORD "$WORK/data/secrets.env")
for s in $KEY $(cut -d= -f2 <<<"$pw"); do
  docker logs imatra 2>&1 | grep -qF "$s" && fail "a secret appears in the App log"
done
log "ok: no secret in the App log"

# --- the station and the EV from the harness ---------------------------------------
own="$WORK/own"; mkdir -p "$own"
docker exec imatra cat "/share/imatra/devices/$DEV.pem" > "$own/$DEV.pem"
docker exec imatra cat /share/imatra/ca.crt > "$own/ca.crt"
chmod 0644 "$own"/*
docker create --name station --network imatra-lab -v "$own:/own:ro" imatra-station:ci \
  --device-id "$DEV" --cert "/own/$DEV.pem" --key "/own/$DEV.pem" --ca /own/ca.crt \
  --address mqtt:8883 --v2g-subnet fd15:118::/64 --replug-s 30 >/dev/null
docker network connect --ip6 fd15:118::10 v2g station
docker start station >/dev/null
docker run -d --name ev --network v2g --ip6 fd15:118::20 -e EV_TLS=0 imatra-ev:ci >/dev/null
since=$(date -u -d '-60 sec' +%Y-%m-%dT%H:%M:%SZ)

wait_for "the station online and bound as a station" "$API/devices/$DEV" \
  '.online == true and .registry.state == "bound" and .registry.type == "station"'
wait_for "an ISO 15118-2 session in progress" "$API/devices/$DEV" '.online == true and .session != null' 300

# --- operator limit during the session ----------------------------------------------
r=$(api -X POST "$API/devices/$DEV/limit" -d '{"limit_a": 10, "duration_s": 600}') || fail "POST limit: $r"
cid=$(jq -r '.command_id' <<<"$r")
wait_for "limit 10 A confirmed by the device" "$API/devices/$DEV" \
  ".limit.command_id == $cid and .limit.limit_a == 10 and .limit.confirmed_at != null" 60
echo "limit_reaction_ms=$(jq -r '.limit.reaction_ms' <<<"$LAST")" >> "$SUMMARY"
code=$(curl -sS -o /dev/null -w '%{http_code}' -X POST -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  "$API/devices/$DEV/limit" -d '{"limit_a": 2, "duration_s": 60}')
[ "$code" = 422 ] || fail "limit 2 A: expected 422, got $code"
code=$(curl -sS -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' \
  "$API/devices/$DEV/limit" -d '{"limit_a": 10, "duration_s": 60}')
[ "$code" = 401 ] || fail "limit without a key: expected 401, got $code"
log "ok: 2 A refused (422), no key refused (401)"
api -X DELETE "$API/devices/$DEV/limit" >/dev/null || fail "DELETE limit"
wait_for "limit cancelled" "$API/devices/$DEV" '.limit == null' 60
wait_for "an ISO 15118-2 session ended normally with the limit recorded" \
  "$API/sessions?device=$DEV&from=$since&open=false" \
  '[.sessions[] | select(.mode == "iso15118-2" and .end_reason == "ev_unplugged" and .limits_applied > 0)] | length > 0' 300
log "summary: $(jq -c '[.sessions[] | select(.limits_applied > 0)][0] | {mode, end_reason, energy_wh, limits_applied, duration_s}' <<<"$LAST")"

# --- network boundary: only 8080 and 8883 answer from another container ---------------
probe() { # port -> "open" or "closed"
  docker run --rm --network imatra-lab --entrypoint python3 "$APP" -c "
import socket,sys
s=socket.socket(); s.settimeout(3)
try: s.connect(('mqtt', $1)); print('open')
except Exception: print('closed')"
}
for p in 1883 5432 6379 8000 8090 8091 8092; do
  [ "$(probe $p)" = closed ] || fail "port $p is reachable from the network"
done
for p in 8080 8883; do
  [ "$(probe $p)" = open ] || fail "port $p is not reachable from the network"
done
log "ok: only 8080 and 8883 reachable; 1883, Postgres, Valkey, API and health ports internal"

# --- resource use (before the restart) ----------------------------------------------
{ echo '```'; docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}' imatra station ev
  docker images --format 'table {{.Repository}}:{{.Tag}}\t{{.Size}}' "$APP"; echo '```'; } | tee -a "$SUMMARY"

# --- restart: the same CA, the device back online ------------------------------------
ca1=$(docker exec imatra sha256sum /pki/ca.crt | cut -d' ' -f1)
docker stop -t 30 imatra >/dev/null
docker logs imatra 2>&1 | tail -60 | grep -q '\[imatra-ha\] stopping' || fail "no graceful stop"
docker logs imatra 2>&1 | tail -10 | grep -q 'database system is shut down' || fail "Postgres not shut down cleanly"
docker start imatra >/dev/null
for _ in $(seq 1 180); do curl -fsS http://127.0.0.1:18080/health >/dev/null 2>&1 && break; sleep 1; done
ca2=$(docker exec imatra sha256sum /pki/ca.crt | cut -d' ' -f1)
[ "$ca1" = "$ca2" ] || fail "the CA changed across a restart"
wait_for "the station back online after a restart" "$API/devices/$DEV" '.online == true' 180
docker logs imatra 2>&1 | grep -c "registry entry published" | grep -qx 1 || fail "registry entry published again without a change"
log "ok: restart kept the CA, the database and the registry; the station reconnected"
log "PASSED"
