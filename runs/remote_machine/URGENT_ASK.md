# Urgent Ask — v12c JTAG-only still hits CPU-can't-halt, PC=0x100140 (CheckEFUSE entry)

## Status

v12c bitstream + ELF + boot.S CheckEFUSE-skip + cache-enable platform.c all in place. Yet:
- CPU still cannot be halted via `stop` after `con`
- PC samples at 0x100140 (CheckEFUSE entry — though patched to `b OKToRun`)
- mrd -force fails: "Cannot read memory if not stopped. Execution context is running"
- Status block at OUTPUT_BUF_PHYS+0x5400 is unreadable

## What's different now

| Run | bit | ELF main | WPWS | CPU halts? | UART | Status |
|---|---|---|---:|---|---|---|
| v12b initial | v12b | xil_printf | -0.755 | no | silent | PC=0x100154 (CheckEFUSE ldr) |
| v12b + boot.S | v12b | xil_printf | -0.755 | no | silent | PC=0x100120 (vector table) |
| v12b + main_jtag_only | v12b | jtag-only | -0.755 | no | silent | PC=0x100120 |
| **v12c + main_jtag_only** | v12c | jtag-only | **+0.445** | **no** | silent | **PC=0x100140** |

v12c FIXED the pulse-width violation but the CPU **still** hangs. New PC location (0x100140 vs prior 0x100154/0x100120) confirms the boot.S patch IS in the ELF — CPU reaches CheckEFUSE entry but doesn't advance past it.

## Hypothesis

The `b OKToRun` at CheckEFUSE entry SHOULD branch immediately. Yet PC stays at 0x100140 across multiple JTAG samples. Possibilities:

1. **CPU IS running through but JTAG sampling artifact**: Maybe CPU completes main(), enters WFI loop, and PC=0x100140 is where the last successful halt-arrest captured. Then the WFI loop is what makes subsequent halts fail (WFI uninterruptible until external IRQ wakes it). But this contradicts "Cannot read memory if running" → memory should be readable post-WFI.

2. **Cortex-A9 dual-core CPU1 issue**: Boot.S checks if we're CPU0 (line 156-159: `mrc p15,0,r1,c0,c0,5` to read MPIDR, `and r1,#0xf`, `cmp r1,#0`). If we're somehow on CPU1, the branch wouldn't go to CheckEFUSE. But Z-7020 starts on CPU0 by default. Unless ps7_init left state weird. Check via `targets -set` other CPU?

3. **JTAG state hung**: Maybe the JTAG-side stop request hangs from an earlier failed halt attempt and never recovers. `disconnect` + `connect` cycle might help.

## Proposed diagnostics

### Probe A — try halting via different mechanism

```tcl
catch { mb_stop }                 # MicroBlaze flavored halt (probably no-op)
catch { rrd cpsr }                 # Read CPSR — works on halted CPU; if fails, CPU isn't halted
catch { state }                    # current target state
```

### Probe B — explicit CPU0 target + JTAG step

```tcl
targets -set -filter {name =~ "*MPCore #0*"}
state                              # before
catch { stop -wait 5000 }          # 5s wait timeout
state                              # after
catch { rrd pc }                   # post-stop PC
catch { stp -n 1 }                 # single-step one instruction
catch { rrd pc }                   # PC after step
```

### Probe C — disconnect + power-cycle + reconnect

User physically power-cycles ZYBO. xsct disconnect, reconnect. Halt CPU IMMEDIATELY before any fpga/ps7_init. See if CPU halts cleanly from cold start.

### Probe D — different baseline: just `fpga`, no ELF, no ps7_init

```tcl
connect
targets -set -filter {name =~ "*MPCore #0*"}
fpga -file system.bit
stop
rrd pc                              # CPU0's PC at cold start of v12c bitstream
mrd 0x10000000 4                    # DDR read with no ps7_init — should fail (DDR not up)
```

If `stop` works here (no ELF running), then problem is specifically with ELF execution.

## Working tree

- ELF on disk at `vitis_workspace/spike_accel_w9_smoke/Debug/spike_accel_w9_smoke.elf` — objdump confirms `b OKToRun` at 0x100140 ✓
- system.bit + system.xsa fresh at 01:17, 01:18
- main.c overlay with main_jtag_only.c content
- main_jtag_only.c has `_unused_main_jtag_only` rename (no duplicate symbols)
- libxil.a updated with patched boot.o

## Fallback if all probes fail

Last-resort manual: **user enables SD-card boot mode**, FSBL boots, executes our ELF without any JTAG/DEVCFG hangs. Won't help with byte-exact but proves accelerator can run end-to-end. ~30 min user-side.

OR: **defer byte-exact board hash**; Main uses host-side gen_w9_golden when schema bridge is ready. We've validated the toolchain end-to-end already (bit + ELF + xsct flow all green); the remaining gap is mrd-during-WFI.

— Remote Claude, 2026-05-27T10:30:00+08:00
