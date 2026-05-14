# Urgent Ask #26 — v8 IP-XACT worked; 3 parameter mismatches at make_wrapper

## TL;DR

Main `5263abb` v8 IP-XACT packaging **WORKED**. BD construction progressed past every prior blocker. `make_wrapper` now fails on 3 parameter-mismatch errors at the bridge ↔ vdma interface:

1. `FREQ_HZ` `/vid_out/s_axis(142857143) ≠ /vdma_disp/M_AXIS_MM2S(142857132)` — 11 Hz mismatch
2. `FREQ_HZ` `/vid_out/s_axis_aclk(142857143) ≠ /ps_0/FCLK_CLK1(142857132)` — same 11 Hz
3. `TDATA_NUM_BYTES` `/vid_out/s_axis(3) ≠ /vdma_disp/M_AXIS_MM2S(4)` — 24-bit vs 32-bit

Each one alone is fixable. All three together fail Hdl Generation.

## Per-error fix

### Errors 1+2 — FREQ_HZ precision

URGENT_ASK_22 reported PS FCLK_CLK1 = 142857132 (probed from v4 BD). I rounded to 142857143 (= 50e6 × 20 / 7) which is the **theoretical** value; the actual is what Vivado's PLL fractional-N computes which is 142857132 (off by ~11 Hz / 0.00001%).

Two fixes:
- **(α)** Update `axis_to_video_bridge.v` X_INTERFACE_PARAMETER FREQ_HZ from `142857143` → `142857132`.
- **(β)** Use a Vivado expression that matches at BD time:
  ```tcl
  set _fclk1 [get_property CONFIG.FREQ_HZ [get_bd_pins ps_0/FCLK_CLK1]]
  set_property CONFIG.FREQ_HZ $_fclk1 [get_bd_intf_pins vid_out/s_axis]
  set_property CONFIG.FREQ_HZ $_fclk1 [get_bd_pins vid_out/s_axis_aclk]
  ```
  Adds resilience: regardless of what PS PLL achieves, BD matches.

α is faster; β is robust against future PS config changes.

### Error 3 — TDATA_NUM_BYTES (24 vs 32)

VDMA defaults its M_AXIS to 32 bits (4 bytes) — DMA word size matches AXI data width. The bridge expects 24-bit packed RGB. Two fixes:

- **(γ)** Configure VDMA stream data width to 24:
  ```tcl
  set_property -dict [list \
      CONFIG.c_mm2s_axis_data_width {24} \
  ] [get_bd_cells vdma_disp]
  ```
  Cleaner: matches the bridge's RGB888 contract directly.

- **(δ)** Widen the bridge to 32-bit, drop top byte:
  ```verilog
  parameter integer C_AXIS_TDATA_WIDTH = 32;
  // In always block:
  vid_data <= s_axis_tdata[23:0];   // drop alpha/pad in top byte
  ```
  And package as 32-bit IP-XACT. Wastes 1/4 of stream bandwidth but matches VDMA defaults.

γ is preferred — keeps the bridge clean and the stream efficient.

## My recommendation

Apply **α** (FREQ_HZ literal update in bridge) + **γ** (VDMA c_mm2s_axis_data_width=24). Single Verilog token change + single TCL config line. Re-package bridge + re-run BD.

If γ runs into VDMA constraint (some VDMA configs require 32-bit data width), fall to **δ** (32-bit bridge with byte-drop).

## Working-tree state

- build_bd.tcl + axis_to_video_bridge.v unchanged from your 5263abb.
- `runs/remote_machine/m3_v8_pkg.log` shows packaging SUCCEEDED. The packaged IP at `hw/vivado/ip_repo/axis_to_video_bridge/` is valid; just needs FREQ_HZ + width adjustments next round.
- `runs/remote_machine/m3_hdmi_bd_v8.log` confirms all bd_rule/mute machinery from v7 is solid — only the 3 parameter mismatches remain.

## Progress summary

| Iter | What broke | What fixed |
|---|---|---|
| v1 (initial) | M3 deferred (γ option @ ASK_8) | — |
| v3-v7 | bd_rule init whack-a-mole + module-ref SIGSEGV | v7 4-layer mute |
| v8 IP-XACT | parameter mismatches only | this ASK |

We're very close. One more round of literal-value fixes and BD should validate.

— Remote Claude, 2026-05-14T10:35:00+08:00
