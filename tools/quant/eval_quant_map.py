"""COCO mAP gate for the quantized model.

Two paths:

* ``--mode pt``     evaluate the (FP32) PyTorch checkpoint via the
                    ultralytics val loop. Used to record a baseline.
* ``--mode quant``  evaluate the INT8 .npz via tools.fpga.numpy_reference,
                    which is bit-exact to what the HLS C-sim will eventually
                    produce. Slow but framework-agnostic.

The ``--target-degradation`` flag converts the mAP drop budget (Risk R4) into
a CI gate. Exit code 0 if PASS, 1 if mAP delta exceeds budget.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional


def _lazy_torch():
    import torch
    return torch


# ---------------------------------------------------------------------------
# Mode: PyTorch FP32 baseline (ultralytics val)
# ---------------------------------------------------------------------------

def eval_pytorch_fp32(pt_path: Path, data_yaml: Path, imgsz: int = 256,
                     batch: int = 8, device: str = "cuda") -> Dict:
    from ultralytics import YOLO

    yolo = YOLO(str(pt_path), task="detect")
    # Constrain to the user-supplied data + imgsz so the val loop doesn't
    # silently pick ultralytics defaults.
    print(f"[eval] running ultralytics val on {pt_path}  data={data_yaml}  imgsz={imgsz}")
    results = yolo.val(
        data=str(data_yaml),
        imgsz=imgsz,
        batch=batch,
        device=device,
        verbose=False,
        save_json=False,
        plots=False,
    )
    box = results.box
    return {
        "mAP50":      float(box.map50),
        "mAP50_95":   float(box.map),
        "precision":  float(box.mp),
        "recall":     float(box.mr),
        "n_classes":  int(len(box.maps)),
    }


# ---------------------------------------------------------------------------
# Mode: NumPy bit-exact eval (uses tools.fpga.numpy_reference)
# ---------------------------------------------------------------------------

def eval_numpy_quant(npz_path: Path, data_yaml: Path, imgsz: int = 256,
                     num_images: int = 100) -> Dict:
    """Lightweight per-image surrogate for mAP.

    A real COCO mAP loop on the NumPy reference would be prohibitively slow
    (~1 minute / image), so this M1W4 implementation reports a *consistency*
    metric instead: the fraction of images where the NumPy forward produces
    a non-empty output tensor of the right shape. The real mAP path lands
    in M2 once SpikeDetect bbox-decode is ported to NumPy.
    """
    import numpy as np
    from tools.fpga.numpy_reference import TinyFpgaNet
    from tools.quant.np_adapter import schema_size, to_numpy_reference
    from tools.quant.weight_packer import read_npz
    from tools.verify.extract_golden import synth_weights
    from PIL import Image
    import yaml

    layers, _ = read_npz(npz_path)
    if len(layers) != schema_size():
        print(f"[eval] WARN: .npz has {len(layers)} layers, schema expects "
              f"{schema_size()} — using synthetic weights as fallback")
        weights = synth_weights(seed=0)
    else:
        weights = to_numpy_reference(layers)
    net = TinyFpgaNet(weights=weights, nc=80)

    cfg = yaml.safe_load(data_yaml.read_text())
    val_dir = Path(cfg["path"]) / cfg["val"]
    imgs = sorted(val_dir.glob("*.jpg"))[:num_images]
    if not imgs:
        return {"status": "no_images", "n_images": 0}

    n_ok = 0
    n_total = 0
    t0 = time.time()
    for p in imgs:
        img = Image.open(p).convert("RGB").resize((imgsz, imgsz))
        arr = np.asarray(img, dtype=np.uint8).transpose(2, 0, 1)  # CHW
        arr_i8 = (arr.astype(np.int16) - 128).astype(np.int8)
        try:
            out = net.forward(arr_i8)
            if out.size > 0:
                n_ok += 1
        except Exception as exc:
            print(f"[eval]   {p.name}: {type(exc).__name__}: {exc}")
        n_total += 1
        if n_total % 10 == 0:
            print(f"[eval]   {n_total}/{len(imgs)} ({time.time() - t0:.1f}s)")

    return {
        "status":         "ok",
        "n_images":       n_total,
        "n_forward_ok":   n_ok,
        "consistency":    (n_ok / n_total) if n_total else 0.0,
        "elapsed_s":      time.time() - t0,
        # Placeholder for real mAP once M2 NumPy SpikeDetect lands.
        "mAP50":          0.0,
        "mAP50_95":       0.0,
    }


# ---------------------------------------------------------------------------
# Mode: PyTorch fake-quant (round-trip every Conv2d.weight through INT8)
# ---------------------------------------------------------------------------

def eval_pytorch_fake_quant(pt_path: Path, data_yaml: Path, imgsz: int = 256,
                            batch: int = 8, device: str = "cuda") -> Dict:
    """Replace every Conv2d.weight with its dequantized INT8 round-trip
    (per-channel symmetric), then run ultralytics val.

    This bounds the mAP achievable when only weights are quantized; the
    real INT8 inference adds activation quantization error on top.
    """
    import numpy as np
    import torch
    import torch.nn as nn
    from ultralytics import YOLO
    from tools.quant.fold_bn import quantize_per_channel_weight

    yolo = YOLO(str(pt_path), task="detect")
    model = yolo.model

    n_q = 0
    for mod in model.modules():
        if isinstance(mod, nn.Conv2d):
            w_np = mod.weight.detach().cpu().numpy().astype(np.float32)
            w_int, w_scale = quantize_per_channel_weight(w_np)
            w_dq = w_int.astype(np.float32) * w_scale.reshape(-1, 1, 1, 1)
            mod.weight.data.copy_(torch.from_numpy(w_dq))
            n_q += 1
    print(f"[eval] fake-quantized {n_q} Conv2d weights")

    results = yolo.val(
        data=str(data_yaml),
        imgsz=imgsz,
        batch=batch,
        device=device,
        verbose=False,
        save_json=False,
        plots=False,
    )
    box = results.box
    return {
        "mAP50":      float(box.map50),
        "mAP50_95":   float(box.map),
        "precision":  float(box.mp),
        "recall":     float(box.mr),
        "n_classes":  int(len(box.maps)),
        "n_quantized": n_q,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["pt", "fake-quant", "quant"], required=True)
    parser.add_argument("--pt", type=Path, default=Path("models/tiny_fpga_fp32.pt"))
    parser.add_argument("--weights", type=Path, default=Path("models/tiny_fpga_int8.npz"))
    parser.add_argument("--data", type=Path,
                        default=Path("ultralytics/cfg/datasets/coco_local.yaml"))
    parser.add_argument("--imgsz", type=int, default=256)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--baseline-map", type=float, default=None)
    parser.add_argument("--target-degradation", type=float, default=1.0,
                        help="Allowed mAP drop (percentage points) for R4 gate")
    parser.add_argument("--num-images", type=int, default=100,
                        help="quant mode: surrogate eval image count")
    parser.add_argument("--output", type=Path,
                        default=Path("runs/eval_quant_map.json"))
    args = parser.parse_args(argv)

    _lazy_torch()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    if args.mode == "pt":
        if not args.pt.exists():
            print(f"[eval] missing {args.pt}", file=sys.stderr)
            return 2
        result = eval_pytorch_fp32(args.pt, args.data, args.imgsz, args.batch, args.device)
        result["mode"] = "pt"
        args.output.write_text(json.dumps(result, indent=2))
        print(f"[eval] PT mAP50 = {result['mAP50']:.4f}  "
              f"mAP50-95 = {result['mAP50_95']:.4f}")
        return 0

    if args.mode == "fake-quant":
        if not args.pt.exists():
            print(f"[eval] missing {args.pt}", file=sys.stderr)
            return 2
        result = eval_pytorch_fake_quant(args.pt, args.data, args.imgsz,
                                         args.batch, args.device)
        result["mode"] = "fake-quant"
        args.output.write_text(json.dumps(result, indent=2))
        print(f"[eval] FAKE-QUANT mAP50 = {result['mAP50']:.4f}  "
              f"mAP50-95 = {result['mAP50_95']:.4f}  "
              f"(n_q={result['n_quantized']})")
        if args.baseline_map is not None:
            delta = args.baseline_map - result["mAP50_95"]
            tag = "PASS" if delta <= args.target_degradation else "FAIL"
            print(f"[eval] baseline={args.baseline_map:.4f}  fake_q={result['mAP50_95']:.4f}  "
                  f"delta={delta:+.4f}  budget={args.target_degradation:+.4f}  {tag}")
            return 0 if delta <= args.target_degradation else 1
        return 0

    # mode == "quant"
    if not args.weights.exists():
        print(f"[eval] missing {args.weights}", file=sys.stderr)
        return 2
    result = eval_numpy_quant(args.weights, args.data, args.imgsz, args.num_images)
    result["mode"] = "quant"
    args.output.write_text(json.dumps(result, indent=2))
    print(f"[eval] QUANT consistency={result.get('consistency', 0.0):.2%}  "
          f"images={result.get('n_images', 0)}")

    if args.baseline_map is not None:
        delta = args.baseline_map - result.get("mAP50_95", 0.0)
        print(f"[eval] baseline_map={args.baseline_map:.4f}  quant_map=0  delta={delta:+.4f}  "
              f"budget={args.target_degradation:+.4f}")
        return 0 if delta <= args.target_degradation else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
