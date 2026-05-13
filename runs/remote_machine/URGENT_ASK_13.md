# Urgent Ask #13 — ALLOCATION v2 (conv2d_bn + top) STILL zero Vivado effect

## TL;DR

Main `3651059` added `#pragma HLS ALLOCATION instances=mul limit=16` to **conv2d_bn.cpp** AND **tiny_fpga_top.cpp** (both scopes). Re-csynth + re-Vivado-impl: **IDENTICAL R2 failure**.

```
Place 30-487:
  total slices: 13300
  available  : 4741
  required   : 10614     <-- NO CHANGE from v1
  Luts: 54339 combined / 65250 total (cap 53200)  <-- NO CHANGE
  control sets: 1590
```

```
grp_sa_conv2d_bn_40_71_118_240_333_426_1_fu_658:
  LUT: 28195   <-- NO CHANGE from v1
  FF : 31122   <-- NO CHANGE
  DSP: 2       <-- NO CHANGE
```

## What this means

ALLOCATION pragma is **not the right knob** for fu_658's 28K LUT cost in this Vitis HLS 2024.1 install. Tried:
- v1: pragma in `conv2d_int.cpp` → ZERO effect on fu_658
- v2: pragma in `conv2d_bn.cpp` + `tiny_fpga_top.cpp` → ZERO effect on fu_658

HLS-est `sa_conv2d_bn_40_71_118_240_333_426_1` = 54470 LUT / 1 DSP (line 22 of v2 csynth.rpt). Vivado post-synth = 28195 LUT / 2 DSP. The LUT bulk is **not** in mul ops — it's in **address-decode + control logic + non-mul operators** that ALLOCATION doesn't touch.

The HLS-est detail (`sa_conv2d_bn_..._1_csynth.rpt` line 65) shows:
```
Instance subtree | DSP=1, FF=31551, LUT=53848
  grp_sa_conv2d_int_43_74_429_1_fu_366  | DSP=1, FF=31151, LUT=53261  <-- HERE
```

So inside fu_658, almost all LUTs come from the `grp_sa_conv2d_int_43_74_429_1_fu_366` sub-instance. This is a DIFFERENT sa_conv2d_int instance than the one Main's pragma in conv2d_int.cpp targets (the `_429_1` variant vs `_429_536_1` variant). Maybe.

But more importantly: 53261 LUTs in ONE conv2d_int sub-instance is unusual. The sibling sa_conv2d_int instance `_429_536_1` shows just 3436 LUT (line 28 v2 csynth.rpt). Same source, 15× LUT cost.

## Diagnosis

The `_429_1` (vs `_429_536_1`) suffix means **a different call-site of sa_conv2d_int** got specialized differently. One was inlined cleanly with DSP-friendly mul; the other was specialized in a way that bloats LUTs.

Look at where sa_conv2d_int gets called WITHOUT the `_535_` middle suffix — that's likely the call-site whose tile_w * tile_h * IC * OC parameters got fixed to a value Vitis chose to fully unroll. With unrolled multipliers in INT8 arithmetic, Vitis often emits them as LUT-based shift-add instead of DSP MAC.

## Recommendation: **Option β — explicit BIND_OP DSP forcing**

Instead of ALLOCATION (which limits *count*, not *implementation*), force DSP binding:

In `conv2d_int.cpp` inside `sa_conv2d_int` (where the MAC happens):

```cpp
// In the accumulator update line (likely line 99 area, VITIS_LOOP_99_10 / 100_11 / 101_12)
int32_t prod = (int32_t)a * (int32_t)b;
#pragma HLS BIND_OP variable=prod op=mul impl=DSP latency=3
acc += prod;
#pragma HLS BIND_OP variable=acc op=add impl=DSP latency=1
```

If `prod`/`acc` variable lifetime is too short to name, target the loop instead:
```cpp
for (...) {
  #pragma HLS PIPELINE
  // ...
}
#pragma HLS BIND_OP variable=<accumulator> op=mul impl=DSP
```

Z-7020 has 220 DSP48E1 blocks, currently using 161. Forcing 50-100 more mul to DSP costs DSPs but saves ~20K LUT.

## Recommendation: **Option γ — diff the two sa_conv2d_int specializations**

Pull `synth_sa_tiny_fpga_top/sol1/.autopilot/db/sa_conv2d_int.43.74.429.1.bc.dump` vs `sa_conv2d_int.43.74.429.536.1.bc.dump` to see why HLS chose different impl. The `.bc` files are LLVM bitcode dumps revealing impl decisions per call-site. Maybe inline depth / partial constant propagation differed.

If `_429_1` was fully unrolled but `_429_536_1` was rate-limited, forcing inline depth limits via `#pragma HLS INLINE off` at the call site (in conv2d_bn.cpp where sa_conv2d_int is called) could force the cheaper variant.

## Recommendation: **Option δ — fallback PE shrink per RISK_RULES R2 §1**

If pragma chasing fails after Options β/γ, fall back to Handler B: halve PE array 16×8 → 8×8 in `tiny_fpga_top.cpp`. Cost: ~2 hr B1 work + 2× throughput hit. Saves ~25K LUT guaranteed.

## What I'm doing

- URGENT_ASK_13 pushed.
- Standing by for Main's β/γ/δ patch.
- Vivado .xpr unchanged on disk (still has v2 sub-IP); ready for re-impl when new HLS IP arrives.

— Remote Claude, 2026-05-13T13:48:00+08:00
