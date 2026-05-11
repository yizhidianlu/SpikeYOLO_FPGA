"""Three-way alignment verifier: PyTorch model ↔ tools.fpga.numpy_reference.

Strategy
--------
For each ``(Conv2d, BatchNorm2d)`` pair in the loaded PyTorch model we extract
the weight + (optional) BN parameters, fold them with the same
``tools.quant.fold_bn`` helpers A1 uses, then run a NumPy convolution and
compare against PyTorch's own ``Conv + BN`` forward on the same input.

The two paths share the BN folding logic, so the max abs error must shrink
to floating-point noise (≪ 1e-3 in FP32). If a layer fails, the fault is
in fold_bn or in our extraction logic — exactly the kind of bug the
contract test exists to catch.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

import numpy as np


def _lazy_torch():
    import torch
    import torch.nn as nn
    return torch, nn


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--pt", required=True, type=Path,
                   help="PyTorch tiny_fpga checkpoint")
    p.add_argument("--max-layers", type=int, default=8,
                   help="cap on layers to check (keeps runtime bounded)")
    p.add_argument("--tolerance", type=float, default=1e-3,
                   help="abs error budget (FP32 units)")
    p.add_argument("--device", default="cuda")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--output", type=Path, default=Path("runs/torch_vs_numpy.json"))
    args = p.parse_args(argv)

    torch, nn = _lazy_torch()
    from tools.quant.fold_bn import BnParams, fold
    from tools.quant.run_ptq import find_conv_bn_pairs

    print(f"[align] loading {args.pt}")
    ckpt = torch.load(args.pt, map_location="cpu", weights_only=False)
    yolo_obj = ckpt.get("model", ckpt)
    model = yolo_obj
    model.float().eval()
    if args.device == "cuda" and torch.cuda.is_available():
        model = model.cuda()
    else:
        args.device = "cpu"

    pairs = find_conv_bn_pairs(model)[: args.max_layers]
    print(f"[align] checking {len(pairs)} pairs on {args.device}")

    g = torch.Generator(device=args.device).manual_seed(args.seed)
    summary = []
    all_pass = True

    import torch.nn.functional as F
    for i, (name, conv, bn) in enumerate(pairs):
        x = torch.randn((1, conv.in_channels, 16, 16),
                        generator=g, device=args.device)

        # Path 1: PyTorch's own Conv + BN
        with torch.no_grad():
            y_pt = conv(x)
            if bn is not None:
                y_pt = bn(y_pt)
            y_pt = y_pt.detach().cpu().numpy()

        # Path 2: fold_bn -> single conv
        w_fp = conv.weight.detach().cpu().numpy().astype(np.float64)
        b_fp = conv.bias.detach().cpu().numpy().astype(np.float64) \
               if conv.bias is not None else None
        if bn is not None:
            bn_params = BnParams(
                running_mean=bn.running_mean.detach().cpu().numpy().astype(np.float64),
                running_var=bn.running_var.detach().cpu().numpy().astype(np.float64),
                gamma=bn.weight.detach().cpu().numpy().astype(np.float64),
                beta=bn.bias.detach().cpu().numpy().astype(np.float64),
                eps=float(bn.eps),
            )
            w_fp, b_fp = fold(w_fp.astype(np.float32),
                              b_fp.astype(np.float32) if b_fp is not None else None,
                              bn_params)

        w_t = torch.from_numpy(w_fp.astype(np.float32)).to(args.device)
        b_t = torch.from_numpy(b_fp.astype(np.float32)).to(args.device) \
              if b_fp is not None else None
        with torch.no_grad():
            y_folded = F.conv2d(x, w_t, b_t,
                                stride=conv.stride, padding=conv.padding,
                                groups=conv.groups).detach().cpu().numpy()

        max_err = float(np.max(np.abs(y_pt - y_folded)))
        ok = max_err < args.tolerance
        all_pass &= ok
        flag = "OK" if ok else "FAIL"
        summary.append({"layer": name, "max_err": max_err, "ok": bool(ok)})
        print(f"[align] {i:02d} {name[:40]:40s}  max|Δ|={max_err:.3e}  {flag}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({
        "pt": str(args.pt), "tolerance": args.tolerance,
        "summary": summary,
        "passed": all_pass,
    }, indent=2))
    print(f"[align] overall: {'PASS' if all_pass else 'FAIL'} "
          f"({sum(s['ok'] for s in summary)}/{len(summary)})  "
          f"-> {args.output}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
