#!/bin/sh
# Image checks for a built Open Dynamic Export App image, shared by PR CI and
# the publish job. Usage: ci_image_checks.sh <image-ref>   (from the repo root)
# Offline only: a fixed export limit, an unreachable SunSpec device and
# inverter control off, so nothing outside the container is contacted.
set -eu
IMAGE="$1"
TESTS=open_dynamic_export/tests
NAME=ode-app-smoke

echo "== Packaged files"
docker run --rm --entrypoint sh "$IMAGE" -c '
  set -e
  cat /usr/share/doc/open-dynamic-export/COMMIT
  test "$(cat /usr/share/doc/open-dynamic-export/COMMIT)" = bc807abbc4c58be3294257ee76f0348dc87c4945
  test -s /usr/share/doc/open-dynamic-export/LICENSE
  test -s /usr/share/doc/open-dynamic-export/ingress.patch
  test -s /usr/share/doc/open-dynamic-export/ramp-tms.patch
  test -s /usr/share/doc/open-dynamic-export/influxdb-quiet.patch
  test -s /usr/share/doc/open-dynamic-export/stdout-log-level.patch
  grep -q STDOUT_LOGLEVEL /app/dist/helpers/logger.js
  grep -q rampTmsToSeconds /app/dist/setpoints/csipAus/index.js
  grep -q "status(503)" /app/dist/app.js
  test "$(readlink /app/logs)" = /tmp/ode-logs
  grep -q "src=\"./assets/" /app/dist/ui/index.html
  ! grep -q "src=\"/assets/" /app/dist/ui/index.html
  grep -rq "hassio_ingress" /app/dist/ui/assets
  node --version'

echo "== Missing configuration fails closed"
docker rm -f "$NAME" > /dev/null 2>&1 || true
docker create --network none --name "$NAME" "$IMAGE" > /dev/null
docker cp "$TESTS/options-empty.json" "$NAME:/data/options.json"
docker start -a "$NAME" > "$NAME.log" 2>&1 || true
grep -q "Open Dynamic Export not started: No configuration" "$NAME.log"
test "$(docker inspect -f '{{.State.ExitCode}}' "$NAME")" = 1
docker rm -f "$NAME" > /dev/null

echo "== Offline start, UI and API, clean shutdown"
trap 'docker logs "$NAME" 2>&1 | tail -40; docker rm -f "$NAME" > /dev/null 2>&1 || true' EXIT
docker create --network none --name "$NAME" "$IMAGE" > /dev/null
docker cp "$TESTS/options-offline.json" "$NAME:/data/options.json"
docker start "$NAME" > /dev/null
ok=""
for _ in $(seq 1 60); do
  if docker exec "$NAME" node -e '
    fetch("http://127.0.0.1:3000/api/coordinator/status").then(r => r.json())
      .then(d => process.exit(d.running === true ? 0 : 1)).catch(() => process.exit(1))'; then
    ok=1; break
  fi
  sleep 2
done
test -n "$ok" || { echo "coordinator did not report running"; exit 1; }
docker exec "$NAME" node -e '
  fetch("http://127.0.0.1:3000/").then(r => r.text()).then(t => {
    if (!t.includes("./assets/")) { console.error("index.html assets are not relative"); process.exit(1); }
  })'
docker exec "$NAME" sh -c 'test -s /data/ode/config.json && test "$(stat -c %a /data/ode/config.json)" = 600'
docker stop --time 15 "$NAME" > /dev/null
code=$(docker inspect -f '{{.State.ExitCode}}' "$NAME")
test "$code" = 0 || { echo "exit code $code after SIGTERM"; exit 1; }
echo "PASS: $IMAGE"
