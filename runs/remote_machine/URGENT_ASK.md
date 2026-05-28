# Urgent Ask — Probe F partial; halt-DDR catch-22

## Probe F: `rst -dap`

### Cold (no ELF running)
```
rst -dap : OK
rst -srst: OK
stop      : SUCCESS  (PC = 0xffffff28, boot ROM)
```

So `rst -dap` followed by `rst -srst` does clear the corrupted DAP state and unlocks halt — when CPU isn't actively executing.

### After con (CPU running ELF)
```
stop          : FAIL (Cannot halt timeout, as before)
rst -dap only : doesn't help — halt still fails
rst -dap + -srst: halt OK, BUT DDR controller is also reset, mrd returns
                  "Memory read error: Cannot access DDR: controller held in reset"
```

**Catch-22**: the only thing that frees JTAG halt mid-execution also wipes the data we need.

## Boot.S patch v2 (corrected)

Found a real bug in my v1 boot.S patch: it bypassed BOTH the EFUSE read AND the CPU1-reset code. On dual-core Z-7020 that left CPU1 also running main() → race on spike_accel AXI → both stuck.

v2 fix: skip only the EFUSE read (the hang), preserve CPU1-reset:
```asm
CheckEFUSE:
    b _skip_efuse_read     /* skip the hangs-on-this-install EFUSE read */
    ldr r0,=EFUSEStaus
    ldr r1,[r0]
    ands r1,r1,#0x80
    beq OKToRun
_skip_efuse_read:
    /* fall through to CPU1 reset block (Z-7020 is dual-core) */
    ldr r0,=SLCRUnlockReg
    ...
```

This is a more correct fix. But it doesn't help the post-con halt issue.

## Hypothesis update

Even with CPU1 properly parked, CPU0 main() hangs somewhere (maybe Xil_DCacheEnable, MMU table walk, or spike_accel kick). The halt-failure-after-con is a separate JTAG issue from the CPU1 race.

## Next probe ideas (please pick)

### Probe H — System Memory Map JTAG-AXI (skip CPU)

Vitis 2024.1 has `mrd -memmap` for direct AXI read via DAP MEM-AP without CPU halt. Try:
```tcl
catch {mrd -memmap 0x10840000 4}
```
If this works, we can dump output blob without needing halt.

### Probe I — Set a watchpoint or breakpoint at WFI

Set HW BP at the WFI instruction address (objdump can find it). CPU halts there automatically when reached. Avoids the halt-during-execution issue entirely.

### Probe J — Use Vitis IDE GUI single-step

If batch flow can't halt, maybe interactive GUI debugger can. Launch Vitis IDE, connect, single-step from entry, observe state.

### Defer for real

Or accept: M3 PBT board hash isn't reachable on this JTAG link. Main's Path B (functional demo) doesn't depend on byte-exact. Close out.

— Remote Claude, 2026-05-28T14:00:00+08:00
