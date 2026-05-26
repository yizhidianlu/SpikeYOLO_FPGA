# Step PBT Deploy — partial (toolchain green, board UART silent)

## Status

| Phase | Status | Notes |
|---|---|---|
| Pull `tiny_fpga_int8_pbt.bin` | ✅ DONE | 1343776 bytes, matches expected |
| Patch xsdb_setup.tcl `_real.bin → _pbt.bin` | ✅ DONE | committed |
| Build Vitis platform + app | ✅ DONE | new `build_w9_smoke.tcl` script under sw/baremetal/.../ |
| Produce `spike_accel_w9_smoke.elf` | ✅ DONE | 254124 bytes |
| XSCT: connect JTAG + program bitstream | ✅ DONE | hw_server launches, finds ZYBO target |
| XSCT: ps7_init (clocks + DDR) | ✅ DONE | DDR readback shows weights loaded |
| XSCT: download ELF + con | ✅ DONE | PC = 0x00100000 set, con returned |
| **Capture board UART** | ❌ **SILENT** | COM3 @ 115200 8N1 opened but no bytes for 60 s |
| Halt CPU for dump | ❌ FAIL | `stop` → "Cannot halt processor core, timeout" |
| Dump 21504-byte feat_out.bin | ❌ blocked by halt fail | — |
| **board fnv1a32 hash** | ❌ **not captured** | — |

## What worked end-to-end

XSCT got further than ever before. Full flow log at `runs/remote_machine/w9_pbt_xsct.log`:

```
[w9-smoke] programming bitstream...
[w9-smoke] sourcing ps7_init.tcl...
[w9-smoke] loading weights into DDR @ 0x10000000...
[w9-smoke] DDR @ 0x10000000 readback (4x u32):
  10000000:   02040100
  10000004:   00070101
  10000008:   00180003
  1000000C:   00003100
[w9-smoke] downloading elf...
[w9-smoke] elf loaded, PC = pc: 00100000
[w9-smoke] >>> con — watch your UART terminal for results
Cannot halt processor core, timeout
```

DDR readback **proves** XSDB load worked (first 16 weight bytes match `tiny_fpga_int8_pbt.bin` first 16 bytes — non-zero, varying values, not all 0xFF or 0x00).

## What's broken

**`con` returns successfully and the CPU is "running", but**:
1. **UART is silent** — 60 s capture on COM3 yields 0 bytes (file is empty 0 B)
2. **CPU cannot be halted via JTAG** — `stop` times out after ~5 s

These two symptoms together suggest the CPU is in an unrecoverable state, NOT idle. Likely candidates:

1. **AXI-Lite read to `SA_REG_BASE = 0x43C00000` hangs**. main.c reads spike_accel control regs to poll `ap_done`. If the AXI transaction never completes (e.g. due to v12b's marginal timing closure on PS↔HP path, or spike_accel's interrupt logic stuck), the CPU stalls indefinitely waiting for the AXI bridge. JTAG can't preempt a hung AXI access.
2. **Early crash before any `xil_printf`**: main.c's `init_platform()` → `Xil_DCacheEnable()`. If DCache enable hits a memory-fault, CPU may end up in undefined-handler infinite loop. But the proper `platform.c` is now in place (cache enable + uart-by-ps7_init).
3. **UART not actually wired to COM3 in v12b bitstream**: COM3 may be a different port (e.g. PMOD UART, USB-to-serial bridge). Need to verify which physical port the v12b BD wires PS_UART0 to.

## My infrastructure changes (committed below)

- `sw/baremetal/spike_accel_w9_smoke/xsdb_setup.tcl`:
  - `tiny_fpga_int8_real.bin → tiny_fpga_int8_pbt.bin` (per work order)
  - Escape `[w9-smoke]` literals in `puts` (TCL bracket parsing fix)
  - Target filter `*Cortex-A9 #0*` → `*Cortex-A9 MPCore #0*` (Vitis 2024.1 emits "MPCore")
  - `print -e` (deprecated) → `rrd pc`
- `sw/baremetal/spike_accel_w9_smoke/build_w9_smoke.tcl` (new): scripted Vitis platform + app build for future deploys
- `sw/baremetal/spike_accel_w9_smoke/app_build_only.tcl` (new): rebuild ELF after src edits
- `runs/remote_machine/capture_uart.ps1`: COM3 → log with terminator detection
- `runs/remote_machine/w9_smoke_oneshot.tcl`: XSCT wrapper with global `source $::W9_PS7_INIT` workaround (xsdb_setup.tcl sources it inside the proc → vars go local)
- `vitis_workspace/spike_accel_w9_smoke/src/platform.c`: init_platform/cleanup_platform with cache enable (Empty template doesn't emit these; main.c references them; without them link fails)

## Asks for Main

1. **Verify which COM port** the v12b BD's PS_UART0 reaches. If PMOD UART instead of USB-UART bridge, Remote may need a different physical cable. (Check `hw/vivado/out/system_bd_dump.tcl` or `address_map.yaml` for UART_0 EMIO/MIO routing.)
2. **Confirm spike_accel reg-poll won't hang on v12b's marginal R1 timing**. If you've seen this elsewhere, document the workaround.
3. **Optional fallback**: rebuild app with `xil_printf` calls BEFORE the first AXI read, so if AXI hangs we still see the banner. main.c likely does this; verify with `objdump -d` if you have it locally.

Standing by; full XSCT + UART logs pushed alongside this report.

— Remote Claude, 2026-05-26T13:46:00+08:00
