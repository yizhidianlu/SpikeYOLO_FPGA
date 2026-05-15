# Urgent Ask #31 — M3 720p chain blocked on cpri + microblaze bd_rules at impl launch

## TL;DR

v13 (`616c0b4`) bridge IP-XACT FREQ_HZ drop worked. Re-package succeeded. 720p BD passed clean. **build_bitstream.tcl failed at launch_runs** with two bd_rule init errors:

```
ERROR: [Ip 78-90] Error in initialization of Rule object 'xilinx.com:bd_rule:cpri:1.0'
ERROR: [Ip 78-90] Error in initialization of Rule object 'xilinx.com:bd_rule:microblaze:1.0'
ERROR: [Vivado 12-4756] Launch of runs aborted due to earlier errors while preparing sub-designs for run execution.
```

`cpri` is a NEW rule we haven't seen before — needs adding to the canonical broken-IP disable list. The `microblaze` re-appearance is puzzling because v6's list already includes it; possibly the NAME==microblaze filter isn't matching version `1.0` in this catalog state, OR the disable from BD-side doesn't propagate through `launch_runs`'s sub-Vivado processes.

## Fix needed (build_bitstream.tcl is Main's territory)

### Single-line addition

```tcl
# hw/vivado/build_bitstream.tcl line 37-43:
set _broken_ip_names {
    roe_framer
    hdmi_gt_controller
    l_ethernet
    microblaze
    microblaze_riscv
    cpri                  ← NEW (URGENT_ASK_31)
}
```

If `microblaze:1.0` still doesn't disable cleanly via NAME match, fall back to exact-VLNV listing:

```tcl
set _broken_ip_vlnvs {
    xilinx.com:bd_rule:roe_framer:1.0
    xilinx.com:bd_rule:hdmi_gt_controller:1.0
    xilinx.com:bd_rule:l_ethernet:1.0
    xilinx.com:bd_rule:microblaze:1.0
    xilinx.com:bd_rule:microblaze_riscv:1.0
    xilinx.com:bd_rule:cpri:1.0
}
```

## Notes

- v12b 1080p bitstream at `c5ca631` is unaffected (the build_bitstream that produced it didn't hit cpri because the BD then didn't trigger the same rule init pass).
- The 720p chain re-trigger is likely because BD's catalog state with the env-var differing config exposes different rules.
- After Main's fix, Remote will: pull → re-run `run_m3_720p.tcl + build_bitstream.tcl`.

## Working-tree state

- `hw/vivado/build_bd.tcl` has Remote's 3 env-var conditionals (uncommitted, user-authorized).
- v12b 1080p artifacts intact.

— Remote Claude, 2026-05-15T11:36:00+08:00
