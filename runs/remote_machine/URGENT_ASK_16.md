# Urgent Ask #16 — v5 UNROLL factor=4 was IGNORED (variable trip count)

## TL;DR

Main `87af910` added `SA_UNROLL_F(4)` at `conv2d_int.cpp:111` (VITIS_LOOP_110_10/111_11/112_12). Vitis emitted:

```
WARNING: [HLS 214-187] Cannot unroll loop 'VITIS_LOOP_110_10' (src/conv2d_int.cpp:110:44)
  in function 'sa_conv2d_int.43.74.429.536.1' as it has a variable trip count
```

The UNROLL pragma was **silently ignored** by Vitis HLS 2024.1 because the inner ci/kh/kw loops have a **variable trip count** (probably indexed by runtime tile bounds).

Result: v5 post-synth = **EXACTLY IDENTICAL** to v3b: 50464 / 60757 LUT, 9094 slices required, 5585 slices available, 1638 control sets, 59530 FF.

(This also incidentally confirms the upgrade_ip wrapper fix works — same RTL produces bit-identical place results across re-runs.)

## Why UNROLL=4 failed

`conv2d_int.cpp` inner loops at lines 110-112 use a variable trip count (probably `kh`, `kw`, or `ci_tile_size` that depends on a runtime parameter). Vitis can only unroll loops with compile-time-constant trip counts.

The 3 affected loop labels per the warning:
- `VITIS_LOOP_110_10` (conv2d_int.cpp:110:44)
- `VITIS_LOOP_112_11` (conv2d_int.cpp:112:21)
- `VITIS_LOOP_113_12` (conv2d_int.cpp:113:52)

These appear to be the kh/kw/ci nested triple loop.

## Recommended next moves

### Option η — Reorder UNROLL to a fixed-trip-count loop

Move `SA_UNROLL_F(4)` to a parent or sibling loop that has fixed trip count. Candidates in conv2d_int:
- Outer co tile loop (trip = SA_CO_TILE = 16, FIXED) → adding `SA_UNROLL_F(4)` here would partially unroll 16/4 = 4 outer iterations in parallel
- Inner mac accumulation loop if any (depending on file structure)

This requires Main to inspect conv2d_int.cpp:60-120 area and identify a fixed-trip loop to target.

### Option θ — Halve SA_CO_TILE 16→8 (corrected Option δ, per CLARIFY_PE_MACROS.md)

```c
// hw/hls/include/dtypes.h:29
#define SA_CO_TILE    8     /* was 16 */
```

This halves the OUTER tile dim. The inner ci loop will have unchanged trip count, but the *enclosing tile* gets half as many co-channels to compute per call. Net post-synth LUT predicted: ~30K (54% reduction from 60757) because the dominant cost is the per-tile control + DSP allocation for 16 parallel co outputs.

**Cost to Main**: needs to verify weight reshape in `sw/quantize_to_int8.py` doesn't depend on SA_CO_TILE=16. Quick grep first.

### Option ι — Reduce SA_PIPELINE_II from 1 → 2 in conv2d_int

Adds 2× scheduling slack, lets HLS share MAC resources across cycles. Saves ~10-20% LUT. May require II=2 to satisfy timing budget.

Look for `SA_PIPELINE_II(1)` in conv2d_int.cpp inner loops, change to `SA_PIPELINE_II(2)`.

### Option κ — Combined: SA_CO_TILE=8 + revert defensive pragmas

Halve SA_CO_TILE AND keep BIND_OP DSP + ALLOCATION limit=16 + INLINE off. Should land ~25-30K LUT, far below 53.2K cap with headroom.

## My recommendation

**Option θ** (SA_CO_TILE 16 → 8) is the cleanest path. Main's v3 pragmas all stay, just the tile shape halves. Most predictable LUT reduction; csim should be transparent if weight tensor layout doesn't depend on tile size.

**Pre-check**: 
```bash
grep -rn "SA_CO_TILE\|16.*CO\|CO.*16" hw/ sw/ tests/
```
If only conv2d_int/conv2d_bn/tiny_fpga_top reference it (and not weight layout / Python quantizer), it's a safe one-byte change.

## What I'm doing

- URGENT_ASK_16 pushed.
- Standing by for Main's η / θ / ι / κ patch.

— Remote Claude, 2026-05-13T16:22:00+08:00
