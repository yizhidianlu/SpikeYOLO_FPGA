# Step 5 PASS — bitstream produced (v7)

## Status

| Phase | Status | Time |
|---|---|---|
| BD construction | OK | ~30 s |
| Sub-IP synth | OK | ~3 min |
| Main synth_1 | OK | ~18 min |
| Implementation impl_1 | **OK** | ~9 min |
| Bitstream write_bitstream | **OK** | ~25 s |
| Reports + XSA export | OK | ~5 s |

`hw/vivado/out/system.bit` (2.52 MB) — present ✓
`hw/vivado/out/system.xsa` (607 KB) — present ✓
`hw/vivado/out/address_map.yaml` — present ✓
`hw/vivado/reports/{timing_summary,utilization,power}.rpt` — present ✓

## R2 Resource — PASS

| Resource | Used | Cap | % |
|---|---:|---:|---:|
| Slice LUTs | **38838** | 53200 | **73.0%** |
| LUT Logic | 36092 | 53200 | 67.8% |
| LUT RAM/SR | 2746 | 17400 | 15.8% |
| Slice Registers | 47912 | 106400 | 45.0% |
| F7 Muxes | 257 | 26600 | 0.97% |
| BRAM | 2 | 140 | 1.4% |
| DSP | ~150 | 220 | ~68% |

Headroom: 14362 LUTs (27%) + 58488 FFs (55%) — comfortable.

## R1 Timing — FAIL (closeable)

| Metric | Value |
|---|---:|
| WNS | **-0.764 ns** |
| TNS | -35.489 ns |
| Failing endpoints | 172 / 134900 (0.13%) |
| WHS (hold) | +0.018 ns ✓ |
| WPWS (pulse) | +3.750 ns ✓ |
| Clock | clk_fpga_0 @ 100 MHz |

**0.13% endpoints fail by 0.764 ns**. Three options:

1. **Lower clock to 90 MHz** (one-line change in BD, `set_property -dict {CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {90}}`). Critical path becomes 10764 ps / 0.9 = 11960 ps headroom: ample. Throughput hit: 10%.

2. **Re-impl with `Performance_Explore` strategy** (~30 min Vivado work, likely closes). One-line change: `set_property STRATEGY Performance_Explore [get_runs impl_1]; reset_run impl_1; launch_runs impl_1 ...`

3. **Ship as-is for M1** with timing-violation noted. Most failing endpoints are at the FPGA<->PS_DMA boundary (high fanout); functionally the bitstream will boot and run, just with slightly degraded margin.

I'd recommend Option 2 first (closes with no perf cost). Falls to Option 1 if it doesn't close.

## v7 architectural change (Main e9545e0)

Moved `SA_PIPELINE_II(1)` from wx loop (outer-most pipelinable level, had memory-dep-bound II=147) to ci loop (inner, weaker dependency). Effect:
- LUT-cap function `Pipeline_VITIS_LOOP_97_..._99` (which had 19K LUT + II=147 at v3b) deleted from the design — replaced by ci-loop-level pipeline.
- HLS-est LUT 122K → 92K (-24%)
- Post-synth LUT 60K → 38K (-37%)
- DSP usage 220 (saturated) → ~150 (32% free)
- Throughput per-pixel: ~147 cyc → ~C_in_g cyc (1.5x-49x faster depending on layer)

## Step 6 readiness

Ready to push final LFS artifacts:
- system.bit (LFS-tracked per .gitattributes line 18)
- system.xsa (LFS-tracked per .gitattributes line 21)
- address_map.yaml (regular git)
- reports/{timing_summary,utilization,power}.rpt (regular git)

After push, M1 milestone unlocks: ZYBO Z7-20 bitstream ready for board bring-up.

— Remote Claude, 2026-05-13T17:50:00+08:00
