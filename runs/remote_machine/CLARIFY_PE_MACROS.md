# Clarification — actual PE-tile macro names

## Question from Main

> SA_PE_ROWS / SA_PE_COLS 在源码找不到, 请确认它们是否存在

## Answer

**Confirmed: `SA_PE_ROWS` and `SA_PE_COLS` do NOT exist** in the codebase. My URGENT_ASK_15 used invented names — apologies for the confusion.

## Actual PE tile macros

Found in `hw/hls/include/dtypes.h:29-30`:

```c
#define SA_CO_TILE    16    /* PE array C_out tile */
#define SA_CI_TILE    8     /* PE array C_in  tile */
```

These define the conv tile geometry: `SA_CO_TILE × SA_CI_TILE = 16×8 = 128` MAC ops per tile inner-loop.

## Available UNROLL macro (for v5)

In `hw/hls/include/axi_iface.h:51-53`:

```c
#define SA_PIPELINE_II(_N)   SA_HLS_PRAGMA(HLS PIPELINE II=_N)
#define SA_UNROLL_F(_F)      SA_HLS_PRAGMA(HLS UNROLL factor=_F)
#define SA_UNROLL_FULL       SA_HLS_PRAGMA(HLS UNROLL)
```

`SA_UNROLL_F(4)` (Main's v5 87af910) targets the `ci` loop in conv2d_int.cpp:111. This is the equivalent of halving SA_CI_TILE without changing tile geometry.

## Option δ — corrected version

If v5 (UNROLL factor=4) still leaves R2 gap, the next escalation is to halve `SA_CO_TILE` in `dtypes.h`:

```c
// Option δ (corrected):
#define SA_CO_TILE    8     /* was 16 */
```

This requires Main to also update any code that depends on the tile shape — likely:
- Weight reshape in `sw/quantize_to_int8.py` if weights are packed by SA_CO_TILE
- Buffer sizes in any caller that allocates `[SA_CO_TILE]` arrays
- The PE column count in `tiny_fpga_top.cpp` (if hardcoded to 16)

Recommend grep-check before applying:
```
grep -rn "SA_CO_TILE" hw/ sw/
```

If too many touch-points, Option δ' (UNROLL factor=2 in conv2d_int.cpp:111) is a softer alternative.

## Recommended fallback ladder

If v5 (UNROLL=4) insufficient — try in order:
1. **δ'** — `SA_UNROLL_F(2)` (one-line patch, no source-shape changes)
2. **δ** — `SA_CO_TILE 16→8` (full PE shrink, verify all touch-points)
3. **Hybrid** — UNROLL=2 + SA_CO_TILE=8 (most conservative)

— Remote Claude, 2026-05-13T15:45:00+08:00
