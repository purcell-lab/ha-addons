#!/bin/sh
# Extract the EVerest runtime image from a from-source EVerest build.
#
# Usage: everest_runtime_source.sh <dist image> <output tag>
# Env:   VERSION, MODULES (default: everest_runtime_source/VERSION, MODULES)
#
# <dist image> is everest_runtime_source/Dockerfile built locally. It has the
# everest-demo image layout, so the unchanged everest_runtime/Dockerfile
# extracts, prunes and strips it (EVEREST_IMAGE and MODULES are build
# arguments there). Then the runtime image's contents are checked.
set -eu
dist=$1
out=$2
VERSION=${VERSION:-$(cat everest_runtime_source/VERSION)}
MODULES=${MODULES:-$(cat everest_runtime_source/MODULES)}
kit=$(sed -n 's/^ARG BUILD_KIT_IMAGE=//p' everest_runtime_source/Dockerfile)
core_tag=$(sed -n 's/^ARG EVEREST_CORE_TAG=//p' everest_runtime_source/Dockerfile | head -1)
core_commit=$(sed -n 's/^ARG EVEREST_CORE_COMMIT=//p' everest_runtime_source/Dockerfile)
[ -n "$kit" ] && [ -n "$core_tag" ] && [ -n "$core_commit" ]

docker build --build-arg EVEREST_IMAGE="$dist" --build-arg MODULES="$MODULES" \
  --build-arg RUNTIME_VERSION="$VERSION" \
  --label org.opencontainers.image.base.name="$kit" \
  --label org.opencontainers.image.description="EVerest everest-core $core_tag ($core_commit) built from source" \
  -t "$out" everest_runtime

echo "== Runtime image contents"
tmp=$(mktemp -d)
cid=""
trap 'docker rm -f "$cid" > /dev/null 2>&1 || true; rm -rf "$tmp"' EXIT
cid=$(docker create "$out" /none)
docker export "$cid" | tar -C "$tmp" -xf -
need() { test -e "$tmp/$1" || { echo "::error::runtime image lacks /$1"; exit 1; }; echo "ok /$1"; }
need opt/everest/bin/manager
for module in $MODULES; do need "opt/everest/libexec/everest/modules/$module"; done
need opt/everest/lib/everest/everestpy
need opt/everest/libexec/everest/3rd_party/josev/iso15118
need opt/everest/share/everest/modules/OCPP201/component_config/standardized/InternalCtrlr.json
need opt/everest/share/everest/modules/OCPP201/core_migrations/7_up-der_controls_db.sql
need opt/everest/share/everest/modules/OCPP201/device_model_migrations
need opt/everest/share/everest/interfaces/grid_support.yaml
need opt/everest/share/everest/types/grid_support.yaml
need opt/everest/share/everest/www
need usr/share/doc/everest/EVerest-LICENSE
test "$(find "$tmp/usr/share/doc/everest/third_party" -type f | wc -l)" -gt 0 \
  || { echo "::error::no third-party licence files"; exit 1; }
echo "third-party licence files: $(find "$tmp/usr/share/doc/everest/third_party" -type f | wc -l)"
if find "$tmp" -name '*.key' -o -name '*.p12' | grep -q .; then
  echo "::error::private keys in the runtime image"; find "$tmp" -name '*.key' -o -name '*.p12'; exit 1
fi
echo "Runtime $VERSION: $(du -sh "$tmp/opt/everest" | cut -f1) under /opt/everest, $(docker save "$out" | gzip -c | wc -c) bytes gzipped" \
  | tee -a "${GITHUB_STEP_SUMMARY:-/dev/null}"
