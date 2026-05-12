#!/usr/bin/env bash
# tools/ci/monitor_distill_local.sh — 5-min watchdog for A1 sanity / distill.
# Owner: D2 (CI/CD). Companion .ps1 same logic. Cron via setup_distill_cron.sh.
# M1 W7: merged D1's check_distill_progress (ETA + slope + --md).
# Usage: bash tools/ci/monitor_distill_local.sh [--notify] [--md]
set -uo pipefail

PID_FILE="runs/distill/sanity_5ep.pid"
LOG_FILE="runs/distill/sanity_5ep_log.csv"
STDOUT="runs/distill/sanity_5ep_stdout.log"
STATE_FILE="runs/distill/monitor_state.txt"
ALERT_FILE="runs/distill/monitor_alerts.log"
SPEED_STATE_FILE="runs/distill/monitor_speed_state.txt"
TOTAL_STEPS="${DISTILL_TOTAL_STEPS:-740}"   # 5 ep * 148 step/ep default

NOTIFY=0; MD=0
for a in "$@"; do [ "$a" = "--notify" ] && NOTIFY=1; [ "$a" = "--md" ] && MD=1; done
mkdir -p runs/distill
TS="$(date -Iseconds)"

if [ ! -f "$PID_FILE" ]; then
    echo "[$TS] no PID file ($PID_FILE) — no training in progress"; exit 0
fi
PID="$(tr -d ' \r\n' < "$PID_FILE")"
ALIVE=0
# MSYS `ps -p` exits 0 with header-only output on miss; need >=1 data row.
# Also handle native Linux ps (-o pid= works) and Windows tasklist.
if ps -p "$PID" -o pid= > /dev/null 2>&1 && [ -n "$(ps -p "$PID" -o pid= 2>/dev/null)" ]; then ALIVE=1
elif ps -p "$PID" 2>/dev/null | awk 'NR>1 && $1 ~ /^[0-9]+$/ {n++} END{exit n?0:1}'; then ALIVE=1
elif command -v powershell.exe > /dev/null 2>&1 && powershell.exe -NoProfile -Command "if (Get-Process -Id $PID -EA SilentlyContinue) {exit 0} else {exit 1}" > /dev/null 2>&1; then ALIVE=1
elif command -v tasklist > /dev/null 2>&1 && tasklist /FI "PID eq $PID" 2>/dev/null | grep -q " $PID "; then ALIVE=1
fi
if [ "$ALIVE" -eq 0 ]; then
    echo "[$TS] PID=$PID DEAD"
    tail -n 5 "$STDOUT" 2>/dev/null > "$STATE_FILE" || true
    [ "$NOTIFY" -eq 1 ] && echo "[$TS] TRAINING ENDED pid=$PID — last stdout in $STATE_FILE" | tee -a "$ALERT_FILE"
    exit 1
fi

LAST_ROW="$(tail -n 1 "$LOG_FILE" 2>/dev/null || echo "")"
LAST_STEP="$(echo "$LAST_ROW" | awk -F, '{print $2}')"
LAST_LOSS="$(echo "$LAST_ROW" | awk -F, '{print $3}')"

