#!/usr/bin/env bash
# tools/ci/monitor_distill_local.sh
# ----------------------------------------------------------------------------
# Local cron-driven monitor for the A1 sanity / distill training run.
# Designed to be triggered every ~5 minutes by Linux cron or
# Windows Task Scheduler -> Git-Bash. See setup_distill_cron.sh.
#
# Owner: D2 (CI/CD). Companion: tools/ci/monitor_distill_local.ps1
# (same logic via Get-Process + Get-Content for native PowerShell).
# ----------------------------------------------------------------------------
set -uo pipefail

PID_FILE="runs/distill/sanity_5ep.pid"
LOG_FILE="runs/distill/sanity_5ep_log.csv"
STDOUT="runs/distill/sanity_5ep_stdout.log"
STATE_FILE="runs/distill/monitor_state.txt"
ALERT_FILE="runs/distill/monitor_alerts.log"

NOTIFY=0
[ "${1:-}" = "--notify" ] && NOTIFY=1
mkdir -p runs/distill

if [ ! -f "$PID_FILE" ]; then
    echo "[$(date -Iseconds)] no PID file ($PID_FILE) — no training in progress"
    exit 0
fi

PID="$(cat "$PID_FILE")"
ALIVE=0
if ps -p "$PID" > /dev/null 2>&1; then
    ALIVE=1
elif command -v powershell.exe > /dev/null 2>&1 \
     && powershell.exe -NoProfile -Command "if (Get-Process -Id $PID -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" > /dev/null 2>&1; then
    ALIVE=1
fi

if [ "$ALIVE" -eq 0 ]; then
    echo "[$(date -Iseconds)] PID=$PID DEAD"
    tail -n 5 "$STDOUT" 2>/dev/null > "$STATE_FILE" || true
    if [ "$NOTIFY" -eq 1 ]; then
        echo "[$(date -Iseconds)] TRAINING ENDED pid=$PID — last stdout in $STATE_FILE" \
            | tee -a "$ALERT_FILE"
    fi
    exit 1
fi

# Alive — read latest csv row (skip header)
LAST_ROW="$(tail -n 1 "$LOG_FILE" 2>/dev/null || echo "")"
LAST_STEP="$(echo "$LAST_ROW" | awk -F, '{print $2}')"
LAST_LOSS="$(echo "$LAST_ROW" | awk -F, '{print $3}')"
echo "[$(date -Iseconds)] PID=$PID ALIVE step=${LAST_STEP:-?} loss=${LAST_LOSS:-?}"

# Health: csv mtime within last 5 min
if [ -f "$LOG_FILE" ] && find "$LOG_FILE" -mmin -5 2>/dev/null | grep -q .; then
    echo "  ok log updating (<5 min)"
else
    echo "  warn log STALE >5 min (possible hang / dataloader stuck)"
    if [ "$NOTIFY" -eq 1 ]; then
        echo "[$(date -Iseconds)] STALE WARNING pid=$PID last_step=${LAST_STEP:-?}" \
            >> "$ALERT_FILE"
    fi
fi

# GPU telemetry (best-effort)
if command -v nvidia-smi > /dev/null 2>&1; then
    nvidia-smi --query-gpu=memory.used,utilization.gpu,temperature.gpu \
               --format=csv,noheader 2>/dev/null \
        | sed 's/^/  gpu /'
fi
