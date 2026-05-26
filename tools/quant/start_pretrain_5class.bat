@echo off
REM A2-W11 Phase A3 launcher: supervised pretrain of snn_yolov8_tiny_fpga on
REM COCO 5-class subset (person / bottle / cup / cell phone / book).
REM
REM Pre-req:
REM   1. Run label filter once:
REM        python tools\quant\filter_coco_5class.py ^
REM          --src-labels C:\Users\jielu\Desktop\Project\UI\RK3588\YOLOv8\datasets\coco\labels ^
REM          --src-images C:\Users\jielu\Desktop\Project\UI\RK3588\YOLOv8\datasets\coco\images ^
REM          --out C:\Users\jielu\Desktop\Project\UI\RK3588\YOLOv8\datasets\coco_5class
REM
REM Double-click to start. Double-click again after reboot - auto-resumes
REM from runs\pretrain_5class\run1\weights\last.pt.

setlocal EnableDelayedExpansion

set PYTHON=D:\Application\Miniconda3\envs\spikeyolo\python.exe
set REPO=C:\Users\jielu\Desktop\Project\SpikeYOLO
set DATA_YAML=ultralytics\cfg\datasets\coco_5class_local.yaml
set COCO_5CLASS_ROOT=C:\Users\jielu\Desktop\Project\UI\RK3588\YOLOv8\datasets\coco_5class
cd /d %REPO%

REM ---- Preflight: filtered labels present? ----
if not exist "%COCO_5CLASS_ROOT%\train2017.txt" (
    echo [start-5class] ERROR: filtered dataset missing: %COCO_5CLASS_ROOT%\train2017.txt
    echo [start-5class] Run filter first:
    echo         %PYTHON% tools\quant\filter_coco_5class.py ^^
    echo             --src-labels C:\Users\jielu\Desktop\Project\UI\RK3588\YOLOv8\datasets\coco\labels ^^
    echo             --src-images C:\Users\jielu\Desktop\Project\UI\RK3588\YOLOv8\datasets\coco\images ^^
    echo             --out %COCO_5CLASS_ROOT%
    pause
    endlocal ^& exit /b 1
)

if not exist runs\pretrain_5class mkdir runs\pretrain_5class

REM ---- Detect already-running training ----
if exist runs\pretrain_5class\training.pid (
    set /p OLD_PID=<runs\pretrain_5class\training.pid
    powershell -NoProfile -Command "if (Get-Process -Id !OLD_PID! -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
    if !errorlevel! equ 0 (
        echo [start-5class] Training already running. PID=!OLD_PID! - exiting.
        endlocal ^& exit /b 0
    ) else (
        echo [start-5class] Stale PID file - cleaning up
        del runs\pretrain_5class\training.pid
    )
)

set ARGS='tools/quant/pretrain_tiny_fpga_5class.py','--cfg','ultralytics/cfg/models/v8/snn_yolov8_tiny_fpga.yaml','--data','ultralytics/cfg/datasets/coco_5class_local.yaml','--epochs','30','--batch','16','--imgsz','256','--device','0','--lr0','0.01','--lrf','0.01','--optimizer','SGD','--mosaic','1.0','--mixup','0.1','--copy-paste','0.1','--workers','2','--project','runs/pretrain_5class','--name','run1','--no-amp'

if exist runs\pretrain_5class\run1\weights\last.pt (
    echo [start-5class] Resumable last.pt found - will RESUME
) else (
    echo [start-5class] No resumable ckpt - FRESH start
)

powershell -NoProfile -Command "$proc = Start-Process -FilePath '%PYTHON%' -ArgumentList !ARGS! -WorkingDirectory '%REPO%' -RedirectStandardOutput 'runs\pretrain_5class\training_stdout.log' -RedirectStandardError 'runs\pretrain_5class\training_stderr.log' -PassThru -WindowStyle Hidden; $proc.Id | Out-File runs\pretrain_5class\training.pid -Encoding ascii"

echo.
echo [start-5class] Launched. PID:
type runs\pretrain_5class\training.pid
echo.
echo [start-5class] Logs:        runs\pretrain_5class\training_stdout.log
echo                              runs\pretrain_5class\training_stderr.log
echo                              runs\pretrain_5class\run1\results.csv  (ultralytics)
echo [start-5class] Best ckpt:    runs\pretrain_5class\run1\weights\best.pt
echo                              also mirrored to models\tiny_fpga_5class_supervised_ep30.pt at end
echo.
echo [start-5class] Expected wall time: 5-class is ~30%% of full COCO instances;
echo                                     estimate 4-7 h for 30 epoch on RTX 5060 Laptop.
echo.
echo [start-5class] To watch progress:
echo         Get-Content runs\pretrain_5class\training_stderr.log -Wait -Tail 10
echo.
echo [start-5class] To stop:
echo         Stop-Process -Id ^<PID^>
echo.
echo [start-5class] After reboot: double-click this .bat again - auto-resumes.
endlocal
