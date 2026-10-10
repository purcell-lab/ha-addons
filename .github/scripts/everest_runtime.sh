#!/bin/sh
# Resolve the EVerest runtime image for an EVerest App build.
#
# Usage: everest_runtime.sh <app directory>
# Env:   BASE, HEAD (pull request SHAs, optional), GITHUB_OUTPUT
#
# Uses the Dockerfile's pinned ARG EVEREST_RUNTIME when it is pinned by
# digest and pullable, and the pull request does not change
# everest_runtime/. Otherwise it asks for a local runtime build from
# everest_runtime/ (which pulls the 4.3 GB upstream image) so the App is
# still built and tested. Outputs: ref, build_local.
set -eu
app=$1
out=${GITHUB_OUTPUT:-/dev/stdout}
ref=$(sed -n 's/^ARG EVEREST_RUNTIME=//p' "$app/Dockerfile")
[ -n "$ref" ] || { echo "::error::$app/Dockerfile has no ARG EVEREST_RUNTIME"; exit 1; }

why=""
if [ -n "${BASE:-}" ] && [ -n "${HEAD:-}" ] \
   && git diff --name-only "$BASE...$HEAD" | grep -q '^everest_runtime/'; then
  why="this pull request changes everest_runtime/"
elif ! echo "$ref" | grep -q '@sha256:[0-9a-f]\{64\}$'; then
  why="$ref is not pinned by digest yet"
elif ! docker manifest inspect "$ref" > /dev/null 2>&1; then
  why="$ref is not publicly pullable"
fi

if [ -n "$why" ]; then
  echo "EVerest runtime: build locally ($why)"
  { echo "build_local=true"; echo "ref=everest-runtime:local"; } >> "$out"
else
  echo "EVerest runtime: $ref"
  { echo "build_local=false"; echo "ref=$ref"; } >> "$out"
fi
