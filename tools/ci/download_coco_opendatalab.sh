#!/usr/bin/env bash
# tools/ci/download_coco_opendatalab.sh
#
# Download COCO 2017 from OpenDataLab (上海AI实验室国内镜像).
#
# Prerequisite (one-time, 30 sec):
#   1. 浏览器打开 https://sso.openxlab.org.cn/ 注册 (微信/Github/手机号皆可)
#   2. 进 https://sso.openxlab.org.cn/usercenter/personalToken 复制 AK/SK
#
# Usage on A800:
#   export OPENXLAB_AK="<your access key>"
#   export OPENXLAB_SK="<your secret key>"
#   bash download_coco_opendatalab.sh
# OR:
#   bash download_coco_opendatalab.sh   # 会 prompt 让你 paste AK/SK

set -e
echo "[coco-odl] === OpenDataLab COCO download $(date) ==="

COCO=/root/autodl-fs/coco_dataset
mkdir -p $COCO

# ---- Install openxlab CLI ----
if ! command -v openxlab >/dev/null 2>&1; then
    echo "[coco-odl] installing openxlab (清华源)"
    pip install -q openxlab -i https://pypi.tuna.tsinghua.edu.cn/simple
fi

# ---- Login (auto-skip if already logged) ----
if [ -z "${OPENXLAB_AK:-}" ] || [ -z "${OPENXLAB_SK:-}" ]; then
    if [ ! -f ~/.openxlab/config ]; then
        echo ""
        echo "============================================================"
        echo "FIRST-TIME SETUP:"
        echo "  1. Open https://sso.openxlab.org.cn/  → register (微信/Github/手机号)"
        echo "  2. Open https://sso.openxlab.org.cn/usercenter/personalToken"
        echo "     → copy AK (Access Key) and SK (Secret Key)"
        echo "  3. Run:"
        echo "       export OPENXLAB_AK=\"<paste AK>\""
        echo "       export OPENXLAB_SK=\"<paste SK>\""
        echo "       bash $0"
        echo "============================================================"
        echo ""
        echo "Or paste interactively (Ctrl+C to abort):"
        read -p "Enter OPENXLAB_AK: " OPENXLAB_AK
        read -sp "Enter OPENXLAB_SK: " OPENXLAB_SK
        echo ""
    fi
fi

if [ -n "${OPENXLAB_AK:-}" ] && [ -n "${OPENXLAB_SK:-}" ]; then
    # NOTE: openxlab CLI ≥ 0.0.40 dropped --ak/--sk flags; `openxlab login`
    # is interactive-only. Workaround: write the credentials file directly,
    # bypassing the CLI prompt entirely. Format reverse-engineered from
    # openxlab-python source (~/.openxlab/openxlab.yaml).
    echo "[coco-odl] writing ~/.openxlab/openxlab.yaml (bypass interactive login)"
    mkdir -p ~/.openxlab
    cat > ~/.openxlab/openxlab.yaml <<EOF
ak: $OPENXLAB_AK
sk: $OPENXLAB_SK
EOF
    chmod 600 ~/.openxlab/openxlab.yaml

    # Belt-and-suspenders: also try piped stdin to `openxlab login` in case
    # this CLI version reads from yaml at a different path.
    printf "%s\n%s\n" "$OPENXLAB_AK" "$OPENXLAB_SK" | openxlab login 2>&1 | head -5 || true

    # Final fallback: export env vars so dataset get can pick them up directly.
    export OPENXLAB_AK OPENXLAB_SK
fi

# ---- Download COCO 2017 ----
DST=$COCO/_opendatalab
mkdir -p $DST
echo "[coco-odl] downloading OpenDataLab/COCO_2017 to $DST (国内 CDN, 期望 10-50 MB/s, 36 GB)"
openxlab dataset get --dataset-repo OpenDataLab/COCO_2017 --target-path $DST

# ---- Detect layout ----
echo "[coco-odl] OpenDataLab layout:"
ls -R $DST 2>&1 | head -30

