@echo off
REM A1 W10 - real distillation training on COCO train2017 118K (RTX 5060 Laptop).
REM Wall time ~48 hours for 30 epoch. Resumable; auto-resume after reboot.
REM
REM Prerequisites:
REM   1. train2017 images at C:\...\UI\RK3588\YOLOv8\datasets\coco\images\train2017\
REM      (download via: tools\ci\download_train2017_bits.ps1)
REM   2. YOLO labels already present at .../coco/labels/train2017/ (117266 .txt)
REM
REM Double-click to start. Double-click again after reboot - auto-resumes
REM from runs\distill_train2017\resumable\latest.pt (saved every epoch).
setlocal EnableDelayedExpansion

set PYTHON=D:\Application\Miniconda3\envs\spikeyolo\python.exe
set REPO=C:\Users\jielu\Desktop\Project\SpikeYOLO
set COCO_TRAIN=C:\Users\jielu\Desktop\Project\UI\RK3588\YOLOv8\datasets\coco\images\train2017
cd /d %REPO%

REM ---- Preflight: train2017 imgs present? ----
if not exist "%COCO_TRAIN%" (
    echo [start] ERROR: train2017 image dir missing: %COCO_TRAIN%
    echo [start] Run download first:
    echo         powershell -ExecutionPolicy Bypass -File tools\ci\download_train2017_bits.ps1
    pause
    endlocal & exit /b 1
)

REM Sanity count
for /f %%i in ('dir /a-d /b "%COCO_TRAIN%\*.jpg" 2^>nul ^| find /c /v ""') do set IMG_COUNT=%%i
echo [start] train2017 image count: !IMG_COUNT!
if !IMG_COUNT! lss 117000 (
    echo [start] WARNING: only !IMG_COUNT! jpgs found; expected ~118287. Download may be incomplete.
    echo [start] Continuing anyway. If you see file-not-found errors below, re-run download script.
)

if not exist runs\distill_train2017\resumable mkdir runs\distill_train2017\resumable

REM ---- Detect already-running training to avoid duplicate launch ----
if exist runs\distill_train2017\training.pid (
    set /p OLD_PID=<runs\distill_train2017\training.pid
    powershell -NoProfile -Command "if (Get-Process -Id !OLD_PID! -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
    if !errorlevel! equ 0 (
        echo [start] Training already running. PID=!OLD_PID! - exiting.
        endlocal & exit /b 0
    ) else (
        echo [start] Stale PID file - cleaning up
        del runs\distill_train2017\training.pid
    )
)

set BASE_ARGS='tools/quant/distill_from_teacher.py','--teacher','models/SpikeYOLO_23.1M_T1D4.pt','--student-cfg','ultralytics/cfg/models/v8/snn_yolov8_tiny_fpga.yaml','--student-init','models/tiny_fpga_fp32.pt','--config','tools/quant/distill_config_train2017.yaml','--out','models/tiny_fpga_fp32_distilled_train2017.pt','--log','runs/distill_train2017/training_log.csv','--device','cuda','--epochs','30','--batch-size','16'

if exist runs\distill_train2017\resumable\latest.pt (
    echo [start] Resumable ckpt found at runs\distill_train2017\resumable\latest.pt - will RESUME
    set FULL_ARGS=!BASE_ARGS!,'--resume-auto'
) else (
    echo [start] No resumable ckpt - FRESH start (epoch 0)
    set FULL_ARGS=!BASE_ARGS!
)

powershell -NoProfile -Command "$proc = Start-Process -FilePath '%PYTHON%' -ArgumentList !FULL_ARGS! -WorkingDirectory '%REPO%' -RedirectStandardOutput 'runs\distill_train2017\training_stdout.log' -RedirectStandardError 'runs\distill_train2017\training_stderr.log' -PassThru -WindowStyle Hidden; $proc.Id | Out-File runs\distill_train2017\training.pid -Encoding ascii"

echo.
echo [start] Launched. PID:
type runs\distill_train2017\training.pid
echo.
echo [start] Logs:        runs\distill_train2017\training_stdout.log
echo                      runs\distill_train2017\training_log.csv
echo [start] Resumable:   runs\distill_train2017\resumable\latest.pt + epoch_NN.pt (every ~97 min)
echo [start] Final model: models\tiny_fpga_fp32_distilled_train2017.pt
echo.
echo [start] Expected wall time: 30 epoch * ~97 min/ep ~= 48-50 hours
echo.
echo [start] To watch progress:
echo         Get-Content runs\distill_train2017\training_stderr.log -Wait -Tail 5
echo.
echo [start] To stop gracefully (saves latest.pt then exits):
echo         Stop-Process -Id ^<PID^>
echo.
echo [start] After reboot: double-click this .bat again - auto-resumes.
endlocal
