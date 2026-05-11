"""Tests for sw/app/reference/preproc_ref.py — keeps the Python reference in
sync with the C++ implementation."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

# Add the C3 app reference dir to import path
APP_REF = Path(__file__).resolve().parent.parent / "sw" / "app" / "reference"
sys.path.insert(0, str(APP_REF))

from preproc_ref import (         # noqa: E402
    Letterbox, plan_letterbox, letterbox_rgb_to_int8_chw,
    unletterbox_bbox, yuyv_to_rgb888,
)


@pytest.mark.contract
class TestPlanLetterbox:
    def test_square_no_padding(self):
        lb = plan_letterbox(256, 256, 256, 256)
        assert lb.scale == 1.0
        assert lb.pad_x == 0 and lb.pad_y == 0

    def test_landscape_vertical_padding(self):
        # 640x480 source: scale = min(256/480, 256/640) = 256/640 = 0.4
        # new_h = round(480 * 0.4) = 192, new_w = 256, pad_y = 32, pad_x = 0
        lb = plan_letterbox(480, 640)
        assert lb.scale == pytest.approx(256 / 640)
        assert lb.pad_y == 32
        assert lb.pad_x == 0

    def test_portrait_horizontal_padding(self):
        lb = plan_letterbox(640, 480)
        assert lb.scale == pytest.approx(256 / 640)
        assert lb.pad_x == 32
        assert lb.pad_y == 0


@pytest.mark.contract
class TestLetterboxOutput:
    def test_output_shape_and_dtype(self):
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        lb = plan_letterbox(480, 640)
        out = letterbox_rgb_to_int8_chw(img, lb)
        assert out.shape == (3, 256, 256)
        assert out.dtype == np.int8

    def test_fill_borders_with_grey_minus_128(self):
        """Top/bottom bands must equal 114 - 128 = -14."""
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        lb = plan_letterbox(480, 640)
        out = letterbox_rgb_to_int8_chw(img, lb)
        # rows [0..pad_y) should all be fill = -14 in all channels
        for c in range(3):
            assert (out[c, :lb.pad_y, :] == -14).all()
            assert (out[c, lb.pad_y + int(round(lb.src_h * lb.scale)):, :] == -14).all()

    def test_centre_pixel_round_trip(self):
        """A uniform-coloured source becomes that colour (-128) in centre."""
        img = np.full((480, 640, 3), 200, dtype=np.uint8)  # mid-bright
        lb = plan_letterbox(480, 640)
        out = letterbox_rgb_to_int8_chw(img, lb)
        # at centre row of filled region
        cy = lb.pad_y + int(round(lb.src_h * lb.scale)) // 2
        assert out[0, cy, lb.dst_w // 2] == np.int8(200 - 128)


@pytest.mark.contract
class TestUnletterbox:
    def test_inverse_recovers_full_image(self):
        lb = plan_letterbox(480, 640)
        # bbox in 256-space exactly covering the letterboxed image:
        x1, y1, x2, y2 = unletterbox_bbox(
            lb, lb.pad_x, lb.pad_y,
                lb.pad_x + 256 - 2 * lb.pad_x,
                lb.pad_y + 256 - 2 * lb.pad_y,
        )
        # Should map back to ~(0, 0, src_w-1, src_h-1)
        assert x1 == pytest.approx(0.0, abs=1.0)
        assert y1 == pytest.approx(0.0, abs=1.0)
        assert x2 == pytest.approx(lb.src_w - 1, abs=1.0)
        assert y2 == pytest.approx(lb.src_h - 1, abs=1.0)

    def test_clipping_inside_bounds(self):
        lb = plan_letterbox(480, 640)
        # negative box must clip to 0
        x1, y1, x2, y2 = unletterbox_bbox(lb, -50, -50, 100, 100)
        assert x1 == 0.0
        assert y1 == 0.0
        assert x2 >= 0.0 and y2 >= 0.0


@pytest.mark.contract
class TestYUYV:
    def test_grey_yuyv_is_neutral(self):
        # YUYV grey: Y=128, U=128, V=128 means RGB ≈ ((298*112)>>8) ≈ 130
        src_h, src_w = 2, 4
        yuyv = np.full((src_h * src_w * 2,), 128, dtype=np.uint8)
        rgb = yuyv_to_rgb888(yuyv, src_h, src_w)
        assert rgb.shape == (src_h, src_w, 3)
        # tight tolerance — formula rounding only
        assert (np.abs(rgb.astype(int) - 130) <= 2).all()
