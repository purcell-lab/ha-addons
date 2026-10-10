#!/bin/sh
# Release gate for a built App image, shared by PR CI and the publish job.
# Usage: ci_image_checks.sh <image-ref>   (run from the repository root)
set -eu
IMAGE="$1"

echo "== Packaged runtime has no V2G or ISO 15118 modules"
docker run --rm --entrypoint sh "$IMAGE" -c \
  'ls /opt/everest/libexec/everest/modules; ! ls /opt/everest/libexec/everest/modules | grep -E "V2G|Josev|Iso15118|Slac"'

echo "== OCPP 2.1, 2.0.1 fallback, pinned 2.0.1 and offline acceptance (no network)"
docker tag "$IMAGE" everest:test
docker build -q -t everest:smoke -f everest_simulator/tests/Dockerfile.smoke .
docker run --rm --network none everest:smoke

echo "== Offline App entrypoint, listeners and clean shutdown"
name="everest-check-$$"
trap 'docker logs "$name" 2>&1 | tail -80; docker rm -f "$name" >/dev/null 2>&1 || true' EXIT
docker create --network none --name "$name" "$IMAGE" >/dev/null
docker cp everest_simulator/tests/offline-options.json "$name":/data/options.json
docker start "$name" >/dev/null
ready=no
for _ in $(seq 60); do
  if docker exec "$name" python3 -c 'import json, urllib.request; s=json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/status")); assert s["app"]["csms_configured"] is False; assert s["app"]["offered_subprotocols"] == ["ocpp2.1", "ocpp2.0.1"]; assert s["evse"]["session_info"]["value"]["state"] == "Unplugged"' 2>/dev/null; then
    ready=yes; break
  fi
  sleep 2
done
test "$ready" = yes || { echo "App did not reach a disconnected, Unplugged state"; exit 1; }
docker cp everest_simulator/tests/listeners.py "$name":/tmp/listeners.py
docker exec "$name" python3 /tmp/listeners.py
docker stop --time 25 "$name" >/dev/null
test "$(docker inspect -f '{{.State.ExitCode}}' "$name")" = "0"
echo "== All image checks passed for $IMAGE"
