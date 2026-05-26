@echo off
REM A1 W10-prep - coco128 distillation training (resumable, ~30-60 min).
REM Bridge sprint while A800 COCO download is pending.
REM
REM Double-click to start. Double-click again after reboot -> auto-resumes
REM from runs\distill_coco128\resumable\latest.pt (saved every epoch).
setlocal EnableDelayedExpansion

set PYTHON=D:\Application\Miniconda3\envs\spikeyolo\python.exe
set REPO=C:\Users\jielu\Desktop\Project\SpikeYOLO
cd /d %REPO%

if not exist runs\distill_coco128\resumable mkdir runs\distill_coco128\resumable

REM Detect already-running training to avoid duplicate launch.
if exist runs\distill_coco128\training.pid (
    set /p OLD_PID=<runs\distill_coco128\training.pid
    powershell -NoProfile -Command "if (Get-Process -Id !OLD_PID! -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
    if !errorlevel! equ 0 (
        echo [start] Training already running. PID=!OLD_PID! - exiting.
        echo [start] To stop: Stop-Process -Id !OLD_PID!  ^|^|  delete runs\distill_coco128\training.pid + rerun
        endlocal & exit /b 0
    ) else (
        echo [start] Stale PID file runs\distill_coco128\training.pid - cleaning up
        del runs\distill_coco128\training.pid
    )
)

set BASE_ARGS='tools/quant/distill_from_teacher.py','--teacher','models/SpikeYOLO_23.1M_T1D4.pt','--student-cfg','ultralytics/cfg/models/v8/snn_yolov8_tiny_fpga.yaml','--student-init','models/tiny_fpga_fp32.pt','--config','tools/quant/distill_config_coco128.yaml','--out','models/tiny_fpga_fp32_distilled_coco128.pt','--log','runs/distill_coco128/training_log.csv','--device','cuda','--epochs','100','--batch-size','16'

if exist runs\distill_coco128\resumable\latest.pt (
    echo [start] Resumable ckpt found at runs\distill_coco128\resumable\latest.pt - will RESUME
    set FULL_ARGS=!BASE_ARGS!,'--resume-auto'
) else (
    echo [start] No resumable ckpt - FRESH start (coco128 will auto-download ~7 MB to datasets\coco128\)
    set FULL_ARGS=!BASE_ARGS!
)

powershell -NoProfile -Command "$proc = Start-Process -FilePath '%PYTHON%' -ArgumentList !FULL_ARGS! -WorkingDirectory '%REPO%' -RedirectStandardOutput 'runs\distill_coco128\training_stdout.log' -RedirectStandardError 'runs\distill_coco128\training_stderr.log' -PassThru -WindowStyle Hidden; $proc.Id | Out-File runs\distill_coco128\training.pid -Encoding ascii"

echo.
echo [start] Launched. PID:
type runs\distill_coco128\training.pid
echo.
echo [start] Logs:        runs\distill_coco128\training_stdout.log
echo                      runs\distill_coco128\training_log.csv
echo [start] Resumable:   runs\distill_coco128\resumable\latest.pt + epoch_NN.pt
echo [start] Final model: models\tiny_fpga_fp32_distilled_coco128.pt
echo.
echo [start] To watch progress in real time:
echo         Get-Content runs\distill_coco128\training_stdout.log -Wait -Tail 30
echo.
echo [start] To stop gracefully (saves latest.pt before exit):
echo         Stop-Process -Id ^<PID^>     # SIGTERM trigger graceful_save
echo.
echo [start] After reboot: just double-click this .bat again - it auto-resumes.
endlocal
