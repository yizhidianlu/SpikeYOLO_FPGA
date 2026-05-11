# Quick progress check for the M1 W4 sanity 5-epoch distillation run (PowerShell).
# Usage:   powershell -File tools/ci/check_distill_progress.ps1
# Owner:   A1 Quantization (M1 W4 sanity sprint, 2026-05-11).

$repo  = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$pidF  = Join-Path $repo "runs\distill\sanity_5ep.pid"
$csv   = Join-Path $repo "runs\distill\sanity_5ep_log.csv"
$outL  = Join-Path $repo "runs\distill\sanity_5ep_stdout.log"
$errL  = Join-Path $repo "runs\distill\sanity_5ep_stderr.log"

Write-Output "=== PID ==="
if (Test-Path $pidF) {
    $procPid = (Get-Content $pidF -Raw).Trim()
    Get-Process -Id $procPid -ErrorAction SilentlyContinue |
        Format-List Id, ProcessName, StartTime, CPU, @{N='WS_MB';E={[int]($_.WorkingSet64/1MB)}}
    if (-not (Get-Process -Id $procPid -ErrorAction SilentlyContinue)) {
        Write-Output "PID $procPid NOT running"
    }
} else {
    Write-Output "no pid file at $pidF"
}

Write-Output "`n=== last 5 CSV rows ==="
if (Test-Path $csv) { Get-Content $csv -Tail 5 } else { Write-Output "(csv missing)" }

Write-Output "`n=== last 15 stdout lines ==="
if (Test-Path $outL) { Get-Content $outL -Tail 15 } else { Write-Output "(stdout missing)" }

Write-Output "`n=== last 5 stderr lines ==="
if (Test-Path $errL) { Get-Content $errL -Tail 5 } else { Write-Output "(stderr missing)" }

Write-Output "`n=== GPU ==="
nvidia-smi --query-gpu=memory.used,memory.free,utilization.gpu,temperature.gpu --format=csv
