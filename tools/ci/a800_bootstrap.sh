#!/usr/bin/env bash
# A800 one-shot bootstrap — git clone + conda + COCO download/unzip + tmux launch.
# Usage on A800:
#   curl -sL https://raw.githubusercontent.com/yizhidianlu/SpikeYOLO_FPGA/main/tools/ci/a800_bootstrap.sh | bash
#
# Prerequisite: user scp'd teacher + student .pt to /root/ on A800 first:
#   scp -P 50535 models/SpikeYOLO_23.1M_T1D4.pt models/tiny_fpga_fp32.pt root@connect.nma1.seetacloud.com:/root/

set -e
echo "[bootstrap] === A800 setup start $(date) ==="

WORKDIR=/root/autodl-tmp
cd $WORKDIR

# ---- 1. Clone repo ----
if [ ! -d SpikeYOLO_FPGA ]; then
    echo "[bootstrap] git clone"
    git clone https://github.com/yizhidianlu/SpikeYOLO_FPGA.git
fi
cd SpikeYOLO_FPGA
git pull origin main || true

# ---- 2. Move .pt from /root/ to models/ ----
mkdir -p models
[ -f /root/SpikeYOLO_23.1M_T1D4.pt ] && mv -n /root/SpikeYOLO_23.1M_T1D4.pt models/
[ -f /root/tiny_fpga_fp32.pt ] && mv -n /root/tiny_fpga_fp32.pt models/
if [ ! -f models/SpikeYOLO_23.1M_T1D4.pt ]; then
    echo "[bootstrap] ERROR: models/SpikeYOLO_23.1M_T1D4.pt missing."
    echo "  On local PowerShell run:"
    echo "    cd C:\\Users\\jielu\\Desktop\\Project\\SpikeYOLO"
    echo "    scp -P 50535 models/SpikeYOLO_23.1M_T1D4.pt models/tiny_fpga_fp32.pt root@connect.nma1.seetacloud.com:/root/"
    echo "  then re-run this bootstrap."
    exit 1
fi
echo "[bootstrap] teacher + student .pt present"

# ---- 3. Conda env ----
echo "[bootstrap] setup conda env spikeyolo"
source /root/miniconda3/etc/profile.d/conda.sh 2>/dev/null || \
    source $(conda info --base)/etc/profile.d/conda.sh
if ! conda env list | grep -q '^spikeyolo'; then
    conda create -n spikeyolo python=3.10 -y
fi
conda activate spikeyolo
pip install -q -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple || \
    pip install -q -r requirements.txt
pip install -q -r requirements-fpga.txt -i https://pypi.tuna.tsinghua.edu.cn/simple || \
    pip install -q -r requirements-fpga.txt
echo "[bootstrap] python env ready: $(which python) / torch $(python -c 'import torch;print(torch.__version__)')"

