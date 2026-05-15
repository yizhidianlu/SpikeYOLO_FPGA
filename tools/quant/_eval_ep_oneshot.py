"""One-shot helper: rewrap a distill epoch ckpt into ultralytics format,
then run yolo.val to print mAP. Throwaway tool — not committed.

Usage:
    PYTHONPATH=<repo_root> python tools/quant/_eval_ep_oneshot.py \
        --ep models/eval/ep21_safe.pt \
        --base models/tiny_fpga_fp32.pt \
        --data ultralytics/cfg/datasets/coco_train2017_local.yaml \
        --device 0 --batch 4 --imgsz 256
"""
from __future__ import annotations
import argparse, time, sys, json
from pathlib import Path

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ep",    type=Path, required=True, help="distill epoch ckpt (state_dict-only)")
    ap.add_argument("--cfg",   type=Path,
                    default=Path("ultralytics/cfg/models/v8/snn_yolov8_tiny_fpga.yaml"),
                    help="student arch yaml (must match the one distill_from_teacher used)")
    ap.add_argument("--data",  type=Path, default=Path("ultralytics/cfg/datasets/coco_train2017_local.yaml"))
    ap.add_argument("--imgsz", type=int, default=256)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--device", default="0")
    ap.add_argument("--out-rewrap", type=Path, default=Path("models/eval/_rewrapped.pt"))
    ap.add_argument("--out-json",   type=Path, default=Path("runs/eval_ep_oneshot.json"))
    ap.add_argument("--use-ema", action="store_true",
                    help="A2-W11: prefer ema_state_dict over state_dict when present "
                         "in ep ckpt (usually +2-5% mAP for late-distill ckpts).")
    args = ap.parse_args()

    import torch
    from ultralytics import YOLO

    print(f"[oneshot] cfg = {args.cfg}")
    print(f"[oneshot] ep  = {args.ep}")

    # Build empty student from the same yaml distill_from_teacher used.
    # This guarantees channel widths match the saved state_dict.
    yolo_empty = YOLO(str(args.cfg), task="detect")
    model = yolo_empty.model

    ep_ck = torch.load(args.ep, map_location="cpu", weights_only=False)
    if "state_dict" not in ep_ck:
        print("[oneshot] ep ckpt missing 'state_dict' key — abort", file=sys.stderr)
        return 2

    use_ema_actual = False
    if args.use_ema:
        ema_sd = ep_ck.get("ema_state_dict")
        if ema_sd is None:
            print("[oneshot] WARN: --use-ema set but ckpt has no ema_state_dict; "
                  "falling back to state_dict (raw)")
        else:
            print("[oneshot] using EMA weights")
            sd = {k: v.float() for k, v in ema_sd.items()}
            use_ema_actual = True
    if not use_ema_actual:
        sd = {k: v.float() for k, v in ep_ck["state_dict"].items()}

    miss, unx = model.load_state_dict(sd, strict=False)
    print(f"[oneshot] load_state_dict: missing={len(miss)}  unexpected={len(unx)}  "
          f"(source={'ema' if use_ema_actual else 'raw'})")
    if miss:  print(f"[oneshot]   first 5 missing:    {miss[:5]}")
    if unx:   print(f"[oneshot]   first 5 unexpected: {unx[:5]}")

    # Build a minimal ultralytics-format ckpt around the loaded model.
    new_ck = {
        "epoch":      ep_ck.get("epoch", -1),
        "best_fitness": None,
        "model":      model,
        "ema":        None,
        "updates":    0,
        "optimizer":  None,
        "train_args": ep_ck.get("train_args", {}),
        "train_metrics": {},
        "train_results": {},
        "date":       "rewrapped-by-_eval_ep_oneshot",
        "version":    "x",
    }
    args.out_rewrap.parent.mkdir(parents=True, exist_ok=True)
    torch.save(new_ck, args.out_rewrap)
    print(f"[oneshot] rewrapped -> {args.out_rewrap}  ({args.out_rewrap.stat().st_size/1e6:.1f} MB)")

    print(f"[oneshot] ===== running yolo.val =====")
    t0 = time.time()
    yolo = YOLO(str(args.out_rewrap), task="detect")
    res = yolo.val(
        data   = str(args.data),
        imgsz  = args.imgsz,
        batch  = args.batch,
        device = args.device,
        verbose = True,
        save_json = False,
        plots = False,
    )
    box = res.box
    out = {
        "ckpt":          str(args.ep),
        "epoch":         int(ep_ck.get("epoch", -1)),
        "mAP50":         float(box.map50),
        "mAP50_95":      float(box.map),
        "precision":     float(box.mp),
        "recall":        float(box.mr),
        "n_classes":     int(len(box.maps)),
        "elapsed_s":     time.time() - t0,
        "imgsz":         args.imgsz,
        "batch":         args.batch,
        "device":        args.device,
    }
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(out, indent=2))
    print(f"\n[oneshot] ===== RESULT =====")
    print(f"[oneshot] epoch       = {out['epoch']}")
    print(f"[oneshot] mAP50       = {out['mAP50']:.4f}")
    print(f"[oneshot] mAP50-95    = {out['mAP50_95']:.4f}")
    print(f"[oneshot] precision   = {out['precision']:.4f}")
    print(f"[oneshot] recall      = {out['recall']:.4f}")
    print(f"[oneshot] elapsed     = {out['elapsed_s']:.1f} s")
    print(f"[oneshot] saved JSON  = {args.out_json}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
