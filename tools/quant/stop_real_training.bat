@echo off
REM A1 W8 — stop real training. Note: taskkill /F on Windows does NOT trigger
REM Python signal handlers, so graceful save only happens at natural epoch
REM boundaries (every epoch is auto-saved to runs/distill/resumable/latest.pt;
REM worst-case force-kill loses ≤1 epoch of progress).

set PIDFILE=runs\distill\real_training.pid

if not exist %PIDFILE% (
    echo [stop] No PID file at %PIDFILE%
    exit /b 1
)

set /p PID=<%PIDFILE%
echo [stop] Killing PID %PID% (force; resume from latest.pt on next start)
taskkill /PID %PID% /F /T

if exist runs\distill\resumable\latest.pt (
    echo [stop] Resumable ckpt at: runs\distill\resumable\latest.pt
    echo [stop] Re-launch with: tools\quant\start_real_training.bat (auto-resume)
) else (
    echo [stop] WARN: no latest.pt found ^(was killed before first epoch end^)
)
