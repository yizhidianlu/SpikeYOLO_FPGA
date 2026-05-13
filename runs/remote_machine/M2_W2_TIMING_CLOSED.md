# M2-W2 TIMING CLOSURE — PASS

## TL;DR

**WNS +0.067 ns, TNS 0.000 ns, 0 failing endpoints. "All user specified timing constraints are met."**

Path A (Performance_Explore @ 100 MHz) recovered 27%. Path B (FCLK_CLK0 100→90 MHz via Main's `01b3e78`) + Perf_Explore closed the remaining gap.

## Timing summary

| Step | WNS | TNS | Failing | Clock |
|---|---:|---:|---:|---|
| v7 baseline (100 MHz, default) | -0.764 ns | -35.489 | 172 | 100 MHz |
| Path A (100 MHz + Perf_Explore) | -0.557 ns | -13.811 | 79 | 100 MHz |
| Path B retry4 (90 MHz, default) | -0.194 ns | -0.568 | 4 | 90 MHz |
| **Path B + Perf_Explore (final)** | **+0.067 ns** | **0.000** | **0** | **90 MHz** |

Hold: WHS +0.009 ns ✓; Pulse-width: WPWS +4.250 ns ✓.

## What broke and how it was fixed (Vivado tool quirks)

1. **board_part :1.0 vs :1.2** — Main's build_bd.tcl uses `digilentinc.com:zybo-z7-20:part0:1.0` but this Vivado install has `:1.2`. Worked around in `runs/remote_machine/run_step5_bd_patched.tcl` (string-map :1.0→:1.2). Pre-existing.
2. **hdmi_gt_controller IP missing bd.tcl** — added to disable-IP list in `run_step6_bt_patched.tcl` (alongside roe_framer).
3. **IPCACHE multi-thread crash** — silent vivado exit at IPCACHE `runCacheChecks() threadPool finishWork()` after `create_project -force`. Added `set_param general.maxThreads 1` to serialize cache check.

## Build chain to reproduce

```bash
# 1. Rebuild BD with Main's 90 MHz config (uses string-map wrapper for :1.2)
vivado -mode batch -source runs/remote_machine/run_step5_bd_patched.tcl

# 2. Run synth_1 + impl_1 (default strategy)
vivado -mode batch -source runs/remote_machine/run_step6_bt_patched.tcl

# 3. Apply Performance_Explore + re-impl_1 (default failed at WNS -0.194)
vivado -mode batch -source runs/remote_machine/run_step6_timing_perf_explore.tcl
```

Wall-clock: ~30 min for the full chain on this machine (Win11, Vivado 2024.1).

## Artifacts (LFS)

- `hw/vivado/out/system.bit` — 2.51 MB, 90 MHz timing-met bitstream
- `hw/vivado/out/system.xsa` — hw platform export
- `hw/vivado/out/address_map.yaml` — peripheral addresses
- `hw/vivado/reports/timing_summary.rpt` — WNS +0.067 ns
- `hw/vivado/reports/utilization.rpt` — same as v7 (LUT 73%)
- `hw/vivado/reports/power.rpt`
- `runs/remote_machine/timing_summary_perf_explore.rpt` — same WNS +0.067
- `runs/remote_machine/m2w2_pathb_synth4.log` — synth+default-impl pass (WNS -0.194)
- `runs/remote_machine/m2w2_pathb_perfexp.log` — Perf_Explore close (WNS +0.067)

## Hardware platform

- Throughput: ~30 FPS @ 90 MHz (vs target 30 FPS, 0% headroom but within budget)
- Critical path: 11.044 ns (90 MHz period = 11.111 ns → +0.067 ns slack)
- ZYBO Z7-20 (xc7z020-clg400-1)
- 8 IPs in BD: ps_0, spike_accel_0, ic_data_hp0/1, ic_ctrl, axi_dma_feat, rst_clk0/1

## M3 readiness

The HDMI Section 10 rebuild can now start. Recommend Main proceed with task 2 (axi_vdma + v_tc + v_axis_to_video_out + rgb2dvi). Once added to build_bd.tcl, my wrappers will re-run the full chain and verify it still closes timing.

Note that the HDMI path will likely use FCLK_CLK1 = 148.5 MHz for pixel clock, separate from the spike_accel's 90 MHz clock — should not affect M2-W2 closure.

— Remote Claude, 2026-05-13T23:17:00+08:00
