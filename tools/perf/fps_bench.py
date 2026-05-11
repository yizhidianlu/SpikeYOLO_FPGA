#!/usr/bin/env python3
"""FPS / latency benchmark for SpikeYOLO tiny_fpga.

Three modes (only --help works in this skeleton):

  * gpu        — torch model on cuda, run N inference passes on a constant
                 input tensor. Useful for tracking pre-quant baseline drift
                 between months.
  * host_csim  — invoke the binaries under hw/hls/build/host_csim_layer_xx
                 N times and time each. Stub: M3+ wireup once tiny_fpga_top
                 host_csim binary exists.
  * board      — SSH ZYBO, run /opt/spike_accel_demo --bench --json, parse
                 stdout JSON-per-line. Stub: M3+ wireup once C3 ships demo.

Output schema (runs/perf/fps_bench.json):

  {
    "mode": "gpu",
    "frames": 600,
    "input_size": 256,
    "ms_avg": 12.3, "ms_p50": 11.8, "ms_p99": 18.1,
    "fps_avg": 81.0, "fps_p1": 55.0,
    "jitter_pct": 4.2,
    "dropped_frames": 0,
    "git_sha": "abc1234",
    "timestamp": "2026-05-11T12:00:00Z"
  }

The skeleton intentionally lazy-imports torch / paramiko so that --help
works on a bare interpreter (matches D2 numpy_regress CI assumption).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Allow `from ultralytics import YOLO` to resolve to the in-repo package
# (matches tools/quant/eval_baseline_triple.py bootstrap).
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _git_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
        )
        return out.decode().strip()
    except Exception:
        return "unknown"


def _summarize(samples_ms):
    """Compute summary stats from a list of per-frame latencies in ms.

    Lazy-imports numpy. Returns dict with keys matching the output schema.
    """
    import numpy as np  # lazy

    arr = np.asarray(samples_ms, dtype=float)
    ms_avg = float(arr.mean())
    ms_p50 = float(np.percentile(arr, 50))
    ms_p99 = float(np.percentile(arr, 99))
    fps_arr = 1000.0 / arr
    fps_avg = float(fps_arr.mean())
    fps_p1 = float(np.percentile(fps_arr, 1))
    jitter_pct = float(arr.std() / arr.mean() * 100.0) if ms_avg > 0 else 0.0
    return {
        "ms_avg": round(ms_avg, 3),
        "ms_p50": round(ms_p50, 3),
        "ms_p99": round(ms_p99, 3),
        "fps_avg": round(fps_avg, 2),
        "fps_p1": round(fps_p1, 2),
        "jitter_pct": round(jitter_pct, 3),
    }


def run_gpu(args) -> list:
    """Run the torch tiny_fpga model on cuda; return per-frame latency in ms.

    Loads `args.weights` (ultralytics .pt), runs `args.frames` forward passes
    on a constant random INT8-uint8-style RGB tensor at `args.input_size`, and
    times each via `torch.cuda.Event` (preferred) or `time.perf_counter`
    (CPU fallback). Includes 20 warm-up frames not counted in the samples.
    """
    import torch  # lazy

    weights_path = Path(args.weights)
    if not weights_path.exists():
        raise FileNotFoundError(f"weights not found: {weights_path}")

    has_cuda = torch.cuda.is_available()
    if not has_cuda:
        print(
            "[fps_bench] WARN: CUDA unavailable; falling back to CPU timing.",
            file=sys.stderr,
        )
    device = torch.device("cuda" if has_cuda else "cpu")

    # Load via ultralytics so we get the wrapped DetectionModel ready to call.
    from ultralytics import YOLO  # lazy
    yolo = YOLO(str(weights_path), task="detect")
    model = yolo.model.to(device)
    model.eval()

    # tiny_fpga input contract: RGB 256x256, uint8 -> float in [0,1].
    rng = torch.Generator(device="cpu").manual_seed(0)
    img_u8 = torch.randint(
        0, 256, (1, 3, args.input_size, args.input_size),
        dtype=torch.uint8, generator=rng,
    )
    x = (img_u8.to(device).float() / 255.0)

    samples_ms = []
    warmup = 20
    total = warmup + int(args.frames)
    with torch.inference_mode():
        if has_cuda:
            start_evt = torch.cuda.Event(enable_timing=True)
            end_evt = torch.cuda.Event(enable_timing=True)
            for i in range(total):
                start_evt.record()
                _ = model(x)
                end_evt.record()
                torch.cuda.synchronize()
                ms = start_evt.elapsed_time(end_evt)
                if i >= warmup:
                    samples_ms.append(float(ms))
        else:
            for i in range(total):
                t0 = time.perf_counter()
                _ = model(x)
                t1 = time.perf_counter()
                if i >= warmup:
                    samples_ms.append((t1 - t0) * 1000.0)

    return samples_ms


def run_host_csim(args) -> list:
    """Run hw/hls/build/host_csim_layer_xx N times; return per-frame latency.

    TODO M3: invoke `tools/ci/run_host_csim.py` for the tiny_fpga_top binary
    once B1 publishes it. For now, no top-level binary exists, only per-layer.
    """
    raise NotImplementedError(
        "host_csim mode wireup deferred to M3. Needs B1 tiny_fpga_top "
        "host_csim binary; currently only per-layer binaries exist."
    )


def run_board(args) -> list:
    """SSH to ZYBO, parse spike_accel_demo --bench --json output.

    TODO M4: paramiko / subprocess ssh; existing reference impl in
    docs/AGENT_PLAYBOOKS/D1_verification.md. Needs C3 demo binary on board.
    """
    raise NotImplementedError(
        "board mode wireup deferred to M4. Needs Petalinux image (C1) "
        "and spike_accel_demo binary (C3) on board first."
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="fps_bench",
        description=(
            "Run inference N frames; report avg/p50/p99 latency + FPS + jitter. "
            "Three modes: gpu (PC torch baseline), host_csim (HLS C-sim), board "
            "(ZYBO over SSH). All modes write the same JSON schema; only --help "
            "works in this skeleton."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=["gpu", "host_csim", "board"],
        default="gpu",
        help="Where to run inference. Default: gpu (PC baseline).",
    )
    parser.add_argument(
        "--frames",
        type=int,
        default=600,
        help="Number of inference passes (default 600 = 20 s @ 30 FPS).",
    )
    parser.add_argument(
        "--input-size",
        type=int,
        default=256,
        help="Square input edge in pixels. Tiny_fpga is 256.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("runs/perf/fps_bench.json"),
        help="Output JSON path. Parent dir auto-created.",
    )
    parser.add_argument(
        "--min-fps",
        type=float,
        default=None,
        help=(
            "If set, exit non-zero when fps_avg < min-fps. Used by D2 nightly "
            "gate. Recommended values: 30 (M6 KPI), 10 (M4 KPI)."
        ),
    )
    parser.add_argument(
        "--weights",
        type=Path,
        default=Path("models/tiny_fpga_fp32.pt"),
        help="Student .pt for gpu mode. Will switch to _distilled.pt post-R8.",
    )
    parser.add_argument(
        "--board-host",
        default="root@zybo",
        help="SSH target for board mode. Default: root@zybo.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip the actual run; only validate args + emit a stub JSON.",
    )
    args = parser.parse_args(argv)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    git_sha = _git_sha()

    print(f"[fps_bench] mode={args.mode} frames={args.frames} "
          f"input_size={args.input_size}", file=sys.stderr)

    if args.dry_run:
        result = {
            "mode": args.mode,
            "frames": args.frames,
            "input_size": args.input_size,
            "ms_avg": 0.0, "ms_p50": 0.0, "ms_p99": 0.0,
            "fps_avg": 0.0, "fps_p1": 0.0,
            "jitter_pct": 0.0,
            "dropped_frames": 0,
            "git_sha": git_sha,
            "timestamp": timestamp,
            "_dry_run": True,
        }
        args.out.write_text(json.dumps(result, indent=2))
        print(f"[fps_bench] dry-run wrote {args.out}", file=sys.stderr)
        return 0

    runner = {"gpu": run_gpu, "host_csim": run_host_csim, "board": run_board}[args.mode]
    samples_ms = runner(args)

    summary = _summarize(samples_ms)
    summary.update({
        "mode": args.mode,
        "frames": args.frames,
        "input_size": args.input_size,
        "dropped_frames": 0,
        "git_sha": git_sha,
        "timestamp": timestamp,
    })
    args.out.write_text(json.dumps(summary, indent=2))
    print(f"[fps_bench] wrote {args.out}", file=sys.stderr)
    print(json.dumps(summary, indent=2))

    if args.min_fps is not None and summary["fps_avg"] < args.min_fps:
        print(
            f"[fps_bench] FAIL fps_avg={summary['fps_avg']} < "
            f"min_fps={args.min_fps}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
