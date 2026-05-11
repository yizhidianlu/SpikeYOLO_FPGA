#!/usr/bin/env python3
"""Latency breakdown per-stage (M3+ board-side measurement).

Per `docs/ARCHITECTURE.md` §2.3, a 30 FPS frame has a 33 ms budget split
across 5 stages: capture (V4L2 grab), preproc (letterbox + INT8 cast),
infer (PL spike_accel 11-layer SNN), postproc (NMS + coordinate restore),
display (framebuffer draw + VDMA push).

Four modes:

  * simulate   — emit the theoretical numbers from ARCHITECTURE §2.3.
                 No torch / no board. Runs in any CI minimal env.
  * gpu        — load tiny_fpga .pt on cuda, time per-stage with cuda
                 events. Stub: M2+ once we split preproc/postproc out of
                 the YOLO forward (currently the model only has `infer`).
  * host_csim  — invoke `hw/hls/build/host_csim_top` once per frame and
                 parse the stdout `PerStageLat` summary lines C3 W5
                 wired into `sw/app`. Stub: M3.
  * board      — SSH ZYBO, run `/opt/spike_accel_demo --bench --latency`
                 and grep the `summary: stage_*` line C3 prints. Stub: M3.

Output schema (`runs/perf/latency_breakdown.json`):

  {
    "mode": "simulate",
    "frames": 600,
    "stages": {
      "capture":  {"ms_avg": 3.0, "ms_p99": 4.5, "fps_eq": 333},
      "preproc":  {"ms_avg": 4.0, "ms_p99": 6.0, "fps_eq": 250},
      "infer":    {"ms_avg": 18.0, "ms_p99": 22.0, "fps_eq": 55},
      "postproc": {"ms_avg": 2.0, "ms_p99": 3.0, "fps_eq": 500},
      "display":  {"ms_avg": 2.0, "ms_p99": 3.0, "fps_eq": 500}
    },
    "total_ms_avg": 29.0,
    "fps_avg": 34.5,
    "headroom_pct": 12.0,
    "bottleneck": "infer",
    "git_sha": "abc1234",
    "timestamp": "2026-05-12T00:00:00Z"
  }

Owner: D1 System Verification. Reads alongside `tools/perf/fps_bench.py`
(end-to-end fps) so D1 can attribute regressions to a specific stage.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# Theoretical budget from docs/ARCHITECTURE.md §2.3 (M1-baseline / pre-ping-pong).
# Per-stage avg + a +50% p99 worst-case heuristic until we have real board data.
_ARCH_STAGES = {
    "capture":  {"ms_avg": 3.0, "ms_p99": 4.5},
    "preproc":  {"ms_avg": 4.0, "ms_p99": 6.0},
    "infer":    {"ms_avg": 18.0, "ms_p99": 22.0},
    "postproc": {"ms_avg": 2.0, "ms_p99": 3.0},
    "display":  {"ms_avg": 2.0, "ms_p99": 3.0},
}
_FRAME_BUDGET_MS = 33.0  # 30 FPS contract


def _git_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
        )
        return out.decode().strip()
    except Exception:
        return "unknown"


def _finalize(stages: dict) -> dict:
    """Compute total / fps / headroom / bottleneck from per-stage ms."""
    for name, s in stages.items():
        s["fps_eq"] = round(1000.0 / s["ms_avg"]) if s["ms_avg"] > 0 else 0
    total = sum(s["ms_avg"] for s in stages.values())
    headroom = max(0.0, (_FRAME_BUDGET_MS - total) / _FRAME_BUDGET_MS * 100.0)
    bottleneck = max(stages.items(), key=lambda kv: kv[1]["ms_avg"])[0]
    return {
        "stages": stages,
        "total_ms_avg": round(total, 2),
        "fps_avg": round(1000.0 / total, 2) if total > 0 else 0.0,
        "headroom_pct": round(headroom, 2),
        "bottleneck": bottleneck,
    }


def run_simulate(args) -> dict:
    """Emit ARCHITECTURE.md §2.3 numbers verbatim (no measurement)."""
    stages = {k: {"ms_avg": v["ms_avg"], "ms_p99": v["ms_p99"]}
              for k, v in _ARCH_STAGES.items()}
    return _finalize(stages)


def run_gpu(args) -> dict:
    raise NotImplementedError(
        "gpu mode wireup deferred to M2+. Needs the model split into "
        "preproc / forward / postproc segments. Today only fps_bench.py "
        "gpu mode (single-stage forward) is real."
    )


def run_host_csim(args) -> dict:
    raise NotImplementedError(
        "host_csim mode deferred to M3. Needs C3 sw/app PerStageLat parser "
        "wired to the host_csim_top binary; currently C3 PerStageLat is "
        "board-mode-only."
    )


def run_board(args) -> dict:
    raise NotImplementedError(
        "board mode deferred to M3. Needs spike_accel_demo on ZYBO + ssh "
        "reachability + the C3 W5 `summary: stage_*` print-line parser."
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="latency_breakdown",
        description="Per-stage latency breakdown (capture / preproc / "
                    "infer / postproc / display) per ARCHITECTURE §2.3.",
    )
    parser.add_argument(
        "--mode",
        choices=["gpu", "host_csim", "board", "simulate"],
        default="simulate",
        help="Where to measure. Default: simulate (theoretical, no HW).",
    )
    parser.add_argument(
        "--frames", type=int, default=600,
        help="Frames to time (default 600 = 20 s @ 30 FPS).",
    )
    parser.add_argument(
        "--out", type=Path,
        default=Path("runs/perf/latency_breakdown.json"),
        help="Output JSON path. Parent dir auto-created.",
    )
    parser.add_argument(
        "--board-host", default="root@zybo",
        help="SSH target for --mode board. Default: root@zybo.",
    )
    args = parser.parse_args(argv)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    git_sha = _git_sha()

    print(f"[latency_breakdown] mode={args.mode} frames={args.frames}",
          file=sys.stderr)

    runner = {
        "simulate": run_simulate,
        "gpu": run_gpu,
        "host_csim": run_host_csim,
        "board": run_board,
    }[args.mode]
    summary = runner(args)
    summary.update({
        "mode": args.mode,
        "frames": args.frames,
        "git_sha": git_sha,
        "timestamp": timestamp,
    })

    args.out.write_text(json.dumps(summary, indent=2))
    print(f"[latency_breakdown] wrote {args.out}", file=sys.stderr)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
