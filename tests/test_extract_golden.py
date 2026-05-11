"""Integration tests for tools.verify.extract_golden.

Verify:
* synth_weights produces a numpy_reference-compatible dict
* trace_forward runs without exception on the synthetic weights
* every yaml-node emits a layer_*.npz with the expected schema
* each .npz includes input/output/kind/params_hash and the meta.json sibling
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from tools.verify.extract_golden import (
    LAYER_NAMES, hash_weights_dict, save_layer,
    synth_weights, trace_forward,
)


# Layer count expected after trace (12 nodes including detect)
EXPECTED_LAYER_COUNT = 12


@pytest.fixture(scope="module")
def weights():
    return synth_weights(seed=0)


@pytest.fixture(scope="module")
def golden_dir(weights, tmp_path_factory):
    """Run trace_forward once at 256x256 (slow, ~20 s on plain NumPy)."""
    out_dir = tmp_path_factory.mktemp("golden")
    rng = np.random.default_rng(1)
    img = rng.integers(-128, 127, size=(3, 256, 256), dtype=np.int8)
    paths = trace_forward(weights, img, out_dir)
    return out_dir, paths


# Tests that depend on the trace_forward fixture get @slow so plain
# `pytest tests/` (used in numpy_regress.yml fast path) skips them. CI
# opts in via `pytest -m "contract or slow"`.
pytestmark = pytest.mark.slow


# -----------------------------------------------------------------------------
# Sanity on the synthetic weight dictionary
# -----------------------------------------------------------------------------

@pytest.mark.contract
def test_synth_weights_yaml_node_keys(weights):
    """numpy_reference expects yaml node indices 1..9."""
    assert set(weights.keys()) == set(range(1, 10))


@pytest.mark.contract
def test_synth_weights_acb_lists_have_two_subblocks(weights):
    """yaml nodes 4 and 6 must be lists of length 2 (depth=2 AllConvBlocks)."""
    assert isinstance(weights[4], list) and len(weights[4]) == 2
    assert isinstance(weights[6], list) and len(weights[6]) == 2


@pytest.mark.contract
def test_hash_weights_is_deterministic(weights):
    h1 = hash_weights_dict(weights)
    h2 = hash_weights_dict(weights)
    assert h1 == h2
    # different seed => different hash
    other = synth_weights(seed=99)
    assert hash_weights_dict(other) != h1


# -----------------------------------------------------------------------------
# Trace forward
# -----------------------------------------------------------------------------

@pytest.mark.contract
def test_trace_produces_all_layers(golden_dir):
    out_dir, paths = golden_dir
    assert len(paths) == EXPECTED_LAYER_COUNT
    expected_names = {n for n, _ in LAYER_NAMES}
    assert set(paths.keys()) == expected_names


@pytest.mark.contract
def test_each_layer_npz_has_required_keys(golden_dir):
    out_dir, paths = golden_dir
    for name, path in paths.items():
        with np.load(path, allow_pickle=False) as data:
            for key in ("input", "output", "input_shape", "output_shape",
                        "params_hash", "kind"):
                assert key in data.files, f"{name} missing key {key}"


@pytest.mark.contract
def test_layer_meta_json_matches_npz(golden_dir):
    out_dir, paths = golden_dir
    for name, npz_path in paths.items():
        meta_path = npz_path.with_suffix("").with_suffix(".meta.json")
        meta = json.loads(meta_path.read_text())
        with np.load(npz_path) as data:
            assert list(data["input"].shape) == meta["input"]["shape"]
            assert list(data["output"].shape) == meta["output"]["shape"]
            assert str(data["input"].dtype) == meta["input"]["dtype"]
            assert str(data["output"].dtype) == meta["output"]["dtype"]


@pytest.mark.contract
def test_stem_input_shape(golden_dir):
    """Layer 00 'stem' input must be (1, 3, 256, 256) int8."""
    out_dir, paths = golden_dir
    with np.load(paths["stem"]) as data:
        assert tuple(data["input"].shape) == (1, 3, 256, 256)
        assert data["input"].dtype == np.int8


@pytest.mark.contract
def test_backbone_output_shrinks_spatially(golden_dir):
    """As we descend the backbone, H and W should halve at each DownSampling."""
    out_dir, paths = golden_dir
    # stem -> 64x64, ds1 -> 32x32, ds2 -> 16x16
    with np.load(paths["stem"]) as d:
        assert d["output"].shape[-2:] == (64, 64)
    with np.load(paths["ds1"]) as d:
        assert d["output"].shape[-2:] == (32, 32)
    with np.load(paths["ds2"]) as d:
        assert d["output"].shape[-2:] == (16, 16)


@pytest.mark.contract
def test_layer_outputs_are_deterministic_with_seed(weights, tmp_path):
    """Re-running trace_forward with same inputs gives byte-identical .npz."""
    rng_a = np.random.default_rng(1)
    rng_b = np.random.default_rng(1)
    img_a = rng_a.integers(-128, 127, size=(3, 256, 256), dtype=np.int8)
    img_b = rng_b.integers(-128, 127, size=(3, 256, 256), dtype=np.int8)
    a = tmp_path / "a"
    b = tmp_path / "b"
    paths_a = trace_forward(weights, img_a, a)
    paths_b = trace_forward(weights, img_b, b)
    for name in paths_a:
        with np.load(paths_a[name]) as da, np.load(paths_b[name]) as db:
            np.testing.assert_array_equal(da["output"], db["output"])
            np.testing.assert_array_equal(da["input"], db["input"])


# -----------------------------------------------------------------------------
# np_adapter schema sanity
# -----------------------------------------------------------------------------

@pytest.mark.contract
def test_np_adapter_schema_size():
    """tiny_fpga has 37 Conv2d entries in the PyTorch-derived schema:
       1 stem + 6 acb1 + 1 ds1 + 6 acb2 + 1 ds2 + 6 acb3
       + 2 sppf + 1 head_reduce + 6 head_refine + 7 detect head."""
    from tools.quant.np_adapter import schema_size
    assert schema_size() == 37


@pytest.mark.contract
def test_np_adapter_rejects_wrong_length():
    from tools.quant.np_adapter import to_numpy_reference
    with pytest.raises(ValueError, match="expected 37 LayerEntry"):
        to_numpy_reference([])
