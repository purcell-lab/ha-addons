#!/bin/sh
# Image checks shared by PR CI (operator-ui.yml) and the publish gate
# (operator-ui-publish.yml). Usage: ci_image_checks.sh <image>
set -eu
IMAGE="$1"
NAME="operator-ui-check-$$"
TMP=$(mktemp -d)
trap 'docker logs "$NAME" 2>&1 | tail -40; docker rm -f "$NAME" > /dev/null 2>&1 || true; rm -rf "$TMP"' EXIT

echo "== Packaged upstream, licence and patch"
docker run --rm --entrypoint sh "$IMAGE" -c '
  test "$(cat /usr/share/doc/citrineos-operator-ui/COMMIT)" = 4fd7599b91c2fb6e6065e7c9b94be69880cced27
  test -s /usr/share/doc/citrineos-operator-ui/LICENSE
  test -s /usr/share/doc/citrineos-operator-ui/operator-ui.patch
  test -s /usr/share/doc/citrineos-operator-ui/UPSTREAM.md
  test -f /app/apps/operator-ui/server.js
  # No development .env file (it carried an admin secret and password).
  test -z "$(find /app -name ".env*" | head -1)"
  # The browser bundle targets the same-origin proxy, not upstream defaults.
  grep -rqs "/__ha_ingress_base__/hasura/v1/graphql" /app/apps/operator-ui/.next/static
'

echo "== Missing configuration fails closed"
printf '{}' > "$TMP/empty.json"
docker create --network none --name "$NAME" "$IMAGE" > /dev/null
docker cp "$TMP/empty.json" "$NAME:/data/options.json"
docker start -a "$NAME" > "$TMP/log" 2>&1 || true
grep -q "Operator UI not started: gateway_url" "$TMP/log"
test "$(docker inspect -f '{{.State.ExitCode}}' "$NAME")" = 1
docker rm -f "$NAME" > /dev/null

echo "== Start, Ingress prefix, proxy routes, unprivileged, clean shutdown"
printf '{"gateway_url":"http://127.0.0.1:19","operator_token":"%s","commands_enabled":false}' \
  "$(printf 'a%.0s' $(seq 1 64))" > "$TMP/options.json"
# Inside the container requests come from loopback, so trust it for the check.
docker create --network none -e OPERATOR_UI_TRUSTED_PEER=127.0.0.1 --name "$NAME" "$IMAGE" > /dev/null
docker cp "$TMP/options.json" "$NAME:/data/options.json"
docker start "$NAME" > /dev/null
ok=""
for _ in $(seq 1 60); do
  if docker exec "$NAME" node -e '
    const h={"x-ingress-path":"/api/hassio_ingress/CiToken_1"};
    const get=(p,o={})=>fetch("http://127.0.0.1:8099"+p,{redirect:"manual",...o,headers:{...h,...(o.headers||{})}});
    (async()=>{
      const page=await get("/charging-stations");const html=await page.text();
      if(page.status!==200||!html.includes("/api/hassio_ingress/CiToken_1/_next/")||html.includes("__ha_ingress_base__"))process.exit(1);
      const gql=await get("/hasura/v1/graphql",{method:"POST",body:"{}"});
      if(gql.status!==502)process.exit(2);
      const cmd=await get("/core/ocpp/2.0.1/configuration/reset?identifier=A&tenantId=1",{method:"POST",body:"{}"});
      if(cmd.status!==403)process.exit(3);
      const perms=await get("/core/permissions/user");
      if(perms.status!==200||(await perms.json()).enforcing!==false)process.exit(5);
      const dev=await get("/core/dev/token",{method:"POST",body:"{}"});
      if(dev.status!==404)process.exit(6);
    })().catch(()=>process.exit(4));
  ' 2>/dev/null; then ok=1; break; fi
  sleep 1
done
test -n "$ok"
docker exec "$NAME" sh -c 'grep -q "^Uid:[[:space:]]*1001" /proc/1/status'
docker stop --time 15 "$NAME" > /dev/null
code=$(docker inspect -f '{{.State.ExitCode}}' "$NAME")
test "$code" = 0 || { echo "exit code $code after SIGTERM"; exit 1; }
echo "PASS: $IMAGE"
