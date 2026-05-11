#!/usr/bin/env bash
# hw/vivado/scripts/setup_ip_repo.sh — fetch Digilent vivado-library so that
# build_bd.tcl can resolve digilentinc.com:ip:rgb2dvi:1.4.
#
# Idempotent: safe to run on every clone or CI job.
#
# Note: hw/vivado/ip_repo/digilent/.gitignore intentionally ignores
# `vivado-library/` so that hand-unzipped releases don't accidentally land in
# the index. Adding the submodule therefore requires `-f` on first install.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
DEST_REL="hw/vivado/ip_repo/digilent/vivado-library"
DEST="$REPO_ROOT/$DEST_REL"
URL="https://github.com/Digilent/vivado-library.git"

retry_hint() {
    echo ""
    echo "If clone failed (network / proxy), retry manually:"
    echo "  git -C $REPO_ROOT submodule add -f $URL $DEST_REL"
    echo "or pre-clone, then re-run this script:"
    echo "  git clone $URL $DEST"
}
trap retry_hint ERR

if [ -d "$DEST/.git" ] || [ -f "$DEST/.git" ]; then
    echo "[setup_ip_repo] vivado-library already present"
    # Only run `submodule update` when the submodule is fully registered in
    # both .gitmodules AND the git index. Right after a fresh `submodule add`
    # the index entry may not be committed yet (especially in a test/dry-run
    # workflow), so we fall back to a no-op instead of crashing.
    if git -C "$REPO_ROOT" ls-files --error-unmatch "$DEST_REL" >/dev/null 2>&1; then
        echo "[setup_ip_repo] updating submodule"
        git -C "$REPO_ROOT" submodule update --init --recursive -- "$DEST_REL"
    else
        echo "[setup_ip_repo] (submodule staged but not yet committed — skipping update;"
        echo "                commit '.gitmodules' + '$DEST_REL' to make this path live)"
    fi
elif [ -d "$DEST" ]; then
    echo "[setup_ip_repo] vivado-library/ exists but is not a git submodule"
    echo "                (probably an unzipped release). Leaving as-is."
else
    echo "[setup_ip_repo] adding vivado-library as a submodule under $DEST_REL"
    # -f bypasses the digilent/.gitignore rule (vivado-library/). The rule
    # exists to deter unzipped drops; the submodule entry is the canonical
    # way to bring the library in.
    git -C "$REPO_ROOT" submodule add -f "$URL" "$DEST_REL"
fi

trap - ERR

echo "[setup_ip_repo] OK — Digilent IP repo at $DEST"
echo "[setup_ip_repo] IP catalogue (first 10 entries):"
ls "$DEST/ip" 2>/dev/null | head -n 10 || echo "  (ip/ not found — clone may be incomplete)"
