# tools/ci/monitor_distill_local.ps1
# ----------------------------------------------------------------------------
# Windows Task Scheduler companion to monitor_distill_local.sh.
# Same contract: every ~5 minutes, check the A1 sanity training PID file,
# log progress, alert on death / stale-log / loss-collapse conditions.
#
# Owner: D2 (CI/CD).
#
# M1 W7: merged D1-proposed check_distill_progress.ps1 enrichment —
#   * ETA estimate from delta_step / delta_wall across invocations
#   * loss_det linear-regression slope (collapse early-warn)
#   * -Md markdown-table output mode (paste into README / 月报)
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass `
#     -File tools\ci\monitor_distill_local.ps1 [-Notify] [-Md]
# ----------------------------------------------------------------------------
param(
    [switch]$Notify,
    [switch]$Md
)

$ErrorActionPreference = 'Continue'
$repoRoot   = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repoRoot

$pidFile         = "runs/distill/sanity_5ep.pid"
$logFile         = "runs/distill/sanity_5ep_log.csv"
$stdoutFile      = "runs/distill/sanity_5ep_stdout.log"
$stateFile       = "runs/distill/monitor_state.txt"
$alertFile       = "runs/distill/monitor_alerts.log"
$speedStateFile  = "runs/distill/monitor_speed_state.txt"
$ts              = (Get-Date).ToString("o")
$totalSteps      = if ($env:DISTILL_TOTAL_STEPS) { [int]$env:DISTILL_TOTAL_STEPS } else { 740 }

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

# Alive - parse latest CSV row (header: epoch,step,loss_total,loss_det,...)
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

# --- W7 enrichments: slope + speed via cross-invocation state -----------------
$lossSlope = "n/a"; $speedItps = "n/a"; $etaMin = "n/a"
if (Test-Path $logFile) {
    # Slope of last 30 loss_det rows (drop step=0 init row)
    $rows = Get-Content $logFile | Select-Object -Skip 1 |
        Where-Object {
            $p = $_ -split ","
            ($p.Count -ge 8) -and ($p[1] -match '^\d+$') -and ([int]$p[1] -gt 0)
        } | Select-Object -Last 30
    if ($rows.Count -ge 5) {
        $ys = $rows | ForEach-Object { [double]($_ -split ",")[3] }
        $xs = 0..($ys.Count - 1)
        $n  = $ys.Count
        $sumX  = ($xs | Measure-Object -Sum).Sum
        $sumY  = ($ys | Measure-Object -Sum).Sum
        $sumXX = ($xs | ForEach-Object { $_ * $_ } | Measure-Object -Sum).Sum
        $sumXY = 0.0
        for ($i = 0; $i -lt $n; $i++) { $sumXY += $xs[$i] * $ys[$i] }
        $denom = $n * $sumXX - $sumX * $sumX
        if ($denom -ne 0) {
            $slope = ($n * $sumXY - $sumX * $sumY) / $denom
            $lossSlope = "{0:+0.0000;-0.0000}" -f $slope
        }
    }

    # Speed = delta_step / delta_wall across monitor invocations
    $nowEpoch = [int][double]::Parse((Get-Date -UFormat %s))
    $prevTs   = 0; $prevStep = 0
    if (Test-Path $speedStateFile) {
        $parts = (Get-Content $speedStateFile -Raw).Trim() -split "\s+"
        if ($parts.Count -ge 2) {
            $prevTs   = [int]$parts[0]
            $prevStep = [int]$parts[1]
        }
    }
    $curStepInt = 0
    if ($lastStep -match '^\d+$') { $curStepInt = [int]$lastStep }
    "$nowEpoch $curStepInt" | Set-Content -Path $speedStateFile -Encoding ascii

    if ($prevTs -gt 0 -and $nowEpoch -gt $prevTs -and $curStepInt -gt $prevStep) {
        $its = ($curStepInt - $prevStep) / [double]($nowEpoch - $prevTs)
        $speedItps = "{0:0.00}" -f $its
        $remaining = [math]::Max(0, $totalSteps - $curStepInt)
        if ($its -gt 0) {
            $etaMin = "{0:0.0}" -f ($remaining / $its / 60.0)
        }
    }
}

# GPU telemetry
$gpuLine = "n/a"
$nvsmi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($nvsmi) {
    $gpu = & nvidia-smi --query-gpu=memory.used,utilization.gpu,temperature.gpu --format=csv,noheader 2>$null
    if ($gpu) { $gpuLine = ($gpu | Select-Object -First 1) }
}

if ($Md) {
    @"
| Field | Value |
|---|---|
| Timestamp | $ts |
| PID | $procId (alive) |
| Step | $lastStep / $totalSteps |
| Loss(det) | $lastLoss |
| Loss slope | $lossSlope / step (last 30) |
| Speed | $speedItps it/s |
| ETA | $etaMin min |
| GPU | $gpuLine |
"@
} else {
    Write-Output "[$ts] PID=$procId ALIVE step=$lastStep/$totalSteps loss=$lastLoss slope=$lossSlope eta=${etaMin}min speed=${speedItps}it/s"
}

# Health: csv mtime within 5 min
$stale = $true
if (Test-Path $logFile) {
    $age = (Get-Date) - (Get-Item $logFile).LastWriteTime
    if ($age.TotalMinutes -lt 5) { $stale = $false }
}
if ($stale) {
    if (-not $Md) { Write-Output "  warn log STALE >5 min (possible hang / dataloader stuck)" }
    if ($Notify) {
        "[$ts] STALE WARNING pid=$procId last_step=$lastStep" |
            Add-Content -Path $alertFile -Encoding utf8
    }
} else {
    if (-not $Md) { Write-Output "  ok log updating (<5 min)" }
}

# Collapse early-warn: positive slope >= 0.05 over last 30 step
if ($lossSlope -ne "n/a") {
    $slopeNum = [double]($lossSlope -replace "[+]","")
    if ($slopeNum -ge 0.05) {
        if (-not $Md) { Write-Output "  warn loss_det slope=$lossSlope - potential collapse" }
        if ($Notify) {
            "[$ts] LOSS COLLAPSE WARN pid=$procId slope=$lossSlope" |
                Add-Content -Path $alertFile -Encoding utf8
        }
    }
}

if (-not $Md -and $nvsmi -and $gpuLine -ne "n/a") {
    Write-Output "  gpu $gpuLine"
}
