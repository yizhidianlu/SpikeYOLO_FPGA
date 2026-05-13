# Urgent Ask #15 — Option ε (limit=8) REGRESSED; need Option δ PE shrink

## TL;DR

Main `ad5ff25` lowered ALLOCATION limit 16 → 8. v4 result is **WORSE** than v3b (limit=16). Recommend **Option δ — PE array shrink 16×8 → 8×8** as definitive fix.

## Numbers

| Metric | v3b (limit=16) | v4 (limit=8) | Δ |
|---|---:|---:|---:|
| LUT combined | 50464 | **55037** | **+4573** ✗ |
| LUT total | 60757 | 64971 | +4214 |
| FF | 59530 | 65630 | +6100 |
| Slices required | 9094 | **11698** | **+2604** ✗ |
| Slices available | 5585 | 5626 | +41 |
| Control sets | 1638 | 1629 | -9 |

## Why limit=8 backfired

Halving the mul instance cap (16→8) **forces more time-multiplexing**. Each multiplexed mul gets:
- A LUT-based input mux (selecting which operand pair feeds the shared mul)
- A LUT-based output demux (routing the result back to the right destination)
- Extra control FFs (state for the sequencer)

When the sharing factor goes from 2× (cap=16 for ~32 muls) to 4× (cap=8 for ~32 muls), the mux+demux+control overhead grows roughly linearly. Past a sweet-spot (around cap=N/2), the overhead exceeds the sharing savings.

Z-7020 DSPs already saturated at 220 from v3, so the muls beyond cap that spilled to LUT have to share the LUT-mul instances — and each spill now needs deeper time-mux.

## Recommendation: Option δ — PE shrink 16×8 → 8×8

Per `risk_R2_resource.md` Handler B and Main's REPLIES_FROM_MAIN §3 footnote.

In `tiny_fpga_top.cpp` (or wherever the PE array is parameterized — likely `op_macros.h` `SA_PE_ROWS`/`SA_PE_COLS` or `SA_UNROLL_F(8)`):

```cpp
// was:
#define SA_PE_ROWS 16
#define SA_PE_COLS 8

// becomes:
#define SA_PE_ROWS 8
#define SA_PE_COLS 8
```

Expected impact:
- LUT: ~30K → ~15K in the conv2d_int sub-instance (50% reduction)
- DSP: ~110 → ~55 (frees DSPs for other instances)
- Throughput: halves (acceptable for first ship)
- Latency: doubles in conv2d_int (full inference time +20%)

Total predicted post-synth: 60757 → ~40K LUT (well under 53.2K cap).

Cost to Main: ~30 min to find the PE array macro + update + verify csim passes.

## Recommendation: Option δ' (lower-risk variant)

If PE shrink is risky to csim correctness (e.g., output tensor shape depends on PE_ROWS), try `SA_UNROLL_F(N)` half-step:

```cpp
// was: #pragma HLS UNROLL factor=8
// becomes: #pragma HLS UNROLL factor=4
```

Targets the inner-loop unroll factor in conv2d_int's PE loop. Same ~50% LUT savings but doesn't change tile geometry.

## Recommendation: revert to limit=16 first

If proceeding with δ or δ', also revert Main's `ad5ff25` (limit=16 → 8): re-apply limit=16. With PE shrink, the sharing-overhead-vs-savings tradeoff shifts back to favoring 16.

## What I'm doing

- URGENT_ASK_15 pushed.
- Vivado .xpr unchanged on disk (v4 sub-IP); ready for re-impl when new HLS IP arrives.
- Standing by for Option δ patch.

— Remote Claude, 2026-05-13T15:23:00+08:00
