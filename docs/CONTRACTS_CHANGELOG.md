# Contracts Changelog

Track every change to `docs/CONTRACTS.md` and its associated `tests/test_contract_<n>.py`.

Format per entry:

```
## YYYY-MM-DD — vX.Y.Z
- **Contract N (Agent X → Agent Y)**: <one-line summary of change>
  - Motivation: <why>
  - Migration: <what downstream Agents need to update>
  - PR: #<number>
```

---

## 2026-05-11 — v1.0.0 (initial)
- **Contract 1** A1 → B1: weight `.npz` PE-tile packing schema locked
- **Contract 2** A2 → B1: per-layer golden tensor format locked
- **Contract 3** B1 → B2: IP regmap.yaml + AXI-Stream packing locked
- **Contract 4** B2 → C2: address_map.yaml + dts generator locked
- **Contract 5** C2 → C3: SDK C API + ABI v1.0 locked
- **Contract 6** A2 → C3/D1: COCO val100 baseline JSON locked
- PR: (initial commit)

## 2026-05-11 — v1.0.1 (A1 W3 layer-table correction)
- **Contract 2** A2 → B1: layer table L122-127 corrected to match the real
  PyTorch model channel widths under `tiny_fpga` scaling
  (width=0.1875, max_channels=256). Previous values were derived from
  pre-scaled yaml args and were off for SPPF and head-reduce.
  - layer_08_sppf:        `(96,16,16) -> (192,16,16)` → `(96,16,16) -> (48,16,16)`
    (SpikeSPPF.cv2 emits `make_divisible(min(512,256)*0.1875, 8) = 48`, not 192)
  - layer_09_head_reduce: `(192,16,16) -> (48,16,16)` → `(48,16,16) -> (48,16,16)`
    (input is SPPF output = 48; MS_StandardConv 1×1 with c2_arg=256 → 48)
  - Motivation: A2 sprint W2 found the actual `models/tiny_fpga_int8.npz`
    schema (192→48 for SPPF cv2) disagreed with the contract literal
    (192→96). Verified ground truth by walking the real PyTorch
    `tiny_fpga_fp32.pt` — A1 .npz is correct, contract was wrong.
  - Migration: A2's `LAYER_TABLE` in `tools/verify/extract_golden.py`
    already aligned to .npz reality; no further change needed there.
    B1 should consume the corrected channel widths from this updated
    contract when sizing HLS test buffers.

## 2026-05-11 — v1.0.2 (A1 W3 weight regeneration)
- **Contract 1** A1 → B1: `models/tiny_fpga_int8.npz` regenerated after
  fixing the SepRepConv inner-3×3-dwconv pad bug
  (L04/L11/L18/L27 now emit `pad=1` instead of `pad=0`).
  - Schema unchanged; only on-disk values changed.
  - Old sha256: `f016875b...cbc903b4`
  - New sha256: `d5385c05de1930d05d08202c96d4ae681db904c3d97ea19047f524ce8baa365a`
  - Migration: A2 should regenerate golden tensors via
    `tools/verify/extract_golden.py` *without* `--no-autocorrect-pad`
    once the new `.npz` lands in the repo, so
    `pad_autocorrected: false` is recorded in `golden_index.json`.
