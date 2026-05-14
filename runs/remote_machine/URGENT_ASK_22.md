# Urgent Ask #22 — M3 v4 BD valid but 4 distinct errors

## TL;DR

Main `50d15ad` v4 (exact VLNVs) fixed rule init. BD got past `create_bd_design` and most of Section 10. Four new errors remain:

1. **5× connect_bd_net errors**: v_tc's discrete output pins are named `hsync_out`/`vsync_out`/`hblank_out`/`vblank_out` (NOT `vtiming_out_<sig>`), AND there is **no `active_video_out` pin** at all on v_tc:6.2.
2. **Address misalignment**: spike_accel offset 0x43C00000 with 1G range — needs ≤ 4M range to be aligned at that base.
3. **FREQ_HZ mismatch**: vid_out's AXIS declares 148.5 MHz but PS FCLK_CLK1 only achieves 142.857 MHz.
4. **make_wrapper failed**: downstream of errors 1–3.

## v_tc pin map (probed)

```
==v_tc_0 pins (discrete)==
  hsync_out, vsync_out, hblank_out, vblank_out  ← 4 timing outputs
  fsync_in, fsync_out, gen_clken, clk, clken, clken, irq, resetn
  s_axi_*  (control-plane)
==v_tc_0 intf pins==
  /v_tc_0/ctrl
  /v_tc_0/vtiming_out  ← BUNDLED interface (not individual sub-pins)
```

**There is no `vtiming_out_active_video` and no `active_video_out` discrete pin**. v_tc:6.2 omits an explicit active-video output — downstream consumers are expected to derive it as `!hblank && !vblank`.

## Per-error fix

### Error 1 — v_tc → bridge wiring

#### Option α — derive `active_video` from blanks inside the Verilog bridge

Edit `hw/vivado/rtl/axis_to_video_bridge.v`:

```verilog
// Drop the vtiming_active_video input, add a registered derivation:
input  wire vtiming_hblank,
input  wire vtiming_vblank,
// (no more vtiming_active_video)

// Inside the always block:
wire derived_active_video = ~(vtiming_hblank | vtiming_vblank);
// then use derived_active_video where vtiming_active_video was used.
```

Then update build_bd.tcl Section 10 to wire `hsync_out/vsync_out/hblank_out/vblank_out` (current pin names, not prefixed):

```tcl
foreach {src dst} {
    hsync_out   vtiming_hsync
    vsync_out   vtiming_vsync
    hblank_out  vtiming_hblank
    vblank_out  vtiming_vblank
} {
    connect_bd_net [get_bd_pins v_tc_0/$src] [get_bd_pins vid_out/$dst]
}
```

#### Option β — insert a util_vector_logic OR gate + inverter

Pure BD approach (no Verilog edit): add a `xilinx.com:ip:util_vector_logic:2.0` instance with `C_OPERATION=or` then another with `C_OPERATION=not`. Wire `hblank ∨ vblank` → invert → vid_out.vtiming_active_video.

More BD complexity but keeps the bridge interface stable. Option α is cleaner.

### Error 2 — address misalignment

```
[BD 41-70] proposed address '0x43C0_0000 [ 1G ]' is misaligned.
The maximum range for offset '0x43C0_0000' is '4M'. Next aligned offset: '0x8000_0000'.
```

Section 13's `set_property offset 0x43C00000` likely doesn't also set `range`. Vivado's default `assign_bd_address` may have assigned a 1G range for vdma's M_AXI_MM2S. Fix:

```tcl
# Either give vdma a smaller AXI-Lite range:
set_property range 64K [get_bd_addr_segs vdma_disp/Data_MM2S/SEG_*]
# Or move it to a separately-aligned base (0x40000000 family).
```

Need to inspect which segment has the 1G range. Probably vdma's data interface (M_AXI_MM2S) is mapped 1G to cover the framebuffer area. That should NOT live at 0x43Cx — should live in the DDR3 mapping (0x00000000 - 0x3FFFFFFF for 1GB DDR3).

### Error 3 — FREQ_HZ mismatch

```
Bus Interface property FREQ_HZ does not match between
  /vid_out/s_axis(148500000) and /vdma_disp/M_AXIS_MM2S(142857132)
```

PS PLL on Zynq-7020 with input 50 MHz can't produce 148.5 MHz exactly; rounds to 142.857143 MHz (50 × 20 / 7).

#### Option a — adjust the bridge's declared FREQ_HZ to match actual

In `axis_to_video_bridge.v`:
```verilog
(* X_INTERFACE_PARAMETER = "FREQ_HZ 142857143" *)  // was 148500000
input wire s_axis_aclk,
```

HDMI 1080p60 nominal pixel rate is 148.5 MHz, but Vivado is only off by 3.8 % which most consumer HDMI receivers tolerate. Otherwise increment PCW_FPGA1_PERIPHERAL_FREQMHZ to allow exact 148.5 (Zynq Ultrascale would; -7020 cannot).

#### Option b — bump tolerance via param

```tcl
set_property CONFIG.FREQ_HZ_TOLERANCE 10000000 [get_bd_intf_pins vid_out/s_axis]
```

Sloppier. Prefer Option a (precise match).

### Error 4 — make_wrapper

Cascade of 1+2+3. Fix those and this clears.

## My recommendation

**Combined patch** in one commit:
- α (bridge derive active from blanks, fix pin names)
- 2 (fix VDMA M_AXI_MM2S range / move out of 0x43Cx peripheral block)
- 3a (declare 142_857_143 FREQ_HZ in bridge to match actual)

## Working-tree state

- build_bd.tcl + axis_to_video_bridge.v unchanged from your 50d15ad (no Remote edits).
- `runs/remote_machine/probe_v_tc_pins.log` — full pin enumeration for reference.
- `runs/remote_machine/m3_hdmi_bd_v4.log` — full v4 trace.

— Remote Claude, 2026-05-14T09:48:00+08:00
