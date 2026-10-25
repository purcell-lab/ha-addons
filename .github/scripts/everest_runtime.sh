#!/bin/sh
# Resolve the EVerest runtime image for an EVerest App build.
#
# Usage: everest_runtime.sh <app directory>
# Env:   BASE, HEAD (pull request SHAs, optional), GITHUB_OUTPUT
#
# Uses the Dockerfile's pinned ARG EVEREST_RUNTIME when it is pinned by
# digest and pullable, and the pull request does not change the runtime
# directory it comes from. Otherwise it asks for a local runtime build so the
# App is still built and tested. Outputs: ref, build_local, dir.
#
# dir is the runtime build directory whose VERSION has the same EVerest
# version as the pinned tag (the tag without its trailing -<n>):
#   everest_runtime/         extract of the upstream everest-demo image
#   everest_runtime_source/  EVerest compiled from source
set -eu
app=$1
out=${GITHUB_OUTPUT:-/dev/stdout}
ref=$(sed -n 's/^ARG EVEREST_RUNTIME=//p' "$app/Dockerfile")
[ -n "$ref" ] || { echo "::error::$app/Dockerfile has no ARG EVEREST_RUNTIME"; exit 1; }

# Tag of the ref (between ':' and an optional '@sha256:...'), without -<n>.
tag=${ref%@*}
tag=${tag##*:}
base=$(echo "$tag" | sed 's/-[0-9][0-9]*$//')
dir=""
for candidate in everest_runtime everest_runtime_source; do
  [ -f "$candidate/VERSION" ] || continue
  if [ "$(sed 's/-[0-9][0-9]*$//' "$candidate/VERSION")" = "$base" ]; then
    dir=$candidate
  fi
done
[ -n "$dir" ] || { echo "::error::no runtime directory has a VERSION for EVerest $base ($ref)"; exit 1; }

why=""
if [ -n "${BASE:-}" ] && [ -n "${HEAD:-}" ] \
   && git diff --name-only "$BASE...$HEAD" | grep -q "^$dir/"; then
  why="this pull request changes $dir/"
elif ! echo "$ref" | grep -q '@sha256:[0-9a-f]\{64\}$'; then
  why="$ref is not pinned by digest yet"
elif ! docker manifest inspect "$ref" > /dev/null 2>&1; then
  why="$ref is not publicly pullable"
fi

if [ -n "$why" ]; then
  echo "EVerest runtime: build locally from $dir/ ($why)"
  { echo "build_local=true"; echo "ref=everest-runtime:local"; echo "dir=$dir"; } >> "$out"
else
  echo "EVerest runtime: $ref"
  { echo "build_local=false"; echo "ref=$ref"; echo "dir=$dir"; } >> "$out"
fi
