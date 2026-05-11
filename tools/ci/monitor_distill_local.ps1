# tools/ci/monitor_distill_local.ps1
# ----------------------------------------------------------------------------
# Windows Task Scheduler companion to monitor_distill_local.sh.
# Same contract: every ~5 minutes, check the A1 sanity training PID file,
# log progress, alert on death / stale-log conditions.
#
# Owner: D2 (CI/CD).
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass `
#     -File tools\ci\monitor_distill_local.ps1 [-Notify]
# ----------------------------------------------------------------------------
param(
    [switch]$Notify
)

$ErrorActionPreference = 'Continue'
$repoRoot   = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repoRoot

$pidFile    = "runs/distill/sanity_5ep.pid"
$logFile    = "runs/distill/sanity_5ep_log.csv"
$stdoutFile = "runs/distill/sanity_5ep_stdout.log"
$stateFile  = "runs/distill/monitor_state.txt"
$alertFile  = "runs/distill/monitor_alerts.log"
$ts         = (Get-Date).ToString("o")

New-Item -ItemType Directory -Force -Path "runs/distill" | Out-Null

if (-not (Test-Path $pidFile)) {
    Write-Output "[$ts] no PID file ($pidFile) - no training in progress"
    exit 0
}

$procId = (Get-Content $pidFile -Raw).Trim()
$proc   = Get-Process -Id $procId -ErrorAction SilentlyContinue

if (-not $proc) {
    Write-Output "[$ts] PID=$procId DEAD"
    if (Test-Path $stdoutFile) {
        Get-Content $stdoutFile -Tail 5 | Set-Content $stateFile -Encoding utf8
    }
    if ($Notify) {
        "[$ts] TRAINING ENDED pid=$procId - last stdout in $stateFile" |
            Tee-Object -FilePath $alertFile -Append | Out-Null
    }
    exit 1
}

# Alive - parse latest CSV row (header: epoch,step,loss_total,...)
$lastRow = ""
if (Test-Path $logFile) {
    $lastRow = (Get-Content $logFile -Tail 1)
}
$lastStep = "?"; $lastLoss = "?"
if ($lastRow -and $lastRow -notmatch "^epoch") {
    $cols = $lastRow -split ","
    if ($cols.Count -ge 3) {
        $lastStep = $cols[1]
        $lastLoss = $cols[2]
    }
}
Write-Output "[$ts] PID=$procId ALIVE step=$lastStep loss=$lastLoss"

# Health: csv mtime within 5 min
$stale = $true
if (Test-Path $logFile) {
    $age = (Get-Date) - (Get-Item $logFile).LastWriteTime
    if ($age.TotalMinutes -lt 5) { $stale = $false }
}
if ($stale) {
    Write-Output "  warn log STALE >5 min (possible hang / dataloader stuck)"
    if ($Notify) {
        "[$ts] STALE WARNING pid=$procId last_step=$lastStep" |
            Add-Content -Path $alertFile -Encoding utf8
    }
} else {
    Write-Output "  ok log updating (<5 min)"
}

# Best-effort GPU telemetry
$nvsmi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($nvsmi) {
    $gpu = & nvidia-smi --query-gpu=memory.used,utilization.gpu,temperature.gpu --format=csv,noheader 2>$null
    foreach ($line in $gpu) { Write-Output "  gpu $line" }
}
