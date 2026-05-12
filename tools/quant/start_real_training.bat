@echo off
REM A1 W8 - REAL distillation training (resumable, ~3h, val2017 alias).
REM Auto-detects runs/distill/resumable/latest.pt and resumes if found.
setlocal EnableDelayedExpansion

set PYTHON=D:\Application\Miniconda3\envs\spikeyolo\python.exe
set REPO=C:\Users\jielu\Desktop\Project\SpikeYOLO
cd /d %REPO%

if not exist runs\distill\resumable mkdir runs\distill\resumable

set BASE_ARGS='tools/quant/distill_from_teacher.py','--teacher','models/SpikeYOLO_23.1M_T1D4.pt','--student-cfg','ultralytics/cfg/models/v8/snn_yolov8_tiny_fpga.yaml','--student-init','models/tiny_fpga_fp32.pt','--config','tools/quant/distill_config_real.yaml','--out','models/tiny_fpga_fp32_distilled_real.pt','--log','runs/distill/real_training_log.csv','--device','cuda','--epochs','30','--batch-size','16'

if exist runs\distill\resumable\latest.pt (
    echo [start] Resumable ckpt found at runs\distill\resumable\latest.pt; will RESUME
    set FULL_ARGS=!BASE_ARGS!,'--resume-auto'
) else (
    echo [start] No resumable ckpt; FRESH start
    set FULL_ARGS=!BASE_ARGS!
)

powershell -NoProfile -Command "$proc = Start-Process -FilePath '%PYTHON%' -ArgumentList !FULL_ARGS! -WorkingDirectory '%REPO%' -RedirectStandardOutput 'runs\distill\real_training_stdout.log' -RedirectStandardError 'runs\distill\real_training_stderr.log' -PassThru -WindowStyle Hidden; $proc.Id | Out-File runs\distill\real_training.pid -Encoding ascii"

echo [start] Launched. PID:
type runs\distill\real_training.pid
echo [start] Logs: runs\distill\real_training_stdout.log + real_training_log.csv
echo [start] Resumable ckpts: runs\distill\resumable\latest.pt + epoch_NN.pt
endlocal
