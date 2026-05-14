# M3 — bitstream PRODUCED with R1 timing failure (closeable)

## TL;DR

After 12 iterations of HDMI BD restoration (v1 deferred → v12b passes), M3 produces a usable bitstream with these caveats:

- **R2 PASS**: 75.7% LUT, 90% DSP, 5.4% BRAM. Fits Z-7020 comfortably.
- **R1 marginal**: WNS -0.516 ns, 21/140923 endpoints fail (0.015%)
- **Pulse-width fail**: WPWS -0.755 ns, 9 endpoints on the HDMI clock domain. **HARD STOP** without further BD/clock changes.

Bitstream: `hw/vivado/out/system.bit` 2.52 MB (Performance_Explore strategy @ 90 MHz spike_accel + 142.857 MHz pixel clock).

## Per-iteration progression

| Iter | Knob | R2 slices over | WNS |
|---|---|---:|---:|
| v1-v8 | structural iterations (mute, IP-XACT, FREQ_HZ, TDATA) | — | n/a |
| v9 Area_Explore | full chain | 120 | n/a (didn't reach impl) |
| v10 Area_Explore | VDMA shrink | 88 | n/a |
| v11 Area_Explore | VDMA 32b + v_tc trim | 53 | n/a |
| **v12b default** | **+v_tc hardcoded** | **0 (PASS!)** | -1.043 |
| v12b Area_Explore | strategy retry | 0 | -0.704 |
| **v12b Performance_Explore** | **best strategy** | **0** | **-0.516** |

The marginal R2 was finally closed by v12 (Main's `ffc6838` — hardcode v_tc to 1080p60 + drop AXI-Lite). After that, R1 timing dominates.

## Pulse-width failure (the hard part)

```
WPWS(ns): -0.755   TPWS Failing Endpoints: 9
```

These 9 endpoints are on the high-speed TMDS serial clock domain (PixelClk × 5 = 714.3 MHz). At this frequency, FF clock pulse-width specs are violated by 0.755 ns. This is a **device-level limit**, not a placer-fixable issue.

To fix WPWS:
- **Reduce pixel clock**: 142.857 MHz → say 74.25 MHz (720p60 spec) → serial 371.25 MHz, much more headroom. But this drops display resolution.
- **Change rgb2dvi PLL config**: use a different multiplier so serial clock is lower.
- **Use a different TMDS encoder**: an HDMI IP that doesn't need 5× serial multiplication (e.g., DDR signaling at 2× would halve the serial rate).

## Working bitstream caveats

- spike_accel datapath @ 90 MHz: **clean** (no failing endpoints on this clock)
- HDMI display @ 142.857 MHz pixel / 714.3 MHz TMDS: **9 failing endpoints, marginal**
- Output may exhibit pixel-level glitches or wrong colors on some displays; some HDMI receivers more tolerant than others

## Path forward

### Option α — Ship v12b bit, downscale HDMI to 720p in software

Use the produced bitstream as-is. SW configures v_tc-equivalent timing inside vdma's framebuffer addresses to use 720p timing instead of 1080p. The hardware can support it because the rgb2dvi PLL covers a range.

### Option β — Rebuild BD with 720p config

Modify build_bd.tcl Section 4 v_tc:
- `CONFIG.VIDEO_MODE {720p}` (was 1080p)
- Adjust PCW_FPGA1_PERIPHERAL_FREQMHZ from 148.5 → 74.25
- rgb2dvi kClkRange from 1 (120-240 MHz) → 0 (25-120 MHz)

Should close all timing. Throughput hit: half resolution.

### Option γ — Run final Performance_ExtraTimingOpt or aggressive_directed strategies

Try a few more impl strategies. May close last 0.5 ns. But pulse-width fail is structural — strategy can't fix it.

### Option δ — Push v12b as-is (M3 partial pass)

Document this as M3 milestone with caveat. SW W9 smoke test will work on board because spike_accel domain timing is clean. HDMI demo can use 720p workaround.

## My recommendation

**Push v12b + URGENT_ASK_30 with options α/β**. Main decides which display mode to ship.

— Remote Claude, 2026-05-15T02:13:00+08:00
