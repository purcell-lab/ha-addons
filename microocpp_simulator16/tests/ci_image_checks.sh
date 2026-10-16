#!/bin/sh
# Image checks for a built MicroOCPP 1.6 App image, shared by PR CI and the
# publish job. Usage: ci_image_checks.sh <image-ref>   (from the repository root)
set -eu
IMAGE="$1"
docker tag "$IMAGE" microocpp16:test

echo "== Native 1.6 smart-charging acceptance"
docker build -q -t microocpp16:smoke -f microocpp_simulator16/tests/Dockerfile.smoke .
docker run --rm --network none microocpp16:smoke

echo "== Offline App entrypoint and shutdown"
trap 'docker logs app16-smoke 2>&1 | tail -50; docker rm -f app16-smoke > /dev/null 2>&1 || true' EXIT
docker create --network none --name app16-smoke "$IMAGE" > /dev/null
docker cp microocpp_simulator16/tests/offline-options.json app16-smoke:/data/options.json
docker start app16-smoke > /dev/null
sleep 3
docker exec app16-smoke python3 -c 'import json, urllib.request; data=json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/websocket")); assert data["backendUrl"] == ""; assert data["chargeBoxId"] == "SIM-16-MICROOCPP-01"'
docker stop --time 12 app16-smoke > /dev/null
test "$(docker inspect -f '{{.State.ExitCode}}' app16-smoke)" = "0"
echo "PASS: $IMAGE"
