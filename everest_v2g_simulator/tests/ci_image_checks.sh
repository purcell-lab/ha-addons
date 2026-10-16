#!/bin/sh
# Release gate for a built V2G App image, shared by PR CI and the publish job.
# Usage: ci_image_checks.sh <image-ref>   (run from the repository root)
# CHECKS=full (default, release gate) runs every acceptance scenario and the
# discovery recovery run on an IPv6 eth0 network.
# CHECKS=minimal (pull request CI) runs one OCPP 2.1 V2G session with the
# TxProfile steps, the fail-closed, self-test, listener and firewall checks.
# Offline, recovery, 2.0.1 fallback and pinned 2.0.1 run at release.
set -eu
IMAGE="$1"
TESTS=everest_v2g_simulator/tests
CHECKS="${CHECKS:-full}"
case "$CHECKS" in
  full) SCENARIOS="offline recovery v2g21 fallback pinned201" ;;
  minimal) SCENARIOS="v2g21" ;;
  *) echo "CHECKS must be full or minimal"; exit 2 ;;
esac
echo "== Checks: $CHECKS ($SCENARIOS)"

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
  grep -q "ha-everest: EV ISO 15118 stack stopped" /opt/everest/libexec/everest/modules/PyEvJosev/module.py
  grep -q "ha-everest: send SDP on the configured interface" /opt/everest/libexec/everest/3rd_party/josev/iso15118/evcc/transport/udp_client.py
  java -version 2>&1 | head -1; nft --version
  test "$(readlink -f /usr/bin/java)" = /opt/java/bin/java
  test ! -e /usr/lib/jvm'

echo "== EXI codec round trip on the slim Java runtime"
docker run --rm -v "$PWD/$TESTS:/tests:ro" --entrypoint python3 "$IMAGE" /tests/exi_roundtrip.py

echo "== Acceptance (no network): $SCENARIOS"
docker tag "$IMAGE" everest-v2g:test
docker build -q -t everest-v2g:smoke -f "$TESTS/Dockerfile.smoke" .
# shellcheck disable=SC2086
docker run --rm --network none --cap-add NET_ADMIN everest-v2g:smoke $SCENARIOS

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

echo "== Discovery with an IPv6 eth0 (as on Home Assistant OS)"
# Upstream Josev sent SDP by the first multicast route, which is eth0 on this
# IPv6 network and on HA OS; only the patched EV completes discovery here.
if [ "$CHECKS" = full ]; then
  docker run --rm --network "$net" --cap-add NET_ADMIN everest-v2g:smoke recovery > /tmp/recovery-eth0.log 2>&1 \
    || { tail -120 /tmp/recovery-eth0.log; exit 1; }
  grep "unscoped multicast via" /tmp/recovery-eth0.log
  grep -q "unscoped multicast via eth0" /tmp/recovery-eth0.log
else
  echo "recovery run on IPv6 eth0: release gate only; the start self-test below still runs on this network"
fi
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
echo "== Discovery self-test at start passes and diagnostics are served"
passed=no
for _ in $(seq 30); do
  if docker logs "$name" 2>&1 | grep -q "Discovery self-test PASSED: unicast=reply multicast=reply"; then
    passed=yes; break
  fi
  sleep 2
done
docker logs "$name" 2>&1 | grep "Discovery self-test" || true
test "$passed" = yes || { echo "Discovery self-test did not pass at start"; exit 1; }
# HA OS condition (0.1.2): on this IPv6 network an unscoped multicast would
# leave by eth0, as on HA OS. The self-test above must pass under it.
docker logs "$name" 2>&1 | grep "Discovery self-test PASSED" | grep -q "unscoped-multicast-via=eth0" \
  || { echo "test network does not reproduce the HA OS route (unscoped multicast via eth0)"; exit 1; }
docker exec "$name" python3 -c 'import json, urllib.request
d = json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/diagnostics"))
s = d["snapshot"]
assert d["selftest"]["pass"] is True, d["selftest"]
assert s["sdp_udp_listeners"], s
assert all(s["links"][n]["addresses"] for n in ("v2g0", "v2g1")), s["links"]
rules = {r["rule"]: r["packets"] for r in s["firewall"]["rules"]}
assert rules["private V2G link"] > 0 and "dropped by policy" in rules, rules
print("diagnostics:", json.dumps({"capture": {k: v.get("count", v.get("error")) for k, v in d["selftest"]["capture"].items()}, "firewall": rules}))'
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