# ---- 4. COCO download (aria2 if available, else wget) ----
echo "[bootstrap] check COCO dataset"
TRAIN_IMGS=$(ls datasets/coco/images/train2017 2>/dev/null | wc -l)
if [ "$TRAIN_IMGS" -lt 118000 ]; then
    echo "[bootstrap] COCO incomplete ($TRAIN_IMGS train imgs); download/unzip"
    mkdir -p datasets/coco/_downloads
    cd datasets/coco/_downloads
    DL_TOOL="wget -c -q --show-progress"
    command -v aria2c >/dev/null && DL_TOOL="aria2c -x16 -s16 -c --console-log-level=warn"
    for url in \
        "http://images.cocodataset.org/zips/train2017.zip" \
        "http://images.cocodataset.org/zips/val2017.zip" \
        "http://images.cocodataset.org/annotations/annotations_trainval2017.zip" \
        "https://github.com/ultralytics/yolov5/releases/download/v1.0/coco2017labels.zip"; do
        f=$(basename $url)
        if [ ! -f $f ] || [ $(stat -c%s $f 2>/dev/null || echo 0) -lt 1000000 ]; then
            echo "[bootstrap]   downloading $f ..."
            $DL_TOOL "$url"
        else
            echo "[bootstrap]   $f already present"
        fi
    done
    cd $WORKDIR/SpikeYOLO_FPGA

    echo "[bootstrap] unzip"
    for zip in datasets/coco/_downloads/*.zip; do
        case $(basename $zip) in
            train2017.zip|val2017.zip)
                unzip -qn $zip -d datasets/coco/images/ ;;
            annotations_trainval2017.zip)
                unzip -qn $zip -d datasets/coco/ ;;
            coco2017labels.zip)
                rm -rf /tmp/_yolo_lbl
                unzip -qn $zip -d /tmp/_yolo_lbl/
                rm -rf datasets/coco/labels
                mv /tmp/_yolo_lbl/coco/labels datasets/coco/ 2>/dev/null || true
                rm -rf /tmp/_yolo_lbl
                ;;
        esac
    done
fi

TRAIN_IMGS=$(ls datasets/coco/images/train2017 2>/dev/null | wc -l)
VAL_IMGS=$(ls datasets/coco/images/val2017 2>/dev/null | wc -l)
echo "[bootstrap] COCO ready: train=$TRAIN_IMGS val=$VAL_IMGS"
[ "$TRAIN_IMGS" -lt 118000 ] && { echo "ERROR: train2017 incomplete"; exit 1; }

# ---- 5. Path-fix yaml ----
sed -i 's|C:/Users/jielu/Desktop/Project/SpikeYOLO|/root/autodl-tmp/SpikeYOLO_FPGA|g' \
    ultralytics/cfg/datasets/coco_real_local.yaml 2>/dev/null || true

# ---- 6. A800 distill config ----
echo "[bootstrap] write distill_config_a800.yaml"
cat > tools/quant/distill_config_a800.yaml <<'YAML_EOF'
optimizer:    AdamW
lr:           5e-4
lr_schedule:  cosine
weight_decay: 1e-4
epochs:       30
batch_size:   64
warmup_epochs: 3
loss_weights:
  det:        1.0
  kd_logits:  1.5
  feat_align: 0.5
  spike_rate: 0.3
data:
  dataset_yaml: ultralytics/cfg/datasets/coco_real_local.yaml
  val_every:    0
  imgsz:        256
freeze_teacher: true
adapter_init:   kaiming
seed:           42
teacher_inference_mode: avgpool_from_640
device:        cuda
log_interval:  10
ckpt_interval: 1
resume_dir:    runs/distill/resumable/
amp:           false
gradient_clip_norm: 1.0
data_loader_workers: 8
prefetch_factor: 4
YAML_EOF

# ---- 7. Launch training in tmux ----
mkdir -p runs/distill/resumable runs/distill
RESUME_FLAG=""
if [ -f runs/distill/resumable/latest.pt ]; then
    RESUME_FLAG="--resume-auto"
    echo "[bootstrap] RESUMING from runs/distill/resumable/latest.pt"
fi

echo "[bootstrap] tmux new-session 'spike-train'..."
tmux kill-session -t spike-train 2>/dev/null || true
tmux new-session -d -s spike-train \
    "cd $WORKDIR/SpikeYOLO_FPGA && source $(conda info --base)/etc/profile.d/conda.sh && conda activate spikeyolo && python tools/quant/distill_from_teacher.py \
        --teacher models/SpikeYOLO_23.1M_T1D4.pt \
        --student-cfg ultralytics/cfg/models/v8/snn_yolov8_tiny_fpga.yaml \
        --student-init models/tiny_fpga_fp32.pt \
        --config tools/quant/distill_config_a800.yaml \
        --out models/tiny_fpga_fp32_distilled_a800.pt \
        --log runs/distill/a800_training_log.csv \
        --device cuda --epochs 30 --batch-size 64 $RESUME_FLAG \
        2>&1 | tee runs/distill/a800_training.log"

echo "[bootstrap] tmux launched; sleeping 45s for first step..."
sleep 45
echo ""
echo "============================================================"
echo "[bootstrap] tmux session:"
tmux ls 2>&1 || echo "  (no tmux session)"
echo ""
echo "[bootstrap] last 30 log lines:"
tail -30 runs/distill/a800_training.log 2>/dev/null || echo "  (log empty)"
echo "============================================================"
echo ""
echo "[bootstrap] === BOOTSTRAP COMPLETE ==="
echo ""
echo "  Monitor:  tmux attach -t spike-train   (Ctrl+B then D to detach)"
echo "  Log tail: tail -f $WORKDIR/SpikeYOLO_FPGA/runs/distill/a800_training.log"
echo "  Ckpts:    ls $WORKDIR/SpikeYOLO_FPGA/models/tiny_fpga_fp32_distilled_a800*.pt"
echo "  GPU:      nvidia-smi"
echo ""
echo "  ETA: 10-15h (A800 batch=64, train2017 118K, 30 epoch)"
echo "  Resume after disconnect: 'tmux attach -t spike-train' or simply re-run this bootstrap"
echo "  Auto-resume: latest.pt in runs/distill/resumable/ — re-running bootstrap continues from last epoch"
