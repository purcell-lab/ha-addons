#!/usr/bin/env bash
# Imatra ISO 15118-2 Lab: one container in place of upstream's Compose project.
#
# Order on every start (upstream's "depends_on" order):
#   secrets, preflight, PKI, broker auth  (one-shot, upstream scripts unmodified)
#   Postgres, Valkey, Mosquitto           (internal, 127.0.0.1 only; 8883 for devices)
#   API (applies the migrations)          (127.0.0.1:8000)
#   engine, relay, projector              (health ports on 127.0.0.1)
#   gateway                               (Caddy on 8080: /v1 and /health)
#   device certificates and registry      (from the App options)
# If any service exits, everything stops and the App exits with an error.
#
# Never printed or logged: the generated passwords, the operator key, private keys.
set -euo pipefail

OPT=${OPTIONS_FILE:-/data/options.json}
DATA=${DATA_DIR:-/data}
SHARE=${SHARE_DIR:-/share/imatra}
PG_BIN=/usr/lib/postgresql/16/bin

log() { echo "[imatra-ha] $*"; }
die() { echo "[imatra-ha] ERROR: $*" >&2; exit 1; }
opt() { jq -r "$1 // empty" "$OPT"; }

[ -f "$OPT" ] || die "no options file at $OPT"

# --- options -----------------------------------------------------------------
OPERATOR_KEY=$(opt '.operator_api_key')
[ -n "$OPERATOR_KEY" ] || die "set operator_api_key in the App configuration (16+ characters, e.g. openssl rand -hex 24)"
case "$OPERATOR_KEY" in *[!A-Za-z0-9._~+-]*) die "operator_api_key: letters, digits and . _ ~ + - only" ;; esac
BROKER_DNS=$(opt '.broker_dns'); BROKER_DNS=${BROKER_DNS:-$(hostname)}
BROKER_IPS=$(opt '.broker_ips | join(" ")')
case "$(opt '.evse_phases')" in 1|3) ;; *) die "evse_phases must be 1 or 3" ;; esac

# --- persistent layout and secrets ---------------------------------------------
mkdir -p "$DATA/pki" "$DATA/mqtt-auth" "$DATA/mqtt-data" "$DATA/postgres" "$DATA/valkey" \
         "$DATA/caddy" "$DATA/registry" /mosquitto/conf.d /run/postgresql
