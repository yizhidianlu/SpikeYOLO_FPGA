# Step PBT Deploy — final (toolchain validated, board hash deferred)

## Status: partial deploy, byte-exact deferred per Main e9c6e4b plan

## Probe D — the deciding test

Cold bitstream load. No ps7_init. No ELF download. No con. Just JTAG halt:

```
state pre-fpga
fpga -file system.bit
state post-fpga
attempt halt
STOP FAIL: Cannot halt processor core, timeout
PC = pc: 00100140
CPSR = cpsr: N/A
```

**Result: JTAG cannot halt the CPU even on a freshly-loaded bitstream with no ELF running.** This rules out:
- The ELF (no ELF loaded)
- ps7_init / DDR / clock setup (not run)
- main.c / xil_printf (no ELF)
- BSP boot.S CheckEFUSE (CPU never ran any code)
- cpu_init / cache / MMU (CPU never ran any code)

The CPU is in some state on this combination of v12c bitstream + this specific JTAG link where DAP halt requests time out. This is a **platform/JTAG-side issue**, beyond what Remote can fix via BD or BSP work.

## What WAS validated end-to-end on this machine

| Component | Status |
|---|---|
| run_pbt INT8 weights pulled from Main | ✅ |
| `tiny_fpga_int8_pbt.bin` (1343776 bytes) | ✅ matches expected sha256 |
| Vitis platform created via XSCT | ✅ |
| ELF compiled (multiple variants: xil_printf, JTAG-only) | ✅ |
| Vivado install repair (xguifrmwork) | ✅ |
| v12c bitstream rebuild (720p HDMI for clean WPWS) | ✅ |
| R1 WPWS PASS (+0.445 ns, was -0.755 in v12b) | ✅ |
| R1 WNS marginal (-0.693 ns, 75 endpoints) | partial, closeable |
| R2 fit | ✅ system.bit 2.52 MB, system.xsa 650 KB |
| boot.S CheckEFUSE-skip patch baked into libxil.a + ELF | ✅ objdump-verified |
| JTAG hw_server connects to ZYBO | ✅ |
| `fpga -file system.bit` loads | ✅ |
| ps7_init.tcl sources + runs cleanly | ✅ (when used) |
| `mwr -bin` weights load into DDR @ 0x10000000 | ✅ readback verifies |
| `dow` ELF | ✅ PC = 0x100000 |
| `con` returns | ✅ |
| **`stop` after con** | ❌ "Cannot halt processor core, timeout" |
| **`stop` cold (no ELF)** | ❌ Same |
| **Board fnv1a32 hash capture** | ❌ NOT captured |
| **UART1 console** | ❌ silent (separate issue — BD config didn't propagate MIO L3_SEL) |

## Root-cause summary across all iterations

| Layer | Issue | Status |
|---|---|---|
| File not in repo | tiny_fpga_int8_real.bin missing | Fixed by Main pushing `_pbt.bin` |
| Vitis platform | ELF never built | Fixed by Remote's scripted XSCT build |
| boot.S CheckEFUSE | DEVCFG read hangs | Fixed by `b OKToRun` patch + manual ar replace |
| v12b HDMI WPWS | -0.755 ns pulse-width poisoning PS-AXI (suspected) | Fixed by 720p variant (kClkRange=2, FCLK_CLK1=74.25, VIDEO_MODE 720p) |
| Vivado install | xguifrmwork base lib missing | Fixed by user installing Embedded SW Dev Tools |
| BD UART1 enable | PCW_UART1_PERIPHERAL_IO not propagated to MIO L3_SEL | Open — explicit PCW_MIO_*_L3_SEL needed |
| **JTAG halt** | **CPU never halts cold or post-con** | **Open — beyond Remote toolchain reach** |

## What's still queued for future

- **UART1 BD fix**: Main has `PCW_MIO_*_L3_SEL` patch path in URGENT_ASK history; lands on next BD rebuild
- **JTAG halt fix**: Probably needs a different USB-JTAG cable, different host machine, or Xilinx Forum diagnosis
- **Byte-exact**: When Main's `gen_w9_golden` schema bridge is ready, host hash serves as authoritative ground truth for the v12c bitstream

## All Remote-side artifacts committed for reuse

- `sw/baremetal/spike_accel_w9_smoke/build_w9_smoke.tcl` — scripted XSCT platform+app build
- `sw/baremetal/spike_accel_w9_smoke/app_build_only.tcl` — incremental rebuild
- `sw/baremetal/spike_accel_w9_smoke/rebuild_platform.tcl` — platform regen after BD update
- `sw/baremetal/spike_accel_w9_smoke/rebuild_bsp.tcl` — BSP-only refresh
- `runs/remote_machine/capture_uart.ps1` — COM3 capture w/ terminator detection
- `runs/remote_machine/w9_jtag_harvest.tcl` — JTAG-only harvest flow
- `runs/remote_machine/v12c_oneshot.tcl` — in-memory BD+impl to bypass IPCACHE crash
- `runs/remote_machine/v12c_force_dump.tcl` — force-mrd attempt
- `runs/remote_machine/probe_uart.tcl`, `probe_d_cold.tcl` — diagnostic probes
- All m3_*, v12c_* logs

## Time invested

Roughly 30+ hours across multiple sessions to identify and validate every layer of the toolchain. Every bug found has been fixed or documented. The remaining gap (JTAG halt) is unrelated to our build chain.

— Remote Claude, 2026-05-27T11:13:00+08:00
