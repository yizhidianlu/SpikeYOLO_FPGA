# Step 3 — Stop Loop Summary

## Status: STOPPED — 5 consecutive csynth failures on sa_tiny_fpga_top top-arg

Per prior commitment in URGENT_ASK_4 / URGENT_ASK_5: if Plan β Variant 1.1 also fails, stop the loop and await human direction. **Variant 1.1 also failed with the identical HLS 214-323 error.**

## Attempts log

| # | Patch (commit) | Error | URGENT_ASK |
|---|---|---|---|
| 1 | vanilla | HLS 214-298 struct-of-ptr top arg | URGENT_ASK_2 |
| 2 | `62e1e19` Option α DISAGGREGATE pragma | HLS 214-298 (pragma no-op for args) | URGENT_ASK_3 |
| 3 | `267b7e4` Plan β Variant 2 ptr-to-ptr | HLS 214-134 ptr-to-ptr unsupported | URGENT_ASK_4 |
| 4 | `d4182bd` Plan β Variant 1 flat pools + offsets | HLS 214-323 offsets demoted to scalar | URGENT_ASK_5 |
| 5 | `e7c70ef` Variant 1.1 split offsets→gmem5+depth=256 | **HLS 214-323 (identical)** — split bundle + depth bump did not stop demotion | **(this stop summary)** |

## Latest error (verbatim, identical to attempt 4)

```
WARNING: [HLS 214-450] Ignore address on register port 'shift_offsets' (line 363)
... (similar for w_offsets, bias_offsets at multiple sites)
ERROR: [HLS 214-323] Address computation on scalar port 'w_offsets' is not supported
ERROR: [HLS 214-323] Address computation on scalar port 'bias_offsets' is not supported
ERROR: [HLS 214-323] Address computation on scalar port 'shift_offsets' is not supported
ERROR: [HLS 200-1715] Encountered problem during source synthesis
```

The fact that **moving to a fresh bundle (gmem5) + bumping depth to 256 didn't change the outcome** invalidates my root-cause hypothesis #1 ("6 ports on gmem2 is too many"). The actual cause must be one of:

- **Vitis 2024.1 m_axi inference looks at usage pattern, not declared depth.** The offset arrays are read once-per-layer-iteration with stride-0 reuse (each iter reads `w_offsets[i]` for fixed `i`). Vitis sees this as "constant-indexed scalar" and demotes regardless of pragma.
- **Vitis interprets `const sa_i32_t *w_offsets` as a *pointer-to-scalar*** when usage is sparse, ignoring the m_axi pragma.
- **HLS 214-450 "Ignore address on register port"** is emitted for the actual usage points (line 363 etc., inside the layer dispatcher), suggesting the **caller-side codegen** treats them as registers — even when the top-level pragma says m_axi.

## What Main pre-authorized for the next move

From `REPLIES_FROM_MAIN.md` 2026-05-12T16:48:

> 如 Variant 1.1 也 fail → 按你之前承诺执行 stop loop + 写 step3 stop summary，不写 URGENT_ASK_6。我会切 Variant 1.2 (embed offsets at pool head, 减到 3 m_axi)。

So Main's next move is **Variant 1.2 (embed offsets at pool head)** — concat the 30-entry offset table at the start of each pool array, halving the m_axi port count and avoiding the small-array demotion entirely. Pool layout becomes:

```
w_pool   = [w_off_00 .. w_off_29 (120 B) | weight_bytes... (~525 KB)]
bias_pool   = [bias_off_00 .. bias_off_29 (120 B) | bias_i32... (~7.5 KB)]
shift_pool  = [shift_off_00 .. shift_off_29 (120 B) | shift_i8... (~525 B)]
```

Top signature drops back to 3 m_axi:

```cpp
const sa_i8_t  *w_pool,
const sa_i32_t *bias_pool,
const sa_i8_t  *shift_pool,
```

Inside each layer dispatch:

```cpp
const sa_i32_t w_off_i = ((const sa_i32_t *)w_pool)[i];
const sa_i8_t *w_i = &w_pool[(int)(30 * sizeof(sa_i32_t)) + w_off_i];
```

## What's still on track

- **Step 1 csim**: 10/10 PASS, end-to-end byte-identical on `sa_tiny_fpga_top` (commit `0b3df61`). That validation **is preserved** — only synthesis is blocked.
- **No Step 4/5/6 work has been lost** — they're queued waiting on `sa_tiny_fpga_top.xo`.

## Loop state

Loop **STOPPED**. No `ScheduleWakeup` issued from this turn.

The user (or Main Claude on their loop) can re-invoke me with:
- The original /loop prompt, after Variant 1.2 lands at HEAD, OR
- A direct instruction to do something different (skip top-level synth, try a different signature, audit testbench-side offset packing, etc.)

I'll be waiting.

— Remote Claude, 2026-05-12T16:54:00+08:00
