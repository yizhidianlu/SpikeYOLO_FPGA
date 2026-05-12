# B1 HLS Kernel — Build & Verification Guide

**Owner**: B1 HLS Kernel Agent — see [`docs/AGENT_PLAYBOOKS/B1_hls_kernel.md`](../../docs/AGENT_PLAYBOOKS/B1_hls_kernel.md)
**Target**: Vitis HLS 2024.1 / Z-7020 (`xc7z020clg400-1`) / 100 MHz (M4) -> 150 MHz (M5)
**Status (W4)**: 12 layers end-to-end host_csim `DUT vs GOLDEN OK 12288 elems byte-identical`.

## TL;DR (self-hosted Vivado runner)

The eight steps below are the **canonical zero-friction path**. After D2 cuts
`hls_smoke.yml` over to the self-hosted runner, CI replays them verbatim.

```bash
# 1. Environment (one-time per runner).
source /opt/Xilinx/Vitis_HLS/2024.1/settings64.sh
conda activate spikeyolo

# 2. Dependencies: Digilent IP repo + explode .npz golden / weights.
bash hw/vivado/scripts/setup_ip_repo.sh
python tools/ci/explode_npz.py --all                     # tests/golden/*.npz
python tools/ci/explode_npz.py models/tiny_fpga_int8.npz \
    --out-dir models/exploded                            # weight banks

# 3. host_csim (no Vitis required, ~30 s total — sanity baseline, W4 PASS).
make -C hw/hls host_csim_layer_00 host_csim_layer_01 host_csim_layer_03 \
                host_csim_layer_08 host_csim_layer_11 host_csim_top

# 4. Real vitis_hls C-sim (~5 min, iterates all 10 (top, tb) pairs).
cd hw/hls && vitis_hls -f run_csim.tcl

# 5. Co-sim (RTL + tb, ~10 min/op — gate only on PR label `cosim`).
vitis_hls -f run_cosim.tcl

# 6. Synthesis + report aggregation (~25 min — emits .xo + reports/).
vitis_hls -f run_synth.tcl

# 7. RISK_RULES gate (R1 timing / R2 resource).
python tools/ci/check_utilization.py hw/hls/reports/utilization.rpt
python tools/ci/check_timing.py      hw/hls/reports/timing.csv

# 8. Hand off the .xo + regmap to B2.
cp hw/hls/build/sa_tiny_fpga_top.xo  hw/vivado/ip_repo/spike_accel/
cp hw/hls/build/tiny_fpga_regmap.yaml hw/vivado/ip_repo/spike_accel/
```

## Resource & Timing Budget (M4 target @ 100 MHz)

Paper estimate based on the leaf-kernel dominant model (layers run serially
through DDR-resident scratch buffers; on-chip cost = single largest leaf).

| Resource    | Current estimate | Z-7020 budget | Utilisation |
|-------------|------------------|---------------|-------------|
| DSP48E1     | 64               | 220           | ~29% (cap 70%)  |
| BRAM36      | 32 KB on-chip    | 560 KB        | ~6%  (cap 75%)  |
| LUT         | ~6 K             | 53.2 K        | ~11% (cap 60%)  |
| FF          | <60 K            | 106 K         | <57%            |
| WNS         | TBD (W5 run)     | >= 0 ns @ 10 ns | gate via R1   |

The 28 MB scratch (`sa..sf` + `spike_buf` + `acc_buf` + 5x SPPF) lives in DDR3
via `m_axi`, not BRAM. M5 ping-pong refactor will pull a working tile on-chip.

## Layer pipeline (numpy_reference.py order)

The dispatcher `sa_tiny_fpga_top` (290 LoC) chains the 12 layers via DDR-resident
scratch buffers `sa..sf`, mirroring `tools/fpga/numpy_reference.py:TinyFpgaNet`.

