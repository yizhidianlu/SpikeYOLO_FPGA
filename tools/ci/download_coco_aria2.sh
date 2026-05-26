#!/usr/bin/env bash
# COCO 2017 multi-threaded download via aria2 (Plan A, Linux/macOS variant).
# Resumes from existing train2017.zip if present.
# Throttled at 10 MB/s overall to avoid saturating other IO.
set -u

DL="datasets/coco/_downloads"
mkdir -p "$DL"

echo "[$(date)] Plan A: aria2 multi-thread COCO 2017 download starting..."
echo "Target dir: $DL"

# train2017 (19.3 GB) - 16 threads, continue from existing partial
aria2c -x 16 -s 16 --continue=true --max-tries=20 --retry-wait=10 \
    --max-overall-download-limit=10M \
    --console-log-level=warn --summary-interval=30 \
    --file-allocation=none --auto-file-renaming=false \
    -d "$DL" -o train2017.zip \
    http://images.cocodataset.org/zips/train2017.zip || echo "train2017 returned $?"

# val2017 (~1 GB)
aria2c -x 8 -s 8 --continue=true --max-tries=10 --retry-wait=10 \
    --console-log-level=warn --summary-interval=30 \
    --file-allocation=none --auto-file-renaming=false \
    -d "$DL" -o val2017.zip \
    http://images.cocodataset.org/zips/val2017.zip || echo "val2017 returned $?"

# annotations (~250 MB)
aria2c -x 4 -s 4 --continue=true --max-tries=10 --retry-wait=10 \
    --console-log-level=warn --summary-interval=30 \
    --file-allocation=none --auto-file-renaming=false \
    -d "$DL" -o annotations_trainval2017.zip \
    http://images.cocodataset.org/annotations/annotations_trainval2017.zip || echo "annotations returned $?"

# YOLO-format labels
aria2c -x 4 -s 4 --continue=true --max-tries=10 --retry-wait=10 \
    --console-log-level=warn --summary-interval=30 \
    --file-allocation=none --auto-file-renaming=false \
    -d "$DL" -o coco2017labels.zip \
    https://github.com/ultralytics/yolov5/releases/download/v1.0/coco2017labels.zip || echo "labels returned $?"

echo "[$(date)] All COCO 2017 archives downloaded."
