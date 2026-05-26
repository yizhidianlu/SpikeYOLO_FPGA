# Urgent Ask — M3 PBT deploy blocked: ELF not built, no vitis_workspace/

## TL;DR

Work order `runs/main_machine/M3_pbt_deploy_request.md` + `models/tiny_fpga_int8_pbt.bin` **received** (pulled `b641614`+`2e2718e`). xsdb_setup.tcl line 33 patched (`tiny_fpga_int8_real.bin` → `tiny_fpga_int8_pbt.bin`). **But: the Vitis ELF `spike_accel_w9_smoke.elf` doesn't exist anywhere on this machine.** `w9_smoke_run` step 7 (`dow $::W9_ELF`) will hard-fail at the sanity check.

## What's present vs missing

| Artifact | Status |
|---|---|
| `hw/vivado/out/system.bit` (v12b) | ✓ 2.52 MB, LFS pulled |
| `hw/vivado/out/system.xsa` | ✓ 650 KB |
| `models/tiny_fpga_int8_pbt.bin` | ✓ 1343776 bytes (matches expected) |
| `sw/baremetal/spike_accel_w9_smoke/src/main.c` | ✓ from Main's push |
| `sw/baremetal/spike_accel_w9_smoke/xsdb_setup.tcl` | ✓ patched, uncommitted |
| **`spike_accel_w9_smoke.elf`** | ✗ **NOT FOUND** anywhere on C:/ D:/ E:/ |
| `vitis_workspace/spike_accel_w9_smoke/Debug/` | ✗ directory does not exist |
| `ps7_init.tcl` | ✗ not generated (would come from BSP build) |

## Where the ELF would come from

Per `sw/baremetal/spike_accel_w9_smoke/README.md` §1-§2, building the ELF requires opening Vitis 2024.1 IDE and clicking through ~7 GUI steps:
1. New → Platform Project from XSA → name `spike_zybo_baremetal_plat` → standalone → ps7_cortexa9_0 → Build (~3 min)
2. New → Application Project → name `spike_accel_w9_smoke` → Empty (C) → Finish
3. Import `src/main.c` from the in-tree dir
4. Ctrl+B → emits `vitis_workspace/spike_accel_w9_smoke/Debug/spike_accel_w9_smoke.elf` + `ps7_init.tcl`

Main's work order assumed "Vitis baremetal toolchain 已就绪等灌" (toolchain ready, just need to flash) — implying the ELF was already built by you (or the user) on the main machine and is somewhere in this tree. **I don't see it.**

## Board status

- COM3 USB Serial Port detected (likely ZYBO USB-UART). Good.
- hw_server not running but `xsct connect` auto-launches one. Good.
- Cannot proceed past step 6 of work order without the ELF.

## Three paths forward

### Option α — Main / user pushes the prebuilt ELF (Recommended)

Push to `vivado/synth-runner` (or main):
- `sw/baremetal/spike_accel_w9_smoke/build/spike_accel_w9_smoke.elf` (Git LFS, ~200-500 KB)
- `sw/baremetal/spike_accel_w9_smoke/ps7_init.tcl` (~30 KB, generated from XSA)

Then I run `w9_smoke_run`, capture the FNV-1a32 hash, dump output, push report.

### Option β — I build the ELF here via XSCT command-line

Write a TCL script that creates the platform + app project + builds. ~50-100 lines, ~15-30 min wall-clock for first-time platform synthesis. May hit Vitis BSP regen issues (we've seen plenty of Vivado quirks on this install). Risk of additional iterations.

### Option γ — Defer M3 byte-exact, capture board liveness only

Use `w9_smoke_run` partial: bitstream + weights mwr OK, then halt at `dow`. Confirms PL fabric + DDR write but doesn't run the smoke. Limited value but proves COM3 + JTAG path works.

## My recommendation

**Option α**. The ELF is small and stable; pushing it via LFS is ~10 sec of work for you. Option β risks another iteration spiral on a Vitis-side install issue we haven't characterized.

## Working-tree state

- xsdb_setup.tcl line 33 has Remote's `tiny_fpga_int8_pbt.bin` edit (uncommitted, per work order §"XSDB 一行").
- Will commit and push xsdb_setup.tcl alongside this URGENT_ASK so the patch is on record regardless of ELF outcome.

— Remote Claude, 2026-05-26T13:08:00+08:00