# Enrichments: slope over last 30 loss_det + speed from delta across invocations.
# csv schema: epoch,step,loss_total,loss_det,loss_kd,loss_align,loss_spike,lr
LOSS_SLOPE="n/a"; ETA_MIN="n/a"; SPEED_ITPS="n/a"
if [ -f "$LOG_FILE" ]; then
    NOW_TS=$(date +%s); PREV_TS=0; PREV_STEP=0
    [ -f "$SPEED_STATE_FILE" ] && read PREV_TS PREV_STEP < "$SPEED_STATE_FILE" || true
    echo "$NOW_TS ${LAST_STEP:-0}" > "$SPEED_STATE_FILE"
    read LOSS_SLOPE SPEED_ITPS ETA_MIN < <(python - "$LOG_FILE" "$TOTAL_STEPS" "${LAST_STEP:-0}" "$NOW_TS" "$PREV_TS" "$PREV_STEP" <<'PY' 2>/dev/null || echo "n/a n/a n/a"
import csv, sys
path, total, last, now_ts, prev_ts, prev_step = sys.argv[1:7]
total=int(total); last=int(last) if last.isdigit() else 0
now_ts=int(now_ts); prev_ts=int(prev_ts); prev_step=int(prev_step)
rows = list(csv.reader(open(path)))[1:]
rows = [r for r in rows if len(r)>=8 and r[1].lstrip("-").isdigit() and int(r[1])>0][-30:]
if len(rows)<5: print("insufficient n/a n/a"); sys.exit()
ys=[float(r[3]) for r in rows]; xs=list(range(len(ys))); n=len(xs)
d=n*sum(x*x for x in xs)-sum(xs)**2
slope=(n*sum(x*y for x,y in zip(xs,ys))-sum(xs)*sum(ys))/d if d else 0.0
its="n/a"; eta="n/a"
if prev_ts and now_ts>prev_ts and last>prev_step:
    s=(last-prev_step)/float(now_ts-prev_ts)
    its=f"{s:.2f}"; eta=f"{(max(0,total-last)/s/60.0):.1f}" if s>0 else "n/a"
print(f"{slope:+.4f} {its} {eta}")
PY
)
fi

if [ "$MD" -eq 1 ]; then
    GPU_LINE=""
    command -v nvidia-smi > /dev/null 2>&1 && GPU_LINE="$(nvidia-smi --query-gpu=memory.used,utilization.gpu,temperature.gpu --format=csv,noheader 2>/dev/null | head -1)"
    cat <<MD
| Field | Value |
|---|---|
| Timestamp | $TS |
| PID | $PID (alive) |
| Step | ${LAST_STEP:-?} / $TOTAL_STEPS |
| Loss(det) | ${LAST_LOSS:-?} |
| Loss slope | $LOSS_SLOPE / step (last 30) |
| Speed | $SPEED_ITPS it/s |
| ETA | $ETA_MIN min |
| GPU | ${GPU_LINE:-n/a} |
MD
else
    echo "[$TS] PID=$PID ALIVE step=${LAST_STEP:-?}/$TOTAL_STEPS loss=${LAST_LOSS:-?} slope=$LOSS_SLOPE eta=${ETA_MIN}min speed=${SPEED_ITPS}it/s"
fi

# Health: csv mtime within last 5 min
if [ -f "$LOG_FILE" ] && find "$LOG_FILE" -mmin -5 2>/dev/null | grep -q .; then
    [ "$MD" -eq 0 ] && echo "  ok log updating (<5 min)"
else
    [ "$MD" -eq 0 ] && echo "  warn log STALE >5 min (possible hang / dataloader stuck)"
    [ "$NOTIFY" -eq 1 ] && echo "[$TS] STALE WARNING pid=$PID last_step=${LAST_STEP:-?}" >> "$ALERT_FILE"
fi

# Collapse early-warn: loss_det slope >= +0.05
if [ "$LOSS_SLOPE" != "n/a" ] && [ "$(awk -v v="$LOSS_SLOPE" 'BEGIN{print (v+0>=0.05)?1:0}')" = "1" ]; then
    [ "$MD" -eq 0 ] && echo "  warn loss_det slope=$LOSS_SLOPE — potential collapse"
    [ "$NOTIFY" -eq 1 ] && echo "[$TS] LOSS COLLAPSE WARN pid=$PID slope=$LOSS_SLOPE" >> "$ALERT_FILE"
fi

if [ "$MD" -eq 0 ] && command -v nvidia-smi > /dev/null 2>&1; then
    nvidia-smi --query-gpu=memory.used,utilization.gpu,temperature.gpu --format=csv,noheader 2>/dev/null | sed 's/^/  gpu /'
fi
