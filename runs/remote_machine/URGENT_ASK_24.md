# Urgent Ask #24 — disable_ip whack-a-mole; need global mute

## TL;DR

Five iterations of "add another rule to disable list" so far:
- v3: `*roe_framer* *hdmi_gt_controller* *l_ethernet* *microblaze*`
- v4: regression on wildcards → switch to exact VLNV
- v5: + `microblaze:1.0` only (missed `microblaze_riscv`)
- v6: + `microblaze_riscv:1.0` (NAME-equality)
- **v7 needed**: + `versal_cips:1.0` — sources missing `connect_noc.tcl`

The 7th and 8th and Nth rule will surface as we keep going. The Vivado install is missing **many** Design Assistant scripts, not just two or three. Every bd_rule init that references a helper TCL outside `rules.tcl`/`bd.tcl` is a potential failure.

## Path forward — global mute

### Option α — Vivado tool param to skip Design Assistant rule init

Try setting these before `create_bd_design`:

```tcl
catch { set_param bd.skipDesignAssistant true }
catch { set_param bd.disableDesignAssistant true }
catch { set_param ::bd::utils::nodesignassistant 1 }
```

Need a Main probe (or someone with Vivado UG895 to confirm). If any work, all bd_rule init errors disappear in one shot.

### Option β — catch the error and continue

The v3-v6 logs show `Wrote: ...system.bd` is emitted by Vivado BEFORE the failure declaration. Treating `create_bd_design` failure as a warning may let us proceed:

```tcl
if {[catch {create_bd_design system} _err]} {
    puts "WARN: create_bd_design rule-init errors: $_err"
    puts "      attempting to continue if .bd was saved..."
    open_bd_design [file join $OUT_DIR ${PROJECT}.srcs sources_1 bd system system.bd]
}
```

If subsequent `create_bd_cell` calls work, we proceed. If the partial init leaves the BD in a bad state, we get a cleaner error there.

### Option γ — fully list all bd_rules and disable everything

Probe the catalog, get every `xilinx.com:bd_rule:*` def, disable them all (we don't need ANY design-assistant automation since our BD is hand-written). Only one rule is actually used: `processing_system7` (via `apply_bd_automation` at line 100 of build_bd.tcl) — we keep that one enabled.

Probe results from a fresh catalog: ~30-50 bd_rules exist in 2024.1, most for IPs we never touch (versal_*, microblaze*, ethernet variants, pcie*, qdma, xdma, gt_*, dfx, hdmi_gt_*, roe_framer, l_ethernet, etc.).

I can produce the full list via `runs/remote_machine/probe_all_bd_rules.tcl` if Main wants to take Option γ.

### Option δ — defer M3, ship M2 timing-closed bitstream for M4 demo without HDMI

M2-W2 already produced `system.bit` with WNS +0.067 ns. If M4 USB-cam-to-HDMI demo can use UART/UIO output instead of HDMI for first pass, we unblock the user-facing demo without resolving this whack-a-mole.

## My recommendation

Try **Option α** first (cheapest — one TCL set_param line). If it doesn't work, fall back to **Option γ** (disable every bd_rule except processing_system7).

Option β is risky (rule errors may leave BD in undefined state). Skip unless α and γ both fail.

## Working-tree state

- `runs/remote_machine/probe_broken_bd_rules.tcl` / `.log` — static-file probe (found 0 because the breakage is dynamic, not missing-file)
- `runs/remote_machine/probe_all_bd_rules.tcl` / `.log` — enumeration (empty in v6 due to existing disables; can re-run on fresh catalog)
- `m3_hdmi_bd_v6.log` — confirms `versal_cips:1.0` is the next rule

— Remote Claude, 2026-05-14T10:13:00+08:00
