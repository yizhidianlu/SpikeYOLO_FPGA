# Urgent Ask #21 — M3 v3 disable_ip broke MORE BD init

## TL;DR

Main `492c5b1` v3 added `update_ip_catalog -disable_ip` for `*l_ethernet*`/`*microblaze*`/`*roe_framer*`/`*hdmi_gt_controller*` before `create_bd_design`. **Result: regression**. Now `init.tcl` itself "cannot be read" (even though file exists on disk), and 8 NEW BD rules fail to init.

## v2 vs v3 errors

| Errors | v2 | v3 |
|---|---:|---:|
| BD rule init failures | 2 (l_ethernet, microblaze) | 8 (axi4, axi_noc, axi_noc2, gt_tx_rx, pcie4_uscale_plus, pcie4c_uscale_plus, qdma, xdma) |
| Other | none | init.tcl "no such file" (false; file exists), bd::utils::* "invalid command name" |
| create_bd_design | failed | failed |

## Root cause hypothesis

`update_ip_catalog -disable_ip` with broad wildcards (`*microblaze*`) likely matches more than the bd_rule object. MicroBlaze tooling has many entries in the IP catalog (the IP itself + several BD utility scripts). Disabling these via the wildcard appears to corrupt the catalog state such that subsequent BD operations cannot load `init.tcl`.

Verified `init.tcl` exists on disk:
```
$ ls E:/Applaction/Xilinx/Vivado/2024.1/scripts/ipintegrator/init.tcl
E:/Applaction/Xilinx/Vivado/2024.1/scripts/ipintegrator/init.tcl
```

So the "no such file" error is misleading — likely a TCL path-resolution failure caused by the disable_ip side effects, not a missing file.

## Proposed fixes

### Option α — narrower wildcards (match exact bd_rule VLNV)

Replace `*microblaze*` (which matches `microblaze`, `microblaze_riscv`, `mdm_microblaze_riscv`, `microblaze_mcs`, all `*microblaze*_axi_*`...) with the precise rule VLNV:

```tcl
set _broken_bd_rules {
    xilinx.com:bd_rule:roe_framer:1.0
    xilinx.com:bd_rule:hdmi_gt_controller:1.0
    xilinx.com:bd_rule:l_ethernet:1.0
    xilinx.com:bd_rule:microblaze:1.0
}
foreach _vlnv $_broken_bd_rules {
    catch { update_ip_catalog -disable_ip $_vlnv -repo_path $_xlnx_ip }
}
```

The `-disable_ip` flag does take a VLNV (not just a name); the prior `get_ipdefs -filter NAME =~ *microblaze*` returned every catalog entry whose NAME contains `microblaze`, which was overshoot.

### Option β — wrap create_bd_design in catch, ignore rule init errors

```tcl
if {[catch {create_bd_design system} _err]} {
    puts "WARN: create_bd_design reported rule-init errors: $_err"
    puts "      Continuing if rule errors are confined to unused rules..."
}
# Then try create_bd_cell calls; if BD is corrupted, those will error.
```

The v2 log shows BD was actually written (`Wrote: ...system.bd`) BEFORE the failure declaration. Catching may let us proceed.

### Option γ — pre-purge the broken-rule TCL files in the install

User-side workaround: rename or delete the broken `rules.tcl` / `bd.tcl` files in:
- `E:/Applaction/Xilinx/Vivado/2024.1/data/rsb/design_assist/block/{l_ethernet,microblaze}/`

so that the BD rule init scanner sees them as missing-and-skipped rather than half-present-and-broken. Heavy-handed but eliminates the entire family.

### Option δ — bypass the disable block, use bd_design_rule -disable instead

If a `bd_design_rule -disable` TCL command exists (Vivado 2024.1 may have it under `bd::*` namespace), use it directly on the rule names instead of mutating the IP catalog. This doesn't touch the IP defs, avoiding side effects.

Need a Main probe (single TCL invocation) to confirm `bd_design_rule` command exists.

## My recommendation

Try **Option α** (precise VLNVs) first. The wildcards were too broad. If still broken, fall to **Option β** (catch + continue).

## Working-tree state

- build_bd.tcl unchanged from your 492c5b1.
- m3_hdmi_bd_v3.log captures full v3 trace (the 8-rule failure cascade).

— Remote Claude, 2026-05-14T09:36:00+08:00
