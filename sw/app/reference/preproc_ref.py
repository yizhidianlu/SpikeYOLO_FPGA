"""Python reference for sw/app/src/preproc.{h,cpp}.

Mirrors the C++ algorithms bit-for-bit so pytest can verify the C++
implementation independently of any compiler. The C++ code is kept
*structurally* identical (line-for-line) so divergence shows up in code
review, not as a silent algorithmic drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import numpy as np


@dataclass
class Letterbox:
    src_h: int
    src_w: int
    dst_h: int
    dst_w: int
    scale: float
    pad_x: int
    pad_y: int

    FILL = (114, 114, 114)


def plan_letterbox(src_h: int, src_w: int,
                   dst_h: int = 256, dst_w: int = 256) -> Letterbox:
    scale = min(dst_h / src_h, dst_w / src_w)
    new_h = int(round(src_h * scale))
    new_w = int(round(src_w * scale))
    pad_x = (dst_w - new_w) // 2
    pad_y = (dst_h - new_h) // 2
    return Letterbox(src_h=src_h, src_w=src_w,
                     dst_h=dst_h, dst_w=dst_w,
                     scale=scale, pad_x=pad_x, pad_y=pad_y)


def letterbox_rgb_to_int8_chw(rgb_in: np.ndarray, lb: Letterbox) -> np.ndarray:
    """rgb_in: (src_h, src_w, 3) uint8  ->  (3, dst_h, dst_w) int8."""
    if rgb_in.dtype != np.uint8 or rgb_in.shape[2] != 3:
        raise ValueError(f"bad input shape/dtype: {rgb_in.shape} {rgb_in.dtype}")
    out = np.empty((3, lb.dst_h, lb.dst_w), dtype=np.int8)
    inv = 1.0 / lb.scale
    new_h = int(round(lb.src_h * lb.scale))
    new_w = int(round(lb.src_w * lb.scale))

    fill = np.array(Letterbox.FILL, dtype=np.uint8)

    for c in range(3):
        plane = np.full((lb.dst_h, lb.dst_w), fill[c], dtype=np.uint8)
        # filled region
        ys = np.arange(lb.pad_y, lb.pad_y + new_h)
        xs = np.arange(lb.pad_x, lb.pad_x + new_w)
        # Reverse map to source (nearest neighbour rounded the same way C++ does)
        src_y = np.clip(np.round((ys - lb.pad_y) * inv).astype(int), 0, lb.src_h - 1)
        src_x = np.clip(np.round((xs - lb.pad_x) * inv).astype(int), 0, lb.src_w - 1)
        plane[lb.pad_y:lb.pad_y + new_h, lb.pad_x:lb.pad_x + new_w] = \
            rgb_in[np.ix_(src_y, src_x)][:, :, c]
        out[c] = plane.astype(np.int16) - 128
    return out


def yuyv_to_rgb888(yuyv: np.ndarray, src_h: int, src_w: int) -> np.ndarray:
    """yuyv: (src_h * src_w * 2,) uint8 -> (src_h, src_w, 3) uint8 (BT.601)."""
    yuyv = yuyv.reshape(src_h, src_w * 2)
    out = np.empty((src_h, src_w, 3), dtype=np.uint8)
    for y in range(src_h):
        row = yuyv[y]
        for x in range(0, src_w, 2):
            y0 = int(row[x * 2 + 0]); u = int(row[x * 2 + 1])
            y1 = int(row[x * 2 + 2]); v = int(row[x * 2 + 3])
            c0 = y0 - 16; c1 = y1 - 16; d = u - 128; e = v - 128
            def clip(v_: int) -> int:
                return max(0, min(255, v_))
            r0 = clip((298 * c0 + 409 * e + 128) >> 8)
            g0 = clip((298 * c0 - 100 * d - 208 * e + 128) >> 8)
            b0 = clip((298 * c0 + 516 * d + 128) >> 8)
            r1 = clip((298 * c1 + 409 * e + 128) >> 8)
            g1 = clip((298 * c1 - 100 * d - 208 * e + 128) >> 8)
            b1 = clip((298 * c1 + 516 * d + 128) >> 8)
            out[y, x] = (r0, g0, b0)
            out[y, x + 1] = (r1, g1, b1)
    return out


def unletterbox_bbox(lb: Letterbox,
                     x1: float, y1: float,
                     x2: float, y2: float) -> Tuple[float, float, float, float]:
    inv = 1.0 / lb.scale
    nx1 = (x1 - lb.pad_x) * inv
    nx2 = (x2 - lb.pad_x) * inv
    ny1 = (y1 - lb.pad_y) * inv
    ny2 = (y2 - lb.pad_y) * inv

    def clip(v, lo, hi):
        return max(lo, min(hi, v))

    return (clip(nx1, 0.0, lb.src_w - 1),
            clip(ny1, 0.0, lb.src_h - 1),
            clip(nx2, 0.0, lb.src_w - 1),
            clip(ny2, 0.0, lb.src_h - 1))
