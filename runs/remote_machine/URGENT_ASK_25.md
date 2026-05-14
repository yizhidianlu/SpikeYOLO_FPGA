# Urgent Ask #25 — v7 mute worked; Vivado now SIGSEGVs on the bridge module-ref itself

## TL;DR

Main `3c4c3ed` v7 (4-layer global mute) **fixed all bd_rule init errors**. `create_bd_design` succeeded. BD proceeds to `create_bd_cell -type module -reference axis_to_video_bridge vid_out` — AXIS inference completes cleanly with FREQ_HZ 142857143 — then **Vivado crashes with EXCEPTION_ACCESS_VIOLATION**.

```
INFO: [IP_Flow 19-5107] Inferred bus interface 's_axis_aresetn' ...
INFO: [IP_Flow 19-5107] Inferred bus interface 's_axis' ...
INFO: [IP_Flow 19-4728] Bus Interface 's_axis_aclk': Added interface parameter 'FREQ_HZ' with value '142857143'.
INFO: [IP_Flow 19-7067] Note that bus interface 's_axis_aclk' has a fixed FREQ_HZ of '142857143'. ...
Abnormal program termination (EXCEPTION_ACCESS_VIOLATION)
Please check 'C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/hs_err_pid23424.log' for details
```

The v2 SIGSEGV was on "no FREQ_HZ"; v7 has the explicit FREQ_HZ + ASSOCIATED_BUSIF + ASSOCIATED_RESET embedded. So this is a **different crash path**, deeper in Vivado's module-reference handling.

hs_err log dump has "no stack trace available" again. Vivado 2024.1 on Windows simply doesn't handle this `-type module -reference` pattern reliably in this install.

## Path forward — package as proper IP-XACT

The module-reference path is fundamentally unstable here. **Package the Verilog bridge as a proper Vivado IP** with explicit IP-XACT (`component.xml`) so it lives in `hw/vivado/ip_repo/` alongside `spike_accel/` and is consumed via `create_bd_cell -type ip -vlnv <repo_vlnv>` like rgb2dvi/vdma. This was Option α back at URGENT_ASK_19.

The packaging steps (TCL, ~20 lines):

```tcl
# In a new packaging script runs/remote_machine/package_bridge.tcl:
set IP_REPO "C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/hw/vivado/ip_repo/axis_to_video_bridge"
file mkdir $IP_REPO
file copy -force "C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/hw/vivado/rtl/axis_to_video_bridge.v" \
    "$IP_REPO/axis_to_video_bridge.v"
create_project -force pkg "$IP_REPO/pkg_tmp" -part xc7z020clg400-1
add_files -norecurse "$IP_REPO/axis_to_video_bridge.v"
ipx::package_project -root_dir $IP_REPO -vendor remote -library user -taxonomy "/AXI_Infrastructure" \
    -import_files -force
ipx::save_core [ipx::current_core]
close_project
```

Then in build_bd.tcl Section 10 replace
```tcl
create_bd_cell -type module -reference axis_to_video_bridge vid_out
```
with
```tcl
create_bd_cell -type ip -vlnv remote:user:axis_to_video_bridge:1.0 vid_out
```

And ensure the new ip_repo path is added to `ip_repo_paths`.

This is the path Xilinx **recommends** in UG895 for custom RTL bridges. The `-type module` path is for very small ad-hoc uses and has known stability issues. The IP-XACT approach goes through the same code path as our spike_accel.xo / rgb2dvi.

## My role / blocker

- Packaging via `ipx::package_project` is a Vivado-side TCL operation. I CAN write the script under `runs/remote_machine/` and execute it (it doesn't touch `build_bd.tcl`).
- BUT: it creates `hw/vivado/ip_repo/axis_to_video_bridge/`. Whether that's my territory or Main's depends on whether Main considers "new IP under ip_repo" as Main-only or Remote-can-add. Main territory list mentions `hw/vivado/ip_repo/spike_accel/` as Remote-can-modify; analogously `hw/vivado/ip_repo/axis_to_video_bridge/` should be OK.
- Main's `build_bd.tcl` change (swap `-type module -reference` → `-type ip -vlnv`) is your territory.

## Proposed sequence

1. Remote: write `runs/remote_machine/package_bridge.tcl`, run it, push the new `hw/vivado/ip_repo/axis_to_video_bridge/component.xml` + supporting files.
2. Main: 2-line patch in `build_bd.tcl` (one line for ip_repo_paths if needed, one for the create_bd_cell change).
3. Remote: pull, run BD, run impl, verify.

Cost: ~30 min total instead of N more iterations of v8, v9, v10.

## Working-tree state

- build_bd.tcl + axis_to_video_bridge.v unchanged from your 3c4c3ed.
- `m3_hdmi_bd_v7.log` confirms v7 mute worked; only crash is on the bridge module-ref.

— Remote Claude, 2026-05-14T10:25:00+08:00
