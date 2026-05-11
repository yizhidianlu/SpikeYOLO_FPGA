#!/usr/bin/env bash
# hw/vivado/scripts/cleanup_ip_repo.sh — undo setup_ip_repo.sh.
#
# Usage:
#   bash hw/vivado/scripts/cleanup_ip_repo.sh           # soft: rm workdir only
#   bash hw/vivado/scripts/cleanup_ip_repo.sh --hard    # also drop submodule
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
SUBPATH="hw/vivado/ip_repo/digilent/vivado-library"
DEST="$REPO_ROOT/$SUBPATH"

if [ ! -e "$DEST" ] && [ "${1:-}" != "--hard" ]; then
    echo "[cleanup_ip_repo] nothing to clean (no $SUBPATH)"
    exit 0
fi

if [ "${1:-}" = "--hard" ]; then
    echo "[cleanup_ip_repo] hard cleanup — removing submodule registration"
    if git -C "$REPO_ROOT" ls-files --error-unmatch "$SUBPATH" >/dev/null 2>&1; then
        git -C "$REPO_ROOT" submodule deinit -f -- "$SUBPATH" || true
        git -C "$REPO_ROOT" rm -rf "$SUBPATH" || true
    fi
    rm -rf "$DEST"
    rm -rf "$REPO_ROOT/.git/modules/$SUBPATH"
    echo "[cleanup_ip_repo] hard cleanup done — review 'git status' and commit if intended"
else
    echo "[cleanup_ip_repo] soft cleanup — removing $SUBPATH workdir only"
    rm -rf "$DEST"
    echo "[cleanup_ip_repo] re-run setup_ip_repo.sh to restore"
fi
