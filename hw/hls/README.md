# hw/hls — HLS Kernel IP (B1 Agent)

**Owner**: B1 HLS Kernel Agent — see [`docs/AGENT_PLAYBOOKS/B1_hls_kernel.md`](../../docs/AGENT_PLAYBOOKS/B1_hls_kernel.md)

## Purpose

Vitis HLS 2023.2 C++ implementations of all 11 SpikeYOLO tiny_fpga layers, packaged as a single Vivado IP `tiny_fpga_top`. Line-for-line ports of `tools/fpga/numpy_reference.py`.

## Layout

```
include/          ap_int dtypes, AXI iface macros
src/              one .cpp per operator + tiny_fpga_top.cpp top-level
sim/              testbenches + golden loader
build/            generated .xo IP + regmap.yaml (Contract 3)
reports/          timing.csv, utilization.rpt
run_csim.tcl      C-simulation script
run_cosim.tcl     C/RTL co-simulation script
```

## Build

```bash
source /opt/Xilinx/Vitis_HLS/2023.2/settings64.sh
vitis_hls -f run_csim.tcl     # fast, against tests/golden/*.npz
vitis_hls -f run_cosim.tcl    # slow, RTL co-sim
```

## Contracts produced

- **C3**: `build/tiny_fpga_top.xo` + `build/tiny_fpga_regmap.yaml` → B2

## Acceptance gates

- C-sim 100% pass against all `tests/golden/layer_*.npz`
- WNS ≥ 0 @ 100 MHz (M4) → ≥ 0 @ 150 MHz (M5)
- DSP ≤ 70%, LUT ≤ 60%, BRAM ≤ 75%

## References

- [`tools/fpga/numpy_reference.py`](../../tools/fpga/numpy_reference.py) — translation source
- [`docs/CONTRACTS.md`](../../docs/CONTRACTS.md) — interface schemas
- Xilinx UG902 Vitis HLS User Guide
