"""Bootstrap a tiny_fpga checkpoint so the PTQ pipeline can run end-to-end
without first training a full mAP-accurate model.

This is a stand-in for the real training stage (which would need the COCO
train2017 set ~18 GB). We initialize the model with PyTorch's default
Kaiming weights, then optionally copy compatible-shape conv weights from a
larger SpikeYOLO checkpoint (knowledge bootstrap, not real distillation).

Output:
    models/tiny_fpga_fp32.pt   — ultralytics-compatible checkpoint
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import torch
from ultralytics import YOLO


def _maybe_transfer(target_sd: dict, donor_path: Path) -> int:
    """Copy weights from donor whose key + shape match. Returns # copied."""
    if not donor_path.exists():
        return 0
    print(f"[init] attempting weight transfer from {donor_path}")
    ckpt = torch.load(donor_path, map_location="cpu", weights_only=False)
    donor = ckpt.get("model", ckpt)
    donor_sd = donor.state_dict() if hasattr(donor, "state_dict") else donor
    matched = 0
    for k, v in donor_sd.items():
        if k in target_sd and target_sd[k].shape == v.shape:
            target_sd[k] = v.clone()
            matched += 1
    return matched


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--yaml", default="ultralytics/cfg/models/v8/snn_yolov8_tiny_fpga.yaml")
    p.add_argument("--donor", type=Path, default=Path("models/SpikeYOLO_23.1M_T1D4.pt"),
                   help="larger SpikeYOLO checkpoint to harvest compatible weights from")
    p.add_argument("--output", type=Path, default=Path("models/tiny_fpga_fp32.pt"))
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    torch.manual_seed(args.seed)

    print(f"[init] building model from {args.yaml}")
    yolo = YOLO(args.yaml, task="detect")
    model = yolo.model
    n_params = sum(p.numel() for p in model.parameters())
    print(f"[init] params: {n_params/1e6:.3f}M")

    # Try opportunistic weight transfer (rare matches due to channel widths).
    sd = model.state_dict()
    matched = _maybe_transfer(sd, args.donor)
    if matched:
        model.load_state_dict(sd, strict=False)
        print(f"[init] copied {matched} tensors from donor")
    else:
        print("[init] no compatible donor tensors — keeping Kaiming init")

    # Save in ultralytics' expected format.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # ultralytics' val loop expects train_args to be a dict, even if empty.
    ckpt = {
        "model":   model.half(),
        "ema":     None,
        "updates": 0,
        "epoch":   0,
        "best_fitness": None,
        "train_args": {
            "task":  "detect",
            "data":  "ultralytics/cfg/datasets/coco_local.yaml",
            "imgsz": 256,
            "model": str(args.yaml),
        },
        "date":          None,
        "version":       "spikeyolo-tiny-fpga-init-1.0",
    }
    torch.save(ckpt, args.output)
    print(f"[init] saved -> {args.output} ({args.output.stat().st_size/1e6:.2f} MB)")

    # Restore to float for sanity-check forward.
    model.float().cuda().eval()
    with torch.no_grad():
        x = torch.randn(1, 3, 256, 256, device="cuda")
        out = model(x)
    print(f"[init] forward sanity ok: out type={type(out).__name__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
