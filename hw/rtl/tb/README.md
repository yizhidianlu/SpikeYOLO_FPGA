# hw/rtl/tb — RTL testbench framework (M5+ only)

## Status

**Empty skeleton — populated in M5 W2** when B3 is triggered.

## Framework choice

**Primary: cocotb + Verilator** (open-source, CI-friendly)

- runs in `make rtl_sim` on the same self-hosted runner B1 uses for vitis_hls
- Python testbench can directly load A2 golden tensors via `tests/golden/*.npz`,
  feeding the same inputs B1 host_csim feeds — guarantees cycle-accurate parity
  vs the HLS-generated baseline
- no Vivado license needed in CI, runs on any Linux/Windows runner

**Backup: SystemVerilog UVM via Vivado xsim**

- only if Verilator chokes on a Xilinx primitive (`DSP48E1` instantiation, etc.)
- requires the self-hosted ZYBO runner with full Vivado install

## First task when B3 enters M5 W2

Write `tb_popcount_tree.py` (cocotb) that:

1. Loads the binary spike inputs from a B1 host_csim dump
   (e.g. `runs/hls_csim_dumps/popcount_input.bin`) — B1 W4 already wired
   `report_timing` + per-kernel scratch dumps via `run_synth.tcl`
2. Drives `popcount_tree.in_bits` with one packet per clock
3. Compares `out_count` against `np.unpackbits(...).sum(axis=...)` golden
4. Fails on first cycle mismatch with a full waveform dump (Verilator FST)

Same template applies to `tb_pe_array.py` and `tb_lif_fsm.py`.

## File naming convention

```
tb_<dut_name>.py        cocotb test driver
tb_<dut_name>_gen.py    optional input/golden generator
sim_build_<dut_name>/   Verilator output (gitignored)
```
