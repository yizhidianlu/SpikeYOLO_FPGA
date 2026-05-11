"""Dump every nn.Conv2d in tiny_fpga along with its dotted parent path.

Used once to author tools/quant/np_adapter._SCHEMA without guessing.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import torch
from ultralytics import YOLO


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--yaml", default="ultralytics/cfg/models/v8/snn_yolov8_tiny_fpga.yaml")
    p.add_argument("--pt", type=Path, default=None,
                   help="optional checkpoint to load (just for shape consistency)")
    args = p.parse_args()

    yolo = YOLO(args.yaml, task="detect")
    model = yolo.model
    model.float().eval()

    if args.pt is not None and args.pt.exists():
        ckpt = torch.load(args.pt, map_location="cpu", weights_only=False)
        # ignore — we only need the structure
        del ckpt

    print(f"{'idx':>3}  {'name':<48s}  shape (C_out, C_in/g, K, K)  groups  stride  pad  has_bn")
    print("-" * 110)

    # Walk top-level yaml-node submodules first so the trace order matches the
    # yaml table in CONTRACTS.md.
    pairs = []
    last_conv = None
    for name, mod in model.named_modules():
        if isinstance(mod, torch.nn.Conv2d):
            if last_conv is not None:
                pairs.append((last_conv[0], last_conv[1], None))
            last_conv = (name, mod)
        elif isinstance(mod, torch.nn.BatchNorm2d) and last_conv is not None:
            if mod.num_features == last_conv[1].out_channels:
                pairs.append((last_conv[0], last_conv[1], mod))
                last_conv = None
    if last_conv is not None:
        pairs.append((last_conv[0], last_conv[1], None))

    n_with_bn = 0
    for i, (name, conv, bn) in enumerate(pairs):
        sh = (conv.out_channels, conv.in_channels // conv.groups,
              conv.kernel_size[0], conv.kernel_size[1])
        has_bn = "Y" if bn is not None else " "
        if bn is not None: n_with_bn += 1
        s = conv.stride[0] if isinstance(conv.stride, tuple) else conv.stride
        pad = conv.padding[0] if isinstance(conv.padding, tuple) else conv.padding
        print(f"{i:>3}  {name:<48s}  {sh}  g={conv.groups}  s={s}  p={pad}  {has_bn}")

    print("-" * 110)
    print(f"Total nn.Conv2d  : {len(pairs)}")
    print(f"With BN-2d match : {n_with_bn}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
