#!/usr/bin/env bash
# A800 one-shot bootstrap (v2 — AutoDL disk-aware layout)
#
# AutoDL 实例规格 (per user 2026-05-12):
#   /                30G  系统盘 (放系统 + conda env)
#   /root/autodl-tmp 75G  数据盘 fast IO (repo + ckpts + training log)
#   /root/autodl-fs  200G 文件存储 (COCO dataset, 18G zip + 18G unzip)
#
# Usage on A800 (conda 已装):
#   curl -sL https://raw.githubusercontent.com/yizhidianlu/SpikeYOLO_FPGA/main/tools/ci/a800_bootstrap.sh | bash
#
# Prerequisite: local PowerShell scp teacher + student .pt to A800 /root/ first:
#   scp -P 50535 models/SpikeYOLO_23.1M_T1D4.pt models/tiny_fpga_fp32.pt root@<host>:/root/

set -e
echo "[bootstrap] === A800 v2.3 setup $(date '+%Y-%m-%d %H:%M:%S') ==="

# ---- 0. AutoDL 学术加速 (opt-in)
# 默认 aria2 -x16 -s16 直连 cocodataset.org (主开发机实测 5-7 MB/s OK).
# 如果你的实例 turbo work, 设 SPIKE_USE_TURBO=1 启用 (可能进一步加速到 30+ MB/s).
# 如果 turbo 失效但仍被启用会污染 proxy env, 拖慢 aria2 -> 默认关.
if [ "${SPIKE_USE_TURBO}" = "1" ] && [ -f /etc/network_turbo ]; then
    echo "[bootstrap] SPIKE_USE_TURBO=1: enabling AutoDL academic proxy"
    source /etc/network_turbo
    echo "[bootstrap] proxy: http_proxy=${http_proxy:-(unset)}"
else
    # 显式 unset 任何之前 session 残留 proxy 让 aria2 干净直连
    unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY 2>/dev/null || true
    echo "[bootstrap] turbo disabled (default); aria2 -x16 will direct-connect cocodataset.org"
fi

WORKDIR=/root/autodl-tmp
COCO_ROOT=/root/autodl-fs/coco_dataset
REPO=$WORKDIR/SpikeYOLO_FPGA

# ---- 1. Repo clone / pull ----
cd $WORKDIR
if [ ! -d SpikeYOLO_FPGA ]; then
    echo "[bootstrap] git clone"
    git clone https://github.com/yizhidianlu/SpikeYOLO_FPGA.git
fi
cd $REPO
git pull origin main || true

# ---- 2. Move teacher / student .pt ----
mkdir -p models
[ -f /root/SpikeYOLO_23.1M_T1D4.pt ] && mv -n /root/SpikeYOLO_23.1M_T1D4.pt models/
[ -f /root/tiny_fpga_fp32.pt ]       && mv -n /root/tiny_fpga_fp32.pt models/
if [ ! -f models/SpikeYOLO_23.1M_T1D4.pt ]; then
    echo "ERROR: models/SpikeYOLO_23.1M_T1D4.pt missing."
    echo "  Run on local PowerShell:"
    echo "    cd C:\\Users\\jielu\\Desktop\\Project\\SpikeYOLO"
    echo "    scp -P <port> models/SpikeYOLO_23.1M_T1D4.pt models/tiny_fpga_fp32.pt root@<host>:/root/"
    echo "  Then re-run this bootstrap."
    exit 1
fi
echo "[bootstrap] teacher + student .pt present in models/"

# ---- 3. Conda env (conda 已装, 仅需创建 spikeyolo env) ----
CONDA_BASE=$(conda info --base 2>/dev/null || echo /root/miniconda3)
[ -f "$CONDA_BASE/etc/profile.d/conda.sh" ] || { echo "ERROR: conda not found at $CONDA_BASE"; exit 1; }
source "$CONDA_BASE/etc/profile.d/conda.sh"

if ! conda env list | grep -qE '^spikeyolo\s'; then
    echo "[bootstrap] create conda env spikeyolo (python 3.10)"
    conda create -n spikeyolo python=3.10 -y
fi
conda activate spikeyolo

PIP_TUNA="pip install -q -i https://pypi.tuna.tsinghua.edu.cn/simple"
echo "[bootstrap] install requirements (tuna mirror)"
$PIP_TUNA -r requirements.txt        || pip install -q -r requirements.txt
$PIP_TUNA -r requirements-fpga.txt   || pip install -q -r requirements-fpga.txt
echo "[bootstrap] torch: $(python -c 'import torch;print(torch.__version__, "cuda="+str(torch.cuda.is_available()), torch.cuda.get_device_name(0) if torch.cuda.is_available() else "")')"

