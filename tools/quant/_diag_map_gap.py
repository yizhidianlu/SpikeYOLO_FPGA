"""One-shot diagnostic for the distill mAP gap.
Runs 4 comparisons against COCO val2017 to localize the root cause.
"""
from __future__ import annotations
import argparse, json, time, sys
from pathlib import Path

CASES = [
    # (label, kind, path, imgsz, note)
    ("A_teacher_256",      "pt",  "models/SpikeYOLO_23.1M_T1D4.pt", 256,
     "teacher @ 256 — what the student CAN learn at training resolution"),
    ("B_teacher_640",      "pt",  "models/SpikeYOLO_23.1M_T1D4.pt", 640,
     "teacher @ 640 — teacher's intrinsic ceiling"),
    ("C_tinyfpga_random",  "cfg", "ultralytics/cfg/models/v8/snn_yolov8_tiny_fpga.yaml", 256,
     "tiny_fpga random init — evaluator sanity"),
    ("D_tinyfpga_baseFP",  "pt",  "models/tiny_fpga_fp32.pt", 256,
     "tiny_fpga base FP32 (pre-distill init) — what distill started from"),
]

def run_one(label: str, kind: str, path: str, imgsz: int, note: str,
            data: str, batch: int, device: str) -> dict:
    from ultralytics import YOLO
    print(f"\n========= {label} =========")
    print(f"  {note}")
    print(f"  source = {path}  imgsz = {imgsz}")
    if not Path(path).exists():
        return {"label": label, "error": f"missing: {path}", "note": note}
    t0 = time.time()
    yolo = YOLO(path, task="detect")
    r = yolo.val(data=data, imgsz=imgsz, batch=batch, device=device,
                 verbose=False, save_json=False, plots=False)
    box = r.box
    out = {
        "label":       label,
        "source":      path,
        "imgsz":       imgsz,
        "mAP50":       float(box.map50),
        "mAP50_95":    float(box.map),
        "precision":   float(box.mp),
        "recall":      float(box.mr),
        "elapsed_s":   time.time() - t0,
        "note":        note,
    }
    print(f"  >> mAP50={out['mAP50']:.4f}  mAP50-95={out['mAP50_95']:.4f}  "
          f"P={out['precision']:.4f}  R={out['recall']:.4f}  ({out['elapsed_s']:.1f}s)")
    return out

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="ultralytics/cfg/datasets/coco_train2017_local.yaml")
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--device", default="0")
    ap.add_argument("--out", type=Path, default=Path("runs/diag_map_gap.json"))
    ap.add_argument("--only", default="", help="comma-list of labels to run, e.g. A_teacher_256,C_tinyfpga_random")
    args = ap.parse_args()

    keep = set(s.strip() for s in args.only.split(",")) if args.only else None
    results = []
    for label, kind, path, imgsz, note in CASES:
        if keep and label not in keep: continue
        try:
            results.append(run_one(label, kind, path, imgsz, note,
                                   args.data, args.batch, args.device))
        except Exception as e:
            print(f"  >> ERROR: {type(e).__name__}: {e}")
            results.append({"label": label, "error": str(e), "note": note})

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2))

    print("\n========= DIAGNOSTIC SUMMARY =========")
    print(f"{'label':<22} {'imgsz':>5} {'mAP50':>8} {'mAP50-95':>9} {'P':>7} {'R':>7}")
    for r in results:
        if "error" in r:
            print(f"{r['label']:<22}  ERR: {r['error'][:50]}")
        else:
            print(f"{r['label']:<22} {r['imgsz']:>5} {r['mAP50']:>8.4f} "
                  f"{r['mAP50_95']:>9.4f} {r['precision']:>7.4f} {r['recall']:>7.4f}")
    print(f"\nJSON saved -> {args.out}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