# OpenDataLab/COCO_2017 typical layout (per docs):
#   $DST/OpenDataLab___COCO_2017/raw/
#     ├── train2017.zip
#     ├── val2017.zip
#     ├── annotations_trainval2017.zip
#     ├── stuff_annotations_trainval2017.zip (optional)
#     └── ...
# Or pre-extracted under raw/Images/train2017/ etc.

mkdir -p $COCO/images $COCO/annotations

ODL_RAW=$(find $DST -type d -name "raw" 2>/dev/null | head -1)
if [ -z "$ODL_RAW" ]; then ODL_RAW=$DST; fi

# Try zip-based layout
TRAIN_ZIP=$(find $ODL_RAW -name "train2017.zip" -size +1G 2>/dev/null | head -1)
VAL_ZIP=$(find $ODL_RAW -name "val2017.zip" -size +100M 2>/dev/null | head -1)
ANN_ZIP=$(find $ODL_RAW -name "annotations_trainval2017.zip" 2>/dev/null | head -1)
TRAIN_DIR=$(find $ODL_RAW -type d -name "train2017" 2>/dev/null | head -1)

if [ -d "$TRAIN_DIR" ] && [ "$(ls $TRAIN_DIR | head -1)" ]; then
    echo "[coco-odl] pre-extracted layout at $TRAIN_DIR"
    PARENT=$(dirname $TRAIN_DIR)
    rm -rf $COCO/images/train2017 $COCO/images/val2017
    ln -sfn $TRAIN_DIR $COCO/images/train2017
    [ -d $PARENT/val2017 ] && ln -sfn $PARENT/val2017 $COCO/images/val2017
    ANN_DIR=$(find $ODL_RAW -type d -name "annotations" 2>/dev/null | head -1)
    [ -d "$ANN_DIR" ] && { rm -rf $COCO/annotations; ln -sfn $ANN_DIR $COCO/annotations; }
elif [ -f "$TRAIN_ZIP" ]; then
    echo "[coco-odl] zip layout at $TRAIN_ZIP"
    unzip -qn "$TRAIN_ZIP" -d $COCO/images/
    [ -f "$VAL_ZIP" ] && unzip -qn "$VAL_ZIP" -d $COCO/images/
    [ -f "$ANN_ZIP" ] && unzip -qn "$ANN_ZIP" -d $COCO/
else
    echo "[coco-odl] ERROR: cannot locate train2017 in $ODL_RAW"
    ls -R $ODL_RAW | head -50
    exit 1
fi

# YOLO labels (small, via gh-proxy)
mkdir -p $COCO/_downloads
YOLO_LBL=$COCO/_downloads/coco2017labels.zip
if [ ! -s $YOLO_LBL ]; then
    echo "[coco-odl] downloading YOLO labels via gh-proxy"
    wget -q --show-progress -O $YOLO_LBL \
        "https://gh-proxy.com/https://github.com/ultralytics/yolov5/releases/download/v1.0/coco2017labels.zip"
fi
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
A=$([ -f $COCO/annotations/instances_train2017.json ] && echo yes || echo no)

echo ""
echo "============================================================"
echo "[coco-odl] === Verification ==="
echo "  train imgs:  $T (expected 118287)"
echo "  val imgs:    $V (expected 5000)"
echo "  train lbls:  $LT (expected 117266)"
echo "  val lbls:    $LV (expected 4952)"
echo "  instances_train2017.json: $A"
echo "============================================================"

if [ "$T" -ge 118000 ] && [ "$V" -ge 4900 ]; then
    echo "[coco-odl] ✅ COCO ready at $COCO"
    echo "  Now run: curl -sL https://raw.githubusercontent.com/yizhidianlu/SpikeYOLO_FPGA/main/tools/ci/a800_bootstrap.sh | bash"
else
    echo "[coco-odl] ⚠️  Verification failed."; exit 1
fi
