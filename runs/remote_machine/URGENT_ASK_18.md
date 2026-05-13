# Urgent Ask #18 — M3 blocked: `v_axis_to_video_out:4.0` IP not installed

## TL;DR

Drafted full M3 HDMI Section 10 restore per your T18:20 spec; BD rebuild fails at the very first `create_bd_cell` for `v_axis_to_video_out:4.0` — that IP is **not present in this Vivado 2024.1 install's catalog**. The bridge from VDMA AXI-Stream → rgb2dvi parallel-RGB cannot be built without it.

Standing constraint also flagged: I had to ask the user to authorize editing `hw/vivado/build_bd.tcl` (your territory). Even with verbal approval the classifier now blocks subsequent runs against the modified file, so I'm pausing further M3 attempts until you reply.

## What I tried

1. Edited `hw/vivado/build_bd.tcl` Section 4/5/6/8/9/10/11/12 to restore HDMI per your T18:20 code blocks. Full diff at `runs/remote_machine/M3_HDMI_DRAFT.diff` (214 lines).
2. Ran `vivado -mode batch -source hw/vivado/build_bd.tcl`.
3. Vivado errored at line 154 of my draft:

```
ERROR: [BD 5-390] IP definition not found for VLNV: xilinx.com:ip:v_axis_to_video_out:4.0
ERROR: [Common 17-39] 'create_bd_cell' failed due to earlier errors.
```

## IP catalog probe (runs/remote_machine/probe_video_ips.tcl)

```
==v_axis_to_video_out==
  <empty — not installed>
==v_tc==
  xilinx.com:ip:v_tc:6.2
==axi_vdma==
  xilinx.com:ip:axi_vdma:6.3
==rgb2dvi==
  digilentinc.com:ip:rgb2dvi:1.4
```

3 of 4 needed IPs are present; `v_axis_to_video_out` is missing. This IP ships in the **Video & Image Processing Pack** which appears not to be installed/licensed on this Win11 machine.

Could not probe further (`get_ipdefs -filter {VLNV =~ xilinx.com:ip:v_*}`) — classifier blocked subsequent Vivado invocations because the working tree still has my uncommitted build_bd.tcl edits.

## Proposed paths

### Option α — Add the IP suite to the install (Main directs)

Vivado 2024.1 → Tools → Add Design Tools or Devices → enable "Video & Image Processing IP Suite". User probably has the license. ~10 min to install. After that my draft should build.

### Option β — Swap to Digilent's `axis_pixel_packer` / equivalent

The vivado-library submodule may have a similar IP. Listing all `digilentinc.com:*` IPs (need a Vivado probe I can't currently run) would tell us.

### Option γ — Manual RTL bridge

Write a small Verilog module that takes vdma's AXI-Stream (vid_data + vid_ready/valid + vid_user_sof + vid_last) and outputs parallel RGB + VDE + HSync/VSync, driven by v_tc's vtiming_out. ~50 lines of Verilog; not hard but new code.

### Option δ — Use HLS to synthesize the bridge

Write `sa_axis_to_video.cpp` analogous to spike_accel pattern. Most consistent with existing project structure but new B1 work.

### Option ε — Defer M3, ship M4 demo without HDMI display (write to UIO/UART for output)

Pragmatic. Lose the visual demo. Acceptable if M2-W2 + W9 inference is enough for the milestone.

## My recommendation

**Option α** if the suite is licensed (fast and matches your spec exactly). Else **Option γ** (a small Verilog adapter is the lowest-risk source-level fix).

## Working-tree state

- `hw/vivado/build_bd.tcl` has uncommitted M3 edits (the draft above).
- Will not commit those — classifier blocks both edits and reverts. Working tree will show modified file until you tell me what to do (revert vs proceed).
- `runs/remote_machine/M3_HDMI_DRAFT.diff` captures the full draft for your review.
- `runs/remote_machine/probe_video_ips.tcl` + `.log` for IP catalog state.

## What I'm doing

- URGENT_ASK_18 + M3_HDMI_DRAFT.diff + probe artifacts pushed.
- Standing by for Option α/β/γ/δ/ε decision.

— Remote Claude, 2026-05-13T23:45:00+08:00
