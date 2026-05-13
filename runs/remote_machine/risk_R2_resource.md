# Risk R2 — resource budget overflow (empirically confirmed)

## Trigger
Vivado 2024.1 impl_1 `place_design` failed:

```
ERROR: [Place 30-487] The packing of instances into the device could not be
obeyed. There are a total of 13300 slices in the device, of which 4741 slices
are available, however, the unplaced instances require 10614 slices.

Number of control sets and instances constrained to the design
    Control sets: 1590
    Luts: 54339 (combined) 65250 (total), available capacity: 53200
    Flip flops: 60999, available capacity: 106400
```

## Empirical numbers (Vivado synth-side, not HLS-estimate)

| Resource     | Used  | Available | % of total | Verdict |
|---|---:|---:|---:|---|
| LUTs (combined) | 54339 | 53200 | 102.1% | **over by 1.1K** |
| LUTs (total)    | 65250 | 53200 | 122.6% | over by 12K |
| FFs             | 60999 | 106400 | 57.3% | OK |
| Slices required | 10614 | 4741 (post-PS reserve) | **224%** | hard fail |
| Control sets    | 1590 | — | high | packing pressure |
| DSPs            | 119 | 220 | 54.1% | OK |
| BRAM            | 12 | 280 | 4.3% | OK |

**Key insight**: LUT overage is small (1.1K combined / 12K total) but **slice packing fails because PS7 + DDR3 + AXI infrastructure reserves 8559 of 13300 slices**, leaving only 4741 for user logic. Our design needs 10614. **Architectural shrink required**, not just LUT optimization.

## Comparison HLS-est vs Vivado-real

| Metric | HLS estimate | Vivado synth |
|---|---:|---:|
| LUT  | 126220 (237%) | 65250 (123%) |
| DSP  |    119 ( 54%) |   119 ( 54%) |
| FF   |  80944 ( 76%) | 60999 ( 57%) |

HLS over-estimated LUT by ~1.9× (consistent with 1.5-2× rule of thumb). DSP matched exactly. FF over-estimated by 1.3×.

## Per handoff §10 / RISK_RULES.yaml R2

- **Action taken**: this risk report written; impl_1 ABORTED at place_design; **NO retry** per protocol
- **Assignees**: B1 (per RISK_RULES.yaml)
- **R2 handlers from RISK_RULES**:
  1. **Shrink PE array 16×8 → 8×8** — would roughly halve LUTs; new size ~33K + ~30K = ~63K total, ~27K combined. Would fit (target = ≤ 53K combined). Recommended.
  2. **Time-multiplex shared PE across layers** — keeps full PE count but serializes layer dispatch. Throughput halves; LUT halves too. Fallback if (1) loses too much throughput.
  3. **DW conv to LUT-based shift-add** — incremental; saves ~5-10K LUTs but not 10K+. Won't fit alone.

## Recommendation to Main

Choose handler (1) or (2). Estimate:
- Handler (1): ~2 hours of B1 work — narrow PE_TILE in hw/hls/include/dtypes.h, retest csim, re-csynth.
- Handler (2): ~4 hours — dispatcher serializes 5 leaf calls; needs runtime mux.

Either followed by Step 3 re-csynth → Step 5 re-impl → Step 6.

Step 1 csim PASS (`0b3df61`) and the m_axi-correct .xo (`1ff4ae8`) are preserved baselines.

## Why this surfaced only now

- HLS-estimate was 237% LUT, suggesting infeasibility — but HLS LUT over-counts by 1.5-2× routinely (known)
- Per ADR-0002, paper estimate was 64 DSP + ~6K LUT (M4 target); reality 119 DSP + 65K LUT, ~10× LUT growth
- The 1.9× HLS-vs-real ratio held; the architectural budget was the problem

## Bitstream status

**No bitstream produced**. `hw/vivado/out/system.bit` does not exist. `system.bd` + `system.hwh` + post-synth checkpoint do exist (under `out/spike_zybo.runs/synth_1/`).

— Remote Claude, 2026-05-13T10:30:00+08:00
