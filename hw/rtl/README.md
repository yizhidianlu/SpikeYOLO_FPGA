# hw/rtl — RTL Tuning (B3 Agent, M5+ only)

**Owner**: B3 RTL Tuning Agent — see [`docs/AGENT_PLAYBOOKS/B3_rtl_tuning.md`](../../docs/AGENT_PLAYBOOKS/B3_rtl_tuning.md)

## Purpose

**Conditional** — only activates in M5 if HLS-generated RTL cannot close timing at 150 MHz. Hand-written SystemVerilog replacements for hot inner loops (PE array, popcount tree, LIF skip controller).

## Activation triggers

- B2 reports `hw/vivado/reports/timing_summary.rpt` WNS < 0 @ 150 MHz, OR
- B1 reports HLS critical path > 6.67 ns, OR
- Risk R1 escalates to handler (c)

If none triggered, this directory stays empty and B3 status remains `pending`.

## Layout

```
src/                  pe_array.sv, popcount_tree.sv, lif_skip_ctrl.sv
sim/                  testbenches (Verilator + cocotb)
verify/uvm_top/       optional UVM environment
scripts/              run_verilator.sh and helpers
```

## Build & test

```bash
verilator --lint-only src/pe_array.sv
bash scripts/run_verilator.sh
```

## Acceptance gates

- Verilator simulation cycle-accurate matches the HLS-generated RTL baseline
- Vivado implementation Fmax ≥ 160 MHz after replacement
- LUT savings ≥ 15% vs M4 baseline

## References

- Xilinx UG479 7 Series DSP48E1 Slice User Guide
- Verilator manual
- The HLS-generated `.v` files in `hw/hls/build/.../verilog/` are the binding reference
