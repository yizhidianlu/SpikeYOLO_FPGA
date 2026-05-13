# M2-W1 Synthesis & Implementation Complete

**Date**: 2026-05-13T18:00
**Owner**: B1 / Main Claude (主开发机) + Remote Claude (synth-runner)
**Trigger**: `fork/vivado/synth-runner` commit `b1eb5d9` (step6 final PASS)

## Status: ✅ PASS

ZYBO Z7-20 (xc7z020) bitstream produced end-to-end. spike accelerator IP fits the device with 14.4K LUT margin. Hardware platform exported for SDK / Vitis workflow consumption.

## Final post-impl resource

| Resource | Used | Cap | % | Verdict |
|---|---:|---:|---:|---|
| Slice LUT | **38838** | 53200 | **73.0%** | ✅ |
| Slice Register | 47912 | 106400 | 45.0% | ✅ |
| DSP48E1 | ~150 | 220 | 68% | ✅ |
| BRAM 18K | 2 | 280 | <1% | ✅ |
| BRAM 36K | (small) | 140 | <1% | ✅ |

## Timing (R1)

- Post-impl WNS: **−0.764 ns** at 100 MHz (172 / 134900 endpoints fail)
- Status: marginal — does NOT close at 100 MHz, M2-W2 task
- Recovery options:
  - `Performance_Explore` impl strategy retry (+ retiming variants)
  - 90 MHz clock fallback (~+1 ns slack, should close cleanly)
  - Pipeline register insertion at the critical path tail

## Bitstream artifacts (`hw/vivado/out/` via Git LFS)

| Path | Size | Purpose |
|---|---:|---|
| `system.bit` | 2.52 MB | PL bitstream for ZYBO Z7-20 boot |
| `system.xsa` | 607 KB | Vitis HW platform (BD + .bit + addr map) |
| `address_map.yaml` | YAML | Contract 4 — runtime DMA base addresses |

## Critical path tour (R2 saga summary)

10 URGENT_ASK rounds + 7 R2 patch iterations got us from Z-7020 fit blocker (URGENT_ASK_8) to PASS (b1eb5d9). Key inflection points:

| Phase | Key fix | Lesson |
|---|---|---|
| URGENT_ASK_8 | Option γ — drop HDMI/VDMA section | Sometimes the right knob is "do less", not "do better" |
| URGENT_ASK_9-10 | `axi_iface.h` macro parameter shadowing fix (`port=port` → `port=_port`) | Pre-2024 Vitis silently accepted broken pragmas; 2024.1 surfaced via `[HLS 207-5569]` warnings |
| URGENT_ASK_11 | `update_ip_catalog -disable_ip` + `-repo_path` for broken roe_framer auto_utils.tcl | Vivado install corruption can be worked around at project level |
| URGENT_ASK_12-13 | Discovered Vivado was running cached IP across iterations | `upgrade_ip [get_ips]` in build wrapper unlocked real Vivado-side propagation |
| URGENT_ASK_14-16 | v3-v6 RTL bit-identical because directive II < memory-dep-bound II | Directive II is a target, dep bound is the floor; `effective_II = max(directive, dep_bound)` |
| **URGENT_ASK_17 / v7** | Moved `SA_PIPELINE_II(1)` from wx loop to ci loop | Pipeline-position-change is the smallest source restructure that breaks memory dep chain |

## Throughput estimate (post v7)

Per-pixel cycles in `sa_conv2d_int` dropped from II=147 (Vitis dep-bound) to ~C_in_g (max 96 cycles for acb3 layers). End-to-end inference roughly **5-10x faster** than the v3-v6 design that didn't fit. Frame budget at 30 FPS = 33 ms/frame remains comfortable.

## M2-W2 backlog

1. **R1 timing closure** — try `Performance_Explore` impl strategy; if fail, 90 MHz fallback
2. **HDMI Section 10 rebuild** — Option γ (URGENT_ASK_8) was a strategic retreat; restore via Option α with `v_axis_to_video_out` + `v_tc` + `rgb2dvi` chain (deferred to M3-W11 by original plan, can pull forward if M2 timing closes early)
3. **Real-HW smoke test** — flash `system.bit` to ZYBO Z7-20, connect USB camera + HDMI panel, verify bitstream actually boots (no AXI hangup, AXI-Lite regs accessible, m_axi reads/writes DDR3 OK)

## A1 W10 distillation training (parallel track, NOT M2 blocker)

- Local RTX 5060 train2017 30-ep distillation: **epoch 4/30 done** (08:54 start, ~76 min/epoch), 25 epoch remaining → completes 5/15 dawn
- A800 cloud track: bootstrap in progress (train2017.zip unzip phase), preparing for batch=64 30-ep parallel run, ~2.5 hr ETA when launched
- Goal: replace W9 PTQ INT8 model (mAP 0.39%) with distilled INT8, target mAP ≥ paper baseline − 1pp

## Dependencies satisfied

- ✅ Contract 4 (address_map.yaml) — sw/runtime/ can compute DMA base offsets at boot
- ✅ Contract 5 (HW platform .xsa) — Vitis SDK can build PetaLinux + bare-metal apps
- ✅ HLS .xo (m_axi-correct, 5 gmem masters per build_bd.tcl)
- ⏳ R1 timing (M2-W2)
- ⏳ HDMI display (M3-W11)
- ⏳ Real-HW boot validation (M2-W2)

## Files / commits

- Final HLS: `fork/vivado/synth-runner@e9545e0` (v7 PIPELINE migration)
- Final report: `fork/vivado/synth-runner@b1eb5d9` (step6 PASS)
- Celebration REPLY: `fork/vivado/synth-runner@4c89869`

## Sign-off

Cron-based 3-min polling loop is STOPPED. /loop cron `510b274a` was cancelled earlier per user request; no further automated checks. Ad-hoc polling on user prompt only.

— Main Claude (主开发机, 2026-05-13T18:00)
