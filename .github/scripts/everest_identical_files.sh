#!/bin/sh
# Identical-file check for the EVerest runtime image.
#
# Usage: everest_identical_files.sh <runtime image ref> <arch: amd64|aarch64>
#
# For each EVerest App, builds the App from the given runtime image and
# compares it with the published release image of the version in its
# config.yaml (built from the upstream 4.3 GB image directly). These paths
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
status=0
for app in everest_simulator everest_v2g_simulator; do
  version=$(sed -n 's/^version: "\(.*\)"$/\1/p' "$app/config.yaml")
  image=$(sed -n 's/^image: //p' "$app/config.yaml" | sed "s/{arch}/$arch/")
  release="$image:$version"
  candidate="identical-check/$app:$arch"
  echo "== $app $version ($arch): release $release vs build from $runtime"
  if ! docker pull -q "$release" > /dev/null 2>&1; then
    echo "::warning::$release is not published; nothing to compare for $app"
    continue
  fi
  docker build -q --build-arg BUILD_ARCH="$arch" --build-arg BUILD_VERSION="$version" \
    --build-arg EVEREST_RUNTIME="$runtime" -t "$candidate" "$app" > /dev/null
  if python3 "$here/image_tree_compare.py" "$release" "$candidate" \
       --strict opt/everest --strict usr/share/doc/everest --strict opt/ha-everest \
       --strict usr/local/lib/python3.11 \
       --report "identical-files/$app-$arch.json"; then
    echo "PASS: $app $version $arch is file-for-file identical under the strict paths"
  else
    status=1
  fi
done
exit $status
