#!/usr/bin/env bash
# tools/ci/download_coco_modelscope.sh
#
# Download COCO 2017 from ModelScope (阿里云国内镜像，无需账号).
# Bypasses cocodataset.org throttling.
#
# Usage on A800:
#   curl -sL https://raw.githubusercontent.com/yizhidianlu/SpikeYOLO_FPGA/main/tools/ci/download_coco_modelscope.sh | bash
# OR after git pull:
#   bash tools/ci/download_coco_modelscope.sh
#
# Target: /root/autodl-fs/coco_dataset (file storage 200G)
# 阿里云 OSS / 国内 CDN: 通常 10-50 MB/s

set -e
echo "[coco-ms] === ModelScope COCO download $(date) ==="

COCO=/root/autodl-fs/coco_dataset
mkdir -p $COCO

# Method 1: git lfs clone (推荐, 自动多文件并发)
#   ModelScope COCO repo: AI-ModelScope/coco_2017 (常见 mirror) or modelscope/coco_2017
DS=$COCO/_modelscope_repo
if [ ! -d $DS/.git ]; then
    echo "[coco-ms] git clone ModelScope COCO (LFS, ~36GB, 国内 CDN ~10-50 MB/s)"
    # Try 2 common repo names
    git clone https://www.modelscope.cn/datasets/AI-ModelScope/coco_2017.git $DS 2>/dev/null || \
    git clone https://www.modelscope.cn/datasets/modelscope/coco_2017.git $DS 2>/dev/null || \
    git clone https://www.modelscope.cn/datasets/swift/coco_2017.git $DS || {
        echo "[coco-ms] ERROR: none of the 3 candidate repos cloned."
        echo "  Browse https://www.modelscope.cn/datasets to find correct coco_2017 path."
        exit 1
    }
fi

cd $DS
echo "[coco-ms] Repo structure:"
ls -la | head -20

# git LFS auto-pulls files on clone (assuming GIT_LFS_SKIP_SMUDGE not set).
# Verify:
echo "[coco-ms] Pulling LFS content (if not already)"
git lfs install 2>/dev/null || true
git lfs pull || true

# Method 2 fallback: openxlab (OpenDataLab) if ModelScope failed schema
# ... (omitted for now, ModelScope usually works)

# ---- Detect ModelScope layout ----
echo "[coco-ms] Detecting downloaded layout"
ls -la $DS/ | grep -E "^d|train|val|annot|coco" | head -20

# Common ModelScope COCO layouts:
#   $DS/data/train2017.zip + val2017.zip + annotations_trainval2017.zip (raw zips)
#   $DS/data/coco/{train2017,val2017,annotations}  (pre-extracted)
#   $DS/train2017.zip + val2017.zip (top-level zips)
#   $DS/raw/...  (varies)

# Find train2017 wherever it is
TRAIN_ZIP=$(find $DS -name "train2017.zip" -size +1G 2>/dev/null | head -1)
VAL_ZIP=$(find $DS -name "val2017.zip" -size +100M 2>/dev/null | head -1)
ANN_ZIP=$(find $DS -name "annotations_trainval2017.zip" 2>/dev/null | head -1)
TRAIN_DIR=$(find $DS -type d -name "train2017" 2>/dev/null | head -1)

mkdir -p $COCO/images $COCO/annotations

if [ -d "$TRAIN_DIR" ]; then
    # Layout: pre-extracted
    echo "[coco-ms] Layout: pre-extracted at $TRAIN_DIR"
    PARENT=$(dirname $TRAIN_DIR)
    ln -sfn $TRAIN_DIR $COCO/images/train2017
    [ -d $PARENT/val2017 ] && ln -sfn $PARENT/val2017 $COCO/images/val2017
    [ -d $PARENT/annotations ] && ln -sfn $PARENT/annotations $COCO/annotations
elif [ -f "$TRAIN_ZIP" ]; then
    # Layout: zip archive — extract
    echo "[coco-ms] Layout: zip archive at $TRAIN_ZIP"
    unzip -qn "$TRAIN_ZIP" -d $COCO/images/
    [ -f "$VAL_ZIP" ] && unzip -qn "$VAL_ZIP" -d $COCO/images/
    [ -f "$ANN_ZIP" ] && unzip -qn "$ANN_ZIP" -d $COCO/
else
    echo "[coco-ms] ERROR: cannot find train2017 in $DS"
    echo "  Manual inspection: ls -R $DS | head -50"
    ls -R $DS | head -50
    exit 1
fi

# Always fetch YOLO labels from ultralytics (small, 70 MB, via gh-proxy)
YOLO_LBL=$COCO/_downloads/coco2017labels.zip
mkdir -p $COCO/_downloads
if [ ! -s $YOLO_LBL ]; then
    echo "[coco-ms] downloading YOLO labels via gh-proxy"
    wget -q --show-progress -O $YOLO_LBL \
        "https://gh-proxy.com/https://github.com/ultralytics/yolov5/releases/download/v1.0/coco2017labels.zip" || \
    wget -q --show-progress -O $YOLO_LBL \
        "https://github.com/ultralytics/yolov5/releases/download/v1.0/coco2017labels.zip"
fi

# Extract labels (replaces only labels dir, doesn't touch images)
if [ -s $YOLO_LBL ]; then
    rm -rf /tmp/_yolo_lbl
    unzip -qn $YOLO_LBL -d /tmp/_yolo_lbl/
    rm -rf $COCO/labels
    mv /tmp/_yolo_lbl/coco/labels $COCO/ 2>/dev/null
    rm -rf /tmp/_yolo_lbl
fi

# ---- Verify ----
T=$(ls $COCO/images/train2017 2>/dev/null | wc -l)
V=$(ls $COCO/images/val2017 2>/dev/null | wc -l)
LT=$(ls $COCO/labels/train2017 2>/dev/null | wc -l)
LV=$(ls $COCO/labels/val2017 2>/dev/null | wc -l)
A=$(ls $COCO/annotations/instances_train2017.json 2>/dev/null && echo yes || echo no)

echo ""
echo "============================================================"
echo "[coco-ms] === Verification ==="
echo "  train imgs:  $T (expected ~118287)"
echo "  val imgs:    $V (expected ~5000)"
echo "  train lbls:  $LT (expected ~117266)"
echo "  val lbls:    $LV (expected ~4952)"
echo "  instances_train2017.json: $A"
echo "============================================================"

if [ "$T" -ge 118000 ] && [ "$V" -ge 4900 ]; then
    echo "[coco-ms] ✅ COCO ready at $COCO"
    echo "  Now run: curl -sL https://raw.githubusercontent.com/yizhidianlu/SpikeYOLO_FPGA/main/tools/ci/a800_bootstrap.sh | bash"
else
    echo "[coco-ms] ⚠️  Verification failed. Inspect $DS manually."
    exit 1
fi
