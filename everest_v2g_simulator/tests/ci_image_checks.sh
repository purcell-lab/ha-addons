#!/bin/sh
# Release gate for a built V2G App image, shared by PR CI and the publish job.
# Usage: ci_image_checks.sh <image-ref>   (run from the repository root)
set -eu
IMAGE="$1"
TESTS=everest_v2g_simulator/tests

echo "== Packaged runtime has the DC V2G modules and no private keys"
docker run --rm --entrypoint sh "$IMAGE" -c '
  set -e
  ls /opt/everest/libexec/everest/modules
  for m in Evse15118D20 PyEvJosev DCSupplySimulator SlacSimulator IMDSimulator; do
    test -d /opt/everest/libexec/everest/modules/$m
  done
  ! ls /opt/everest/libexec/everest/modules | grep -x EvseV2G
  test ! -e /opt/everest/etc/everest/certs
  test -z "$(find / -xdev \( -name "*.key" -o -name "*LEAF*" -o -name "*.p12" \) \
    -not -path "/proc/*" -not -path "/usr/share/*" 2>/dev/null)"
  java -version 2>&1 | head -1; nft --version'

echo "== OCPP 2.1 V2G, 2.0.1 fallback, pinned 2.0.1 and offline acceptance (no network)"
docker tag "$IMAGE" everest-v2g:test
docker build -q -t everest-v2g:smoke -f "$TESTS/Dockerfile.smoke" .
docker run --rm --network none --cap-add NET_ADMIN everest-v2g:smoke

echo "== Fails closed without NET_ADMIN"
nocap="v2g-nocap-$$"
docker create --network none --name "$nocap" "$IMAGE" >/dev/null
docker cp "$TESTS/offline-options.json" "$nocap":/data/options.json
docker start -a "$nocap" > /tmp/$nocap.log 2>&1 || true
tail -20 /tmp/$nocap.log
grep -q "V2G isolation setup failed" /tmp/$nocap.log
! grep -q "Starting SDP server" /tmp/$nocap.log
test "$(docker inspect -f '{{.State.ExitCode}}' "$nocap")" != "0"
docker rm "$nocap" >/dev/null

echo "== Offline entrypoint, listeners, firewall probe and clean shutdown"
name="v2g-check-$$"
net="v2g-net-$$"
trap 'docker logs "$name" 2>&1 | tail -80; docker rm -f "$name" >/dev/null 2>&1 || true; docker network rm "$net" >/dev/null 2>&1 || true' EXIT
docker network create --ipv6 --subnet 172.31.250.0/24 --subnet fd00:2026:10::/64 "$net" >/dev/null
docker create --network "$net" --cap-add NET_ADMIN --name "$name" "$IMAGE" >/dev/null
docker cp "$TESTS/offline-options.json" "$name":/data/options.json
docker cp "$TESTS/listeners.py" "$name":/tmp/listeners.py
docker cp "$TESTS/fwprobe.py" "$name":/tmp/fwprobe.py
docker start "$name" >/dev/null
ready=no
for _ in $(seq 60); do
  if docker exec "$name" python3 -c 'import json, urllib.request; s=json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/status")); assert s["app"]["csms_configured"] is False; assert s["app"]["offered_subprotocols"] == ["ocpp2.1", "ocpp2.0.1"]; assert s["evse"]["session_info"]["value"]["state"] == "Unplugged"' 2>/dev/null; then
    ready=yes; break
  fi
  sleep 2
done
test "$ready" = yes || { echo "App did not reach a disconnected, Unplugged state"; exit 1; }
sleep 5
docker exec "$name" nft list table inet ha_everest_v2g
docker exec "$name" python3 /tmp/listeners.py
docker exec "$name" python3 /tmp/fwprobe.py private-link
ip4=$(docker inspect -f "{{(index .NetworkSettings.Networks \"$net\").IPAddress}}" "$name")
ip6=$(docker inspect -f "{{(index .NetworkSettings.Networks \"$net\").GlobalIPv6Address}}" "$name")
echo "App addresses: $ip4 $ip6"
probe() { docker run --rm --network "$net" -v "$PWD/$TESTS:/t:ro" --entrypoint python3 "$IMAGE" /t/fwprobe.py "$@"; }
probe expect-silence "$ip4" ${ip6:+"$ip6"}
# Negative control: without the nftables table, nginx on 8099 answers.
docker exec "$name" nft delete table inet ha_everest_v2g
probe expect-reachable "$ip4"
docker stop --time 25 "$name" >/dev/null
test "$(docker inspect -f '{{.State.ExitCode}}' "$name")" = "0"
echo "== All image checks passed for $IMAGE"
