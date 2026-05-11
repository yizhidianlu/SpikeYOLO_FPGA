"""A1 Phase 1 baseline gate: produce ``runs/baseline_summary.json``.

Three FP32 mAP numbers (COCO val2017 mAP50-95):
  * ``mAP_teacher_fp32``       — `models/SpikeYOLO_23.1M_T1D4.pt` @ imgsz=640
  * ``mAP_student_init_fp32``  — `models/tiny_fpga_fp32.pt`        @ imgsz=256
  * ``mAP_student_distilled``  — left ``null`` until distill run completes

Run with ``--help`` to see all flags. With no flags it expects the COCO
local config + the two .pt files referenced above. ``--skip-teacher`` /
``--skip-student-init`` let you fill in either side later. torch /
ultralytics imported lazily so ``--help`` works on bare Python.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="eval_baseline_triple",
        description="Produce runs/baseline_summary.json (Phase 1 deliverable).")
    p.add_argument("--teacher", type=Path,
                   default=Path("models/SpikeYOLO_23.1M_T1D4.pt"))
    p.add_argument("--student-init", type=Path,
                   default=Path("models/tiny_fpga_fp32.pt"))
    p.add_argument("--student-distilled", type=Path,
                   default=Path("models/tiny_fpga_fp32_distilled.pt"))
    p.add_argument("--data", type=Path,
                   default=Path("ultralytics/cfg/datasets/coco_local.yaml"))
    p.add_argument("--teacher-imgsz", type=int, default=640)
    p.add_argument("--student-imgsz", type=int, default=256)
    p.add_argument("--device", type=str, default="cuda")
    p.add_argument("--batch", type=int, default=8)
    p.add_argument("--out", type=Path, default=Path("runs/baseline_summary.json"))
    p.add_argument("--skip-teacher", action="store_true")
    p.add_argument("--skip-student-init", action="store_true")
    p.add_argument("--skip-student-distilled", action="store_true",
                   help="default true if .pt missing; explicit only on retries")
    return p


def _eval_one(label: str, pt: Path, data: Path, imgsz: int, device: str, batch: int):
    print(f"[baseline] {label}: evaluating {pt} (imgsz={imgsz})")
    if not pt.exists():
        print(f"[baseline] {label}: file missing -> null")
        return None
    try:
        from ultralytics import YOLO
        yolo = YOLO(str(pt), task="detect")
        results = yolo.val(data=str(data), imgsz=imgsz, batch=batch,
                           device=device, verbose=False,
                           save_json=False, plots=False)
        m = float(results.box.map)
        m_pct = m * 100.0 if m <= 1.0 else m
        print(f"[baseline] {label}: mAP50-95 = {m_pct:.2f}%")
        return m_pct
    except Exception as e:
        print(f"[baseline] {label}: eval FAILED ({type(e).__name__}: {e})")
        return None


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    teacher_map = None if args.skip_teacher else _eval_one(
        "teacher_fp32", args.teacher, args.data,
        args.teacher_imgsz, args.device, args.batch)

    student_init_map = None if args.skip_student_init else _eval_one(
        "student_init_fp32", args.student_init, args.data,
        args.student_imgsz, args.device, args.batch)

    student_distilled_map = None
    if not args.skip_student_distilled and args.student_distilled.exists():
        student_distilled_map = _eval_one(
            "student_distilled", args.student_distilled, args.data,
            args.student_imgsz, args.device, args.batch)

    summary = {
        "teacher": teacher_map,
        "student_init": student_init_map,
        "student_distilled": student_distilled_map,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": str(args.data),
        "teacher_imgsz": args.teacher_imgsz,
        "student_imgsz": args.student_imgsz,
        "schema_version": "1.0",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2))
    print(f"[baseline] wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
