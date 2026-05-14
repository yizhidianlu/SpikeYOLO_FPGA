# Urgent Ask #27 — M3 v9 marginal R2: ~120 slices over (Area_Explore best)

## TL;DR

v9 full BD+synth+impl chain RAN. All earlier blockers resolved (mute, IP-XACT, FREQ_HZ, TDATA). **Impl fails at place** with a tight R2 gap.

| Strategy | Slices req | Slices avail | Δ |
|---|---:|---:|---:|
| Defaults | 8079 | 7809 | **+270** |
| Performance_Explore | 8078 | 7805 | +273 |
| **Area_Explore** | **7926** | **7806** | **+120** (best) |
| Area_ExploreSequential | 8043 | 7808 | +235 |

We need ~120 more slices of compression. Spike_accel alone won't shrink (M2-W2 was tight); the additive load comes from the new HDMI path. Three options below; HDMI-side cuts are cleanest because they don't disturb the validated spike_accel pipeline.

## Proposed fixes

### Option α — Shrink VDMA buffer

`axi_vdma:6.3` currently uses default 3 frame buffers + DRE. Trim:

```tcl
set_property -dict [list \
    CONFIG.c_mm2s_max_burst_length     {128} \   # was 256 — halve
    CONFIG.c_num_fstores               {1}   \   # was default 3
    CONFIG.c_include_mm2s_dre          {0}   \   # was 1 — drop DRE
] [get_bd_cells vdma_disp]
```

Expected savings: ~200-400 slices (DRE alone is ~150 LUT; n_fstores 3→1 halves the frame-buffer ctrl logic; halved max_burst reduces burst-FIFO depth).

Risk: c_include_mm2s_dre=0 requires VDMA source-address to be 64-bit-aligned, which our SW will guarantee. c_num_fstores=1 means no triple-buffering for tear avoidance — for the initial demo (static framebuffer) it's fine; for the live USB-cam demo we may want 2.

### Option β — Drop irq_concat NUM_PORTS back to 3

VDMA's mm2s_introut isn't actually needed by the M4 demo SW (we'll poll status registers). Remove the IRQ wiring:

```tcl
# Section 6: irq_concat NUM_PORTS 4 -> 3
set_property -dict [list CONFIG.NUM_PORTS {3}] [get_bd_cells irq_concat]
# Section 12: drop the vdma_mm2s_introut -> irq_concat/In3 wire
```

Saves ~10-20 slices. Small but pure.

### Option γ — Use a smaller-data-width VDMA stream + format adapter

Set VDMA c_mm2s_axis_data_width to 24 (already done in v9), AND set m_axi_mm2s_data_width to 32 instead of 64. Saves the 64→24 width-adapter inside VDMA (~200 LUT).

```tcl
set_property -dict [list \
    CONFIG.c_m_axi_mm2s_data_width     {32} \    # was 64
    CONFIG.c_m_axis_mm2s_tdata_width   {24} \    # already 24 in v9
] [get_bd_cells vdma_disp]
```

Risk: HP1 will run two narrower transactions per pixel-clock; may hit HP1 bandwidth ceiling at 1080p60 (≈ 1.5 GB/s required vs HP1 max ≈ 1.2 GB/s @ 150 MHz / 64-bit). 1080p30 would be safe; 1080p60 needs the 64-bit data path.

### Option δ — Combined α + β

Most surgical, lowest risk. ~250+ slices saved → 8079 - 250 = 7829 < 7809 avail. Close margin but should work.

### Option ε — Defer M3 again, ship M2-W2 bit for M4 demo

M2-W2 already produced a timing-closed bit (WNS +0.067 ns) without HDMI. The M4 USB-cam-to-HDMI demo can use UART or framebuffer-over-USB as a temporary output channel until M3 closes properly.

## My recommendation

**Option δ (α + β combined)**:
- VDMA: c_num_fstores 3 → 1, c_include_mm2s_dre 1 → 0, c_mm2s_max_burst_length 256 → 128
- irq_concat: NUM_PORTS 4 → 3, drop vdma irq wire

That's a build_bd.tcl-only change, no Verilog edit, no re-package. Single-line config-dict edits.

Predicted post-fix: 7926 - 300 = 7626 slices req vs 7806 avail → ~180 slices headroom. Comfortable.

## Working-tree state

- build_bd.tcl + axis_to_video_bridge.v unchanged from your ccf1208.
- runs/remote_machine/run_step6_timing_perf_explore.tcl modified by Remote (strategy set to Area_ExploreSequential currently — revert to Area_Explore for final close).
- Logs: `m3_v9_bt.log`, `m3_v9_perfexp.log`, `m3_v9_areaexp.log`, `m3_v9_areaseq.log` capture all 4 strategy attempts.

— Remote Claude, 2026-05-14T19:46:00+08:00
