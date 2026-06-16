#!/usr/bin/env bash
# Sync the nem_price_forecaster add-on from upstream into this repository.
#
# Usage:
#   ./scripts/sync-upstream.sh           # uses default upstream branch (main)
#   UPSTREAM_REF=v0.3.0 ./scripts/sync-upstream.sh
#
# Run from the repo root. Requires git and rsync.

set -euo pipefail

UPSTREAM_REPO="${UPSTREAM_REPO:-https://github.com/BrettLynch123/nem-price-forecaster}"
UPSTREAM_REF="${UPSTREAM_REF:-main}"
ADDON_SLUG="nem_price_forecaster"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${REPO_ROOT}"

TMPDIR="$(mktemp -d)"
trap 'rm -rf "${TMPDIR}"' EXIT

echo "[sync] cloning ${UPSTREAM_REPO}@${UPSTREAM_REF} ..."
git clone --depth 1 --branch "${UPSTREAM_REF}" "${UPSTREAM_REPO}" "${TMPDIR}/upstream" >/dev/null 2>&1

UPSTREAM_SHA="$(git -C "${TMPDIR}/upstream" rev-parse HEAD)"
echo "[sync] upstream HEAD: ${UPSTREAM_SHA}"

if [ ! -d "${TMPDIR}/upstream/addon" ]; then
    echo "[sync] ERROR: upstream has no addon/ directory" >&2
    exit 1
fi

echo "[sync] rsyncing addon/ -> ${ADDON_SLUG}/"
rsync -a --delete --exclude='.git' \
    "${TMPDIR}/upstream/addon/" "${ADDON_SLUG}/"

# Stamp the upstream commit so future updates are traceable
mkdir -p "${ADDON_SLUG}"
cat > "${ADDON_SLUG}/UPSTREAM.md" <<EOF
# Upstream provenance

This add-on is synced from:

- Repository: ${UPSTREAM_REPO}
- Ref:        ${UPSTREAM_REF}
- Commit:     ${UPSTREAM_SHA}
- Synced at:  $(date -u +'%Y-%m-%dT%H:%M:%SZ')
EOF

echo "[sync] done. Diff summary:"
git -C "${REPO_ROOT}" status --short "${ADDON_SLUG}" || true
echo
echo "[sync] review changes, then:"
echo "       git add ${ADDON_SLUG} && git commit -m 'sync: upstream ${UPSTREAM_SHA:0:7}' && git push"
