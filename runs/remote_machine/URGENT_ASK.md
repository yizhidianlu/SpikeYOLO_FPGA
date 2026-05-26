# Urgent Ask — CPU hangs at PC=0x100154 (CheckEFUSE in _start), BEFORE main()

## TL;DR

Option β JTAG-only path executed:
1. ✓ `main_jtag_only.c` overlaid on main.c, ELF built (47904 bytes, no xil_printf)
2. ✓ xsct chain: bitstream + ps7_init + weights mwr + ELF dow + con
3. ✗ **CPU still stuck at PC=0x100154** — identical to the previous UART build
4. ✗ `stop` times out; status block at OUTPUT_BUF_PHYS+0x5400 never written
5. ✗ 21504-byte output blob cannot be dumped (mrd needs halted CPU)

**Critical new finding:** `arm-none-eabi-objdump` shows PC=0x100154 sits inside `CheckEFUSE` proc (entry 0x100140), which is part of the Xilinx standalone BSP's **crt0 _start** sequence — runs BEFORE main(). CheckEFUSE reads `0xF8007080` (DEVCFG.MISC_CTRL.PS_VERSION) to detect silicon revision.

```
00100140 <CheckEFUSE>:
  100140:	e59f02ec 	ldr	r0, [pc, #748]	; 100434 <finished+0x14>
  ...
  100154:                                  ← CPU is parked here
```

This means **the hang is NOT in xil_printf** — it's in the BSP startup itself, before any user code runs.

## Implications

The UART1-disabled hypothesis from `697922c` is **correct** as a separate finding, but it's not the cause of the hang. The CPU never gets to the user-level xil_printf call.

The CheckEFUSE hang implies **the CPU cannot complete a read of DEVCFG (0xF800_7000) via the PS-side AXI**. Possible root causes:

1. **DEVCFG clock gated off** — ps7_init missed enabling DEVCFG AMBA clock. Probe: `mrd 0xF800014C` bit 6 (DEVCFG_CPU_1XCLKACT). If 0, ps7_init is incomplete.
2. **v12b PL bitstream interferes with PS-side AXI** — should not, since DEVCFG is PS-internal, but the marginal R1 timing in v12b (WPWS -0.755 ns) might cause stuck transactions in the L2 cache controller.
3. **DAP / debug logic conflict** — JTAG attached but DAP not in the right state. Less likely.

## What I have for Main

| File | Size | Status |
|---|---:|---|
| `vitis_workspace/spike_accel_w9_smoke/Debug/spike_accel_w9_smoke.elf` | 47904 B | Built (JTAG-only variant) |
| `runs/remote_machine/w9_jtag_harvest.tcl` | new | XSCT harvest wrapper |
| `runs/remote_machine/w9_pbt_harvest.log` | new | latest run trace |
| `vitis_workspace/spike_accel_w9_smoke/src/platform.c` | new | enable_caches stub |
| `sw/baremetal/.../src/main.c` | overwritten | TEMPORARILY content of main_jtag_only.c (preserve via `git checkout HEAD~N`) |

## Proposed next probe (Option α extended)

Add to next probe TCL, halt CPU before downloading ELF (which works), then check:

```tcl
puts "DEVCFG_CPU_1XCLKACT (bit 6 of APER_CLK_CTRL):"
mrd 0xF800014C 1
puts "DEVCFG MISC_CTRL (this is what CheckEFUSE reads):"
mrd 0xF8007080 1
puts "DEVCFG STATUS (life-check):"
mrd 0xF8007000 1
```

If `0xF800014C bit 6 = 0` → DEVCFG clock not enabled by ps7_init → BD-side fix (PCW_DEVCFG_PERIPHERAL_ENABLE) OR a different startup_code shim that skips CheckEFUSE.

If clock IS enabled but the read still hangs → suspect L2/AXI deadlock from v12b timing → would need M3 v13 BD rebuild with timing fix, which is blocked by `xguifrmwork` install rot.

## My recommendation

**Option ε** — work around CheckEFUSE entirely:

Use Vitis baremetal "crt0 lite" or write a minimal startup assembly stub that:
1. Sets up SP
2. Skips CheckEFUSE / silicon-version detection
3. Branches directly to main()

This bypasses the broken DEVCFG read entirely. Cost: ~30 lines of ARM asm + linker script adjustment. Main's territory (sw/baremetal/).

If Main provides the lite-crt0, Remote rebuilds and re-runs harvest.

## Working-tree state

- `main.c` overwritten (user-authorized). Restore via `git checkout` once smoke completes.
- `vitis_workspace/spike_accel_w9_smoke/Debug/spike_accel_w9_smoke.elf` is the JTAG-only build.
- v12b 1080p `system.bit` at `c5ca631` unchanged.

— Remote Claude, 2026-05-26T15:00:00+08:00
