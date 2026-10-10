#!/bin/sh
# Decide whether a pull request needs the EVerest image build.
#
# Usage: everest_image_needed.sh <app directory>
# Env:   BASE, HEAD (pull request SHAs), GITHUB_OUTPUT
#
# Writes images=false only when every changed file is one of the App's
# documentation files that the image never contains (DOCS.md,
# VALIDATION.md, RELEASE.md). Any other change, a missing diff, or a
# Dockerfile that copies one of those files writes images=true.
set -eu
app=$1
out=${GITHUB_OUTPUT:-/dev/stdout}
docs="DOCS.md VALIDATION.md RELEASE.md"

decide() {
  echo "images=$1 ($2)"
  echo "images=$1" >> "$out"
  exit 0
}

[ -n "${BASE:-}" ] && [ -n "${HEAD:-}" ] || decide true "no pull request diff"
for name in $docs; do
  if grep -q "$name" "$app/Dockerfile"; then
    decide true "$app/Dockerfile references $name"
  fi
done
files=$(git diff --name-only "$BASE...$HEAD") || decide true "git diff failed"
[ -n "$files" ] || decide true "empty diff"

echo "$files" | while IFS= read -r file; do
  case " $docs " in
    *" ${file#"$app"/} "*) [ "${file%/*}" = "$app" ] && continue ;;
  esac
  echo "needs image: $file"
  exit 1
done && decide false "documentation only" || decide true "non-documentation change"
