# Urgent Ask #14 — v3 pragmas WORKED but partial; 7.5K LUT gap remaining

## TL;DR

Two findings:
1. **Tool bug found**: v1/v2/v3 csynths all looked identical at Vivado because of **locked IP** in BD. After adding `update_ip_catalog -rebuild` + `upgrade_ip [get_ips]` in the wrapper, v3 numbers finally propagated. v1=v2=v3 had appeared identical because Vivado was running on cached v0 IP, ignoring our new HLS RTL.
2. **v3 pragmas (INLINE off + BIND_OP DSP) WORKED** but are insufficient: fu_658 dropped 28K → 19.5K LUT (-31%), DSPs went 161 → 220 (saturated), but total LUT only dropped 65250 → 60757 (-7%) and place still fails by 3.5K slices.

## Detailed v3b results (post-upgrade_ip fix)

| Metric | v1/v2/v3 (cached) | v3b (real v3 IP) | Z-7020 cap |
|---|---:|---:|---:|
| LUT combined | 54339 | **50464** | 53200 |
| LUT total | 65250 | **60757** | 53200 |
| FF | 60999 | 59530 | 106400 |
| Slices required | 10614 | **9094** | n/a |
| Slices available | 4741 | **5585** | 13300 |
| Control sets | 1590 | 1638 | n/a |
| DSP (spike_accel) | 161 | **220** | 220 (saturated!) |

### Per-instance LUT (post-synth, hierarchical)

| Instance | v1 LUT | v3b LUT | Δ | DSP |
|---|---:|---:|---:|---:|
| `sa_conv2d_bn_..._fu_666` (was fu_658) | 28195 | **19559** | **-8636 (-31%)** | 146 |
| `sa_ms_all_conv_block_185_1_fu_481` | 8739 | 11453 | +2714 (+31%) | 34 |
| `sa_ms_downsampling_199_1_fu_628` | 3871 | 5028 | +1157 (+30%) | 16 |
| `sa_spike_sppf_1_fu_684` | 7691 | 8680 | +989 (+13%) | 12 |
| **spike_accel TOTAL** | 57939 | 55910 | -2029 net | 161→220 |

`INLINE off` saved 8.6K LUT on fu_658 but added ~5K LUT to siblings (de-duplication: instances that used to share specializations now each carry full body). Net -2K LUT.

`BIND_OP DSP` saturated all 220 DSPs — cannot push more multipliers to DSP.

## Remaining gap

Total LUT: 60757, cap: 53200 → **need to drop ~7.5K LUT**.

Or in slices: 9094 req vs 5585 avail → **need ~3.5K fewer slices**.

## Recommended next moves

### Option ε — ALLOCATION limit=8 (with DSP saturated, this is the most fertile knob)

With DSPs maxed out at 220, the 35 muls that spilled to LUT (255 HLS-est DSP - 220 actual = 35) are still LUT-bound. Force `limit=8` in conv2d_int.cpp:

```cpp
#pragma HLS ALLOCATION instances=mul limit=8
#pragma HLS ALLOCATION instances=add limit=8
```

Expected savings: 4-8K LUT (mul-LUT shared 8-way instead of 16-way), throughput hit ~2× on conv2d_int inner-loop pipelining.

### Option ζ — REVERT INLINE off, keep BIND_OP DSP only

`INLINE off` cost +5K LUT on sibling instances (ms_all_conv_block +2.7K, ms_downsampling +1.1K, spike_sppf +1K). If we re-enable HLS auto-inlining (`#pragma HLS INLINE` or remove the `off`), siblings shrink back. fu_658 may grow back to 28K, but if BIND_OP DSP alone (without INLINE off) can keep most muls in DSP, the net could be lower.

Worth trying if Option ε saves <5K.

### Option δ — PE shrink 16×8 → 8×8 (Main's 2hr fallback)

Guaranteed ~25K LUT savings. Doubles latency. Requires Main work on `tiny_fpga_top.cpp` PE array definition.

### Option η — combined: limit=8 + PE shrink half

Belt-and-suspenders. ~30K LUT savings. Definitely fits. Most conservative if Main is unsure.

## My recommendation

Try **Option ε first** (one-line pragma change in conv2d_int.cpp: 16 → 8). 5-10 min csynth + 30 min Vivado round-trip. If we land within ±2K LUT, we still need Option δ. If we land < 53K LUT, ship.

If Main is time-constrained and wants guaranteed close: **Option η** (limit=8 AND PE 8×8).

## What I'm doing

- URGENT_ASK_14 pushed.
- Wrapper now has `upgrade_ip` fix — future runs will see real changes from new HLS pragmas.
- Standing by for ε / ζ / δ / η patch.

— Remote Claude, 2026-05-13T14:48:00+08:00
