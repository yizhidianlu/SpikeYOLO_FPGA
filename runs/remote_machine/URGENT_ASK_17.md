# Urgent Ask #17 — Pragma-only fixes exhausted; source restructure required

## TL;DR

v3b through v6: **bit-identical** Vivado place results (9094 slices req, 5585 avail, 50464/60757 LUT). Each new pragma had zero effect on generated RTL:

| Iter | Pragma change | Result |
|---|---|---|
| v3b | INLINE off + BIND_OP DSP | fu_658 -31%, baseline |
| v4 | + ALLOCATION limit 16→8 | REGRESSED (+4.6K LUT) |
| v5 | UNROLL factor=4 | IGNORED (variable trip count) |
| v6 | PIPELINE_II 1→2 + SA_CO_TILE 16→8 | IDENTICAL to v3b |

upgrade_ip confirmed working (IP rev 2114607226 → 2114607272 in v6 log). Vivado IS using fresh RTL each time. **The RTL is the same** because:

1. **SA_CO_TILE is documentation-only**. Grep confirms only 3 refs: 2 defines in dtypes.h + 1 comment in sep_conv.cpp. Not plumbed through conv2d_int / conv2d_bn / tiny_fpga_top. Changing it = changing a comment.

2. **PIPELINE_II=2 was overridden**. Vitis HLS reports the conv2d_int inner Pipeline as `II=147` (achieved), not II=2 (directive). The inner loop has ~147-cycle memory dependency (gmem reads + accumulation). The pragma directive is ignored when memory deps force a higher II.

## Where the 60K LUT really comes from

From v3b post-synth breakdown:
- `sa_conv2d_int_43_74_429_1_fu_366` (inside fu_666): **19113 LUT, 146 DSP**
- This single Vitis-pipelined function holds the conv MAC core
- Its inner loop achieved II=147 (one MAC chain per 147 cycles — heavily serial)

The 19K LUT is the *control + datapath* for these 147-cycle pipelined MACs. Not the MAC arithmetic (already in DSP). Reducing this requires either:
- **Fewer MACs per iteration** (real PE shrink — restructure conv2d_int's loop body)
- **Shorter MAC chain** (replace `acc += x*w` chain with a tree-reduction, e.g. 8-way DSP cluster)
- **Memory partition** that allows higher parallelism, reducing the pipeline state machine

## Recommendation: pivot strategy

**Three realistic paths**:

### λ — REAL PE shrink (touches sw/quantize.py too)

Take the existing 16×8 PE conv2d_int implementation and rewrite as 8×8. Concretely:
- In conv2d_int.cpp inner-loop body: split the `co` iteration (currently full 16-wide MAC array) into TWO 8-wide MAC arrays, executed serially.
- This halves the per-iter resource (LUT, DSP) but doubles latency.

Cost: 30-60 min source work + csim re-verify + re-csynth + re-Vivado. ~1 hr round-trip.

### μ — ARRAY_PARTITION for parallelism (different attack)

Add `#pragma HLS ARRAY_PARTITION variable=w dim=1 cyclic factor=8` (and similar for input arrays) inside conv2d_int's load region. This lets Vitis read 8 weights/cycle from BRAM, lowering II from 147 → ~16. Side effect: more BRAM usage but BRAM is at 2/280 currently (essentially zero). Could free LUTs by replacing MUX-based array access with parallel BRAM ports.

Risk: may push BRAM use up to 30-40 / 280, still well under cap.

Cost: 10-15 min pragma work + re-csynth + Vivado. ~40 min round-trip.

### ν — Accept oversized; relax Z-7020 constraint

LUT total is 60757 / 53200 = 114%. Slices req 9094 / 5585 avail = 162%. We're not THAT far over. Try:
- `set_property STRATEGY {Vivado Implementation Defaults} [get_runs impl_1]` → some retiming strategies pack denser
- Add a placer hint to favor LUT-pair packing
- If still fails, accept that this design will not fit Z-7020 and either:
  - **(ν1)** spec-bump to Z-7045 (larger Zynq, drop-in board change)
  - **(ν2)** ship as Z-7020 functional with timing closure as M2 stretch goal

Cost: 5-10 min Vivado strategy try; if it works we're done.

## My recommendation

**Try μ (ARRAY_PARTITION) first** — pragma-level, no source restructure, addresses the *real* bottleneck (memory bandwidth limiting II to 147). Predicted: II drops to ~16-20, freeing scheduling slack which Vitis uses to share resources differently. May land 30-40K post-synth LUT.

If μ insufficient → **λ (real PE shrink)**.

If both fail → **ν1 board bump or ν2 accept oversize**.

## Verification of v6 root cause (proof)

```
$ grep -rn SA_CO_TILE hw/ sw/ tests/
hw\hls\include\dtypes.h:29:#define SA_CO_TILE    8     /* PE array C_out tile ... */
hw\hls\include\dtypes.h:34:#define SA_CI_TILE    8     /* PE array C_in  tile  */
hw\hls\src\sep_conv.cpp:22: *                 at a time => ceil(SA_CO_TILE * SA_CI_TILE / 2) ...
```

Only 3 hits: 2 defines + 1 comment. **No source code reads SA_CO_TILE** — it's documentation. Changing 16→8 was a no-op.

```
$ grep "II=" hw/hls/synth_sa_tiny_fpga_top/sol1/syn/report/csynth.rpt | head
| Pipeline_VITIS_LOOP_97_7_..._99 ... II=147 ...
```

II=147 directive `SA_PIPELINE_II(2)` requested II=2 but Vitis scheduled II=147 due to dependencies. Standard HLS behavior.

## What I'm doing

- URGENT_ASK_17 pushed with full diagnosis.
- Standing by for Main's μ / λ / ν decision.
- All v6 artifacts preserved at HEAD.

— Remote Claude, 2026-05-13T17:00:00+08:00
