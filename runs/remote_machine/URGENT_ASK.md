# Urgent Ask — Probe H + I both fail; final accept defer

## TL;DR

Tried both Probe H (mrd -memmap / -address-space PA) and Probe I (HW bp at WFI / bkpt instruction). All require halted CPU; halt fails during execution; full reset kills DDR.

## Probe H — mrd via DAP-MEM-AP

Vitis 2024.1 `mrd` valid options: `-target-id -force -size -value -bin -file -arm-dap -arm-ap -address-space -unaligned-access`.

`mrd -address-space AP0/1/2/3` → ERR: "unknown or ambiguous address space: must be PA"

So the only valid address-space on Cortex-A9 here is **PA** (Physical Address). And `mrd -address-space PA` still requires halted CPU:
```
PA fail: Cannot read memory if not stopped. Execution context is running
```

The `-memmap` flag from Main's example doesn't exist in this Vitis 2024.1 build. There is no exposed DAP-MEM-AP-direct memory read for Cortex-A9 in this XSCT version.

## Probe I — HW breakpoint + bkpt instruction

```tcl
bpadd -addr 0x100e0c   ;# success-path WFI
bpadd -addr 0x100d84   ;# timeout-path WFI
con
after 10000
# PC after wait: 00100140  ← still at CheckEFUSE entry, never reached WFI
```

Also tried injecting `__asm__ volatile("bkpt #0")` directly in main() before WFI. CPU still doesn't auto-halt (DBGEN signal may be low; bkpt traps to Prefetch Abort handler rather than halting).

Either:
- CPU genuinely stuck at 0x100140 (CheckEFUSE entry — the `b _skip_efuse_read` branch never completes)
- OR `rrd pc` returns stale value from last successful halt (cold halt at boot ROM), and CPU is actually running but invisible

Without halt working, we can't distinguish.

## What we DO know

- Toolchain fully validated end-to-end through `dow`+`con`
- `rst -dap + rst -srst` consistently unlocks halt on cold board (proven each run)
- DDR controller is in same reset domain as `rst -srst` (mrd fails after srst)
- CPU running prevents any mrd (even -address-space PA)
- Hardware BPs and software BPs don't auto-halt CPU (DBGEN may need explicit assertion)

## Final accept

Per Main's e59c0af M3 PBT close + your fallback in `d7c2983` ("真的接受 defer"), final position:

- **board fnv1a32 hash CANNOT be captured** on this JTAG link with this Vivado/Vitis install
- **toolchain VALIDATED** — bitstream + ps7_init + weights mwr + ELF dow + con all work
- **host hash `0x7474fd3c`** (Main shared at 2026-05-28T14:10) is the authoritative ground truth for v12c + PBT weights + ramp input
- M3 PBT deploy remains PARTIAL CLOSE per `e59c0af`

Standing by for any new direction or close-out signal.

— Remote Claude, 2026-05-28T14:35:00+08:00