# ---- 4. COCO setup ----
# Priority chain:
#   (a) AutoDL public dataset /root/autodl-pub/COCO2017 (符号链接, 零下载, 最快)
#   (b) 已下载到 /root/autodl-fs/coco_dataset (resume)
#   (c) aria2 -x16 直连 cocodataset.org (最后 fallback)
mkdir -p $REPO/datasets
rm -rf $REPO/datasets/coco

PUB=/root/autodl-pub/COCO2017
if [ -d $PUB ]; then
    echo "[bootstrap] Found AutoDL public dataset: $PUB (zero-download path)"
    # Detect layout
    if [ -d $PUB/images/train2017 ] && [ -d $PUB/images/val2017 ]; then
        # Layout A: images/train2017, images/val2017, annotations
        rm -rf $COCO_ROOT/images $COCO_ROOT/annotations $COCO_ROOT/labels
        mkdir -p $COCO_ROOT
        ln -sfn $PUB/images       $COCO_ROOT/images
        ln -sfn $PUB/annotations  $COCO_ROOT/annotations
        [ -d $PUB/labels ] && ln -sfn $PUB/labels $COCO_ROOT/labels
        echo "[bootstrap] symlinked layout A (images/, annotations/, labels/)"
    elif [ -d $PUB/train2017 ] && [ -d $PUB/val2017 ]; then
        # Layout B: train2017, val2017, annotations top-level
        rm -rf $COCO_ROOT/images $COCO_ROOT/annotations $COCO_ROOT/labels
        mkdir -p $COCO_ROOT/images
        ln -sfn $PUB/train2017     $COCO_ROOT/images/train2017
        ln -sfn $PUB/val2017       $COCO_ROOT/images/val2017
        ln -sfn $PUB/annotations   $COCO_ROOT/annotations
        [ -d $PUB/labels ] && ln -sfn $PUB/labels $COCO_ROOT/labels
        echo "[bootstrap] symlinked layout B (train2017/, val2017/ top-level)"
    else
        echo "[bootstrap] WARN: unrecognized autodl-pub layout. Dumping tree (depth=2):"
        find $PUB -maxdepth 2 -type d 2>&1 | head -30
        echo "[bootstrap] WARN: also checking zip layout..."
        find $PUB -maxdepth 3 -name "*.zip" 2>&1 | head -10
        echo "[bootstrap] WARN: if you see *.zip files, run:"
        echo "  cd $COCO_ROOT && unzip -qn $PUB/train2017.zip -d images/ && unzip -qn $PUB/val2017.zip -d images/ && unzip -qn $PUB/annotations_trainval2017.zip -d ."
        echo "[bootstrap] fallback to download path"
    fi
fi

mkdir -p $COCO_ROOT/_downloads $COCO_ROOT/images $COCO_ROOT/annotations
ln -sfn $COCO_ROOT $REPO/datasets/coco
echo "[bootstrap] symlink: $REPO/datasets/coco -> $COCO_ROOT"

# YOLO labels: even if autodl-pub didn't include labels, derive from labels zip
if [ ! -d $COCO_ROOT/labels/train2017 ]; then
    echo "[bootstrap] YOLO labels missing — will download just coco2017labels.zip (small, 70 MB)"
fi

TRAIN_IMGS=$(ls $COCO_ROOT/images/train2017 2>/dev/null | wc -l)
if [ "$TRAIN_IMGS" -lt 118000 ]; then
    echo "[bootstrap] COCO incomplete (train=$TRAIN_IMGS); downloading to $COCO_ROOT/_downloads"
    cd $COCO_ROOT/_downloads
    if ! command -v aria2c >/dev/null 2>&1; then
        echo "[bootstrap] installing aria2c (apt-get, fast)"
        apt-get install -y -qq aria2 2>/dev/null || apt install -y aria2 2>/dev/null || {
            echo "[bootstrap] aria2 install failed, fallback to wget (slower)"
        }
    fi
    if command -v aria2c >/dev/null 2>&1; then
        DL="aria2c -x16 -s16 -c --max-tries=20 --retry-wait=10 --console-log-level=warn --summary-interval=30"
        echo "[bootstrap] aria2c -x16 -s16 ready (主开发机当时同款方案, expected 5-15 MB/s)"
    else
        DL="wget -c --no-verbose"
    fi
    for url in \
        "http://images.cocodataset.org/zips/train2017.zip" \
        "http://images.cocodataset.org/zips/val2017.zip" \
        "http://images.cocodataset.org/annotations/annotations_trainval2017.zip" \
        "https://github.com/ultralytics/yolov5/releases/download/v1.0/coco2017labels.zip"; do
        f=$(basename $url)
        if [ ! -s $f ] || [ $(stat -c%s $f) -lt 1000000 ]; then
            echo "[bootstrap]  downloading $f"
            $DL "$url"
        fi
    done

    echo "[bootstrap] unzip (all to $COCO_ROOT)"
    for zip in *.zip; do
        case $(basename $zip) in
            train2017.zip|val2017.zip)
                unzip -qn $zip -d $COCO_ROOT/images/ ;;
            annotations_trainval2017.zip)
                unzip -qn $zip -d $COCO_ROOT/ ;;
            coco2017labels.zip)
                rm -rf /tmp/_yolo_lbl
                unzip -qn $zip -d /tmp/_yolo_lbl/
                rm -rf $COCO_ROOT/labels
                mv /tmp/_yolo_lbl/coco/labels $COCO_ROOT/ 2>/dev/null || true
                rm -rf /tmp/_yolo_lbl
                ;;
        esac
    done
    cd $REPO
