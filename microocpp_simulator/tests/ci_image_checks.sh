#!/bin/sh
# Image checks for a built MicroOCPP 2.0.1 App image, shared by PR CI and the
# publish job. Usage: ci_image_checks.sh <image-ref>   (from the repository root)
set -eu
IMAGE="$1"
docker tag "$IMAGE" microocpp:test

echo "== Native 2.0.1 smoke test"
docker build -q -t microocpp:smoke -f microocpp_simulator/tests/Dockerfile.smoke .
docker run --rm --network none microocpp:smoke

echo "== Offline App entrypoint and shutdown"
trap 'docker logs app-smoke 2>&1 | tail -50; docker rm -f app-smoke > /dev/null 2>&1 || true' EXIT
docker create --network none --name app-smoke "$IMAGE" > /dev/null
docker cp microocpp_simulator/tests/offline-options.json app-smoke:/data/options.json
docker start app-smoke > /dev/null
sleep 3
docker exec app-smoke python3 -c 'import json, urllib.request; data=json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/websocket")); assert data["backendUrl"] == ""; assert data["chargeBoxId"].startswith("SIM-")'
docker stop --time 12 app-smoke > /dev/null
test "$(docker inspect -f '{{.State.ExitCode}}' app-smoke)" = "0"
if docker logs app-smoke 2>&1 | grep -E 'connector with connectorId|could not find connector'; then
  exit 1
fi
echo "PASS: $IMAGE"
