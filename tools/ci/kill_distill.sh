#!/usr/bin/env bash
# Emergency stop for the M1 W4 sanity 5-epoch distillation run.
# Usage:   bash tools/ci/kill_distill.sh
# Owner:   A1 Quantization (M1 W4 sanity sprint, 2026-05-11).
set -u
REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PID_FILE="$REPO_DIR/runs/distill/sanity_5ep.pid"
if [ ! -f "$PID_FILE" ]; then
    echo "no pid file at $PID_FILE; nothing to kill"
    exit 0
fi
PID=$(tr -d ' \r\n' < "$PID_FILE")
echo "Killing PID $PID ..."
if command -v taskkill > /dev/null 2>&1; then
    taskkill /F /T /PID "$PID"
else
    kill -TERM "$PID" 2>/dev/null || true
    sleep 2
    kill -KILL "$PID" 2>/dev/null || true
fi
echo "done"