fi

TRAIN_IMGS=$(ls $REPO/datasets/coco/images/train2017 2>/dev/null | wc -l)
VAL_IMGS=$(ls $REPO/datasets/coco/images/val2017 2>/dev/null | wc -l)
echo "[bootstrap] COCO ready: train=$TRAIN_IMGS val=$VAL_IMGS"
[ "$TRAIN_IMGS" -lt 118000 ] && { echo "ERROR: train2017 incomplete"; exit 1; }

# ---- 5. yaml path patch ----
YAML=$REPO/ultralytics/cfg/datasets/coco_real_local.yaml
if [ -f $YAML ]; then
    sed -i "s|C:/Users/jielu/Desktop/Project/SpikeYOLO/datasets/coco|$REPO/datasets/coco|g" $YAML
    sed -i "s|C:/Users/jielu/Desktop/Project/SpikeYOLO|$REPO|g" $YAML
fi

# ---- 6. A800-tuned distill config ----
cat > $REPO/tools/quant/distill_config_a800.yaml <<'YAML_EOF'
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
data_loader_workers: 12
prefetch_factor:  4
YAML_EOF

# ---- 7. tmux launch with resume detect ----
cd $REPO
mkdir -p runs/distill/resumable runs/distill
RESUME=""
if [ -f runs/distill/resumable/latest.pt ]; then
    RESUME="--resume-auto"
    echo "[bootstrap] RESUMING from runs/distill/resumable/latest.pt"
fi

tmux kill-session -t spike-train 2>/dev/null || true
tmux new-session -d -s spike-train \
  "cd $REPO && source $CONDA_BASE/etc/profile.d/conda.sh && conda activate spikeyolo && \
   python tools/quant/distill_from_teacher.py \
     --teacher models/SpikeYOLO_23.1M_T1D4.pt \
     --student-cfg ultralytics/cfg/models/v8/snn_yolov8_tiny_fpga.yaml \
     --student-init models/tiny_fpga_fp32.pt \
     --config tools/quant/distill_config_a800.yaml \
     --out models/tiny_fpga_fp32_distilled_a800.pt \
     --log runs/distill/a800_training_log.csv \
     --device cuda --epochs 30 --batch-size 64 $RESUME \
     2>&1 | tee runs/distill/a800_training.log"

echo "[bootstrap] tmux launched; sleeping 50s for first step + dataset scan..."
sleep 50

echo ""
echo "============================================================"
echo "[bootstrap] tmux sessions:"
tmux ls 2>&1
echo ""
echo "[bootstrap] training log (last 40 lines):"
tail -40 runs/distill/a800_training.log 2>/dev/null || echo "  (log empty)"
echo "============================================================"
echo ""
echo "[bootstrap] disk usage:"
df -h / /root/autodl-tmp /root/autodl-fs 2>/dev/null | awk 'NR==1 || /\/$|autodl/'
echo ""
echo "[bootstrap] GPU:"
nvidia-smi --query-gpu=name,memory.used,utilization.gpu,temperature.gpu --format=csv,noheader 2>&1 | head -2
echo ""
echo "============================================================"
echo "[bootstrap] === COMPLETE ==="
echo ""
echo "  Attach:   tmux attach -t spike-train     (Ctrl+B,D detach)"
echo "  Tail:     tail -f $REPO/runs/distill/a800_training.log"
echo "  GPU:      watch -n 1 nvidia-smi"
echo "  Resume:   re-run this bootstrap (auto-detects runs/distill/resumable/latest.pt)"
echo ""
echo "  ETA: 10-15h on A800 80GB (batch=64, train2017 118K, 30 epoch)"
echo "  Final ckpt: $REPO/models/tiny_fpga_fp32_distilled_a800.pt"
echo "  Per-epoch ckpts: $REPO/models/tiny_fpga_fp32_distilled_a800_ep{1..30}.pt"
echo ""
echo "  After training done, scp back to local:"
echo "    scp -P <port> root@<host>:$REPO/models/tiny_fpga_fp32_distilled_a800.pt models/"
