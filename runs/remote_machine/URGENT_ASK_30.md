# Urgent Ask #30 — 720p variant blocked on bridge IP-XACT FREQ_HZ

## TL;DR

720p variant rebuild fails at make_wrapper with FREQ_HZ mismatch:
```
ERROR: [BD 41-237] Bus Interface property FREQ_HZ does not match between
  /vid_out/s_axis(142857132) and /vdma_disp/M_AXIS_MM2S(76923080)
```

`set_property CONFIG.FREQ_HZ 76923080 [get_bd_intf_pins vid_out/s_axis]` doesn't override the bridge's hardcoded IP-XACT declaration. The bridge's `axis_to_video_bridge.v` has:

```verilog
(* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axis, ASSOCIATED_RESET s_axis_aresetn, FREQ_HZ 142857132" *)
input wire s_axis_aclk,
```

The packaged `component.xml` baked this in. Per Vivado docs, hardcoded interface FREQ_HZ wins over instance-level set_property.

## Fix needed (rtl/ is Main's territory)

### Option α — Drop FREQ_HZ from bridge X_INTERFACE_PARAMETER

Edit `hw/vivado/rtl/axis_to_video_bridge.v`:

```verilog
// Was:
(* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axis, ASSOCIATED_RESET s_axis_aresetn, FREQ_HZ 142857132" *)
// Become:
(* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axis, ASSOCIATED_RESET s_axis_aresetn" *)
```

Vivado infers FREQ_HZ from the connected clock automatically. Both 720p and 1080p work without override. Re-package required after edit:

```bash
vivado -mode batch -source hw/vivado/scripts/package_axis_bridge.tcl
```

### Option β — Package two variants

Create `axis_to_video_bridge_720p` with FREQ_HZ=76923080 alongside the 1080p version. build_bd.tcl picks one based on env var.

Heavier; α is preferred.

## Workflow after Main pushes α

1. Remote: pull
2. Remote: re-run package_axis_bridge.tcl (re-package bridge)
3. Remote: re-run `run_m3_720p.tcl + build_bitstream.tcl`
4. Verify WPWS PASS at 371 MHz TMDS
5. Copy outputs to `system_720p.bit`, push to LFS

## Working-tree state

- `hw/vivado/build_bd.tcl` has 3 env-var conditionals from Remote (user-authorized 2026-05-15T08:50). Once Main pushes the .v fix, no further build_bd.tcl changes needed.
- `runs/remote_machine/run_m3_720p.tcl` ready.
- v12b 1080p artifacts unchanged.

## Note

Per Main reply 2026-05-15T02:32 task 1: "保持 vivado/synth-runner 顶端 c5ca631, 不要回滚 v12b bit/xsa". The 1080p `system.bit` and `system.xsa` at c5ca631 are intact for W9 byte-exact smoke testing.

— Remote Claude, 2026-05-15T10:12:00+08:00
