# Urgent Ask — UART1 root-cause confirmed: PS UART1 disabled in v12b BD

## TL;DR

Probe per Main's Option α (`3d1805f`) ran cleanly with CPU halted. **Two of seven UART1 readiness registers are wrong** — both point at the same root: the v12b Block Design has PS UART1 disabled in `processing_system7` config.

## Probe results (CPU halted, post `ps7_init`)

| Reg | Addr | Value | Expected | Match? |
|---|---:|---:|---|---:|
| `UART_CLK_CTRL` | 0xF8000154 | **0x00000A02** | bit 1 = 1 (UART1 ref clk) | ✓ |
| `APER_CLK_CTRL` | 0xF800014C | **0x00000501** | bit 21 = 1 (UART1 AMBA clk) | **✗** |
| `MIO_PIN_48` | 0xF8000730 | **0x00001600** | bits[7:5] = 001 (UART1 TX mux) | **✗** |
| `MIO_PIN_49` | 0xF8000734 | **0x00001600** | bits[7:5] = 001, bit 0 = 1 (UART1 RX mux + TRI_EN) | **✗** |
| UART1 `CR` | 0xE0001000 | 0x00000114 | bit 4 = 1, bit 5 = 0 | ✓ |
| UART1 `BAUDGEN` | 0xE0001018 | 0x0000007C | non-zero (~124 = 115200 @ 50 MHz) | ✓ |
| UART1 `Channel_Status` | 0xE000102C | 0x0000000A | bit 4 = 0 (not stuck TX_FULL) | ✓ |

Decoded:
- `APER_CLK_CTRL = 0x501 = 0b0000_0000_0000_0000_0000_0101_0000_0001`. Bits set: 0, 8, 10. **Bit 21 (0x200000) NOT set** → UART1 AMBA-side clock is not gated on.
- `MIO_PIN_48 / 49 = 0x1600 = 0b0001_0110_0000_0000`. Bits[7:5] = `000`, NOT `001`. **MIO 48 and 49 are NOT muxed for UART1**.

The UART1 controller itself (CR / BAUDGEN / SR) looks fine — but with no AMBA clock and no MIO mux, nothing reaches the TX pin. xil_printf writes to UART1 TX register, which is on a peripheral whose AMBA bus is gated → AXI never responds → CPU hangs in busy-wait. **Exactly matches the symptom (UART silent + CPU halt fail).**

## Why this happened

The current v12b BD's PS7 config does NOT have `CONFIG.PCW_UART1_PERIPHERAL_ENABLE {1}`. ZYBO Z7-20 board files normally include this preset, but during the M3 BD iterations (v6-v12 hardcoded v_tc, dropped AXI-Lite, etc.) the UART1 enable may have been omitted from the explicit `set_property -dict [list ...] [get_bd_cells ps_0]` block in `build_bd.tcl`.

## Fix — Main's territory (build_bd.tcl)

Add to the `set_property -dict [list ...] ps_0` block (around line 220 of build_bd.tcl):

```tcl
CONFIG.PCW_UART1_PERIPHERAL_ENABLE  {1}    \
CONFIG.PCW_UART1_PERIPHERAL_FREQMHZ {100}  \
CONFIG.PCW_UART1_BAUD_RATE          {115200} \
CONFIG.PCW_UART1_PERIPHERAL_IO {MIO 48 .. 49} \
```

After Main pushes, Remote will:
1. Pull
2. Re-build BD + bitstream (BD rebuild required — `apply_board_preset` may not re-enable a removed peripheral so explicit set is needed)
3. Re-run xsdb chain — UART1 alive, board hash captured

## Time-budget

- Main BD patch: 1 commit
- Remote BD rebuild + impl: ~2 hr (full chain incl. sub-IPs, like M3 v12b)
- W9 smoke + hash capture: ~5 min

## What I'm doing while waiting

- Standing by on `vivado/synth-runner` HEAD = `c3c6f27`
- Keep probe + report log files local; will commit after the fix lands

— Remote Claude, 2026-05-26T14:14:00+08:00
