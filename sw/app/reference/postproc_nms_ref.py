"""Python reference for sw/app/src/postproc_nms.{h,cpp}."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import numpy as np


@dataclass
class Detection:
    x1: float
    y1: float
    x2: float
    y2: float
    conf: float
    cls: int


def sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + np.exp(-x))
    ex = np.exp(x)
    return ex / (1.0 + ex)


def iou_xyxy(a: Detection, b: Detection) -> float:
    xa = max(a.x1, b.x1); ya = max(a.y1, b.y1)
    xb = min(a.x2, b.x2); yb = min(a.y2, b.y2)
    inter = max(0.0, xb - xa) * max(0.0, yb - ya)
    area_a = max(0.0, a.x2 - a.x1) * max(0.0, a.y2 - a.y1)
    area_b = max(0.0, b.x2 - b.x1) * max(0.0, b.y2 - b.y1)
    uni = area_a + area_b - inter
    return inter / uni if uni > 0 else 0.0


def nms(boxes: List[Detection], iou_thresh: float) -> List[Detection]:
    boxes = sorted(boxes, key=lambda b: b.conf, reverse=True)
    kept: List[Detection] = []
    suppressed = [False] * len(boxes)
    for i in range(len(boxes)):
        if suppressed[i]:
            continue
        kept.append(boxes[i])
        for j in range(i + 1, len(boxes)):
            if suppressed[j]:
                continue
            if boxes[j].cls != boxes[i].cls:
                continue
            if iou_xyxy(boxes[i], boxes[j]) >= iou_thresh:
                suppressed[j] = True
    return kept


def decode_and_nms(feat: np.ndarray,
                   nc: int,
                   grid_h: int, grid_w: int, stride: int,
                   conf_thresh: float,
                   iou_thresh: float,
                   scale_factor: float = 1.0 / 64.0) -> List[Detection]:
    """feat shape: ((nc+4), grid_h, grid_w) int8."""
    raw: List[Detection] = []
    feat_f = feat.astype(np.float32) * scale_factor
    for y in range(grid_h):
        for x in range(grid_w):
            cls_scores = feat_f[4:, y, x]
            best_cls = int(np.argmax(cls_scores))
            best_score = float(cls_scores[best_cls])
            conf = sigmoid(best_score)
            if conf < conf_thresh:
                continue
            dx = feat_f[0, y, x]; dy = feat_f[1, y, x]
            log_w = feat_f[2, y, x]; log_h = feat_f[3, y, x]
            cx = (x + sigmoid(dx)) * stride
            cy = (y + sigmoid(dy)) * stride
            w = np.exp(log_w) * stride
            h = np.exp(log_h) * stride
            raw.append(Detection(
                x1=cx - 0.5 * w, y1=cy - 0.5 * h,
                x2=cx + 0.5 * w, y2=cy + 0.5 * h,
                conf=conf, cls=best_cls,
            ))
    return nms(raw, iou_thresh)
