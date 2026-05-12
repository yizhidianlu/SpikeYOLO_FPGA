#!/usr/bin/env bash
# hw/vivado/scripts/setup_ip_repo.sh — fetch Digilent (1) vivado-library
# so that build_bd.tcl can resolve digilentinc.com:ip:rgb2dvi:1.4, and
# (2) vivado-boards so that set_property board_part digilentinc.com:zybo-z7-20
# can resolve (otherwise [Board 49-71]). Per Remote URGENT_ASK_7 2026-05-12.
#
# Idempotent: safe to run on every clone or CI job.
#
# Note: hw/vivado/ip_repo/digilent/.gitignore intentionally ignores
# `vivado-library/` and `vivado-boards/` so that hand-unzipped releases don't
# accidentally land in the index. Adding the submodule therefore requires
# `-f` on first install.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"

# Helper: install one submodule (idempotent).
#   $1 = repo URL, $2 = dest relative path
install_submodule() {
    local URL="$1"
    local DEST_REL="$2"
    local DEST="$REPO_ROOT/$DEST_REL"
    if [ -d "$DEST/.git" ] || [ -f "$DEST/.git" ]; then
        echo "[setup_ip_repo] $DEST_REL already present"
        if git -C "$REPO_ROOT" ls-files --error-unmatch "$DEST_REL" >/dev/null 2>&1; then
            git -C "$REPO_ROOT" submodule update --init --recursive -- "$DEST_REL"
        else
            echo "[setup_ip_repo] (submodule staged but not yet committed — skipping update)"
        fi
    elif [ -d "$DEST" ]; then
        echo "[setup_ip_repo] $DEST_REL exists but is not a git submodule (probably unzipped release). Leaving as-is."
    else
        echo "[setup_ip_repo] adding $DEST_REL as submodule from $URL"
        git -C "$REPO_ROOT" submodule add -f "$URL" "$DEST_REL"
    fi
}

retry_hint() {
    echo ""
    echo "If clone failed (network / proxy), retry one of:"
    echo "  git -C $REPO_ROOT submodule add -f <URL> <DEST_REL>  # by hand"
    echo "  git clone <URL> $REPO_ROOT/<DEST_REL>                # pre-clone, then re-run this script"
}
trap retry_hint ERR

# ---- legacy single-library path (compat with prior callers) ----
DEST_REL="hw/vivado/ip_repo/digilent/vivado-library"
DEST="$REPO_ROOT/$DEST_REL"
URL="https://github.com/Digilent/vivado-library.git"

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

# ---- NEW: vivado-boards (Digilent ZYBO Z7-20 + other board files) ----
# Provides board_files/zybo-z7-20/ that Vivado consumes via
# set_param board.repoPaths. build_bd.tcl will set the path automatically.
BOARDS_REL="hw/vivado/ip_repo/digilent/vivado-boards"
BOARDS_URL="https://github.com/Digilent/vivado-boards.git"
install_submodule "$BOARDS_URL" "$BOARDS_REL"

trap - ERR

echo "[setup_ip_repo] OK — Digilent repos at:"
echo "  $DEST_REL"
echo "  $BOARDS_REL"
echo "[setup_ip_repo] IP catalogue (first 10 entries):"
ls "$DEST/ip" 2>/dev/null | head -n 10 || echo "  (ip/ not found — clone may be incomplete)"
echo "[setup_ip_repo] Board files (first 10):"
ls "$REPO_ROOT/$BOARDS_REL/new/board_files" 2>/dev/null | head -n 10 || echo "  (board_files/ not found — clone may be incomplete)"
