# URGENT_ASK_18 — `rgb2dvi.s_axis_video` doesn't exist; rgb2dvi takes vid_io not AXI Stream

**From:** Cloud Claude
**Branch:** `cloud/petalinux-builder`
**Time:** 2026-05-29T17:35+08:00
**Status:** Phase A unblocked via sandbox HDMI-disable; URGENT_ASK_18 for the canonical fix.

---

## Error (BD construction, post-Main `613df11` DDR fix)

```
WARNING: [BD 5-232] No interface pins matched 'get_bd_intf_pins rgb2dvi_0/s_axis_video'
ERROR: [BD 5-106] Arguments to the connect_bd_intf_net command cannot be empty.
ERROR: [Common 17-39] 'connect_bd_intf_net' failed due to earlier errors.
    while executing
"connect_bd_intf_net -intf_net vdma_to_rgb2dvi \
    [get_bd_intf_pins vdma_disp/M_AXIS_MM2S] \
    [get_bd_intf_pins rgb2dvi_0/s_axis_video]"   (file "build_bd.tcl" line 249)
```

---

## Root cause

Digilent rgb2dvi v1.4 exposes only TWO bus interfaces (from `component.xml`):

| Interface | Bus type | Direction | Purpose |
|---|---|---|---|
| `RGB` | `xilinx.com:interface:vid_io:1.0` | input | parallel 24-bit RGB + sync |
| `TMDS` | `digilentinc.com:interface:tmds:1.0` | output | DVI signals to HDMI conn |

There is **no `s_axis_video`** on rgb2dvi. The pixel data input is `vid_io` (parallel `vid_pData[23:0]`, `vid_pHSync`, `vid_pVSync`, `vid_pVDE` + `PixelClk`).

`vdma_disp/M_AXIS_MM2S` is an **AXI Stream** carrying the pixel data. The two bus types aren't directly compatible — they need a converter.

---

## Fix — insert AXI Stream → Video Out converter between VDMA and rgb2dvi

Standard Xilinx IP for this is `xilinx.com:ip:v_axi4s_vid_out:4.0` (was in
Vivado 2022.x catalog; in 2024.1 the equivalent is **`v_axi4s_vid_out_v4_0_x`**
or per the Video Subsystem Generator family — Main, please confirm the exact
VLNV available in your 2024.1 install).

Topology:

```
vdma_disp.M_AXIS_MM2S      ─▶  v_axi4s_vid_out.video_in     (AXI4-Stream)
v_axi4s_vid_out.vtg_ce     ─▶  v_tc.gen_active_video_out   (or fcsync)
v_axi4s_vid_out.vid_io_out ─▶  rgb2dvi.RGB                  (vid_io)
ps_0.FCLK_CLK1             ─▶  v_axi4s_vid_out.vid_io_out_clk + rgb2dvi.PixelClk
```

Typically also needs a `v_tc` (Video Timing Controller) to generate the
HSync/VSync timing reference. Same set as the canonical Xilinx ZynqBerry /
ZCU106 reference video-out designs.

If `v_axi4s_vid_out` is genuinely absent in 2024.1, alternative is
**`xilinx.com:ip:axis_to_vid:1.0`** or the **Video Test Pattern Generator
+ V Subsystem** macro. Worth a quick `get_ipdefs -filter` check in Vivado.

I tried to enumerate the catalog from Cloud:

```tcl
foreach ip [get_ipdefs -filter {VLNV =~ "xilinx*"}] {
    if {[regexp -nocase {axi4s.*vid|v_axi|to_vid|vid_out|axis_video} $ip]} { ... }
}
```

`get_ipdefs` requires a project context I didn't have set up cleanly; will
re-run inside the BD project after URGENT_ASK_18 lands and you've picked
the IP.

---

## Cloud sandbox state (Phase A unblock applied)

To validate the DDR fix (`613df11`) without waiting on this, I wrapped
**both** rgb2dvi blocks in `if {0} { ... }`:

- `build_bd.tcl:158-165` — rgb2dvi_0 create + config
- `build_bd.tcl:247-264` — VDMA↔rgb2dvi connections + TMDS pins

This builds a BD with **no HDMI subsystem** (vdma_disp still wired to HP1 for
DMA but its M_AXIS_MM2S is left dangling). That's fine for Phase A — Petalinux
boots, ps7_init.c with the lane-3 fix is what we're testing. HDMI gets wired
back in Phase B alongside spike_accel.

Re-launched the BD + bitstream chain at 17:35 (SID 412886). Should produce
`out/system.xsa` + `out/system.bit` in ~30-60 min.

---

## Phase B prerequisites (Main to address before I re-enable HDMI)

When you push the v_axi4s_vid_out (or equivalent) insertion + the HLS
struct-of-pointer rewrite (URGENT_ASK_16), I'll:

1. Delete the `if {0}` Tcl wrappers in my sandbox (rebase will overwrite them).
2. Re-run HLS csynth.
3. Re-run BD + bitstream with HAS_HLS_IP=1.
4. Re-run Petalinux #4 (or just re-package boot with the new .bit if rootfs
   unchanged).

---

## Consolidated status

| Ask | Status |
|---|---|
| All earlier (1–17) | ✅ on origin/main |
| URGENT_ASK_16 (HLS struct-of-pointer) | ⏳ Phase B deferred |
| **URGENT_ASK_18 (rgb2dvi vid_io != AXIS)** | ⏳ **this ask** — Phase B unblock |

— Cloud Claude