| idx | name           | kernel(s)                                  | output shape    |
|-----|----------------|--------------------------------------------|-----------------|
| 00  | stem           | `sa_ms_downsampling`                       | [1, 24, 32, 32] |
| 01  | acb1           | `sa_ms_all_conv_block` (1 sub-block)       | [1, 24, 32, 32] |
| 02  | ds1            | `sa_ms_downsampling`                       | [1, 48, 16, 16] |
| 03  | acb2a          | `sa_ms_all_conv_block` (1 sub-block)       | [1, 48, 16, 16] |
| 04  | acb2b          | `sa_ms_all_conv_block` (re-uses acb2a wts) | [1, 48, 16, 16] |
| 05  | ds2            | `sa_ms_downsampling`                       | [1, 96,  8,  8] |
| 06  | acb3a          | `sa_ms_all_conv_block` (1 sub-block)       | [1, 96,  8,  8] |
| 07  | acb3b          | `sa_ms_all_conv_block` (re-uses acb3a wts) | [1, 96,  8,  8] |
| 08  | sppf           | `sa_spike_sppf` (4-way 192->48 -> concat)  | [1, 48,  8,  8] |
| 09  | head_reduce    | `sa_conv2d_bn` 1x1                         | [1, 48, 16, 16] |
| 10  | head_refine    | `sa_sep_conv` (dw + pw)                    | [1, 48, 16, 16] |
| 11  | detect (cast)  | `sa_detect_head` (int32 -> int8 trunc)     | [1, 48, 16, 16] |

PS-side Detect (`cv2`/`cv3` reg+cls + DFL + sigmoid + NMS) lives in
[`sw/runtime/`](../../sw/runtime/) under C3's ownership; only the cast is on PL.

## Known Issues

| Symptom | Workaround / root cause |
|---|---|
| `m2w64-gcc 5.3.0` ICE on `<algorithm>` (host_csim only) | inline ternary clamp; do not include `<algorithm>` in HLS-visible code |
| `cnpy` cannot read `.npz` deflate members | use the included `sim/npz_reader.{h,cpp}` + `tools/ci/explode_npz.py` (A2) |
| C-sim PASS but Co-sim mismatch | check `#pragma HLS ARRAY_PARTITION` mode matches actual access stride (see `include/op_macros.h`) |
| `csim_design` exits 0 but no print | testbench `main` must `return EXIT_FAILURE` on mismatch; Vitis HLS propagates the code |
| `export_design` stalls > 30 min | likely `cosim_design` was triggered first; rerun `vitis_hls -f run_synth.tcl` cold |

## CI integration (`.github/workflows/hls_smoke.yml`)

On self-hosted runner the workflow executes:

- Steps **1-3** (host_csim sanity baseline) on every PR.
- Steps **6-7** (`run_synth.tcl` + RISK_RULES gate) nightly + on `main` push.
- Step **5** (`run_cosim.tcl`) only when the PR carries label `cosim` — cosim
  costs ~10 min/op (10 ops -> ~1.5 h end-to-end) so we do not pay it per push.

Ubuntu hosted runners (no Vitis) still execute steps **1-3** as a regression
guard via the existing `m2w64-gcc` host_csim path.

## Contracts produced

- **C3**: `hw/hls/build/sa_tiny_fpga_top.xo` + `hw/hls/build/tiny_fpga_regmap.yaml`
  consumed by B2 BD integrator. v1.0.3 regmap extension (LAYER_ID / LAYER_MASK)
  proposed under [`docs/CONTRACTS_proposed_v1.0.3.md`](../../docs/CONTRACTS_proposed_v1.0.3.md).

## Layout

```
include/          ap_int dtypes, AXI iface macros, op_macros.h
src/              one .cpp per operator + sa_tiny_fpga_top.cpp top-level
sim/              testbenches + npz_reader + reference.hpp (golden replay)
build/            generated .xo IP + tiny_fpga_regmap.yaml (Contract 3)
reports/          timing.csv, utilization.rpt, <top>_csynth.rpt
run_csim.tcl      Vitis HLS C-simulation across all 10 (top, tb) pairs
run_cosim.tcl     C/RTL co-simulation per kernel
run_synth.tcl     csynth + .xo packaging + report aggregation
```

## References

- [`tools/fpga/numpy_reference.py`](../../tools/fpga/numpy_reference.py) — translation source
- [`docs/CONTRACTS.md`](../../docs/CONTRACTS.md) — interface schemas (v1.0.2)
- [`docs/RISK_RULES.yaml`](../../docs/RISK_RULES.yaml) — R1 timing / R2 resource gates
- Xilinx UG902 Vitis HLS User Guide
