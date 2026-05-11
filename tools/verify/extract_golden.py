"""Extract per-layer golden tensors by running ``tools.fpga.numpy_reference``
end-to-end.

For M1W2 we drive the network with **synthetic weights** generated from a
deterministic RNG seed — A1's real PTQ weights are not on disk yet. This
still produces bit-exact golden inputs/outputs at every yaml node, which is
all B1's HLS C-sim needs to verify algorithmic correctness.

Once A1 ships ``models/tiny_fpga_int8.npz``, point this script at it via
``--npz`` (M1W3): it loads the file through
``tools.quant.np_adapter.to_numpy_reference`` and re-runs the trace, this time
with realistic weights.

Output (Contract 2)::

    tests/golden/layer_00_stem.npz       # input, output, kind, params_hash, ...
    tests/golden/layer_00_stem.meta.json # plain-text metadata (dtype + shape)
    ...
    tests/golden/golden_index.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

# Repo-root bootstrap so `python tools/verify/extract_golden.py ...` works
# directly from the shell as well as from tests/conftest.py.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.fpga.numpy_reference import (
    ConvBnParams, TinyFpgaNet,
    ms_all_conv_block, ms_downsampling, ms_standard_conv, spike_sppf,
)


# Layer index -> human name + ConvBnParams kind for Contract 2.
LAYER_NAMES = [
    ("stem",        "ms_downsample"),
    ("acb1",        "sep_conv"),
    ("ds1",         "ms_downsample"),
    ("acb2a",       "sep_conv"),
    ("acb2b",       "sep_conv"),
    ("ds2",         "ms_downsample"),
    ("acb3a",       "sep_conv"),
    ("acb3b",       "sep_conv"),
    ("sppf",        "sppf"),
    ("head_reduce", "conv2d_bn"),
    ("head_refine", "sep_conv"),
    ("detect",      "detect"),
]


# -----------------------------------------------------------------------------
# Synthetic weight generation (numpy_reference.TinyFpgaNet schema)
# -----------------------------------------------------------------------------

def _conv_bn(rng, c_out: int, c_in_per_group: int, k: int,
             stride: int, pad: int, groups: int = 1,
             first_layer: bool = False) -> ConvBnParams:
    """Generate one ConvBnParams with deterministic random values.

    Out-shift is sampled from [2, 8] to keep the post-shift accumulator in
    range without saturating the int8 LIF clamp.
    """
    return ConvBnParams(
        w=rng.integers(-32, 32, size=(c_out, c_in_per_group, k, k), dtype=np.int8),
        bias=rng.integers(-2_000, 2_000, size=(c_out,), dtype=np.int32),
        out_shift=rng.integers(2, 8, size=(c_out,), dtype=np.int16),
        stride=stride, pad=pad, groups=groups, first_layer=first_layer,
    )


def _sep_block(rng, c: int, k: int) -> Dict[str, ConvBnParams]:
    """SepConv = PW1 -> DW2 -> PW3 -> DW4, all keeping c channels."""
    return {
        "pwconv1": _conv_bn(rng, c, c, 1, stride=1, pad=0),
        "dwconv2": _conv_bn(rng, c, 1, k, stride=1, pad=k // 2, groups=c),
        "pwconv3": _conv_bn(rng, c, c, 1, stride=1, pad=0),
        "dwconv4": _conv_bn(rng, c, 1, k, stride=1, pad=k // 2, groups=c),
    }


def _acb(rng, c: int, k: int) -> Dict:
    """MS_AllConvBlock: sep_conv + conv1 + conv2 (all C channels, residual)."""
    return {
        "sep":   _sep_block(rng, c, k),
        "conv1": _conv_bn(rng, c, c, 1, stride=1, pad=0),
        "conv2": _conv_bn(rng, c, c, 1, stride=1, pad=0),
    }


def synth_weights(seed: int = 0) -> Dict[int, Dict]:
    """Build a numpy_reference.TinyFpgaNet-compatible weights dict.

    Channel widths follow tiny_fpga (24/48/96/192) and the SPPF cv1/cv2
    halve-then-quadruple-and-merge pattern.
    """
    rng = np.random.default_rng(seed)

    return {
        # Layer 1: stem 3 -> 24, k=7, stride=4
        1: {"encode_conv": _conv_bn(rng, 24, 3, 7, stride=4, pad=2, first_layer=True)},
        # Layer 2: acb1 (single block, c=24, k=7)
        2: _acb(rng, 24, k=7),
        # Layer 3: ds1 24 -> 48, k=3, stride=2
        3: {"encode_conv": _conv_bn(rng, 48, 24, 3, stride=2, pad=1)},
        # Layer 4: acb2 (two blocks, c=48, k=7)
        4: [_acb(rng, 48, k=7), _acb(rng, 48, k=7)],
        # Layer 5: ds2 48 -> 96, k=3, stride=2
        5: {"encode_conv": _conv_bn(rng, 96, 48, 3, stride=2, pad=1)},
        # Layer 6: acb3 (two blocks, c=96, k=7)
        6: [_acb(rng, 96, k=7), _acb(rng, 96, k=7)],
        # Layer 7: SPPF — cv1: 96 -> 48 halve; cv2: 48*4=192 -> 96 (re-merge)
        7: {"cv1": _conv_bn(rng, 48, 96, 1, stride=1, pad=0),
            "cv2": _conv_bn(rng, 96, 192, 1, stride=1, pad=0)},
        # Layer 8: head_reduce 96 -> 48 (1x1)
        8: {"conv": _conv_bn(rng, 48, 96, 1, stride=1, pad=0)},
        # Layer 9: head_refine (acb, c=48, k=7)
        9: _acb(rng, 48, k=7),
    }


# -----------------------------------------------------------------------------
# Traced forward — same algorithm as TinyFpgaNet.forward, but each yaml node
# emits its input/output to disk before passing along.
# -----------------------------------------------------------------------------

def hash_weights_dict(weights: Dict) -> str:
    """Compute a deterministic SHA-256 over every ndarray in the nested dict."""
    h = hashlib.sha256()
    def walk(x):
        if isinstance(x, np.ndarray):
            h.update(x.tobytes())
            h.update(str(x.dtype).encode())
            h.update(str(x.shape).encode())
        elif isinstance(x, ConvBnParams):
            walk(x.w); walk(x.bias); walk(x.out_shift)
            h.update(bytes([x.stride, x.pad, x.groups, int(x.first_layer)]))
        elif isinstance(x, dict):
            for k in sorted(x.keys(), key=lambda v: str(v)):
                h.update(str(k).encode())
                walk(x[k])
        elif isinstance(x, list):
            for i, item in enumerate(x):
                h.update(str(i).encode())
                walk(item)
    walk(weights)
    return h.hexdigest()


def save_layer(out_dir: Path, idx: int, name: str,
               in_arr: np.ndarray, out_arr: np.ndarray,
               kind: str, params_hash: str) -> Path:
    """Persist one layer's golden tensor + sibling metadata json."""
    out_dir.mkdir(parents=True, exist_ok=True)
    npz_path = out_dir / f"layer_{idx:02d}_{name}.npz"
    meta_path = out_dir / f"layer_{idx:02d}_{name}.meta.json"

    np.savez(npz_path,
             input=in_arr, output=out_arr,
             input_shape=np.array(in_arr.shape, dtype=np.int32),
             output_shape=np.array(out_arr.shape, dtype=np.int32),
             params_hash=np.array([params_hash.encode()], dtype="S64"),
             kind=np.array([kind.encode()], dtype="S32"))
    meta = {
        "idx": idx,
        "name": name,
        "kind": kind,
        "params_hash": params_hash,
        "input":  {"dtype": str(in_arr.dtype),  "shape": list(in_arr.shape)},
        "output": {"dtype": str(out_arr.dtype), "shape": list(out_arr.shape)},
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return npz_path


def trace_forward(weights: Dict[int, Dict],
                  img_i8: np.ndarray,
                  out_dir: Path) -> Dict[str, Path]:
    """Run ``TinyFpgaNet.forward`` and dump every yaml-node's input/output.

    This mirrors ``TinyFpgaNet.forward_backbone + forward_head`` but inlines
    the traversal so each layer boundary can be intercepted. Algorithm stays
    identical to numpy_reference, so the artifacts ARE the bit-exact golden.
    """
    paths: Dict[str, Path] = {}
    params_hash = hash_weights_dict(weights)

    def dump(idx: int, name: str, kind: str,
             in_arr: np.ndarray, out_arr: np.ndarray) -> None:
        paths[name] = save_layer(out_dir, idx, name, in_arr, out_arr,
                                 kind, params_hash)

    # Layer 0: MS_GetT — only adds a T=1 axis. We still emit a record so HLS
    # has the canonical "stem input" tensor (1, 3, H, W) int8.
    x_in = img_i8[np.newaxis, ...]           # (1, 3, H, W) int8
    dump(0, "stem", "ms_downsample", in_arr=x_in,
         out_arr=ms_downsampling(x_in, weights[1]["encode_conv"]))

    # Layer 1: stem MS_DownSampling (first_layer=True). Already computed above
    # but emit a clean entry for downstream tooling.
    x = ms_downsampling(x_in, weights[1]["encode_conv"])

    # Layer 2: acb1
    layer_in = x
    x = ms_all_conv_block(x, weights[2]["sep"],
                          weights[2]["conv1"], weights[2]["conv2"])
    dump(1, "acb1", "sep_conv", in_arr=layer_in, out_arr=x)

    # Layer 3: ds1
    layer_in = x
    x = ms_downsampling(x, weights[3]["encode_conv"])
    dump(2, "ds1", "ms_downsample", in_arr=layer_in, out_arr=x)

    # Layer 4: acb2 (two blocks). Emit one .npz per sub-block.
    for sub_idx, sub_w in enumerate(weights[4]):
        layer_in = x
        x = ms_all_conv_block(x, sub_w["sep"], sub_w["conv1"], sub_w["conv2"])
        dump(3 + sub_idx, f"acb2{chr(ord('a') + sub_idx)}",
             "sep_conv", in_arr=layer_in, out_arr=x)

    # Layer 5: ds2
    layer_in = x
    x = ms_downsampling(x, weights[5]["encode_conv"])
    dump(5, "ds2", "ms_downsample", in_arr=layer_in, out_arr=x)

    # Layer 6: acb3 (two blocks)
    for sub_idx, sub_w in enumerate(weights[6]):
        layer_in = x
        x = ms_all_conv_block(x, sub_w["sep"], sub_w["conv1"], sub_w["conv2"])
        dump(6 + sub_idx, f"acb3{chr(ord('a') + sub_idx)}",
             "sep_conv", in_arr=layer_in, out_arr=x)

    # Layer 7: SpikeSPPF
    layer_in = x
    x = spike_sppf(x, weights[7]["cv1"], weights[7]["cv2"], k=5)
    dump(8, "sppf", "sppf", in_arr=layer_in, out_arr=x)

    # Layer 8: head_reduce MS_StandardConv
    layer_in = x
    x = ms_standard_conv(x, weights[8]["conv"])
    dump(9, "head_reduce", "conv2d_bn", in_arr=layer_in, out_arr=x)

    # Layer 9: head_refine MS_AllConvBlock
    layer_in = x
    x = ms_all_conv_block(x, weights[9]["sep"],
                          weights[9]["conv1"], weights[9]["conv2"])
    dump(10, "head_refine", "sep_conv", in_arr=layer_in, out_arr=x)

    # Layer 10 (Detect head) runs on PS — emit only the head_refine output
    # as the "detect input" so C3's post-processing pipeline has a reference.
    # (Detect head NMS / DFL decode is C3's job, not B1's.)
    dump(11, "detect", "detect", in_arr=x, out_arr=x.astype(np.int8))

    return paths


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def trace_layer_by_layer(layers, img_i8: np.ndarray, out_dir: Path):
    """Per-Conv2d_bn trace mode.

    Each LayerEntry is applied independently as a ``conv2d_bn`` step (no
    residuals, no SPPF, no Detect head decode) and its input/output is
    dumped. This sidesteps the model-graph differences between PyTorch and
    numpy_reference, giving B1 HLS testbench a per-operator golden it can
    bit-compare against.
    """
    from tools.fpga.numpy_reference import ConvBnParams, conv2d_bn, mem_update, MAX_SPIKE

    paths: Dict[str, Path] = {}
    params_hash = "PTQ-layerbylayer"
    x = img_i8[np.newaxis, ...]   # (T=1, C, H, W) int8

    for i, L in enumerate(layers):
        cbn = ConvBnParams(
            w=L.w, bias=L.bias,
            out_shift=L.out_shift.astype(np.int16),
            stride=L.stride, pad=L.pad,
            groups=L.groups, first_layer=L.first_layer,
        )
        layer_in = x.copy()
        # Guard: ensure dtype expectations match the conv2d_bn contract.
        if L.first_layer and x.dtype != np.int8:
            x = x.astype(np.int8)
        if not L.first_layer and x.dtype != np.int8:
            x = mem_update(x)        # collapse int32 -> 4 binary substeps
        try:
            y = conv2d_bn(x, cbn)
        except Exception as exc:
            print(f"[trace] L{i:02d} {L.kind}: skipping ({exc})")
            continue

        name = f"L{i:02d}_{L.kind}"
        p = save_layer(out_dir, idx=i, name=name,
                       in_arr=layer_in, out_arr=y,
                       kind=L.kind, params_hash=params_hash)
        paths[name] = p
        x = y   # next iteration: next layer expects int32 pre-LIF input
    return paths


def _file_sha256(path: Path) -> str:
    """SHA-256 of a file's raw bytes."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _autocorrect_layer_pads(layers, *, verbose: bool = True) -> int:
    """Patch up A1's known pad-bug for stride-1 k>1 convs.

    A1's PTQ pipeline currently emits ``pad=0`` for the SepRepConv 3×3
    depth-wise inner conv (LayerEntry indices 4 / 11 / 18 / 27 in the 37-conv
    schema). With pad=0 these convs shrink (H, W) by 2, breaking the
    AllConvBlock residual connection downstream.

    Until A1 fixes the bug, we rewrite ``pad`` to ``k // 2`` for any
    stride-1 conv with k > 1 that currently has pad=0. Returns the number of
    patched layers so the caller can log it.
    """
    n_patched = 0
    for i, L in enumerate(layers):
        if L.k > 1 and L.stride == 1 and L.pad == 0:
            new_pad = L.k // 2
            if verbose:
                print(f"[extract_golden] auto-corrected L{i:02d} pad: 0 -> {new_pad} "
                      f"(k={L.k}, stride=1)")
            L.pad = new_pad
            n_patched += 1
    return n_patched


def main(argv: list | None = None) -> int:
    from datetime import datetime, timezone

    p = argparse.ArgumentParser()
    p.add_argument("--npz", type=Path, default=None,
                   help="(M1W3+) quantized weights .npz from A1; use synth if absent")
    p.add_argument("--seed", type=int, default=0,
                   help="RNG seed for synthetic weights / image")
    p.add_argument("--num-images", type=int, default=1,
                   help="(reserved for M1W4) multi-image batch dumping")
    p.add_argument("--layers", type=str, default=None,
                   help="comma-separated layer indices to emit (default: all 12)")
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--stub", action="store_true",
                   help="(legacy) emit zero-filled placeholders without invoking forward")
    p.add_argument("--mode", choices=["yaml", "layer-by-layer"], default="yaml",
                   help="yaml: 12-node trace via TinyFpgaNet; layer-by-layer: 37 "
                        "independent conv2d_bn dumps (use with real --npz)")
    p.add_argument("--no-autocorrect-pad", action="store_true",
                   help="disable the A1 pad-bug workaround for stride-1 k>1 convs")
    p.add_argument("--weights-source-label", default=None,
                   help="override the weights_source field written into golden_index.json")
    args = p.parse_args(argv)

    layers_from_npz = None
    weights_sha256 = None
    if args.npz is not None and args.npz.exists():
        from tools.quant.np_adapter import to_numpy_reference, schema_size
        from tools.quant.weight_packer import read_npz
        layers, _ = read_npz(args.npz)
        weights_sha256 = _file_sha256(args.npz)
        print(f"[extract_golden] loaded {len(layers)} LayerEntry from {args.npz}")
        print(f"[extract_golden] weights_sha256 = {weights_sha256}")
        if not args.no_autocorrect_pad:
            n_fixed = _autocorrect_layer_pads(layers)
            if n_fixed:
                print(f"[extract_golden] auto-corrected pad on {n_fixed} layer(s); "
                      f"this is a workaround for A1's known SepRepConv pad-bug.")
        layers_from_npz = layers
        if len(layers) != schema_size():
            print(f"[extract_golden] WARN: schema expects {schema_size()} layers but "
                  f".npz has {len(layers)} — falling back to synthetic weights")
            weights = synth_weights(seed=args.seed)
        else:
            weights = to_numpy_reference(layers)
    elif args.stub:
        # Legacy behavior — kept for the very first B1 wiring iteration.
        print("[extract_golden] STUB mode — emitting zero-tensor placeholders.")
        weights = None
    else:
        weights = synth_weights(seed=args.seed)
        print(f"[extract_golden] using synthetic weights (seed={args.seed})")

    args.output_dir.mkdir(parents=True, exist_ok=True)

    if weights is None:
        # Stub path: zero-filled, kept for backward compat with M1W1 callers.
        from tools.verify._stub_shapes import emit_stub_layers
        paths = emit_stub_layers(args.output_dir,
                                 layer_names=[n for n, _ in LAYER_NAMES],
                                 kinds_per_layer=[k for _, k in LAYER_NAMES])
    else:
        rng = np.random.default_rng(args.seed + 1)
        img_i8 = rng.integers(-128, 127, size=(3, 256, 256), dtype=np.int8)
        if args.mode == "layer-by-layer" and layers_from_npz is not None:
            paths = trace_layer_by_layer(layers_from_npz, img_i8, args.output_dir)
        else:
            paths = trace_forward(weights, img_i8, args.output_dir)

    if args.weights_source_label is not None:
        weights_source = args.weights_source_label
    elif args.npz is not None and args.npz.exists():
        weights_source = "a1_int8_npz"
    elif args.stub:
        weights_source = "stub"
    else:
        weights_source = "synthetic"

    summary = {
        "weights_source": weights_source,
        "weights_path": str(args.npz) if args.npz is not None else None,
        "weights_sha256": weights_sha256,
        "seed": args.seed,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pad_autocorrected": (args.npz is not None and not args.no_autocorrect_pad),
        "layer_count": len(paths),
        "layers": {name: str(p) for name, p in paths.items()},
    }
    idx_path = args.output_dir / "golden_index.json"
    idx_path.write_text(json.dumps(summary, indent=2))
    print(f"[extract_golden] wrote {len(paths)} layers + index -> {idx_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
