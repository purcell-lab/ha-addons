#!/bin/sh
# Identical-file check for the EVerest runtime image.
#
# Usage: everest_identical_files.sh <runtime image ref> <arch: amd64|aarch64>
#
# For each EVerest App, builds the App twice from the same source tree: once
# from the runtime the App Dockerfile pins (ARG EVEREST_RUNTIME, public and
# digest-pinned) and once from the given runtime, then compares the two.
# This isolates what the runtime change does to the shipped Apps, on every
# architecture, without needing a published App release per architecture.
# App version labels may differ; files may not. These paths must be
# identical (type, mode, owner, content or link target):
#   /opt/everest           EVerest runtime, modules, Josev, App stub/patches
#   /usr/share/doc/everest licences and UPSTREAM.md
#   /opt/ha-everest        App code
#   /usr/local/lib/python3.11  pinned Python packages (V2G)
# Differences elsewhere (Debian packages resolved by apt at build time) are
# listed for information. Reviewed, intended strict differences are listed
# in everest_runtime/EXPECTED_DIFFERENCES. Reports go to identical-files/.
set -eu
runtime=$1
arch=$2
here=$(dirname "$0")
mkdir -p identical-files
for app in everest_simulator everest_v2g_simulator; do
  version=$(sed -n 's/^version: "\(.*\)"$/\1/p' "$app/config.yaml")
  pinned=$(sed -n 's/^ARG EVEREST_RUNTIME=//p' "$app/Dockerfile")
  echo "$pinned" | grep -q '@sha256:[0-9a-f]\{64\}$' || {
    echo "::error::$app/Dockerfile EVEREST_RUNTIME is not digest-pinned: $pinned"; exit 1; }
  baseline="identical-check/$app-pinned:$arch"
  candidate="identical-check/$app:$arch"
  echo "== $app $version ($arch): build from pinned $pinned vs build from $runtime"
  for pair in "$baseline=$pinned" "$candidate=$runtime"; do
    docker build -q --build-arg BUILD_ARCH="$arch" --build-arg BUILD_VERSION="$version" \
      --build-arg EVEREST_RUNTIME="${pair#*=}" -t "${pair%%=*}" "$app" > /dev/null
  done
  if python3 "$here/image_tree_compare.py" "$baseline" "$candidate" \
       --strict opt/everest --strict usr/share/doc/everest --strict opt/ha-everest \
       --strict usr/local/lib/python3.11 \
       --expected everest_runtime/EXPECTED_DIFFERENCES \
       --report "identical-files/$app-$arch.json"; then
    echo "PASS: $app $version $arch from $runtime matches the pinned runtime build under the strict paths (expected differences listed above)"
  else
    exit 1
  fi
done
