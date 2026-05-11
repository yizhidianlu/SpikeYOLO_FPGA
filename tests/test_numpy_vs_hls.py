"""Unit tests for tools.verify.numpy_vs_hls.

We synthesise small int32 tensors, write them out in both .npz and .bin
forms, then verify compare() flags matches/mismatches correctly.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from tools.verify.numpy_vs_hls import (
    compare, load_golden, load_hls_output, main as nv_main,
)


@pytest.fixture
def synth_pair(tmp_path):
    rng = np.random.default_rng(0)
    shape = (1, 24, 8, 8)
    g = rng.integers(-1000, 1000, size=shape, dtype=np.int32)
    g_path = tmp_path / "layer_00_stem.npz"
    np.savez(g_path, output=g)
    h_path = tmp_path / "layer_00_stem.bin"
    h_path.write_bytes(g.tobytes())
    return g, g_path, h_path


@pytest.mark.contract
def test_load_golden_npz(synth_pair):
    g, g_path, _ = synth_pair
    loaded = load_golden(g_path)
    np.testing.assert_array_equal(loaded, g)


@pytest.mark.contract
def test_load_hls_bin(synth_pair):
    g, _, h_path = synth_pair
    loaded = load_hls_output(h_path, dtype=np.int32, shape=g.shape)
    np.testing.assert_array_equal(loaded, g)


@pytest.mark.contract
def test_compare_match(synth_pair):
    g, _, h_path = synth_pair
    h = load_hls_output(h_path, dtype=np.int32, shape=g.shape)
    result = compare(g, h)
    assert result["ok"] is True
    assert result["max_abs_diff"] == 0


@pytest.mark.contract
def test_compare_shape_mismatch():
    a = np.zeros((4, 4), dtype=np.int32)
    b = np.zeros((5, 5), dtype=np.int32)
    result = compare(a, b)
    assert not result["ok"]
    assert "shape" in result["reason"]


@pytest.mark.contract
def test_compare_element_mismatch():
    a = np.arange(16, dtype=np.int32).reshape(4, 4)
    b = a.copy()
    b[2, 1] = 999
    b[3, 3] = -7
    result = compare(a, b)
    assert not result["ok"]
    assert result["n_mismatches"] == 2
    assert result["max_abs_diff"] >= abs(999 - a[2, 1])
    assert len(result["first_mismatches"]) == 2


@pytest.mark.contract
def test_cli_writes_report(tmp_path, synth_pair):
    g, g_path, h_path = synth_pair
    report = tmp_path / "diff.json"
    rc = nv_main([
        "--golden", str(g_path),
        "--hls-output", str(h_path),
        "--dtype", "int32",
        "--shape", ",".join(str(s) for s in g.shape),
        "--report", str(report),
    ])
    assert rc == 0
    payload = json.loads(report.read_text())
    assert payload["ok"] is True
