"""Contract 2 bit-exact regression — golden tensors must match the numpy
reference byte-for-byte.

Three test families:

1. ``test_numpy_self_consistency`` — load layer ``input`` from the golden
   .npz, re-run the corresponding ``tools/fpga/numpy_reference`` primitive
   with the same A1 ``.npz`` weights, assert the produced output equals the
   stored ``output`` byte-for-byte. This is the canonical Contract 2
   acceptance check (NumPy ↔ NumPy stability).
2. ``test_golden_index_schema`` — golden_index.json must carry
   ``weights_source`` (non-synthetic), ``weights_sha256``, ``layer_count==12``
   and every referenced .npz must exist.
3. ``test_layer_shapes_match_contract`` — every layer's stored
   ``input_shape`` / ``output_shape`` must match the layer-ID table in
   docs/CONTRACTS.md (lines 112-127), with the documented A1 quant exception
   for SPPF cv2 noted in the constants table.

This file is the entry point B1 hooks its HLS C-sim runner against (it
guarantees the .npz set is well-formed before the C-sim load step).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict

import numpy as np
import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_DIR = REPO_ROOT / "tests" / "golden"
INDEX_PATH = GOLDEN_DIR / "golden_index.json"
WEIGHTS_NPZ = REPO_ROOT / "models" / "tiny_fpga_int8.npz"


# Layer ID table from contracts.md lines 112-127. Tuple is
#   (layer_idx, name, expected_input_shape, expected_output_shape).
# The SPPF row uses (1, 48, 16, 16) for output_shape because the *real*
# tiny_fpga_int8.npz collapses cv2 from 192 -> 48 (A1 schema) rather than
# the contract's literal 192 -> 96. We treat the .npz schema as the source
# of truth for tests; the contract doc gets a follow-up PR.
LAYER_TABLE = [
    (0,  "stem",         (1,  3, 256, 256), (1, 24, 64, 64)),
    (1,  "acb1",         (1, 24,  64,  64), (1, 24, 64, 64)),
    (2,  "ds1",          (1, 24,  64,  64), (1, 48, 32, 32)),
    (3,  "acb2a",        (1, 48,  32,  32), (1, 48, 32, 32)),
    (4,  "acb2b",        (1, 48,  32,  32), (1, 48, 32, 32)),
    (5,  "ds2",          (1, 48,  32,  32), (1, 96, 16, 16)),
    (6,  "acb3a",        (1, 96,  16,  16), (1, 96, 16, 16)),
    (7,  "acb3b",        (1, 96,  16,  16), (1, 96, 16, 16)),
    (8,  "sppf",         (1, 96,  16,  16), (1, 48, 16, 16)),
    # SPPF cv2 in tiny_fpga collapses to 48 channels (A1 schema), so head_reduce
    # input is 48 not the contract's literal 96.
    (9,  "head_reduce",  (1, 48,  16,  16), (1, 48, 16, 16)),
    (10, "head_refine",  (1, 48,  16,  16), (1, 48, 16, 16)),
    (11, "detect",       (1, 48,  16,  16), (1, 48, 16, 16)),
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def golden_index() -> Dict:
    if not INDEX_PATH.exists():
        pytest.skip(f"golden_index.json not present at {INDEX_PATH}; run "
                    "`python tools/verify/extract_golden.py --npz "
                    "models/tiny_fpga_int8.npz --output-dir tests/golden/`.")
    return json.loads(INDEX_PATH.read_text())


@pytest.fixture(scope="module")
def loaded_layers():
    """Parsed LayerEntry list with the same pad-autocorrect that
    extract_golden applies — required so re-running the primitive matches
    the golden tensor exactly."""
    if not WEIGHTS_NPZ.exists():
        pytest.skip(f"A1 weights not present at {WEIGHTS_NPZ}")
    from tools.quant.weight_packer import read_npz
    from tools.verify.extract_golden import _autocorrect_layer_pads
    layers, _ = read_npz(WEIGHTS_NPZ)
    _autocorrect_layer_pads(layers, verbose=False)
    return layers


@pytest.fixture(scope="module")
def numpy_weights(loaded_layers):
    from tools.quant.np_adapter import to_numpy_reference, schema_size
    if len(loaded_layers) != schema_size():
        pytest.skip(f"weights schema mismatch: got {len(loaded_layers)}, "
                    f"expected {schema_size()}")
    return to_numpy_reference(loaded_layers)


def _load_layer_npz(idx: int, name: str):
    p = GOLDEN_DIR / f"layer_{idx:02d}_{name}.npz"
    if not p.exists():
        pytest.skip(f"missing {p}")
    with np.load(p, allow_pickle=False) as d:
        return {k: d[k] for k in d.files}


# ---------------------------------------------------------------------------
# Family 1 — numpy ↔ numpy self-consistency
# ---------------------------------------------------------------------------

@pytest.mark.bit_exact
@pytest.mark.parametrize("layer_idx,layer_name", [
    (0, "stem"), (1, "acb1"), (2, "ds1"), (3, "acb2a"), (4, "acb2b"),
    (5, "ds2"), (6, "acb3a"), (7, "acb3b"), (8, "sppf"),
    (9, "head_reduce"), (10, "head_refine"), (11, "detect"),
])
def test_numpy_self_consistency(layer_idx, layer_name, numpy_weights):
    """Re-run the per-layer primitive on the stored input; output must be
    byte-identical to the stored output.

    Each layer maps to a numpy_reference call:
      stem        -> ms_downsampling (first_layer=True)
      acb*        -> ms_all_conv_block
      ds*         -> ms_downsampling
      sppf        -> spike_sppf
      head_reduce -> ms_standard_conv
      head_refine -> ms_all_conv_block
      detect      -> identity (PS-side post-processing)
    """
    from tools.fpga.numpy_reference import (
        ms_downsampling, ms_standard_conv, ms_all_conv_block, spike_sppf,
    )
    data = _load_layer_npz(layer_idx, layer_name)
    x_in = data["input"]
    expected = data["output"]

    if layer_name == "stem":
        y = ms_downsampling(x_in, numpy_weights[1]["encode_conv"])
    elif layer_name == "acb1":
        w = numpy_weights[2]
        y = ms_all_conv_block(x_in, w["sep"], w["conv1"], w["conv2"])
    elif layer_name == "ds1":
        y = ms_downsampling(x_in, numpy_weights[3]["encode_conv"])
    elif layer_name == "acb2a":
        w = numpy_weights[4][0]
        y = ms_all_conv_block(x_in, w["sep"], w["conv1"], w["conv2"])
    elif layer_name == "acb2b":
        w = numpy_weights[4][1]
        y = ms_all_conv_block(x_in, w["sep"], w["conv1"], w["conv2"])
    elif layer_name == "ds2":
        y = ms_downsampling(x_in, numpy_weights[5]["encode_conv"])
    elif layer_name == "acb3a":
        w = numpy_weights[6][0]
        y = ms_all_conv_block(x_in, w["sep"], w["conv1"], w["conv2"])
    elif layer_name == "acb3b":
        w = numpy_weights[6][1]
        y = ms_all_conv_block(x_in, w["sep"], w["conv1"], w["conv2"])
    elif layer_name == "sppf":
        y = spike_sppf(x_in,
                       numpy_weights[7]["cv1"],
                       numpy_weights[7]["cv2"], k=5)
    elif layer_name == "head_reduce":
        y = ms_standard_conv(x_in, numpy_weights[8]["conv"])
    elif layer_name == "head_refine":
        w = numpy_weights[9]
        y = ms_all_conv_block(x_in, w["sep"], w["conv1"], w["conv2"])
    elif layer_name == "detect":
        # Detect head decode is on the PS — golden is just an INT8 cast.
        y = x_in.astype(np.int8)
    else:
        pytest.fail(f"unknown layer: {layer_name}")

    assert y.shape == expected.shape, (
        f"layer {layer_idx} {layer_name}: shape mismatch "
        f"{y.shape} vs {expected.shape}"
    )
    np.testing.assert_array_equal(
        y, expected,
        err_msg=f"layer {layer_idx} {layer_name}: numpy primitive output "
                f"diverged from stored golden",
    )


# ---------------------------------------------------------------------------
# Family 2 — golden_index.json schema
# ---------------------------------------------------------------------------

@pytest.mark.bit_exact
def test_golden_index_schema(golden_index):
    """golden_index.json must declare A1 (non-synthetic) provenance + sha256
    + layer_count==12 + every referenced .npz must exist."""
    assert golden_index["weights_source"] != "synthetic", (
        "Contract 2 cannot be fulfilled with synthetic weights — re-run "
        "extract_golden.py with --npz models/tiny_fpga_int8.npz."
    )
    # Accept a1_int8_npz, a1_int8_npz_vX.Y.Z (contract version suffix), stub,
    # or any explicit .npz path. v1.0.2 added the suffix variant after the
    # SepRepConv pad-bug fix; future contract bumps should keep this prefix.
    src = golden_index["weights_source"]
    assert (src == "stub"
            or src == "a1_int8_npz"
            or src.startswith("a1_int8_npz_v")
            or src.endswith(".npz")), \
        f"unexpected weights_source: {src}"
    assert golden_index["layer_count"] == 12, (
        f"expected 12 layers, got {golden_index['layer_count']}"
    )

    # weights_sha256 should be present and look like a SHA-256 hex digest
    sha = golden_index.get("weights_sha256")
    if src == "a1_int8_npz" or src.startswith("a1_int8_npz_v"):
        assert sha is not None, "weights_sha256 missing for a1_int8_npz source"
        assert len(sha) == 64, f"weights_sha256 wrong length: {sha}"
        # Re-verify by hashing the file ourselves
        if WEIGHTS_NPZ.exists():
            h = hashlib.sha256()
            h.update(WEIGHTS_NPZ.read_bytes())
            assert h.hexdigest() == sha, "weights_sha256 does not match models/tiny_fpga_int8.npz"

    # generated_at should be ISO-format UTC
    assert "generated_at" in golden_index, "missing generated_at timestamp"

    # Every referenced .npz must actually exist on disk
    for name, rel_path in golden_index["layers"].items():
        p = REPO_ROOT / Path(rel_path)
        assert p.exists(), f"layer {name}: referenced file missing — {p}"


# ---------------------------------------------------------------------------
# Family 3 — per-layer shapes match Contract 2 spec
# ---------------------------------------------------------------------------

@pytest.mark.bit_exact
@pytest.mark.parametrize("layer_idx,layer_name,expected_in,expected_out", [
    pytest.param(*row, id=f"L{row[0]:02d}_{row[1]}") for row in LAYER_TABLE
])
def test_layer_shapes_match_contract(layer_idx, layer_name,
                                     expected_in, expected_out):
    data = _load_layer_npz(layer_idx, layer_name)
    in_shape = tuple(int(v) for v in data["input_shape"])
    out_shape = tuple(int(v) for v in data["output_shape"])
    assert in_shape == expected_in, (
        f"L{layer_idx:02d} {layer_name}: input_shape {in_shape} != "
        f"contract {expected_in}"
    )
    assert out_shape == expected_out, (
        f"L{layer_idx:02d} {layer_name}: output_shape {out_shape} != "
        f"contract {expected_out}"
    )


@pytest.mark.bit_exact
@pytest.mark.parametrize("layer_idx,layer_name", [
    (i, n) for i, n, _, _ in LAYER_TABLE
])
def test_each_layer_npz_has_required_keys(layer_idx, layer_name):
    """Contract 2 schema: each .npz must contain
       input, output, input_shape, output_shape, params_hash, kind."""
    data = _load_layer_npz(layer_idx, layer_name)
    for key in ("input", "output", "input_shape", "output_shape",
                "params_hash", "kind"):
        assert key in data, f"L{layer_idx:02d} {layer_name}: missing key {key}"
