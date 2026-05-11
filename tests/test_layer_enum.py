"""Cross-language enum sync: dtypes.h SA_KIND_* must agree with
``tools.quant.weight_packer.KIND_TO_ENUM``.

This catches the classic foot-gun where one side adds a kind and the other
forgets, then board-side decodes a layer as the wrong type.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tools.quant.weight_packer import KIND_TO_ENUM


HLS_DTYPES = Path(__file__).resolve().parent.parent / "hw" / "hls" / "include" / "dtypes.h"


# Mapping table — the canonical Python names → C macro names. Keep alphabetical
# by Python key for readability; failure messages show full diffs.
_PY_TO_C = {
    "conv2d_bn":     "SA_KIND_CONV2D_BN",
    "ms_downsample": "SA_KIND_MS_DOWN",
    "sep_conv":      "SA_KIND_SEP_CONV",
    "ms_standard":   "SA_KIND_MS_STANDARD",
    "maxpool":       "SA_KIND_MAXPOOL",
    "sppf":          "SA_KIND_SPPF",
    "detect":        "SA_KIND_DETECT",
}


def _parse_c_macros(path: Path) -> dict:
    """Pull `#define SA_KIND_FOO <int>` lines out of dtypes.h."""
    pat = re.compile(r"#define\s+(SA_KIND_\w+)\s+(\d+)\b")
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = pat.search(line)
        if m:
            out[m.group(1)] = int(m.group(2))
    return out


@pytest.mark.contract
def test_python_and_c_kind_enums_match():
    c_macros = _parse_c_macros(HLS_DTYPES)

    # 1. Same set of kinds on both sides
    expected_c = set(_PY_TO_C.values())
    actual_c = set(c_macros.keys())
    assert expected_c == actual_c, (
        f"C side mismatch — missing: {expected_c - actual_c}  "
        f"extra: {actual_c - expected_c}"
    )

    # 2. Same numeric values
    for py_name, c_name in _PY_TO_C.items():
        py_val = KIND_TO_ENUM[py_name]
        c_val = c_macros[c_name]
        assert py_val == c_val, (
            f"enum value mismatch for {py_name!r}: "
            f"python={py_val}  C({c_name})={c_val}"
        )


@pytest.mark.contract
def test_python_enum_covers_known_kinds():
    """Sanity: KIND_TO_ENUM has no surprise entries beyond the contract."""
    expected_py = set(_PY_TO_C.keys())
    actual_py = set(KIND_TO_ENUM.keys())
    assert expected_py == actual_py, (
        f"Python KIND_TO_ENUM diverged from cross-lang table: "
        f"missing={expected_py - actual_py}  extra={actual_py - expected_py}"
    )
