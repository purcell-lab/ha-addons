#!/usr/bin/env bash
# Imatra test harness station + Josev test EV on a virtual V2G link, from the
# App options. Refuses to start until accept_licence is true.
set -euo pipefail
OPT=${OPTIONS_FILE:-/data/options.json}
DATA=${DATA_DIR:-/data}
SHARE=${SHARE_DIR:-/share/imatra}
# Pinned harness (contracts/IMATRA_REF d07ba26). Change both together.
HARNESS_COMMIT=e1e9dfc522e6b2ca9b83fa7f1150858c9bdd7594
HARNESS_SHA256=2090dac12f61cf1dcd0a6e8cc9371ace7311b9a4957d653caadbe35bc234ed4d
log() { echo "[imatra-harness] $*"; }
die() { log "ERROR: $*"; exit 1; }
opt() { jq -r --arg k "$1" '.[$k] // empty' "$OPT"; }

# --- licence gate ---------------------------------------------------------------
if [ "$(opt accept_licence)" != true ]; then
  log "The Imatra test harness is licensed under PolyForm Internal Use 1.0.0"
  log "(https://polyformproject.org/licenses/internal-use/1.0.0) and may not be"
  log "distributed. Patent FI 20246111: no licence is granted for EVSE, devices or"
  log "vehicles. Read https://github.com/Chargetronic/imatra.test_harness, then set"
  log "accept_licence: true to fetch it for internal use on this host."
  die "accept_licence is false: not starting"
fi

# --- fetch the pinned harness (internal use, this host only) -------------------
H="$DATA/harness-$HARNESS_COMMIT"
if [ ! -f "$H/.verified" ]; then
  log "fetching imatra.test_harness ${HARNESS_COMMIT:0:7}"
  tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
  curl -fsSL --retry 3 -o "$tmp/h.tgz" \
    "https://github.com/Chargetronic/imatra.test_harness/archive/$HARNESS_COMMIT.tar.gz"
  echo "$HARNESS_SHA256  $tmp/h.tgz" | sha256sum -c --quiet - || die "harness archive checksum mismatch"
  rm -rf "$DATA"/harness-*  # older pins and partial fetches
  mkdir -p "$H"; tar -xzf "$tmp/h.tgz" -C "$H" --strip-components=1
  touch "$H/.verified"; rm -rf "$tmp"; trap - EXIT
fi
log "harness ${HARNESS_COMMIT:0:7} ready (checksum verified)"

# --- device credentials from the Imatra server App ------------------------------
DEV=$(opt device_id)
PEM="$SHARE/devices/$DEV.pem"; CA="$SHARE/ca.crt"
for f in "$PEM" "$CA"; do
  [ -r "$f" ] || die "$f not found: add $DEV to the Imatra ISO 15118-2 Lab App devices and restart it"
done
# Copy so the station reads a private file (the share is read-only).
mkdir -p "$DATA/own"; install -m 0600 "$PEM" "$DATA/own/$DEV.pem"; install -m 0644 "$CA" "$DATA/own/ca.crt"

# --- broker address and TLS name ------------------------------------------------
SERVER=$(opt server_host)
if [ -z "$SERVER" ]; then
  # Apps in one repository share the hash prefix: <hash>-imatra-server.
  host=$(hostname); SERVER="${host%-imatra-harness}-imatra-server"
fi
NAME=$(opt broker_name); NAME=${NAME:-$SERVER}
if [ "$NAME" != "$SERVER" ]; then
  # The broker certificate names $NAME (e.g. the public DNS name). Point it at
  # the server App on the internal network, for this App only.
  ip=$(getent hosts "$SERVER" | awk '{print $1; exit}') || true
  [ -n "${ip:-}" ] || die "cannot resolve $SERVER"
  grep -q " $NAME\$" /etc/hosts || echo "$ip $NAME" >> /etc/hosts
  log "broker $NAME -> $SERVER ($ip)"
fi

# --- virtual V2G link: veth pair in this App's namespace ------------------------
if ! ip link show v2g0 >/dev/null 2>&1; then
  ip link add v2g0 type veth peer name v2g1 || die "cannot create the veth pair (NET_ADMIN missing?)"
fi
for i in v2g0 v2g1; do
  if [ "$(cat /proc/sys/net/ipv6/conf/$i/disable_ipv6 2>/dev/null || echo 1)" = 1 ]; then
    echo 0 > /proc/sys/net/ipv6/conf/$i/disable_ipv6 2>/dev/null \
      || die "IPv6 is disabled on $i and /proc/sys is read-only here"
  fi
  ip link set "$i" up
done
ip -6 addr replace fd15:118::10/64 dev v2g0 nodad
ip -6 addr replace fd15:118::20/64 dev v2g1 nodad
for _ in $(seq 1 20); do ip -6 addr show dev v2g0 scope link | grep -q inet6 && break; sleep 0.5; done
log "V2G link up: station v2g0 (fd15:118::10), EV v2g1 (fd15:118::20)"

# --- EV: Josev without TLS (own PKI mode has no V2G signer) -----------------------
mkdir -p "$DATA/ev/pki/iso15118_2/certs"
# charge_loop_cycles sets the EV's ChargingStatus loops per session (about
# 0.3 s each on the Green), so a session can outlast a multi-step control test.
LOOPS=$(opt charge_loop_cycles); LOOPS=${LOOPS:-30}
# ev_protocol: ISO_15118_2 (default) or DIN_SPEC_70121. A DIN-only EV asks for
# DC (DIN allows no AC); Imatra only reads its SoC, then it charges on PWM.
PROTO=$(opt ev_protocol); PROTO=${PROTO:-ISO_15118_2}
case "$PROTO" in
  ISO_15118_2) MODE=AC_three_phase_core ;;
  DIN_SPEC_70121) MODE=DC_extended ;;
  *) die "ev_protocol must be ISO_15118_2 or DIN_SPEC_70121" ;;
esac
jq --argjson n "$LOOPS" --arg p "$PROTO" --arg m "$MODE" \
  '.useTls=false | .enforceTls=false | .chargeLoopCycle=$n | .supportedProtocols=[$p] | .energyTransferMode=$m' \
  "$H/ev/evcc_config.json" > "$DATA/ev/evcc_config.json"
log "test EV offers $PROTO ($MODE)"
export NETWORK_INTERFACE=v2g1 PKI_PATH="$DATA/ev/pki/" EVCC_CONFIG_PATH="$DATA/ev/evcc_config.json" LOG_LEVEL=INFO
PAUSE=$(opt ev_pause_s)

# --- run both; stop the App if the station stops ----------------------------------
cd "$H/station"
python -m station --device-id "$DEV" --cert "$DATA/own/$DEV.pem" --key "$DATA/own/$DEV.pem" \
  --ca "$DATA/own/ca.crt" --address "$NAME:8883" --iface v2g0 --replug-s "$(opt replug_s)" \
  2>&1 | sed -u 's/^/[station] /' &
STATION=$!
sleep 3
( cd "$DATA/ev"; while kill -0 "$STATION" 2>/dev/null; do
    python -c "from iso15118.evcc.main import run; run()" 2>&1 | sed -u 's/^/[ev] /' || true
    sleep "$PAUSE"
  done ) &
EV=$!
trap 'kill "$STATION" "$EV" 2>/dev/null || true' TERM INT
log "running: station $DEV and test EV (simulated only, no physical charging control)"
rc=0; wait "$STATION" || rc=$?
kill "$EV" 2>/dev/null || true
die "station stopped (rc=$rc)"
