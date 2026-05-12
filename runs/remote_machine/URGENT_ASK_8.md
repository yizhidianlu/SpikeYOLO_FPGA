# Urgent Ask #8 from Remote Claude — build_bd.tcl wires VDMA to rgb2dvi but rgb2dvi has no AXI-Stream port

## TL;DR

After fixing BOARD_PART (`:1.0` → `:1.2`) and Vivado IP repo discovery (`.xo` file + extracted IP dir), `build_bd.tcl` BD construction reaches:

```
WARNING: [BD 5-232] No interface pins matched 'get_bd_intf_pins rgb2dvi_0/s_axis_video'
ERROR: [BD 5-106] Arguments to the connect_bd_intf_net command cannot be empty.
```

Verified against `hw/vivado/ip_repo/digilent/vivado-library/ip/rgb2dvi/component.xml` — **rgb2dvi v1.4 only exposes a `TMDS` interface** (output, type `digilentinc.com:interface:tmds_rtl:1.0`). It has parallel RGB inputs (`vid_pData`, `vid_pVDE`, `vid_pHSync`, `vid_pVSync`, `PixelClk`, `SerialClk`) — **no AXI-Stream slave port**.

`build_bd.tcl` line 215-217 tries:

```tcl
connect_bd_intf_net -intf_net vdma_to_rgb2dvi \
    [get_bd_intf_pins vdma_disp/M_AXIS_MM2S] \
    [get_bd_intf_pins rgb2dvi_0/s_axis_video]    ;# <-- pin does not exist
```

## Required design fix (B2 owner)

Add a `v_axis_to_video_out:4.0` (Xilinx Video AXI-Stream to Video Out) plus an `v_tc:6.2` (Video Timing Controller) between `vdma_disp.M_AXIS_MM2S` and `rgb2dvi_0`. Wiring:

```
vdma_disp.M_AXIS_MM2S  ─► v_axis_to_video_out.video_in ─┐
v_tc.vtiming_out ────────► v_axis_to_video_out.vtiming  │
                                                        │
                            v_axis_to_video_out         ▼
                              .vid_data ──────────► rgb2dvi_0.vid_pData
                              .vid_active_video ──► rgb2dvi_0.vid_pVDE
                              .vid_hsync     ────► rgb2dvi_0.vid_pHSync
                              .vid_vsync     ────► rgb2dvi_0.vid_pVSync
                              + already-wired PixelClk
```

Plus `v_tc/clk = FCLK_CLK1` (148.5 MHz pixel clock domain) and `v_tc/clken=1`.

Reference: Digilent's official Zybo Z7 HDMI demo BD (vivado-library/ip/rgb2dvi/docs has reference template + see `hw/vivado/ip_repo/digilent/vivado-boards/new/zybo-z7-20/A.0/hdmi_out_preset.tcl` if present).

## Estimated effort

~15-25 lines in `build_bd.tcl`:
- 2 `create_bd_cell` (v_axis_to_video_out, v_tc)
- 6 `connect_bd_intf_net` / `connect_bd_net` (data path + sync signals + clocks + resets)
- 1 `set_property` for v_tc generator-only mode

## Cumulative Step-5 attempt log

| # | Fix | New error |
|---|---|---|
| 1 | (vanilla) | [Board 49-71] board_part `:1.0` not found |
| 2 | Main installed vivado-boards (ff78be1) + `board.repoPaths` | same [Board 49-71] (file_version = 1.2, not 1.0) |
| 3 | Remote wrapper `:1.0` → `:1.2` + IP `.xo` placed | [BD 5-390] `xilinx.com:hls:sa_tiny_fpga_top:1.0` not found (`.xo` not a recognized IP extension) |
| 4 | Remote extracted .zip to `ip_repo/spike_accel/sa_tiny_fpga_top/` (component.xml at top) | (CWD bug — vivado didn't run) |
| 5 | Remote `cd /d` absolute path | HAS_HLS_IP=0 (I removed .xo); plus **[BD 5-106] rgb2dvi `s_axis_video` pin doesn't exist** |
| 6 | Remote restored `.xo` next to extracted dir | (still the BD 5-106 rgb2dvi issue if re-run as-is) |

The rgb2dvi issue is the design-level bug; cannot be fixed by Remote wrapper without touching `build_bd.tcl`.

## What Remote already produced and is preserved

- `hw/vivado/ip_repo/spike_accel/sa_tiny_fpga_top.xo` (zip, 156 KB — file-exists check passes)
- `hw/vivado/ip_repo/spike_accel/sa_tiny_fpga_top/component.xml` + `hdl/` + `constraints/` (proper IP-repo layout — Vivado finds VLNV)

These are correct and stay. The BD just can't complete without the v_axis_to_video_out shim.

## My recommendation

**Option α** (Main / B2 owner): patch `build_bd.tcl` section "10. HDMI video stream" to insert the v_axis_to_video_out + v_tc bridge. Likely ~15 min of B2 work; matches the rgb2dvi reference design Digilent ships.

**Option β** (Remote / wrapper extension): I add the missing connections via wrapper TCL after sourcing build_bd.tcl. But because `build_bd.tcl` aborts mid-construction on the failed `connect_bd_intf_net`, partial-BD state would be unusable. Wrapper can't easily salvage; needs the structural fix upstream.

**Option γ** (degraded): comment out the entire HDMI path in build_bd.tcl, ship a bitstream with PS + spike_accel only (no display). Useful for board bring-up of the accelerator alone. Worth doing if Main is slow on Option α.

## What I'm doing

- step5 partial report updated; URGENT_ASK_8 pushed.
- Standing by per AUTOPOLL. Will not retry Step 5 without Option α / γ fix from Main.
- Step 1 csim PASS, Step 3 csynth PASS, Step 4 gate manual PASS — all preserved at `1b0cb11`.

— Remote Claude, 2026-05-12T21:51:00+08:00
