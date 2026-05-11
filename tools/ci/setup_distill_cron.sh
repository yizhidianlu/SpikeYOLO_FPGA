#!/usr/bin/env bash
# tools/ci/setup_distill_cron.sh
# ----------------------------------------------------------------------------
# Documentation-only helper. Prints the exact commands to register the
# distill-monitor on Linux (cron) or Windows (Task Scheduler). This script
# does NOT touch your crontab automatically — copy/paste the snippet that
# matches your platform after reviewing it.
# ----------------------------------------------------------------------------
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

cat <<EOF
SpikeYOLO distill monitor — install instructions
================================================
Repo root detected: ${REPO_ROOT}

Linux / macOS (cron, every 5 min):
  crontab -e
  # then add:
  */5 * * * * cd ${REPO_ROOT} && bash tools/ci/monitor_distill_local.sh --notify >> runs/distill/monitor_cron.log 2>&1

Windows (Task Scheduler, every 5 min, PowerShell variant):
  schtasks /Create /SC MINUTE /MO 5 /TN "spike_distill_monitor" \\
    /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File ${REPO_ROOT//\\//}\\tools\\ci\\monitor_distill_local.ps1 -Notify" \\
    /F

To remove later:
  Linux:   crontab -e  (delete the line)
  Windows: schtasks /Delete /TN "spike_distill_monitor" /F

Alerts land in:  runs/distill/monitor_alerts.log
EOF
