# M2-W2 Path A — Performance_Explore: partial success, still need Path B

## TL;DR

Performance_Explore impl strategy improved timing by 207 ps but did NOT fully close (-0.557 ns WNS remains). **Recommend Path B: lower clock 100→90 MHz** (gives +1.1 ns slack, comfortably closes).

## Numbers

| Metric | v7 (Defaults) | v7 (Perf_Explore) | Δ |
|---|---:|---:|---:|
| **WNS** | -0.764 ns | **-0.557 ns** | +0.207 (+27%) |
| **TNS** | -35.489 ns | **-13.811 ns** | +21.678 (+61%) |
| TNS Failing Endpoints | 172 | **79** | -54% |
| WHS (hold) | +0.018 ns ✓ | +0.021 ns ✓ | OK |
| WPWS (pulse) | +3.750 ns ✓ | +3.750 ns ✓ | OK |
| Bitstream | 2520272 B | 2517808 B | -2464 B (re-packed) |

Performance_Explore halved the number of failing endpoints and recovered 27% of WNS. But the worst critical paths are inherently long (likely m_axi DMA register paths or fanout-heavy spike_accel internal nets) and need slack at the constraint level, not just routing optimization.

## Why Path A alone is insufficient

The 0.557 ns gap is too large for further iteration. Each subsequent retiming pass typically saves 50-150 ps; we'd need ~4 more passes with diminishing returns. Better to take a one-shot Path B win.

## Recommendation: Path B

Per Main's REPLIES_FROM_MAIN.md task 1.b: lower PL clock 100 → 90 MHz.

**Note**: clk_wiz_0 may not exist in the current BD — ZYBO Z7-20 PS uses `PCW_FPGA0_PERIPHERAL_FREQMHZ` for FCLK_CLK0 directly. Check `hw/vivado/build_bd.tcl` for the actual clock source. Most likely:

```tcl
# In build_bd.tcl, search for ps_0 / ZYNQ processing_system7
set_property -dict [list \
    CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {90} \
] [get_bd_cells ps_0]
```

Expected after Path B:
- 100 MHz period: 10 ns; current critical path: 10.557 ns
- 90 MHz period: 11.111 ns
- New WNS = 11.111 - 10.557 = **+0.554 ns** ✓
- Throughput hit: 10% (acceptable per Main's REPLIES § "30 FPS budget")

## Build_bd.tcl is Main's territory

I cannot modify `hw/vivado/build_bd.tcl` per access rules. Awaiting Main's clock-config patch.

When Main pushes:
1. I'll pull the BD change
2. Re-build BD (`vivado -mode batch -source hw/vivado/build_bd.tcl`)
3. Run my Performance_Explore wrapper again on the new 90 MHz constraint
4. Verify WNS ≥ 0
5. Refresh `system.bit` and reports

## Alternative paths (if Main prefers)

- **Path C — register slice insertion**: more surgical (insert reg-slice on the offending critical path's m_axi adapter only); preserves 100 MHz. ~1 hr work + verification.
- **Path D — accept timing failure**: 79 failing endpoints @ -0.557 ns. Functionally the bitstream will likely boot and work most cycles (metastability risk on the long paths could cause sporadic glitches). M1 ship-block, not M2.

I'd take Path B as the lowest-risk closure today.

## Artifacts

- `system.bit` — 2.52 MB refreshed at impl_1/Perf_Explore (still timing-failing, but valid for M1 functional bring-up if Main accepts Path D)
- `system.xsa` — 607 KB refreshed
- `runs/remote_machine/timing_summary_perf_explore.rpt` — full timing report
- `runs/remote_machine/utilization_perf_explore.rpt` — util unchanged from v7 (Perf_Explore doesn't touch util)
- `runs/remote_machine/m2w2_perf_explore.log` — full Vivado log

## What I'm doing next

- Pushing Path A artifacts + this report.
- Standing by for Main's Path B (clock change) or Path C (register slice).

— Remote Claude, 2026-05-13T21:56:00+08:00
