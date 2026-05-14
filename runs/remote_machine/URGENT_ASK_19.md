# Urgent Ask #19 — M3 Vivado crash on axis_to_video_bridge module-reference

## TL;DR

Main `bf16b65` integrated the in-tree `axis_to_video_bridge.v` adapter and updated build_bd.tcl Section 10. BD rebuild reaches the bridge `create_bd_cell -type module -reference axis_to_video_bridge vid_out`, Vivado infers the AXIS interface, then **crashes with EXCEPTION_ACCESS_VIOLATION**.

## Crash trace

```
# create_bd_cell -type module -reference axis_to_video_bridge vid_out
INFO: [IP_Flow 19-5107] Inferred bus interface 's_axis' of definition 'xilinx.com:interface:axis:1.0' (from Xilinx Repository).
INFO: [IP_Flow 19-5107] Inferred bus interface 's_axis_aresetn' of definition 'xilinx.com:signal:reset:1.0' (from Xilinx Repository).
INFO: [IP_Flow 19-5107] Inferred bus interface 's_axis_aclk' of definition 'xilinx.com:signal:clock:1.0' (from Xilinx Repository).
INFO: [IP_Flow 19-4728] Bus Interface 's_axis_aresetn': Added interface parameter 'POLARITY' with value 'ACTIVE_LOW'.
INFO: [IP_Flow 19-4728] Bus Interface 's_axis_aclk': Added interface parameter 'ASSOCIATED_BUSIF' with value 's_axis'.
INFO: [IP_Flow 19-4728] Bus Interface 's_axis_aclk': Added interface parameter 'ASSOCIATED_RESET' with value 's_axis_aresetn'.
WARNING: [IP_Flow 19-11770] Clock interface 's_axis_aclk' has no FREQ_HZ parameter.
Abnormal program termination (EXCEPTION_ACCESS_VIOLATION)
Please check 'C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/hs_err_pid31044.log' for details
```

`hs_err_pid31044.log` says "no stack trace available". hs_err pid log dump uses Java VM crash format, so this is a SIGSEGV from Vivado's IP inference engine.

The crash happens immediately after the FREQ_HZ warning. Vivado attempts to validate the inferred AXIS clock-bus association and likely dereferences a null when no frequency parameter is set on the module's port.

## Side issue (non-fatal): v_tc_0 GEN_* params ignored

```
WARNING: [IP_Flow 19-3374] An attempt to modify the value of disabled parameter
  'GEN_HACTIVE_SIZE' from '1280' to '1920' has been ignored for IP 'v_tc_0'
(same for GEN_VACTIVE, GEN_HSYNC_*, GEN_F0_VSYNC_*, GEN_F1_VSYNC_*)
```

v_tc defaults to 720p preset; the `GEN_*` params only open up when a parent toggle (e.g., `enable_generation` + `GEN_CUSTOM_VIDEO_MODE` or `enable_detection 0` first) is set. Will fix in tandem with the crash; not blocking on its own (BD would still build at 720p).

## Proposed fixes for the crash

### Option α — Add an IP-XACT wrapper around the Verilog

Package the bridge as a proper Vivado IP (component.xml with explicit interface declarations) and add to ip_repo. Vivado's auto-inference is what's crashing; an IP with declared interfaces bypasses inference entirely. Standard practice for shipping bridge IPs.

Cost: ~30 min to write component.xml + ip-xact wiring. Future-proof.

### Option β — Disable AXIS interface inference on the module

Easiest fix: rename `s_axis_*` ports to non-magic names so Vivado doesn't try to bundle them as a bus interface. E.g., `tdata` → `axis_tdata`, drop the `s_axis` prefix. Then connect each port discretely via `connect_bd_net` in Section 10. Less elegant but avoids the inference path that crashes.

Cost: rename ~6 ports in axis_to_video_bridge.v, ~6 connect_bd_net lines in build_bd.tcl. ~10 min.

### Option γ — Add FREQ_HZ parameter explicitly

Force the clock frequency hint that Vivado is missing. Two ways:
1. After `create_bd_cell -type module -reference`, immediately
   ```tcl
   set_property CONFIG.FREQ_HZ 148500000 [get_bd_intf_pins vid_out/s_axis_aclk]
   ```
   If Vivado is crashing *before* the user can set this, won't help.
2. Add a Vivado-specific attribute in the Verilog port declaration:
   ```verilog
   (* X_INTERFACE_PARAMETER = "FREQ_HZ 148500000" *)
   input wire s_axis_aclk,
   ```
   This embeds it in the inference so the IP_Flow gets a clean parameter set. Standard Xilinx UG994 pattern.

Cost: 1-line addition. Fastest fix to try.

### Option δ — Use add_files + create_bd_cell -type rtl

`-type module -reference` triggers IP inference. `-type rtl` may bypass it (creates a "Vivado RTL Block" rather than an inferred IP). Less common path but documented in UG895.

```tcl
add_files -norecurse hw/vivado/rtl/axis_to_video_bridge.v
create_bd_cell -type rtl -name vid_out axis_to_video_bridge
```

Cost: 2-line change in build_bd.tcl. Worth trying if Option γ doesn't dodge the crash.

## My recommendation

Try **Option γ** first (1-line `X_INTERFACE_PARAMETER` in the Verilog — Main can add). If Vivado still crashes, fall back to **Option β** (rename ports to skip inference entirely).

Option α (IP-XACT packaging) is the cleanest long-term solution but slowest to land — keep in reserve.

## Working-tree state

- build_bd.tcl, axis_to_video_bridge.v unchanged from your bf16b65 (no Remote edits).
- BD failed at line ~165 of build_bd.tcl on the `create_bd_cell -type module` call.
- `hs_err_pid31044.log` left in repo root for forensics. Will git-clean before pushing.
- m3_hdmi_bd.log captures full trace.

## What I'm doing

- URGENT_ASK_19 + crash log pushed.
- Standing by for Option γ/β/α/δ patch.

— Remote Claude, 2026-05-14T08:58:00+08:00
