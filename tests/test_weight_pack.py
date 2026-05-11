"""Contract 1: weight packing roundtrip + cross-layout consistency tests.

Pure NumPy — no PyTorch required. Constructs synthetic quantized layers
that match the tiny_fpga topology (stem + 2 conv blocks + detect head)
so the suite is realistic without depending on a trained .pt.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from tools.quant.weight_packer import (
    CI_TILE, CO_TILE, KIND_TO_ENUM,
    LayerEntry,
    from_pe_tile, to_pe_tile,
    read_bin, write_bin,
    read_npz, write_npz,
    validate,
)


# -----------------------------------------------------------------------------
# Synthetic layer factory (deterministic via rng seed)
# -----------------------------------------------------------------------------

def _mk_layer(idx: int, kind: str, c_in: int, c_out: int, k: int,
              stride: int = 1, pad: int = 0, groups: int = 1,
              first_layer: bool = False, seed: int = 0) -> LayerEntry:
    rng = np.random.default_rng(seed + idx)
    w = rng.integers(-127, 127, size=(c_out, c_in // groups, k, k), dtype=np.int8)
    bias = rng.integers(-100_000, 100_000, size=(c_out,), dtype=np.int32)
    shift = rng.integers(0, 24, size=(c_out,), dtype=np.int8)
    return LayerEntry(
        idx=idx, kind=kind, w=w, bias=bias, out_shift=shift,
        stride=stride, pad=pad, groups=groups, first_layer=first_layer,
    )


@pytest.fixture
def tiny_layers():
    """A miniature 4-layer 'tiny_fpga lite' model used by every test below."""
    return [
        # stem-ish: 3 -> 24, kernel 7, stride 4, first_layer
        _mk_layer(0, "ms_downsample", 3, 24, 7, stride=4, pad=2,
                  first_layer=True, seed=42),
        # acb1 pointwise expansion 24 -> 48
        _mk_layer(1, "conv2d_bn", 24, 48, 1, stride=1, pad=0, seed=43),
        # DW conv  groups == c_in == c_out
        _mk_layer(2, "conv2d_bn", 48, 48, 7, stride=1, pad=3, groups=48, seed=44),
        # detect head 1x1 channels-not-multiple-of-tile (97 -> 84) to test padding
        _mk_layer(3, "detect", 97, 84, 1, stride=1, pad=0, seed=45),
    ]


# -----------------------------------------------------------------------------
# PE-tile reshape primitive
# -----------------------------------------------------------------------------

@pytest.mark.contract
class TestPeTile:
    def test_to_from_roundtrip(self):
        rng = np.random.default_rng(0)
        for c_out, c_in in [(16, 8), (24, 3), (97, 17), (84, 96)]:
            w = rng.integers(-127, 127, size=(c_out, c_in, 3, 3), dtype=np.int8)
            tile = to_pe_tile(w)
            back = from_pe_tile(tile, c_out, c_in)
            np.testing.assert_array_equal(w, back)

    def test_tile_shape(self):
        w = np.zeros((24, 3, 7, 7), dtype=np.int8)
        tile = to_pe_tile(w)
        co_outer = (24 + CO_TILE - 1) // CO_TILE
        ci_outer = (3 + CI_TILE - 1) // CI_TILE
        assert tile.shape == (co_outer, ci_outer, 7, 7, CO_TILE, CI_TILE)

    def test_padding_is_zero(self):
        rng = np.random.default_rng(1)
        w = rng.integers(-127, 127, size=(20, 5, 3, 3), dtype=np.int8)
        tile = to_pe_tile(w)
        # Padding slots: co indices 20..31 and ci indices 5..7 must be zero
        assert tile.shape[4] == CO_TILE and tile.shape[5] == CI_TILE
        co_outer_last = tile.shape[0] - 1
        ci_outer_last = tile.shape[1] - 1
        # Co padding lives in co_outer_last when 20 % 16 = 4 -> co_tile indices 4..15
        assert (tile[co_outer_last, :, :, :, 4:, :] == 0).all()
        # Ci padding: 5 % 8 = 5 -> ci_tile indices 5..7
        assert (tile[:, ci_outer_last, :, :, :, 5:] == 0).all()


# -----------------------------------------------------------------------------
# .npz roundtrip
# -----------------------------------------------------------------------------

@pytest.mark.contract
class TestNpz:
    def test_pack_unpack_roundtrip_standard(self, tiny_layers, tmp_path):
        path = tmp_path / "tiny_std.npz"
        write_npz(tiny_layers, path, layout="standard")
        loaded, layout = read_npz(path)
        assert layout == "standard"
        assert len(loaded) == len(tiny_layers)
        for orig, got in zip(tiny_layers, loaded):
            np.testing.assert_array_equal(orig.w, got.w)
            np.testing.assert_array_equal(orig.bias, got.bias)
            np.testing.assert_array_equal(orig.out_shift, got.out_shift)
            assert orig.stride == got.stride
            assert orig.pad == got.pad
            assert orig.groups == got.groups
            assert orig.first_layer == got.first_layer
            assert orig.kind == got.kind

    def test_pack_unpack_roundtrip_pe_tile(self, tiny_layers, tmp_path):
        path = tmp_path / "tiny_tile.npz"
        write_npz(tiny_layers, path, layout="pe_tile")
        loaded, layout = read_npz(path)
        assert layout == "pe_tile"
        for orig, got in zip(tiny_layers, loaded):
            np.testing.assert_array_equal(orig.w, got.w)

    def test_layout_independence(self, tiny_layers, tmp_path):
        """Standard and pe_tile .npz must dequantize to the same weights."""
        std_path = tmp_path / "std.npz"
        tile_path = tmp_path / "tile.npz"
        write_npz(tiny_layers, std_path, layout="standard")
        write_npz(tiny_layers, tile_path, layout="pe_tile")
        std_layers, _ = read_npz(std_path)
        tile_layers, _ = read_npz(tile_path)
        for a, b in zip(std_layers, tile_layers):
            np.testing.assert_array_equal(a.w, b.w)


# -----------------------------------------------------------------------------
# .bin roundtrip (board-side blob)
# -----------------------------------------------------------------------------

@pytest.mark.contract
class TestBin:
    def test_bin_roundtrip(self, tiny_layers, tmp_path):
        path = tmp_path / "tiny.bin"
        write_bin(tiny_layers, path, layout="pe_tile")
        loaded = read_bin(path)
        assert len(loaded) == len(tiny_layers)
        for orig, got in zip(tiny_layers, loaded):
            np.testing.assert_array_equal(orig.w, got.w)
            np.testing.assert_array_equal(orig.bias, got.bias)
            np.testing.assert_array_equal(orig.out_shift, got.out_shift)
            assert orig.idx == got.idx
            assert orig.kind == got.kind
            assert orig.stride == got.stride and orig.pad == got.pad
            assert orig.groups == got.groups
            assert orig.first_layer == got.first_layer

    def test_bin_is_16_byte_aligned(self, tiny_layers, tmp_path):
        path = tmp_path / "tiny.bin"
        write_bin(tiny_layers, path)
        assert path.stat().st_size % 16 == 0

    def test_bin_byte_identical_across_runs(self, tiny_layers, tmp_path):
        """Deterministic write: same input -> byte-identical output."""
        p1 = tmp_path / "a.bin"
        p2 = tmp_path / "b.bin"
        write_bin(tiny_layers, p1)
        write_bin(tiny_layers, p2)
        assert p1.read_bytes() == p2.read_bytes()


# -----------------------------------------------------------------------------
# Validate
# -----------------------------------------------------------------------------

@pytest.mark.contract
class TestValidate:
    def test_validate_clean(self, tiny_layers, tmp_path):
        path = tmp_path / "ok.npz"
        write_npz(tiny_layers, path)
        assert validate(path) == []

    def test_validate_catches_duplicate_idx(self, tiny_layers, tmp_path):
        bad = list(tiny_layers)
        bad.append(LayerEntry(
            idx=bad[0].idx,    # duplicate!
            kind="conv2d_bn",
            w=np.zeros((4, 4, 1, 1), dtype=np.int8),
            bias=np.zeros(4, dtype=np.int32),
            out_shift=np.zeros(4, dtype=np.int8),
            stride=1, pad=0, groups=1, first_layer=False,
        ))
        path = tmp_path / "dup.npz"
        write_npz(bad, path)
        errs = validate(path)
        assert any("duplicate" in e for e in errs), errs


# -----------------------------------------------------------------------------
# CLI smoke
# -----------------------------------------------------------------------------

@pytest.mark.contract
def test_cli_smoke(tiny_layers, tmp_path):
    """Verify the CLI entry point at least exits 0 on the happy path."""
    from tools.quant.weight_packer import main as packer_main

    src = tmp_path / "src.npz"
    out_std = tmp_path / "out_std.npz"
    out_tile = tmp_path / "out_tile.npz"
    out_bin = tmp_path / "out.bin"
    write_npz(tiny_layers, src, layout="standard")

    assert packer_main(["pack", "--input", str(src), "--output", str(out_std),
                        "--layout", "standard"]) == 0
    assert packer_main(["pack", "--input", str(src), "--output", str(out_tile),
                        "--layout", "pe_tile"]) == 0
    assert packer_main(["to-bin", "--input", str(out_tile),
                        "--output", str(out_bin)]) == 0
    assert packer_main(["validate", "--input", str(out_std)]) == 0
