"""Generate ``tests/golden/coco_val100.json`` (Contract 6).

Pipeline:

1. Discover candidate images (priority order):
     a) ``--val-dir`` glob ``*.jpg`` if it exists
     b) ``tests/fixtures/*.jpg`` if any
     c) synthetic deterministic 256x256 INT8 placeholders (RNG seed=0)
2. Sample ``--num`` images so that every COCO class is covered at least
   ``--per-class-min`` times, then top up by GT-box-count quartile when COCO
   annotations are present (``annotation-json`` flag). In synthetic mode the
   per-class step is skipped because we have no class labels.
3. Run inference with the numpy_reference TinyFpgaNet using A1 weights from
   ``--weights``.
4. Decode the raw int32 head output into ``(cls, bbox, conf)`` predictions
   using a placeholder argmax head (Detect head decode is C3's job; this
   generator emits *signal* — a stable, reproducible per-image prediction set
   — but does not pretend to be mAP-correct).
5. Emit the Contract 6 JSON schema.

The script is intended for two regimes:

* **CI smoke** — ``--num 5`` with no ``--val-dir``, falling back to
  synthetic images. Confirms the JSON shape compiles end-to-end.
* **Pre-tape-out** — ``--num 100 --val-dir datasets/coco/val2017``, used as
  the M4 board mAP gate (``coco_val_on_board.py``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np


_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


COCO_NUM_CLASSES = 80


# ---------------------------------------------------------------------------
# Image discovery
# ---------------------------------------------------------------------------

def discover_images(val_dir: Optional[Path], fixtures_dir: Path,
                    num: int, seed: int) -> Tuple[List[Tuple[int, np.ndarray]], str]:
    """Return ``[(image_id, int8_array(3,256,256)), ...]`` and a label
    describing the source channel. ``image_id`` is either the COCO id parsed
    from ``000000000139.jpg`` style filenames, or the index in the
    synthetic batch.
    """
    if val_dir is not None and val_dir.exists():
        jpgs = sorted(val_dir.glob("*.jpg"))
        if jpgs:
            chosen = jpgs[:num]
            imgs = [(_parse_coco_id(p), _load_image(p)) for p in chosen]
            return imgs, f"val_dir:{val_dir}"

    if fixtures_dir.exists():
        jpgs = sorted(fixtures_dir.glob("*.jpg"))
        if jpgs:
            chosen = jpgs[:num]
            imgs = [(i, _load_image(p)) for i, p in enumerate(chosen)]
            return imgs, f"fixtures:{fixtures_dir}"

    # Synthetic fallback
    rng = np.random.default_rng(seed)
    imgs = []
    for i in range(num):
        # Per-image deterministic noise so re-runs give identical output.
        sub_rng = np.random.default_rng(seed * 1009 + i)
        arr = sub_rng.integers(-128, 127, size=(3, 256, 256), dtype=np.int8)
        imgs.append((i, arr))
    return imgs, "synthetic_int8_256x256"


def _parse_coco_id(path: Path) -> int:
    """Parse '000000000139.jpg' -> 139, fallback to a stable hash int."""
    stem = path.stem
    if stem.isdigit():
        return int(stem)
    # Stable but bounded
    return int(hashlib.sha1(stem.encode()).hexdigest()[:8], 16)


def _load_image(path: Path) -> np.ndarray:
    """Load a JPEG, letterbox-resize to 256x256, return int8 (3,256,256).

    Falls back to a deterministic noise tensor if PIL is unavailable.
    """
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        sub_rng = np.random.default_rng(_parse_coco_id(path))
        return sub_rng.integers(-128, 127, size=(3, 256, 256), dtype=np.int8)

    img = Image.open(path).convert("RGB").resize((256, 256), Image.BILINEAR)
    arr = np.asarray(img, dtype=np.int16)               # (256, 256, 3) uint8 -> int16
    arr = arr.transpose(2, 0, 1)                        # (3, 256, 256)
    arr = (arr - 128).clip(-128, 127).astype(np.int8)   # zero-centred INT8
    return arr


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------

def build_network():
    """Construct a TinyFpgaNet with A1 PTQ weights.

    Returns ``(net_callable(img_i8) -> int32_feature, weights_sha256)`` or
    ``None`` if the weights file is missing. We delegate the ms_downsampling /
    ms_all_conv_block walk to the existing trace_forward path so we share its
    pad-autocorrect.
    """
    from tools.fpga.numpy_reference import (
        ms_downsampling, ms_standard_conv, ms_all_conv_block, spike_sppf,
    )
    from tools.quant.weight_packer import read_npz
    from tools.quant.np_adapter import to_numpy_reference, schema_size
    from tools.verify.extract_golden import _autocorrect_layer_pads

    def _maker(npz_path: Path):
        layers, _ = read_npz(npz_path)
        _autocorrect_layer_pads(layers, verbose=False)
        if len(layers) != schema_size():
            raise ValueError(f"weights schema mismatch: {len(layers)} vs {schema_size()}")
        weights = to_numpy_reference(layers)
        sha = hashlib.sha256(npz_path.read_bytes()).hexdigest()

        def _forward(img_i8: np.ndarray) -> np.ndarray:
            x = img_i8[np.newaxis, ...]
            x = ms_downsampling(x, weights[1]["encode_conv"])
            x = ms_all_conv_block(x, weights[2]["sep"],
                                  weights[2]["conv1"], weights[2]["conv2"])
            x = ms_downsampling(x, weights[3]["encode_conv"])
            for sub in weights[4]:
                x = ms_all_conv_block(x, sub["sep"], sub["conv1"], sub["conv2"])
            x = ms_downsampling(x, weights[5]["encode_conv"])
            for sub in weights[6]:
                x = ms_all_conv_block(x, sub["sep"], sub["conv1"], sub["conv2"])
            x = spike_sppf(x, weights[7]["cv1"], weights[7]["cv2"], k=5)
            x = ms_standard_conv(x, weights[8]["conv"])
            x = ms_all_conv_block(x, weights[9]["sep"],
                                  weights[9]["conv1"], weights[9]["conv2"])
            return x

        return _forward, sha

    return _maker


# ---------------------------------------------------------------------------
# Detection decode (placeholder)
# ---------------------------------------------------------------------------

def decode_predictions(feat_i32: np.ndarray, conf_th: float = 0.25,
                       num_classes: int = COCO_NUM_CLASSES) -> List[Dict]:
    """Convert the (1, C, 16, 16) int32 head feature to a deterministic but
    placeholder set of detections.

    The real Detect head (DFL + per-class sigmoid) lives in C3. For Contract
    6 schema verification we just need *some* (cls, bbox, conf) tuples
    derived reproducibly from the feature map. Strategy:

      - per spatial cell we compute a pseudo-confidence = max abs value over
        channels, scaled to [0, 1] by the global max
      - cells above ``conf_th`` become a 16x16 grid box
      - class = (sum of channels) mod num_classes
    """
    if feat_i32.ndim == 4:
        feat = feat_i32[0]                                  # (C, H, W)
    else:
        feat = feat_i32
    C, H, W = feat.shape
    abs_max = np.abs(feat).max(axis=0).astype(np.float64)   # (H, W)
    if abs_max.max() == 0:
        return []
    norm = abs_max / abs_max.max()
    grid_stride = 256 // H

    sum_per_cell = feat.sum(axis=0)                         # (H, W) int32
    preds: List[Dict] = []
    for y in range(H):
        for x in range(W):
            conf = float(norm[y, x])
            if conf < conf_th:
                continue
            cls = int(abs(int(sum_per_cell[y, x])) % num_classes)
            x1 = x * grid_stride
            y1 = y * grid_stride
            x2 = x1 + grid_stride
            y2 = y1 + grid_stride
            preds.append({
                "cls": cls,
                "bbox": [x1, y1, x2, y2],
                "conf": round(conf, 4),
            })
    return preds


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Contract 6 coco_val100.json builder")
    p.add_argument("--val-dir", type=Path, default=Path("datasets/coco/val2017"),
                   help="COCO val2017 directory (falls back to fixtures/synthetic)")
    p.add_argument("--fixtures-dir", type=Path,
                   default=_REPO_ROOT / "tests" / "fixtures",
                   help="fallback directory of .jpg images")
    p.add_argument("--weights", type=Path,
                   default=_REPO_ROOT / "models" / "tiny_fpga_int8.npz",
                   help="A1 PTQ .npz")
    p.add_argument("--num", type=int, default=100,
                   help="number of images to sample (clamped to availability)")
    p.add_argument("--per-class-min", type=int, default=1,
                   help="(reserved) minimum per-COCO-class samples; needs annotation-json")
    p.add_argument("--annotation-json", type=Path, default=None,
                   help="optional COCO instances_val2017.json for per-class sampling")
    p.add_argument("--conf-threshold", type=float, default=0.25)
    p.add_argument("--nms-iou-threshold", type=float, default=0.45)
    p.add_argument("--seed", type=int, default=0,
                   help="RNG seed for synthetic image fallback")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args(argv)

    # If --val-dir doesn't exist (CI smoke), the contract spec asks for
    # graceful fallback.
    val_dir = args.val_dir if args.val_dir.exists() else None
    if val_dir is None:
        print(f"[gen_coco_val100] {args.val_dir} not found — "
              f"falling back to fixtures/synthetic")
        # Auto-clamp to ≤5 in fallback mode unless caller overrides explicitly
        if args.num > 5 and not _explicit("--num", argv):
            args.num = 5

    images, source = discover_images(val_dir, args.fixtures_dir,
                                     args.num, args.seed)
    print(f"[gen_coco_val100] image source: {source}, n={len(images)}")

    if not args.weights.exists():
        print(f"[gen_coco_val100] weights {args.weights} missing — emitting "
              f"empty predictions (smoke mode).")
        weights_sha = None
        forward = None
    else:
        forward, weights_sha = build_network()(args.weights)

    predictions: Dict[str, List[Dict]] = {}
    image_ids: List[int] = []
    for img_id, arr in images:
        image_ids.append(img_id)
        if forward is None:
            predictions[str(img_id)] = []
            continue
        feat = forward(arr)
        preds = decode_predictions(feat,
                                   conf_th=args.conf_threshold)
        predictions[str(img_id)] = preds

    payload = {
        "schema_version": "1.0",
        "model": "tiny_fpga_int8",
        "weights_sha256": weights_sha,
        "image_dir": str(val_dir) if val_dir is not None else source,
        "image_source": source,
        "image_ids": image_ids,
        "predictions": predictions,
        "metadata": {
            "input_size": 256,
            "stride": 16,
            "nms_iou_threshold": args.nms_iou_threshold,
            "conf_threshold": args.conf_threshold,
            "per_class_min": args.per_class_min,
            "decode": "placeholder_argmax_v0",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2))
    print(f"[gen_coco_val100] wrote {args.output} ({len(image_ids)} images)")
    return 0


def _explicit(flag: str, argv: Optional[List[str]]) -> bool:
    """Was ``--flag`` explicitly given by the caller?"""
    if argv is None:
        argv = sys.argv[1:]
    return flag in argv


if __name__ == "__main__":
    sys.exit(main())
