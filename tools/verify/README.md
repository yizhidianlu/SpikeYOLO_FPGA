# tools/verify — Three-way bit-exact verification (A2 Agent)

**Owner**: A2 Bit-Exact Reference Agent — see [`docs/AGENT_PLAYBOOKS/A2_bit_exact_reference.md`](../../docs/AGENT_PLAYBOOKS/A2_bit_exact_reference.md)

## Purpose

Ensure **PyTorch ↔ NumPy ↔ HLS C-sim** produce byte-identical outputs at every layer. Extract per-layer golden tensors (Contract 2) and COCO val100 baseline (Contract 6).

## Layout

```
torch_vs_numpy.py         PyTorch model ↔ tools/fpga/numpy_reference.py
numpy_vs_hls.py           NumPy ↔ HLS C-sim output binary blob
extract_golden.py         Dump per-layer input/output to tests/golden/layer_*.npz
gen_coco_val100.py        Generate tests/golden/coco_val100.json (Contract 6)
hooks.py                  Layer hooks shared by all verifiers
```

## Usage

```bash
# Three-way alignment on a single image (debug)
python torch_vs_numpy.py \
    --pt ../../models/tiny_fpga_fp32_retrained.pt \
    --npz ../../models/tiny_fpga_int8.npz \
    --img ../../tests/fixtures/sample.jpg \
    --layer-wise --dump ../../tests/golden/

# HLS comparison
python numpy_vs_hls.py \
    --layer 0 \
    --hls-output ../../hw/hls/build/csim_layer_00_out.bin \
    --golden ../../tests/golden/layer_00_stem.npz

# Generate COCO val100 baseline
python gen_coco_val100.py \
    --val-dir ../../datasets/coco/val2017 \
    --weights ../../models/tiny_fpga_int8.npz \
    --num 100 \
    --output ../../tests/golden/coco_val100.json
```

## Contracts produced

- **C2**: `tests/golden/layer_{00..11}_*.npz` → B1
- **C6**: `tests/golden/coco_val100.json` → C3, D1

## Acceptance gates

- PyTorch ↔ NumPy max abs diff = 0 (INT domain) on all 11 layers × 100 images
- HLS ↔ NumPy 100% match (C-sim binary compare)

## References

- [`tools/fpga/numpy_reference.py`](../fpga/numpy_reference.py) — master golden source
- [`docs/CONTRACTS.md`](../../docs/CONTRACTS.md) — Contracts 2 and 6
