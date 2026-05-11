#!/usr/bin/env bash
# hw/vivado/scripts/setup_ip_repo.sh — fetch Digilent vivado-library so that
# build_bd.tcl can resolve digilentinc.com:ip:rgb2dvi:1.4.
#
# Idempotent: safe to run on every clone or CI job.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
DEST="$REPO_ROOT/hw/vivado/ip_repo/digilent/vivado-library"
URL="https://github.com/Digilent/vivado-library.git"

if [ -d "$DEST/.git" ] || [ -f "$DEST/.git" ]; then
    echo "[setup_ip_repo] vivado-library already present — updating submodule"
    git -C "$REPO_ROOT" submodule update --init --recursive -- "$DEST"
elif [ -d "$DEST" ]; then
    echo "[setup_ip_repo] vivado-library/ exists but is not a git submodule"
    echo "                (probably an unzipped release). Leaving as-is."
else
    echo "[setup_ip_repo] adding vivado-library as a submodule under $DEST"
    git -C "$REPO_ROOT" submodule add "$URL" "hw/vivado/ip_repo/digilent/vivado-library"
fi

echo "[setup_ip_repo] OK — Digilent IP repo at $DEST"
