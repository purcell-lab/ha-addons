#!/bin/sh
# Identical-file check for the EVerest runtime image.
#
# Usage: everest_identical_files.sh <runtime image ref> <arch: amd64|aarch64>
#
# For each EVerest App, builds the App from the given runtime image and
# compares it with the reference release listed in everest_runtime/REFERENCE
# (built from the upstream 4.3 GB image directly). App version labels may
# differ; files may not. These paths
# must be identical (type, mode, owner, content or link target):
#   /opt/everest           EVerest runtime, modules, Josev, App stub/patches
#   /usr/share/doc/everest licences and UPSTREAM.md
#   /opt/ha-everest        App code
#   /usr/local/lib/python3.11  pinned Python packages (V2G)
# Differences elsewhere (Debian packages resolved by apt at build time) are
# listed for information. Reports are written to identical-files/.
set -eu
runtime=$1
arch=$2
here=$(dirname "$0")
mkdir -p identical-files
grep -v '^#' everest_runtime/REFERENCE | while read -r app reference; do
  [ -n "$app" ] || continue
  version=$(sed -n 's/^version: "\(.*\)"$/\1/p' "$app/config.yaml")
  image=$(sed -n 's/^image: //p' "$app/config.yaml" | sed "s/{arch}/$arch/")
  release="$image:$reference"
  candidate="identical-check/$app:$arch"
  echo "== $app $version ($arch): reference release $release vs build from $runtime"
  docker pull -q "$release" > /dev/null || { echo "::error::reference $release is not pullable"; exit 1; }
  docker build -q --build-arg BUILD_ARCH="$arch" --build-arg BUILD_VERSION="$version" \
    --build-arg EVEREST_RUNTIME="$runtime" -t "$candidate" "$app" > /dev/null
  if python3 "$here/image_tree_compare.py" "$release" "$candidate" \
       --strict opt/everest --strict usr/share/doc/everest --strict opt/ha-everest \
       --strict usr/local/lib/python3.11 \
       --report "identical-files/$app-$arch.json"; then
    echo "PASS: $app $version $arch is file-for-file identical to $reference under the strict paths"
  else
    exit 1
  fi
done
