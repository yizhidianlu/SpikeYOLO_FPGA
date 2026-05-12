#!/usr/bin/env bash
# Quick-look monitor for the detached COCO download started by
#   tools/ci/download_coco_train2017.py
# Prints PID liveness, last 10 log lines, datasets/ disk usage, and C: free space.
set -u
PID_FILE="runs/datasets_download.pid"
if [ ! -f "$PID_FILE" ]; then
  echo "No download running (missing $PID_FILE)"
  exit 0
fi
PID="$(cat "$PID_FILE" | tr -d '[:space:]')"
if powershell.exe -NoProfile -Command "if (Get-Process -Id $PID -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >/dev/null 2>&1; then
  echo "ALIVE PID=$PID"
else
  echo "DEAD  PID=$PID"
fi
echo "--- last 10 log lines (runs/datasets_download.log) ---"
tail -n 10 runs/datasets_download.log 2>/dev/null || echo "(no log yet)"
echo "--- disk usage (datasets/coco) ---"
du -sh datasets/coco/ 2>/dev/null || echo "(missing)"
echo "--- C: free space ---"
powershell.exe -NoProfile -Command "Get-PSDrive C | Select-Object Free,Used | Format-Table -AutoSize"
