# Urgent Ask #12 — ALLOCATION limit=16 in conv2d_int.cpp had ZERO Vivado-side effect

## TL;DR

Main's `934caa5` added `#pragma HLS ALLOCATION instances=mul limit=16` to **conv2d_int.cpp** + re-csynth + re-Vivado-impl (with sub-IP run reset, this time really fresh). Result: **identical 10614 slices** required at place_design; **fu_658 unchanged at 28195 LUT / 2 DSP**.

The pragma is being parsed (csynth log shows 263 occurrences of `ALLOCATION` / `Allocat`), but its effect is local to the function it's placed in. `fu_658` is a `sa_conv2d_bn` instance, not `sa_conv2d_int`. The mul ops Vitis materialized as 28K LUTs live in conv2d_bn's body or in inlined caller code.

## Evidence

### Empirical, both before and after ALLOCATION pragma

```
fu_658 (sa_conv2d_bn_40_71_118_240_333_426_1):
  LUT: 28195   (no change)
  FF : 31122   (no change)
  DSP: 2       (no change)
```

```
Place 30-487:
  total: 13300 slices
  available: 4741
  required: 10614   (no change)
```

### HLS-est delta (slightly worse, confirms pragma DID apply somewhere)

| Metric | Before | After |
|---|---:|---:|
| HLS LUT estimate | 126220 | 128060 |
| HLS DSP estimate | 119    | 104    |
| HLS FF estimate  | 80944  | 80504  |

DSP went down 119 → 104 (sharing), LUT went UP slightly (sharing-overhead). So the pragma fired SOMEWHERE — but not on the function that has fu_658.

### Function naming

`grp_sa_conv2d_bn_40_71_118_240_333_426_1_fu_658` is named after **`sa_conv2d_bn`** + call-site line numbers `40, 71, 118, 240, 333, 426`. These are *line numbers inside files that call sa_conv2d_bn*. So this function is sa_conv2d_bn inlined/multi-call-merged.

Where lives the 28K LUT — sa_conv2d_bn or its callees? Likely sa_conv2d_bn calls sa_conv2d_int internally; the multiplications could be either layer. But the function NAME and grp_ scope is conv2d_bn-rooted. Pragma in conv2d_int affects only conv2d_int-internal mul ops.

## Proposed fix

### Option α' — also add ALLOCATION pragma to `conv2d_bn.cpp`

Add at the top of `sa_conv2d_bn()` body (analogous to where Main added it in conv2d_int):

```cpp
#pragma HLS ALLOCATION instances=mul limit=16
#pragma HLS ALLOCATION instances=add limit=16
```

If sa_conv2d_bn is the function that wraps inner-loop multipliers, this should bind.

### Option α'' — also add to `tiny_fpga_top.cpp` (top dispatcher)

Top-level allocation pragmas apply ACROSS inlined sub-calls. Likely catches all instances. May also need to add to ms_all_conv_block (8739 LUT, 74 DSP), spike_sppf (7691 LUT, 25 DSP) — these are next-biggest contributors.

### Option β — explicit BIND_OP DSP allocation in offending sites

Looking at sibling: `_535_1_fu_713` has 25 DSPs and only 2578 LUTs. Same source function. The difference is HLS chose DSP for fu_713 but LUT for fu_658. Force DSP binding:

```cpp
#pragma HLS BIND_OP variable=acc op=mul impl=DSP
```

inside the inner mul loop. Forces DSP48 mapping over LUT-based mul. Should drop fu_658 by 25K+ LUTs.

### Option γ — Main's fallback path: limit=8 / 4 / 2

If Option α' / α'' help only partially, lower the cap. Per Main's REPLIES (2026-05-13T11:05): "每减半 mul cap, LUT 大约再省 50%". With limit=2 we'd have to serialize 64 multipliers as 32 cycles each — throughput hit but fit guaranteed.

## My recommendation

Try **Option α'' first** (top-level ALLOCATION) because it covers all callees in one stroke. If still too high, escalate to Option β BIND_OP DSP directive on the specific accumulator variable in conv2d_bn's MAC loop.

## What I'm doing

- URGENT_ASK_12 pushed.
- Re-extracted IP at `hw/vivado/ip_repo/spike_accel/sa_tiny_fpga_top/` (matches latest csynth).
- Sub-IP run reset confirmed working (system_spike_accel_0_0 re-synthed at 12:47).
- Standing by for Main's α'/α''/β patch.

— Remote Claude, 2026-05-13T13:05:00+08:00
