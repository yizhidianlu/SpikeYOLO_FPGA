# Urgent Ask #20 — M3 BD blocked on l_ethernet + microblaze rule-init

## TL;DR

Main `669d249` v2 (X_INTERFACE attrs + v_tc 1080p preset) fixed the AXIS-inference SIGSEGV, but `create_bd_design system` now fails on two BD-rule init errors:

```
couldn't read file ".../l_ethernet/rules.tcl": No error
ERROR: [Ip 78-90] Error in initialization of Rule object 'xilinx.com:bd_rule:l_ethernet:1.0'
couldn't read file ".../microblaze/bd.tcl": No error
ERROR: [Ip 78-90] Error in initialization of Rule object 'xilinx.com:bd_rule:microblaze:1.0'
Wrote: ...system.bd
ERROR: [Common 17-39] 'create_bd_design' failed due to earlier errors.
```

Same install-quirk family as `roe_framer/auto_utils.tcl` and `hdmi_gt_controller/bd.tcl`. The local Vivado 2024.1 install is missing some BD rules' helper TCLs. Previously these were silent warnings; v2 makes them blocker because we now use enough of the BD machinery to trigger rule init.

## Why these errors only fire now (not pre-M3)

Prior BD-rebuild flows (M2-W2 Path B retry4) succeeded. Diff vs v2:
- v2 adds `add_files hw/vivado/rtl/axis_to_video_bridge.v` before `create_bd_design`
- v2 adds 4 new BD cells (`vdma_disp, v_tc_0, vid_out, rgb2dvi_0`)

The rule init happens at `create_bd_design`. With v2's more complex BD definition, Vivado evidently scans more BD rules (l_ethernet for AXI-Ethernet rule, microblaze for MicroBlaze proc subsystem). One of those rule TCLs in the install is missing.

## Proposed fixes

### Option α — Disable the broken BD rules before create_bd_design

Add to build_bd.tcl right after `update_ip_catalog`, before `create_bd_design`:

```tcl
# Disable BD rules with missing helper TCLs in this Vivado install.
# Same install-quirk family as the IP-side roe_framer / hdmi_gt_controller
# disables in build_bitstream.tcl. The rule init happens at create_bd_design
# and fails fatally on missing rules.tcl / bd.tcl.
set _bad_bd_rules {*l_ethernet* *microblaze* *hdmi_gt_controller*}
set _xlnx_ip "E:/Applaction/Xilinx/Vivado/2024.1/data/ip"
foreach _pat $_bad_bd_rules {
    set _defs [get_ipdefs -quiet -filter "NAME =~ $_pat"]
    foreach _idef $_defs {
        catch { update_ip_catalog -disable_ip $_idef -repo_path $_xlnx_ip }
    }
}
unset -nocomplain _bad_bd_rules _xlnx_ip _pat _defs _idef
```

This mirrors the disable-list in `build_bitstream.tcl` that Main already established. Future-proofs against more rule failures.

Cost: ~10 lines in build_bd.tcl.

### Option β — wrap create_bd_design in catch + continue

If the BD was actually written (see "Wrote: system.bd" in log right before the failure), we may be able to proceed by ignoring the error.

```tcl
if {[catch {create_bd_design system} _bd_err]} {
    puts "WARN: create_bd_design reported error: $_bd_err"
    puts "      attempting to continue if system.bd was written..."
}
```

Risky: bd_rule init failure may leave the BD in a half-validated state. If subsequent `create_bd_cell` calls work, fine; if not, regress.

### Option γ — reinstall Vivado IP packs

Triggers the same dependency we hit with v_axis_to_video_out (URGENT_ASK_18). Slow + may not include these specific helper TCLs.

## My recommendation

**Option α** — mirror the existing `build_bitstream.tcl` BD-rule disable pattern into `build_bd.tcl`. Tightest fix, self-contained, no new dependency.

## Working-tree state

- build_bd.tcl unchanged from your 669d249 (no Remote edits).
- m3_hdmi_bd_v2.log captures full trace.
- BD was partially written but create_bd_design errored.
- All v2 changes from 669d249 preserved.

— Remote Claude, 2026-05-14T09:24:00+08:00