# The paths upstream's broker configuration and scripts expect.
for link in /pki:"$DATA/pki" /mosquitto/auth:"$DATA/mqtt-auth" /mosquitto/data:"$DATA/mqtt-data"; do
  target=${link#*:}; path=${link%%:*}
  [ -L "$path" ] || { rm -rf "$path"; ln -s "$target" "$path"; }
done
chmod 0755 "$DATA/pki"
chown 1883:1883 "$DATA/mqtt-data"
chown postgres:postgres "$DATA/postgres" /run/postgresql && chmod 0700 "$DATA/postgres"
chown imatra:imatra "$DATA/valkey" "$DATA/caddy"

SECRETS="$DATA/secrets.env"
if [ ! -f "$SECRETS" ]; then
  umask 077
  { echo "POSTGRES_PASSWORD=$(openssl rand -hex 24)"
    echo "MQTT_SERVER_PASSWORD=$(openssl rand -hex 24)"; } > "$SECRETS"
  umask 022
  log "generated the internal database and broker passwords (kept in /data, never shown)"
fi
set -a
# shellcheck disable=SC1090
. "$SECRETS"
POSTGRES_DB=imatra
POSTGRES_USER=imatra
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
VALKEY_ADDR=127.0.0.1:6379
MQTT_HOST=127.0.0.1
MQTT_PORT=1883
MQTT_CONF=/etc/imatra/mosquitto.conf
PKI_MODE=own
OPERATOR_API_KEYS="admin:${OPERATOR_KEY}"
EVSE_MAX_CURRENT_A=$(opt '.evse_max_current_a')
EVSE_NOMINAL_VOLTAGE_V=$(opt '.evse_nominal_voltage_v')
EVSE_PHASES=$(opt '.evse_phases')
HEALTH_ADDR=127.0.0.1:8090
RELAY_HEALTH_ADDR=127.0.0.1:8091
PROJECTOR_HEALTH_ADDR=127.0.0.1:8092
API_DB_POOL=6
SITE_ADDRESS=:8080
TRUSTED_PROXIES=127.0.0.1/32
XDG_DATA_HOME="$DATA/caddy"
XDG_CONFIG_HOME="$DATA/caddy"
set +a
export BROKER_DNS BROKER_IPS

# --- one-shot steps: upstream scripts, unmodified ---------------------------
/usr/local/bin/preflight.sh
/usr/local/bin/pki-init.sh init
/usr/local/bin/mqtt-init.sh

# Run as a service user. Arrays, not functions, for background services, so
# that the PID kept is the service itself and signals reach it.
AS_IMATRA=(setpriv --reuid=imatra --regid=imatra --init-groups)
AS_POSTGRES=(setpriv --reuid=postgres --regid=postgres --init-groups)
as_imatra() { "${AS_IMATRA[@]}" "$@"; }

# --- Postgres ------------------------------------------------------------------
if [ ! -s "$DATA/postgres/PG_VERSION" ]; then
  log "initialising the database"
  pwfile=$(mktemp); printf '%s' "$POSTGRES_PASSWORD" > "$pwfile"; chown postgres "$pwfile"
  "${AS_POSTGRES[@]}" "$PG_BIN/initdb" -D "$DATA/postgres" -U "$POSTGRES_USER" --pwfile="$pwfile" \
      --auth-local=scram-sha-256 --auth-host=scram-sha-256 -E UTF8 >/dev/null
  rm -f "$pwfile"
  INIT_DB=1
fi


PIDS=()
NAMES=()
start() { # name command...
  local name=$1; shift
  "$@" &
  PIDS+=("$!"); NAMES+=("$name")
}

stop_all() {
  trap - TERM INT
  log "stopping"
  local i
  for (( i=${#PIDS[@]}-1; i>=0; i-- )); do
    # Postgres: fast shutdown (SIGINT); the others: SIGTERM. A few seconds each.
    if [ "${NAMES[$i]}" = postgres ]; then sig=INT; else sig=TERM; fi
    kill -"$sig" "${PIDS[$i]}" 2>/dev/null || true
    for _ in $(seq 1 20); do kill -0 "${PIDS[$i]}" 2>/dev/null || break; sleep 0.5; done
  done
}
trap 'stop_all; exit 0' TERM INT

wait_until() { # what seconds command...
  local what=$1 secs=$2; shift 2
  for _ in $(seq 1 "$secs"); do "$@" >/dev/null 2>&1 && { log "ready: $what"; return 0; }; sleep 1; done
  stop_all; die "$what did not become ready in ${secs}s"
}

# Nothing else starts Postgres in this container: a lock left by an unclean
# stop would otherwise block the start if its PID is reused after a restart.
rm -f "$DATA/postgres/postmaster.pid" /run/postgresql/.s.PGSQL.5432*
start postgres "${AS_POSTGRES[@]}" "$PG_BIN/postgres" -D "$DATA/postgres" \
  -c listen_addresses=127.0.0.1 -c port=5432 -c unix_socket_directories=/run/postgresql \
  -c shared_buffers=64MB -c effective_cache_size=192MB -c work_mem=4MB -c maintenance_work_mem=32MB \
  -c max_wal_size=512MB -c max_connections=60 -c wal_compression=on -c random_page_cost=1.1 \
  -c log_min_duration_statement=500
wait_until "Postgres" 60 "$PG_BIN/pg_isready" -h 127.0.0.1 -p 5432 -q
if [ "${INIT_DB:-0}" = 1 ]; then
  PGPASSWORD=$POSTGRES_PASSWORD "$PG_BIN/createdb" -h 127.0.0.1 -U "$POSTGRES_USER" -O "$POSTGRES_USER" "$POSTGRES_DB"
  log "database created"
fi

start valkey "${AS_IMATRA[@]}" valkey-server --bind 127.0.0.1 --port 6379 --protected-mode yes --dir "$DATA/valkey" \
  --appendonly yes --appendfsync everysec --save "" --maxmemory 128mb --maxmemory-policy noeviction
wait_until "Valkey" 30 valkey-cli -h 127.0.0.1 ping

start mosquitto /usr/local/bin/mqtt-run.sh
wait_until "Mosquitto" 30 mosquitto_pub -h 127.0.0.1 -p 1883 -u server -P "$MQTT_SERVER_PASSWORD" -t svc/ha-ready -n

start api "${AS_IMATRA[@]}" sh -c 'cd /srv && exec uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log'
wait_until "API (migrations applied)" 120 curl -fsS http://127.0.0.1:8000/health

start engine "${AS_IMATRA[@]}" /usr/local/bin/engine
start relay "${AS_IMATRA[@]}" /usr/local/bin/relay
start projector "${AS_IMATRA[@]}" /usr/local/bin/projector
wait_until "engine" 60 as_imatra /usr/local/bin/engine healthcheck
wait_until "relay" 60 as_imatra /usr/local/bin/relay healthcheck
wait_until "projector" 60 as_imatra /usr/local/bin/projector healthcheck

start gateway "${AS_IMATRA[@]}" caddy run --config /etc/imatra/Caddyfile --adapter caddyfile
wait_until "gateway on 8080" 30 curl -fsS http://127.0.0.1:8080/health

# --- device certificates and registry (lab devices from the options) ------------
mkdir -p "$SHARE/devices"
cp /pki/ca.crt "$SHARE/ca.crt" && chmod 0644 "$SHARE/ca.crt"
count=$(jq '.devices | length' "$OPT")
for i in $(seq 0 $(( count - 1 ))); do
  id=$(jq -r ".devices[$i].id" "$OPT")
  type=$(jq -r ".devices[$i].type // \"station\"" "$OPT")
  rules=$(jq -r ".devices[$i].rules // \"\"" "$OPT")
  [[ "$id" =~ ^[a-z0-9][a-z0-9-]{2,62}$ ]] || { log "skipping device '$id': lowercase letters, digits and '-', 3..63"; continue; }
  if [ -n "$rules" ] && ! jq -e 'type == "object"' >/dev/null 2>&1 <<<"$rules"; then
    log "skipping device $id: rules must be a JSON object"; continue
  fi
  pem="$SHARE/devices/$id.pem"
  if [ ! -s "$pem" ]; then
    ( umask 077; /usr/local/bin/pki-init.sh device "$id" > "$pem.tmp" ) && mv "$pem.tmp" "$pem"
    log "device $id: certificate issued to /share/imatra/devices/$id.pem (test key, lab only)"
  fi
  # Registry entry as upstream scripts/registry.sh writes it; published again
  # only when the type or rules change (a new binding_ver each time).
  desired=$(jq -cn --arg id "$id" --arg type "$type" --arg rules "$rules" \
    '{device_id:$id, state:"bound", type:$type} + (if $rules == "" then {} else {rules: ($rules|fromjson)} end)')
  if [ "$(cat "$DATA/registry/$id.json" 2>/dev/null)" != "$desired" ]; then
    msg=$(jq -c --argjson ver "$(date +%s%3N)" --arg at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      '{v:1, device_id, state, type, binding_ver:$ver, at:$at, tz:""} + (if .rules then {rules} else {} end)' <<<"$desired")
    mosquitto_pub -h 127.0.0.1 -p 1883 -u server -P "$MQTT_SERVER_PASSWORD" -q 1 -r -t "registry/dev/$id" -m "$msg"
    printf '%s' "$desired" > "$DATA/registry/$id.json"
    log "device $id: registry entry published (bound, type $type)"
  fi
done

log "running: Imatra $(cat /usr/share/doc/imatra/COMMIT | cut -c1-7), broker name $BROKER_DNS, devices on 8883 (mTLS), API on 8080"
log "CA fingerprint $(openssl x509 -in /pki/ca.crt -noout -fingerprint -sha256 | cut -d= -f2)"

# --- supervise -------------------------------------------------------------------
set +e
wait -n "${PIDS[@]}"
rc=$?
for i in "${!PIDS[@]}"; do
  kill -0 "${PIDS[$i]}" 2>/dev/null || log "service stopped: ${NAMES[$i]}"
done
stop_all
exit $(( rc == 0 ? 1 : rc ))
