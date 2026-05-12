#!/usr/bin/env bash
# tools/ci/run_workflows_locally.sh
# ----------------------------------------------------------------------------
# Drive GitHub Actions workflows on a developer box via nektos/act before
# pushing to origin. act runs each job in a docker container that mimics
# the ubuntu-22.04 runner image — so a green local act predicts a green
# GitHub-hosted job. Self-hosted runner jobs (board / vitis) are skipped
# automatically because their labels don't match the default act image.
#
# Owner: D2 (CI/CD). Companion: tools/ci/local_validate.sh (host-side,
# no docker required). Use local_validate.sh for the fast pre-commit
# gate, this script for the heavier "did I break the CI?" simulation.
#
# Setup:
#   - Docker Desktop / Engine running (`docker info` must succeed)
#   - act installed:
#       brew install act           # macOS
#       choco install act-cli      # Windows
#       https://github.com/nektos/act/releases  # any
# ----------------------------------------------------------------------------
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

if ! command -v act > /dev/null 2>&1; then
    echo "[run_workflows_locally] act not installed."
    echo "  install: brew install act / choco install act-cli /"
    echo "           https://github.com/nektos/act/releases"
    exit 2
fi
if ! docker info > /dev/null 2>&1; then
    echo "[run_workflows_locally] docker not reachable — start Docker Desktop / dockerd."
    exit 2
fi

WORKFLOW="${1:-numpy_regress.yml}"
EVENT="${2:-pull_request}"
echo "[run_workflows_locally] act $EVENT --workflows .github/workflows/$WORKFLOW"

# --container-architecture linux/amd64 keeps Apple-silicon hosts honest;
# harmless on x86_64. -P pins the runner image so act doesn't yank a
# huge "full" image on first run.
act "$EVENT" \
    --workflows ".github/workflows/$WORKFLOW" \
    --container-architecture linux/amd64 \
    -P ubuntu-22.04=catthehacker/ubuntu:act-22.04 \
    "${@:3}"

# Usage examples:
#   bash tools/ci/run_workflows_locally.sh numpy_regress.yml pull_request
#   bash tools/ci/run_workflows_locally.sh hls_smoke.yml    pull_request
#   bash tools/ci/run_workflows_locally.sh board_nightly.yml schedule
# Self-hosted-only jobs (vitis_csim, board_test) will be skipped because
# their `runs-on: [self-hosted, ...]` labels are not provided by act.
