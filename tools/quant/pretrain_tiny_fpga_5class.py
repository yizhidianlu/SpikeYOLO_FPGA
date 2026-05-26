"""A2-W11 Phase A3: supervised pretrain of snn_yolov8_tiny_fpga on COCO
5-class subset (person / bottle / cup / cell phone / book).

Why not distill_from_teacher.py?
    The distill path silently fell back to random init because the
    `tiny_fpga_fp32.pt` file was a 23M teacher copy (shape mismatch ⇒
    swallowed exception ⇒ random init for 21 epochs). This script
    bypasses that and provides a clean supervised baseline that we then
    feed BACK into distill_from_teacher.py as a real --student-init.

Workflow:
    1. Phase A3:  this script → tiny_fpga_5class_supervised_ep{N}.pt
    2. Phase A4:  _eval_ep_oneshot.py reports mAP@5class
    3. Phase B (optional): distill_from_teacher.py --student-init <above>

Resume:
    Ultralytics' DetectionTrainer maintains its own resume via the
    `resume=True` flag pointed at <project>/<name>/weights/last.pt.
    If runs/pretrain_5class/run1/weights/last.pt exists this script
    auto-passes resume=True.

Usage (run from repo root):
    python tools/quant/pretrain_tiny_fpga_5class.py \
        --cfg ultralytics/cfg/models/v8/snn_yolov8_tiny_fpga.yaml \
        --data ultralytics/cfg/datasets/coco_5class_local.yaml \
        --epochs 30 --batch 16 --imgsz 256
"""
from __future__ import annotations
import argparse
import sys
import time
from pathlib import Path


def parse_args(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--cfg",   type=Path,
                   default=Path("ultralytics/cfg/models/v8/snn_yolov8_tiny_fpga.yaml"))
    p.add_argument("--data",  type=Path,
                   default=Path("ultralytics/cfg/datasets/coco_5class_local.yaml"))
    p.add_argument("--epochs", type=int, default=30)
    p.add_argument("--batch",  type=int, default=16)
    p.add_argument("--imgsz",  type=int, default=256)
    p.add_argument("--device", type=str, default="0")
    p.add_argument("--lr0",    type=float, default=0.01)
    p.add_argument("--lrf",    type=float, default=0.01,
                   help="final lr fraction (cosine end = lr0 * lrf)")
    p.add_argument("--optimizer", default="SGD")
    p.add_argument("--mosaic",   type=float, default=1.0)
    p.add_argument("--mixup",    type=float, default=0.1)
    p.add_argument("--copy-paste", type=float, default=0.1,
                   help="boost rare classes (cell phone has 7K instances; copy-paste helps)")
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--project", type=Path, default=Path("runs/pretrain_5class"))
    p.add_argument("--name",    default="run1")
    p.add_argument("--patience", type=int, default=50,
                   help="early stop patience; default disables since 30ep is short")
    p.add_argument("--no-amp",  action="store_true",
                   help="disable AMP. SNN layers have known Half/float jitter; default OFF.")
    return p.parse_args(argv)


def main():
    args = parse_args()
    print(f"[pretrain-5class] cfg     = {args.cfg}")
    print(f"[pretrain-5class] data    = {args.data}")
    print(f"[pretrain-5class] epochs  = {args.epochs}  batch={args.batch}  imgsz={args.imgsz}")
    print(f"[pretrain-5class] optimizer = {args.optimizer}  lr0={args.lr0}  lrf={args.lrf}")
    print(f"[pretrain-5class] aug: mosaic={args.mosaic} mixup={args.mixup} copy_paste={args.copy_paste}")
    print(f"[pretrain-5class] project/name = {args.project}/{args.name}")

    if not args.cfg.exists():
        print(f"[pretrain-5class] ERROR: cfg yaml missing: {args.cfg}", file=sys.stderr)
        return 2
    if not args.data.exists():
        print(f"[pretrain-5class] ERROR: data yaml missing: {args.data}", file=sys.stderr)
        return 2

    from ultralytics import YOLO

    # Resume detection — if last.pt from a prior run exists, ultralytics
    # picks up scheduler+optimizer+epoch automatically when resume=True.
    last_pt = args.project / args.name / "weights" / "last.pt"
    if last_pt.exists():
        print(f"[pretrain-5class] resume from {last_pt}")
        model = YOLO(str(last_pt))
        resume = True
    else:
        print(f"[pretrain-5class] FRESH start from cfg yaml")
        model = YOLO(str(args.cfg), task="detect")
        resume = False

    t0 = time.time()
    results = model.train(
        data        = str(args.data),
        epochs      = args.epochs,
        batch       = args.batch,
        imgsz       = args.imgsz,
        device      = args.device,
        optimizer   = args.optimizer,
        lr0         = args.lr0,
        lrf         = args.lrf,
        mosaic      = args.mosaic,
        mixup       = args.mixup,
        copy_paste  = args.copy_paste,
        workers     = args.workers,
        project     = str(args.project),
        name        = args.name,
        exist_ok    = True,
        amp         = (not args.no_amp),
        patience    = args.patience,
        resume      = resume,
        save        = True,
        save_period = 1,         # save every epoch
        verbose     = True,
        plots       = False,     # plot module needs matplotlib; skip to keep it lean
        cache       = False,
    )
    dt = time.time() - t0
    print(f"\n[pretrain-5class] done in {dt/3600:.2f} h")

    best_pt = args.project / args.name / "weights" / "best.pt"
    if best_pt.exists():
        print(f"[pretrain-5class] best ckpt -> {best_pt}")
        # Mirror to the canonical name used downstream by distill init
        import shutil
        target = Path("models/tiny_fpga_5class_supervised_ep30.pt")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(best_pt, target)
        print(f"[pretrain-5class] mirrored to {target} (use as distill --student-init)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
