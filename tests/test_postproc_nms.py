"""Tests for sw/app/reference/postproc_nms_ref.py."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

APP_REF = Path(__file__).resolve().parent.parent / "sw" / "app" / "reference"
sys.path.insert(0, str(APP_REF))

from postproc_nms_ref import (   # noqa: E402
    Detection, decode_and_nms, iou_xyxy, nms, sigmoid,
)


@pytest.mark.contract
class TestSigmoid:
    def test_zero(self):
        assert sigmoid(0.0) == pytest.approx(0.5)

    def test_large_positive(self):
        assert sigmoid(50.0) == pytest.approx(1.0, abs=1e-9)

    def test_large_negative(self):
        assert sigmoid(-50.0) == pytest.approx(0.0, abs=1e-9)


@pytest.mark.contract
class TestIoU:
    def test_disjoint(self):
        a = Detection(0, 0, 10, 10, 1.0, 0)
        b = Detection(20, 20, 30, 30, 1.0, 0)
        assert iou_xyxy(a, b) == 0.0

    def test_identical(self):
        a = Detection(0, 0, 10, 10, 1.0, 0)
        b = Detection(0, 0, 10, 10, 1.0, 0)
        assert iou_xyxy(a, b) == pytest.approx(1.0)

    def test_half_overlap(self):
        a = Detection(0, 0, 10, 10, 1.0, 0)
        b = Detection(5, 0, 15, 10, 1.0, 0)
        # inter = 5*10 = 50; uni = 100 + 100 - 50 = 150
        assert iou_xyxy(a, b) == pytest.approx(50.0 / 150.0)


@pytest.mark.contract
class TestNms:
    def test_suppresses_overlap_same_class(self):
        boxes = [
            Detection(0, 0, 10, 10, 0.9, 0),
            Detection(0, 0, 10, 10, 0.8, 0),
            Detection(20, 20, 30, 30, 0.7, 0),
        ]
        kept = nms(boxes, iou_thresh=0.5)
        assert len(kept) == 2
        assert {(int(b.x1), int(b.y1)) for b in kept} == {(0, 0), (20, 20)}

    def test_keeps_overlap_different_class(self):
        """Class-aware NMS: a strong overlap between different classes is kept."""
        boxes = [
            Detection(0, 0, 10, 10, 0.9, 0),
            Detection(0, 0, 10, 10, 0.8, 1),  # different class
        ]
        kept = nms(boxes, iou_thresh=0.5)
        assert len(kept) == 2

    def test_sorts_by_confidence(self):
        boxes = [
            Detection(0,  0, 10, 10, 0.5, 0),
            Detection(20, 0, 30, 10, 0.9, 1),
            Detection(40, 0, 50, 10, 0.7, 2),
        ]
        kept = nms(boxes, iou_thresh=0.5)
        assert [b.conf for b in kept] == [0.9, 0.7, 0.5]


@pytest.mark.contract
class TestDecodeAndNms:
    @pytest.fixture
    def empty_feat(self):
        return np.zeros((84, 16, 16), dtype=np.int8)

    def test_zero_features_no_detections(self, empty_feat):
        # sigmoid(0) = 0.5 exactly, so use threshold > 0.5 to filter
        out = decode_and_nms(empty_feat, nc=80, grid_h=16, grid_w=16, stride=16,
                             conf_thresh=0.6, iou_thresh=0.45)
        assert out == []

    def test_single_high_confidence_cell(self):
        feat = np.zeros((84, 16, 16), dtype=np.int8)
        # cell (5, 7), class 3, INT8 = 127 -> after scale_factor 1/64 = ~2.0
        # sigmoid(2.0) ≈ 0.88, dominates all sigmoid(0)=0.5 cells
        feat[4 + 3, 7, 5] = 127
        out = decode_and_nms(feat, nc=80, grid_h=16, grid_w=16, stride=16,
                             conf_thresh=0.6, iou_thresh=0.45)
        assert len(out) == 1
        assert out[0].cls == 3
        # bbox centre roughly at (5+0.5, 7+0.5) * stride 16 = (88, 120)
        cx = (out[0].x1 + out[0].x2) / 2.0
        cy = (out[0].y1 + out[0].y2) / 2.0
        assert 70 < cx < 110, cx
        assert 100 < cy < 140, cy

    def test_conf_threshold_filters(self):
        feat = np.zeros((84, 16, 16), dtype=np.int8)
        # sigmoid(0) = 0.5, so a 0-scored cell stays right at 0.5
        feat[4, 0, 0] = 0
        out_high = decode_and_nms(feat, 80, 16, 16, 16,
                                  conf_thresh=0.9, iou_thresh=0.45)
        assert out_high == []
        out_low = decode_and_nms(feat, 80, 16, 16, 16,
                                 conf_thresh=0.1, iou_thresh=0.45)
        assert len(out_low) > 0  # something at sigmoid(0)=0.5 > 0.1
