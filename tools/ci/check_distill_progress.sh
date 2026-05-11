#!/usr/bin/env bash
# Quick progress check for the M1 W4 sanity 5-epoch distillation run.
# Usage:   bash tools/ci/check_distill_progress.sh
# Owner:   A1 Quantization (M1 W4 sanity sprint, 2026-05-11).
set -u
REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PID_FILE="$REPO_DIR/runs/distill/sanity_5ep.pid"
LOG_CSV="$REPO_DIR/runs/distill/sanity_5ep_log.csv"
STDOUT="$REPO_DIR/runs/distill/sanity_5ep_stdout.log"
STDERR="$REPO_DIR/runs/distill/sanity_5ep_stderr.log"

echo "=== PID ==="
if [ -f "$PID_FILE" ]; then
    PID=$(tr -d ' \r\n' < "$PID_FILE")
    if command -v tasklist > /dev/null 2>&1; then
        tasklist /FI "PID eq $PID" 2>/dev/null | head -5
    else
        ps -p "$PID" 2>/dev/null || echo "PID $PID not running"
    fi
else
    echo "no pid file at $PID_FILE"
fi

echo
echo "=== last 5 CSV rows ==="
[ -f "$LOG_CSV" ] && tail -5 "$LOG_CSV" || echo "(csv missing)"

echo
echo "=== last 15 stdout lines ==="
[ -f "$STDOUT" ] && tail -15 "$STDOUT" || echo "(stdout missing)"

echo
echo "=== last 5 stderr lines ==="
[ -f "$STDERR" ] && tail -5 "$STDERR" || echo "(stderr missing)"

echo
echo "=== GPU ==="
nvidia-smi --query-gpu=memory.used,memory.free,utilization.gpu,temperature.gpu --format=csv 2>/dev/null \
    || echo "(nvidia-smi unavailable)"
