# Urgent Ask #23 — M3 v5 one more broken bd_rule

## TL;DR

Main `81441c9` v5 fixed all 4 issues from URGENT_ASK_22. Only one new error remains: another bd_rule the install ships partial.

```
ERROR: [Ip 78-90] Error in initialization of Rule object 'xilinx.com:bd_rule:microblaze_riscv:1.0'
ERROR: [Common 17-39] 'create_bd_design' failed due to earlier errors.
```

Same install-quirk family. `*microblaze*` wildcard from v3 caught this (and 6 others, causing the regression). Switching to exact VLNVs in v4 missed it because we listed only `microblaze:1.0`, not `microblaze_riscv:1.0`.

## Fix

Add to `build_bd.tcl` disable list:

```tcl
set _broken_bd_rules {
    xilinx.com:bd_rule:roe_framer:1.0
    xilinx.com:bd_rule:hdmi_gt_controller:1.0
    xilinx.com:bd_rule:l_ethernet:1.0
    xilinx.com:bd_rule:microblaze:1.0
    xilinx.com:bd_rule:microblaze_riscv:1.0   ← NEW
}
```

(Same change in `build_bitstream.tcl` to stay in sync.)

That's the entire patch. Expected outcome: `create_bd_design` succeeds, all other v5 fixes (vtiming pin names, FREQ_HZ 142.857, address ranges 64K) carry through.

## Working-tree state

- m3_hdmi_bd_v5.log — full trace, single error at `create_bd_design`.
- build_bd.tcl / axis_to_video_bridge.v unchanged from 81441c9.

— Remote Claude, 2026-05-14T10:05:00+08:00
