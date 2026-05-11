# tests/ — Project-wide regression suite

**Owner**: D1 (regression + golden) + each Agent for their own contract tests

## Layout

```
test_bit_exact.py             A2: PyTorch ↔ NumPy ↔ HLS three-way (Contract 2)
test_weight_pack.py           A1: Python ↔ C++ packer byte-identical (Contract 1)
test_address_map.py           B2/C2: address_map.yaml validity + dts regenerable (Contract 4)
test_cosim.py                 B1: HLS C-sim ↔ Co-sim consistency
test_api_contract.py          C2: SDK API conformance (Contract 5)
golden/                       Per-layer + COCO val100 baselines
  layer_00_stem.npz
  layer_01_acb1.npz
  ...
  layer_11_detect.npz
  coco_val100.json
fixtures/                     Small sample images for unit tests
regression/                   End-to-end runners
  run_full.sh
  coco_val_on_board.py
perf/                         Performance benchmarks
  fps_bench.py
```

## Running

```bash
# All Python tests (PC side)
pytest tests/ -v

# Only contract tests
pytest tests/ -m contract

# End-to-end including board
bash tests/regression/run_full.sh --full
```

## Conventions

- Every contract has exactly one `tests/test_contract_<n>.py` — don't fragment across files
- Golden tensors live in LFS (size > 5 MB)
- Mark slow board tests with `@pytest.mark.board` so CI can skip on PC
- Mark cosim tests with `@pytest.mark.cosim` (slow, opt-in via label `cosim`)

## CI integration

- `numpy_regress.yml`: runs all PC-side tests
- `hls_smoke.yml`: runs `test_cosim.py` after `vitis_hls run_csim.tcl`
- `board_nightly.yml`: runs `regression/run_full.sh --full`

## References

- [`docs/CONTRACTS.md`](../docs/CONTRACTS.md) — every contract's verification commands
- [`docs/AGENT_PLAYBOOKS/D1_verification.md`](../docs/AGENT_PLAYBOOKS/D1_verification.md)
