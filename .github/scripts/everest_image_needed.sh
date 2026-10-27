#!/bin/sh
# Decide how much image testing a pull request needs.
#
# Usage: everest_image_needed.sh <app directory>
# Env:   BASE, HEAD (pull request SHAs), GITHUB_OUTPUT
#
# Writes two outputs:
# - images=false only when every changed file is one of the App's
#   documentation files that the image never contains (DOCS.md,
#   VALIDATION.md, RELEASE.md);
# - checks=ui when every changed file is such documentation, the App's
#   CHANGELOG.md, its Status page (rootfs/opt/ha-everest/www/), the page
#   preview (tests/ui_preview.py, tests/test_ui_preview.py), or config.yaml
#   with only the version line changed. The page is static and served by
#   ui_server.py, so such a change needs the image built and the page served,
#   not the charging sessions. Anything else writes checks=minimal.
# Any other change, a missing diff, or a Dockerfile that copies one of the
# documentation files writes images=true and checks=minimal.
set -eu
app=$1
out=${GITHUB_OUTPUT:-/dev/stdout}
docs="DOCS.md VALIDATION.md RELEASE.md"

decide() {
  echo "images=$1 checks=$2 ($3)"
  { echo "images=$1"; echo "checks=$2"; } >> "$out"
  exit 0
}

[ -n "${BASE:-}" ] && [ -n "${HEAD:-}" ] || decide true minimal "no pull request diff"
for name in $docs; do
  if grep -q "$name" "$app/Dockerfile"; then
    decide true minimal "$app/Dockerfile references $name"
  fi
done
files=$(git diff --name-only "$BASE...$HEAD") || decide true minimal "git diff failed"
[ -n "$files" ] || decide true minimal "empty diff"

# Prints each changed file's class: docs, ui or other.
classify() {
  echo "$files" | while IFS= read -r file; do
    rel=${file#"$app"/}
    if [ "$rel" = "$file" ]; then echo "other $file"; continue; fi
    case " $docs " in *" $rel "*) [ "${rel%/*}" = "$rel" ] && { echo "docs $file"; continue; } ;; esac
    case "$rel" in
      CHANGELOG.md|rootfs/opt/ha-everest/www/*|tests/ui_preview.py|tests/test_ui_preview.py)
        echo "ui $file"; continue ;;
      config.yaml)
        # Only the version line may change.
        changed=$(git diff -U0 "$BASE...$HEAD" -- "$file" | grep -E '^[-+]' | grep -vE '^(\+\+\+|---) ' \
          | grep -vE '^[-+]version: "[0-9]+\.[0-9]+\.[0-9]+"$' || true)
        [ -z "$changed" ] && { echo "ui $file"; continue; } ;;
    esac
    echo "other $file"
  done
}
classes=$(classify)
echo "$classes" | sed 's/^/  /'
if ! echo "$classes" | grep -qv '^docs '; then
  decide false ui "documentation only"
elif ! echo "$classes" | grep -qv -e '^docs ' -e '^ui '; then
  decide true ui "Status page, changelog or version only"
else
  decide true minimal "other changes"
fi
