#!/usr/bin/env bash
# A1 W8 — REAL distillation training (resumable, ~3h, val2017 alias). bash
# variant of start_real_training.bat for git-bash / WSL / Linux runners.
set -uo pipefail

PYTHON="${PYTHON_BIN:-D:/Application/Miniconda3/envs/spikeyolo/python.exe}"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO"

mkdir -p runs/distill/resumable

RESUME_FLAG=""
if [ -f runs/distill/resumable/latest.pt ]; then
    echo "[start] Resumable ckpt found at runs/distill/resumable/latest.pt; will RESUME"
    RESUME_FLAG="--resume-auto"
else
    echo "[start] No resumable ckpt; FRESH start"
fi

nohup "$PYTHON" tools/quant/distill_from_teacher.py \
    --teacher models/SpikeYOLO_23.1M_T1D4.pt \
    --student-cfg ultralytics/cfg/models/v8/snn_yolov8_tiny_fpga.yaml \
    --student-init models/tiny_fpga_fp32.pt \
    --config tools/quant/distill_config_real.yaml \
    --out models/tiny_fpga_fp32_distilled_real.pt \
    --log runs/distill/real_training_log.csv \
    --device cuda \
    --epochs 30 \
    --batch-size 16 \
    $RESUME_FLAG \
    > runs/distill/real_training_stdout.log \
    2> runs/distill/real_training_stderr.log &

PID=$!
echo "$PID" > runs/distill/real_training.pid
echo "[start] Launched. PID: $PID"
echo "[start] Logs: runs/distill/real_training_stdout.log + real_training_log.csv"
echo "[start] Resumable ckpts: runs/distill/resumable/latest.pt + epoch_NN.pt"
