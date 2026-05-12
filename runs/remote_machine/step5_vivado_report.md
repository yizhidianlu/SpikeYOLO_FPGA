# Step 5 — Vivado BD + bitstream (5 attempts, all BLOCKED)

## Status: BLOCKED — `build_bd.tcl` wires `vdma_disp → rgb2dvi.s_axis_video` but rgb2dvi has no AXI-Stream port (URGENT_ASK_8)

Past two prior blockers (board_part missing, IP catalog discovery) but hit a deeper design-level bug in the HDMI section.

## Attempts

| # | Fix applied | New error |
|---|---|---|
| 1 | vanilla | `[Board 49-71]` zybo-z7-20:part0:1.0 not found |
| 2 | Main `ff78be1` (vivado-boards submodule + board.repoPaths) | same [Board 49-71] (file_version = 1.2, not 1.0) |
| 3 | Remote wrapper :1.0 → :1.2 + .xo placed | `[BD 5-390]` xilinx.com:hls:sa_tiny_fpga_top:1.0 not found |
| 4 | Remote unzipped .xo to ip dir | (CWD bug — vivado didn't even run) |
| 5 | `cd /d` absolute path | HAS_HLS_IP=0 (.xo removed during extract); **+ [BD 5-106] rgb2dvi.s_axis_video pin doesn't exist** |

## Latest error (verbatim)

```
WARNING: [BD 5-232] No interface pins matched 'get_bd_intf_pins rgb2dvi_0/s_axis_video'
ERROR: [BD 5-106] Arguments to the connect_bd_intf_net command cannot be empty.
ERROR: [Common 17-39] 'connect_bd_intf_net' failed due to earlier errors.

    while executing
"connect_bd_intf_net -intf_net vdma_to_rgb2dvi \
    [get_bd_intf_pins vdma_disp/M_AXIS_MM2S] \
    [get_bd_intf_pins rgb2dvi_0/s_axis_video]"
```

Verified against `hw/vivado/ip_repo/digilent/vivado-library/ip/rgb2dvi/component.xml`: rgb2dvi v1.4 exposes only `TMDS` interface plus parallel-RGB inputs (`vid_pData`, `vid_pVDE`, `vid_pHSync`, `vid_pVSync`, `PixelClk`, `SerialClk`). No `s_axis_video`.

## Diagnosis

`build_bd.tcl` lines 215-217 assume rgb2dvi takes AXI-Stream video — wrong. Needs a `v_axis_to_video_out:4.0` + `v_tc:6.2` (Video Timing Controller) bridge between VDMA and rgb2dvi. See URGENT_ASK_8 §"Required design fix" for the wiring.

## Outputs preserved

- `hw/vivado/ip_repo/spike_accel/sa_tiny_fpga_top.xo` (156 KB zip — file-exists check OK)
- `hw/vivado/ip_repo/spike_accel/sa_tiny_fpga_top/` (extracted IP — Vivado catalog OK)
- `runs/remote_machine/run_step5_bd_patched.tcl` (BOARD_PART :1.0 → :1.2 wrapper)
- `runs/remote_machine/diag_get_board_parts.tcl` (verified VLNV)

## Next step

Awaiting Main / B2 patch per URGENT_ASK_8 Option α (insert v_axis_to_video_out + v_tc) or Option γ (drop HDMI for now). Step 6 (push) and Step 5 final reports remain queued.
