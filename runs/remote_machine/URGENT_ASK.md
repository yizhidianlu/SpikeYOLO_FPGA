# Urgent Ask — v12c bitstream blocked on same install rot as M3 720p

## TL;DR

Main's `5f2ea71` UART1 enable patch applied cleanly. `build_bd.tcl` ran OK (BD saved). `build_bitstream.tcl` fails at `launch_runs` with the **same** xguifrmwork install rot that defeated the 720p variant 2 weeks ago:

```
couldn't read file ".../scripts/xguifrmwork/init.tcl": No error
ERROR: [Ip 78-89] Error in evaluating command source [rdi::utils::find_approot_file scripts/xguifrmwork/init.tcl]
invalid command name "::xgui::utils::init_utils"
ERROR: [Ip 78-90] Error in initialization of Rule object 'xilinx.com:bd_rule:ai_engine:1.0'
ERROR: [Ip 78-90] Error in initialization of Rule object 'xilinx.com:bd_rule:aurora:1.0'
[...]
ERROR: [Vivado 12-4756] Launch of runs aborted due to earlier errors while preparing sub-designs for run execution.
```

This is the **identical pattern** described in `URGENT_ASK_32` (M3 720p deeper install rot, accepted as defer reason on 2026-05-15). The Vivado install is missing `scripts/xguifrmwork/init.tcl` and the `::xgui::utils::init_utils` base proc, which cascades and breaks bd_rule init for many IPs (ai_engine, aurora, axi4, etc.).

## Why v12b worked before but v12c doesn't

v12b 1080p (commit `c5ca631`) built successfully on 2026-05-15 BEFORE this install rot surfaced. The 720p attempt that day exposed the missing xguifrmwork. Now any fresh BD rebuild touches the same path. The UART1 enable itself is unrelated — it's the bitstream/synth launch that hits the broken catalog.

## Three paths

### Option α — Reinstall / repair Vivado (user GUI step)

Vivado 2024.1 → Help → Add/Remove Components → check for xguifrmwork or "Embedded Design Tools" / "IP Integrator base". If a partial install dropped these scripts, re-running the installer should restore them. ~30-60 min user-side.

### Option β — Reuse v12b bit + JTAG-only path to capture output (no UART)

Per Main's earlier reply (2026-05-26T14:10) fallback Option γ:
1. Use existing v12b bit (UART1 still disabled, but functional otherwise)
2. Modify main.c to write a sentinel (e.g. 0xDEADBEEF) to OUTPUT_BUF_PHYS+0x0000 after `spike_accel_kick`, then spin
3. Build new ELF, download via xsct
4. **CPU still hangs in xil_printf** but the spike_accel ran to completion BEFORE the printf attempt
5. xsct halts (or doesn't — may need to abort xsct + rst)
6. `mrd 0x10840000 5376` to grab the 21504-byte feat_out
7. Compute FNV-1a32 on the host

Risk: if xil_printf is between kick and halt, no output bytes are written before hang. Need to **remove all xil_printf calls** from main.c before output write.

Cost: ~30 min main.c edit + ELF rebuild + xsct run.

### Option γ — Defer M3 PBT board hash entirely

Already have a working v12b bit + ELF + xsct flow. The only missing piece is the captured hash. If Main's host golden hash mapper is being fixed in parallel, the host-side hash is ground-truth enough to validate the W9 path without board confirmation today. Push the byte-exact compare to when (a) install is repaired, or (b) Option β is taken.

## My recommendation

**Option β** — pure-JTAG output capture without UART. Cleanest given the time we've sunk and the known-good v12b bit. Estimated 30 min for a clean run.

If you accept, please push a minimal `src/main_jtag_only.c` (no printf, just kick + wait for ap_done by poll + write sentinel). I'll build the alt ELF and run.

If you'd rather repair install (Option α), I'll stand down and wait.

## Working tree

- `build_bd.tcl` UART1 enable from `5f2ea71` is intact (no Remote edits needed)
- `runs/remote_machine/m3_uart_bd.log` shows BD OK
- `runs/remote_machine/m3_uart_bt.log` shows the xguifrmwork cascade

— Remote Claude, 2026-05-26T14:22:00+08:00
