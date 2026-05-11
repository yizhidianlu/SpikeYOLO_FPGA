"""A1 entry point: full PTQ orchestrator for tiny_fpga.

Walks the loaded PyTorch model, locates every (Conv2d -> BatchNorm2d) pair,
optionally collects activation statistics on a small calibration batch, and
emits a Contract-1 .npz built from per-channel symmetric INT8 weights with
BN folded in.

End-to-end usable on a GPU with the ``spikeyolo`` conda env. When COCO
calibration images are unavailable the script falls back to
``torch.randn`` calibration so the pipeline still produces a valid .npz.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

# Repo-root bootstrap so `import ultralytics` (and `tools.*`) resolve when this
# script is invoked from any working directory.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# Heavy imports happen inside main() so `python run_ptq.py --help` works on
# machines without torch.

def _lazy_torch():
    try:
        import torch
        import torch.nn as nn
        return torch, nn
    except ImportError as exc:
        raise SystemExit(
            "PyTorch required. Activate the spikeyolo conda env:\n"
            "  conda run -n spikeyolo python tools/quant/run_ptq.py\n"
            f"Original error: {exc}"
        )


# ---------------------------------------------------------------------------
# Calibration loader
# ---------------------------------------------------------------------------

def build_calibration_loader(img_dir: Optional[Path], num: int, size: int = 256):
    """Yield ``(name, tensor_chw_int8_normalized)`` for ``num`` calibration images.

    If ``img_dir`` is None or empty, returns deterministic random tensors so the
    rest of the pipeline can still exercise the hook plumbing on machines
    without COCO downloaded.
    """
    import torch
    from PIL import Image

    if img_dir and img_dir.exists():
        paths = sorted(img_dir.glob("*.jpg"))[:num] + sorted(img_dir.glob("*.png"))[:num]
        paths = paths[:num]
        if paths:
            for p in paths:
                img = Image.open(p).convert("RGB").resize((size, size))
                arr = np.asarray(img, dtype=np.uint8)
                t = torch.from_numpy(arr).permute(2, 0, 1).contiguous()  # (C, H, W)
                t = t.float().div(255.0).sub(0.5).mul(255.0)             # ~[-128, 127]
                yield p.name, t.unsqueeze(0)
            return
    # fallback
    print(f"[ptq] WARN: no images in {img_dir} — using deterministic random tensors")
    g = torch.Generator().manual_seed(0)
    for i in range(num):
        t = (torch.rand((1, 3, size, size), generator=g) * 255 - 128).round().clamp(-128, 127)
        yield f"rand_{i:03d}", t


# ---------------------------------------------------------------------------
# Walk the model: find every (Conv2d, BatchNorm2d|None) pair in execution order
# ---------------------------------------------------------------------------

def find_conv_bn_pairs(model) -> List[Tuple[str, "nn.Conv2d", "Optional[nn.BatchNorm2d]"]]:
    """Walk model.named_modules() and pair Conv2d layers with the BatchNorm2d
    that immediately follows them in the registration order.

    Conv2d entries that are not followed by a BatchNorm2d (e.g. SpikeDetect's
    head conv) are paired with ``None`` and skipped from BN folding.
    """
    import torch.nn as nn
    pairs: List[Tuple[str, nn.Conv2d, Optional[nn.BatchNorm2d]]] = []
    last_conv: Optional[Tuple[str, nn.Conv2d]] = None
    for name, mod in model.named_modules():
        if isinstance(mod, nn.Conv2d):
            if last_conv is not None:
                # Previous conv didn't get a BN — emit it standalone.
                pairs.append((last_conv[0], last_conv[1], None))
            last_conv = (name, mod)
        elif isinstance(mod, nn.BatchNorm2d) and last_conv is not None:
            if mod.num_features == last_conv[1].out_channels:
                pairs.append((last_conv[0], last_conv[1], mod))
                last_conv = None
            # otherwise: BN doesn't match the conv shape, leave conv pending
    if last_conv is not None:
        pairs.append((last_conv[0], last_conv[1], None))
    return pairs


# ---------------------------------------------------------------------------
# Quantize one pair into a Contract-1 LayerEntry
# ---------------------------------------------------------------------------

def quantize_pair(
    name: str,
    conv,
    bn,
    idx: int,
    act_scale: float = 1.0,
    first_layer: bool = False,
) -> "LayerEntry":   # noqa: F821
    """Fold BN (if any) into conv, then per-channel int8 quantize."""
    from tools.quant.fold_bn import (
        BnParams, compute_out_shift, fold, quantize_per_channel_weight,
    )
    from tools.quant.weight_packer import LayerEntry

    w_fp = conv.weight.detach().cpu().to(dtype=__import__("torch").float64).numpy()
    b_fp = conv.bias.detach().cpu().to(dtype=__import__("torch").float64).numpy() \
           if conv.bias is not None else None

    if bn is not None:
        bn_params = BnParams(
            running_mean=bn.running_mean.detach().cpu().numpy().astype(np.float64),
            running_var=bn.running_var.detach().cpu().numpy().astype(np.float64),
            gamma=bn.weight.detach().cpu().numpy().astype(np.float64),
            beta=bn.bias.detach().cpu().numpy().astype(np.float64),
            eps=float(bn.eps),
        )
        w_fp, b_fp = fold(w_fp.astype(np.float32), b_fp.astype(np.float32) if b_fp is not None else None,
                          bn_params)

    # Int8 weight quantization (per output channel, symmetric).
    w_int, w_scale = quantize_per_channel_weight(w_fp.astype(np.float32))

    # Output scale for tiny_fpga's clamped activations stays at MultiSpike4.
    # We assume input/output activation scales = 1 by default.
    out_shift = compute_out_shift(w_scale, input_scale=1.0, output_scale=max(act_scale, 1e-9))

    bias_i32 = np.zeros(w_int.shape[0], dtype=np.int32)
    if b_fp is not None:
        # Quantize bias to the conv's effective scale (per-channel)
        bias_i32 = np.round(b_fp / np.maximum(w_scale, 1e-12)).astype(np.int32)

    # Pick a coarse "kind" enum from naming heuristic.
    kind = "conv2d_bn"
    if "encode_conv" in name:
        kind = "ms_downsample"
    elif "Detect" in name or "head" in name.lower() or "detect" in name.lower():
        kind = "detect"
    elif "sppf" in name.lower():
        kind = "sppf"

    pad = conv.padding[0] if isinstance(conv.padding, (tuple, list)) else int(conv.padding)
    stride = conv.stride[0] if isinstance(conv.stride, (tuple, list)) else int(conv.stride)
    groups = int(conv.groups)
    k_size = conv.kernel_size[0] if isinstance(conv.kernel_size, (tuple, list)) else int(conv.kernel_size)

    # ------------------------------------------------------------------
    # SepRepConv pad fix (W3, 2026-05-11):
    # SepRepConv (yolo_spikformer.py:334) constructs its inner 3×3 dw conv
    # with ``padding=0`` because it is preceded by ``BNAndPadLayer`` which
    # F.pad's the activation by k//2 ahead of the conv. The FPGA pipeline
    # (numpy_reference.spike_*) does NOT have BNAndPadLayer — it folds the
    # padding into the conv itself. So when serializing into the .npz we
    # have to compensate by emitting pad=k//2 even though the PyTorch conv
    # stores pad=0.
    #
    # The four affected modules in tiny_fpga are:
    #   2.Conv.pwconv3.body.1.1   (LayerEntry idx 4)
    #   4.Conv.pwconv3.body.1.1   (LayerEntry idx 11)
    #   6.Conv.pwconv3.body.1.1   (LayerEntry idx 18)
    #   9.Conv.pwconv3.body.1.1   (LayerEntry idx 27)
    # We pattern-match on the ".body.1.1" suffix (defensive against future
    # acb count changes) AND require k>1, stride==1, pad==0 to avoid
    # touching anything else.
    if (name.endswith(".body.1.1")
            and k_size > 1 and stride == 1 and pad == 0):
        new_pad = k_size // 2
        print(f"[ptq] SepRepConv pad fix: L{idx:02d} {name} pad 0 -> {new_pad} (k={k_size})")
        pad = new_pad

    return LayerEntry(
        idx=idx, kind=kind,
        w=w_int, bias=bias_i32, out_shift=out_shift.astype(np.int8),
        stride=stride, pad=pad, groups=groups,
        first_layer=first_layer,
    )


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pt", required=True, type=Path,
                        help="PyTorch tiny_fpga checkpoint (.pt)")
    parser.add_argument("--calib-imgs", type=Path, default=None,
                        help="Directory of calibration images (JPEG/PNG)")
    parser.add_argument("--num-calib", type=int, default=16)
    parser.add_argument("--output", required=True, type=Path,
                        help="Output .npz path (Contract 1)")
    parser.add_argument("--layout", choices=["standard", "pe_tile"], default="standard")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--max-pairs", type=int, default=None,
                        help="Cap on (conv, bn) pairs to quantize")
    args = parser.parse_args(argv)

    torch, nn = _lazy_torch()
    from ultralytics import YOLO

    print(f"[ptq] loading checkpoint {args.pt}")
    ckpt = torch.load(args.pt, map_location="cpu", weights_only=False)
    yolo_obj = ckpt.get("model", ckpt)
    if hasattr(yolo_obj, "model"):
        model = yolo_obj
    else:
        # raw nn.Module
        model = yolo_obj
    model.float().eval()
    if args.device == "cuda" and torch.cuda.is_available():
        model = model.cuda()
    else:
        args.device = "cpu"
    print(f"[ptq] device = {args.device}")

    # Identify conv pairs.
    pairs = find_conv_bn_pairs(model)
    if args.max_pairs is not None:
        pairs = pairs[: args.max_pairs]
    print(f"[ptq] found {len(pairs)} (Conv2d, BN) pairs")

    # Calibration — for now we only run forward to validate the model is sane.
    # Per-tensor activation scales for SpikeYOLO are dominated by MultiSpike4
    # which is constant in [0, 4]; we keep act_scale = 1.0 across the board.
    n_done = 0
    t0 = time.time()
    with torch.no_grad():
        for nm, x in build_calibration_loader(args.calib_imgs, args.num_calib):
            x = x.float().to(args.device)
            try:
                _ = model(x)
            except Exception as exc:
                print(f"[ptq] WARN: forward {nm} failed ({type(exc).__name__}: {exc})")
                continue
            n_done += 1
    print(f"[ptq] calibration: {n_done} images in {time.time() - t0:.1f}s")

    # Quantize each pair.
    entries = []
    for i, (name, conv, bn) in enumerate(pairs):
        is_first = (i == 0)   # only the stem encode_conv treats input as raw INT8
        try:
            le = quantize_pair(name, conv, bn, idx=i, first_layer=is_first)
            entries.append(le)
        except Exception as exc:
            print(f"[ptq] skip {name}: {exc}")

    print(f"[ptq] quantized {len(entries)} layers")

    from tools.quant.weight_packer import write_npz, write_bin
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_npz(entries, args.output, layout=args.layout)
    bin_path = args.output.with_suffix(".bin")
    write_bin(entries, bin_path, layout="pe_tile")
    print(f"[ptq] wrote {args.output}  ({args.output.stat().st_size/1e6:.2f} MB)")
    print(f"[ptq] wrote {bin_path}      ({bin_path.stat().st_size/1e6:.2f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
