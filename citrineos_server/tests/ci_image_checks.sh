#!/bin/sh
# Image checks shared by PR CI (citrineos.yml) and the publish gate
# (citrineos-server-publish.yml). Usage: ci_image_checks.sh <image>
# Run from the repository root (the route probe is mounted from the checkout).
set -eu
IMAGE="$1"
NAME="citrine-server-check-$$"
COMMIT=$(python3 -c "import json;print(json.load(open('citrineos_server/compatibility-lock.json'))['server']['commit'])")
trap 'docker logs "$NAME" 2>&1 | tail -40; docker rm -f "$NAME" > /dev/null 2>&1 || true' EXIT

echo "== Pinned source, licence, patches and runtime layout"
docker run --rm --entrypoint sh -e COMMIT="$COMMIT" "$IMAGE" -c '
  set -e
  test "$(cat /usr/share/doc/citrineos-core/COMMIT)" = "$COMMIT"
  test -s /usr/share/doc/citrineos-core/LICENSE
  test -s /opt/citrine-ha/compatibility-lock.json
  ls /usr/share/doc/citrineos-core/*.patch > /dev/null
  cd /usr/local/apps/citrineos/apps/ocpp-server
  for f in dist/index.js dist/scripts/provision-partitions.js dist/assets/logo.png \
    node_modules/.bin/sequelize-cli .sequelizerc; do test -e "$f"; done
  h=node_modules/@citrineos/ocpp/dist/src/handlers/requests/2
  grep -q "ha-citrine patch (0001-ocpp21-charging-needs)" $h/notify-ev-charging-needs-request-ocpp-2-handler.js
  grep -q "ha-citrine patch (0002-ocpp21-allowed-energy-transfer)" $h/authorize-request-ocpp-21-handler.js
  # The compiled-JS patchers of 0.7.x are gone.
  test -z "$(ls /opt/citrine-ha/patch-*.mjs 2>/dev/null)"
'

echo "== Upstream routes and permissions (no /dev routes in jwt mode)"
docker run --rm -v "$PWD/citrineos_server/tests:/probe:ro" --entrypoint node "$IMAGE" /probe/route-probe.mjs

echo "== Disconnected by default, unprivileged, clean shutdown"
docker create --network none --name "$NAME" "$IMAGE" > /dev/null
docker start "$NAME" > /dev/null
ok=""
for _ in $(seq 1 30); do
  if docker logs "$NAME" 2>&1 | grep -q "CitrineOS disconnected: no database, broker or server activity."; then ok=1; break; fi
  sleep 1
done
test -n "$ok"
docker exec "$NAME" sh -c 'grep -q "^Uid:[[:space:]]*1000" /proc/1/status'
docker stop --time 15 "$NAME" > /dev/null
code=$(docker inspect -f '{{.State.ExitCode}}' "$NAME")
test "$code" = 0 || { echo "exit code $code after SIGTERM"; exit 1; }
echo "PASS: $IMAGE"
