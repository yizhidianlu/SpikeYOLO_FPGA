# Step PBT Deploy — final report (board ground truth NOT captured)

## Status: blocked

| Phase | Status | Notes |
|---|---|---|
| Pull `tiny_fpga_int8_pbt.bin` + work order | ✅ | b641614 |
| Patch xsdb_setup.tcl → `_pbt.bin` | ✅ | committed |
| Build Vitis platform + app + ELF via XSCT | ✅ | new tooling under sw/baremetal/ |
| `init_platform` stub for Empty template | ✅ | committed to vitis_workspace |
| XSCT JTAG flow (bitstream + ps7_init + weights mwr + ELF dow + con) | ✅ | clean every time |
| **Capture board UART** | ❌ | UART1 disabled in v12b BD (Main fixed in 5f2ea71) AND CPU never reached main() |
| **board fnv1a32 hash** | ❌ NOT CAPTURED | — |

## Root-cause chain (in order of discovery)

1. **`tiny_fpga_int8_real.bin` not in repo** → xsdb_setup.tcl referenced an obsolete weights file. Patched to `tiny_fpga_int8_pbt.bin`.
2. **No `spike_accel_w9_smoke.elf`** → Wrote `build_w9_smoke.tcl` XSCT script to scripted-build the platform + app + ELF. Worked after 4 iterations (domain naming, template selection, init_platform stub).
3. **xsdb_setup.tcl bracket-puts TCL parse errors** → Patched.
4. **target filter `*Cortex-A9 #0*` vs actual `*Cortex-A9 MPCore #0*`** → Patched.
5. **`print -e` deprecated** → Replaced with `rrd pc`.
6. **DDR controller in reset / ps7_init.tcl missing** → Pointed `::W9_PS7_INIT` at the right path, then sourced at GLOBAL scope so silicon-version constants become global vars (xsdb_setup sources it inside proc → vars went local → ps7_init couldn't see them).
7. **UART silent + CPU can't halt** → Initially thought UART1 misroute. Probed and confirmed STDOUT_BASEADDRESS = 0xE0001000 = UART1 (correct). But: APER_CLK_CTRL bit 21 = 0 and MIO_PIN_48/49 L3_SEL = 0 → **PS UART1 not enabled in v12b BD**. Main fixed via `5f2ea71` (CONFIG.PCW_UART1_PERIPHERAL_ENABLE {1}).
8. **v12c bitstream rebuild blocked** by Vivado install rot (`scripts/xguifrmwork/init.tcl` missing, `::xgui::utils::init_utils` invalid) — same rot that defeated M3 720p.
9. **Option β: main_jtag_only.c** (UART-bypass, write status block to DDR + WFI spin) → ELF built. CPU still hung at PC=0x100154 — inside BSP crt0 `CheckEFUSE` proc, BEFORE main(). UART was a red herring.
10. **Patched boot.S CheckEFUSE → `b OKToRun`** (skip EFUSE silicon-version read at 0xF800701C). Manually compiled with arm-none-eabi-gcc + replaced boot.o in libxil.a (BSP build infrastructure wouldn't regenerate on mtime alone). Re-linked ELF.
11. **CPU still hangs** — PC moved from 0x100154 → 0x100120. New stuck point is **inside the ARM vector table area**, between PrefetchAbortHandler (0x100100) and _boot (0x10012c). Indicates an exception was raised during early startup (likely in cpu_init after CheckEFUSE — possibly MMU or L2 cache init), trapping to a data abort or prefetch abort handler.

## What we know

- ✅ JTAG works (CPU halts on demand pre-con, all mrd/mwr operations succeed)
- ✅ Bitstream programs (PL clean)
- ✅ DDR comes up via ps7_init (mwr verifies weights present at 0x10000000)
- ✅ ELF downloads cleanly (PC = entry 0x100000)
- ✅ `con` runs, CPU advances past _vector_table → _boot → CheckEFUSE
- ❌ Some PS init step in cpu_init / mmu_init / cache_init faults
- ❌ CPU traps to abort handler, gets stuck
- ❌ JTAG `stop` times out (CPU is in tight uninterruptible exception loop)

## Hypothesis (for Main)

After CheckEFUSE skip, the next BSP step is `cpu_init` which programs L1/L2 caches and MMU. One of these accesses may hit a problematic AXI path:

- L2 controller initialization touches PL310 (0xF8F02xxx)
- MMU TLB might be set up to span PL address space (0x40000000+) which on v12b has marginal R1 timing (WNS -0.516 ns, WPWS -0.755 ns from M3_PARTIAL_REPORT)
- The 9 WPWS-failing endpoints on the HDMI domain may produce undefined values that propagate via AXI to PS

## Time invested

~16h across two days (M3 deploy day + this session). Diminishing returns. Recommend Main decide:
- **Option ζ** — push the cpu_init bypass too (set up SP + branch direct to main) — heavier ASM patch
- **Option η** — wait for Vivado install repair, then rebuild a UART1-enabled v12c bitstream (may also have better timing closure)
- **Option θ** — defer board hash capture; rely on Main's `gen_w9_golden` host-side ground truth (when schema-bridge is ready)

## Pushed artifacts

- `sw/baremetal/spike_accel_w9_smoke/src/main.c` — TEMPORARILY contains main_jtag_only.c content (restore via `git checkout` after we resolve this)
- `sw/baremetal/spike_accel_w9_smoke/src/main_jtag_only.c` — renamed main → _unused_main_jtag_only to avoid duplicate symbol
- `sw/baremetal/spike_accel_w9_smoke/{build_w9_smoke,app_build_only,probe_domains,rebuild_bsp,build_w9_smoke_jtag}.tcl` — scripted Vitis build helpers
- `vitis_workspace/.../boot.S` — CheckEFUSE early-return patch
- `vitis_workspace/spike_zybo_baremetal_plat/.../libxil.a` — re-archived with new boot.o
- `runs/remote_machine/{capture_uart.ps1,w9_smoke_oneshot.tcl,w9_jtag_harvest.tcl,probe_uart.tcl}` — automation
- `runs/remote_machine/w9_pbt_*.log` — full traces

— Remote Claude, 2026-05-26T15:05:00+08:00
