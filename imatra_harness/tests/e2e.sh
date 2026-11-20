#!/usr/bin/env bash
# CI only: the prebuilt Imatra server App image plus this App built locally
# (never pushed), one device, until an ISO 15118-2 session is in progress.
set -euo pipefail
HERE=$(cd "$(dirname "$0")/.." && pwd)
WORK=${WORK:-$(mktemp -d)}
SERVER=${SERVER_IMAGE:-ghcr.io/purcell-lab/amd64-imatra-server:0.1.0}
DEV=harness-01
API=http://127.0.0.1:18080/v1
KEY=$(openssl rand -hex 24)
log() { echo "[harness-e2e] $*"; }
dump() { docker logs --tail 120 imatra 2>&1 | sed 's/^/[server] /' || true
         docker logs --tail 120 harness 2>&1 | sed 's/^/[harness] /' || true; }
fail() { echo "[harness-e2e] FAIL: $*" >&2; dump; exit 1; }
cleanup() { docker rm -f harness imatra >/dev/null 2>&1 || true; docker network rm imatra-lab >/dev/null 2>&1 || true; }
trap cleanup EXIT; cleanup

docker build -q --build-arg BUILD_ARCH=amd64 -t imatra-harness:local "$HERE" >/dev/null
mkdir -p "$WORK/sdata" "$WORK/hdata" "$WORK/share"
jq -n --arg key "$KEY" --arg dev "$DEV" '{operator_api_key: $key, broker_dns: "imatra.example.test", broker_ips: [],
  devices: [{id: $dev, type: "station", rules: "{\"topology\":\"integrated\"}"}],
  evse_max_current_a: 32, evse_phases: 3, evse_nominal_voltage_v: 230}' > "$WORK/sdata/options.json"
docker network create imatra-lab >/dev/null
docker run -d --init --name imatra --hostname ci0000ab-imatra-server --network imatra-lab \
  --network-alias ci0000ab-imatra-server -v "$WORK/sdata:/data" -v "$WORK/share:/share" \
  -p 127.0.0.1:18080:8080 "$SERVER" >/dev/null
for _ in $(seq 1 240); do docker logs imatra 2>&1 | grep -q "device $DEV: registry entry published" && break; sleep 1; done
docker logs imatra 2>&1 | grep -q "device $DEV: registry entry published" || fail "server did not register $DEV"

# Licence gate: refuses to start with the default options.
echo '{"accept_licence": false, "device_id": "harness-01"}' > "$WORK/hdata/options.json"
docker run --rm --cap-add NET_ADMIN -v "$WORK/hdata:/data" imatra-harness:local >"$WORK/gate.log" 2>&1 && fail "started without accept_licence"
grep -q "accept_licence is false" "$WORK/gate.log" || fail "no licence message"
log "ok: refuses to start until the licence is accepted"

# Broker certificate names imatra.example.test, as on the Green (public DNS name).
jq -n '{accept_licence: true, device_id: "harness-01", server_host: "", broker_name: "imatra.example.test", replug_s: 30, ev_pause_s: 20}' \
  > "$WORK/hdata/options.json"
docker run -d --name harness --hostname ci0000ab-imatra-harness --network imatra-lab --cap-add NET_ADMIN \
  -v "$WORK/hdata:/data" -v "$WORK/share:/share:ro" imatra-harness:local >/dev/null
api() { curl -fsS -H "X-API-Key: $KEY" "$@"; }
for _ in $(seq 1 300); do
  s=$(api "$API/devices/$DEV" 2>/dev/null || true)
  if jq -e '.online == true and .session != null' >/dev/null 2>&1 <<<"$s"; then
    log "ok: $DEV online with an ISO 15118-2 session in progress"
    docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' harness imatra
    exit 0
  fi
  docker inspect -f '{{.State.Running}}' harness | grep -q true || fail "harness stopped"
  sleep 1
done
echo "last: ${s:-}" >&2; fail "no session within 300 s"
