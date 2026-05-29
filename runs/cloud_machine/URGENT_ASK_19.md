# URGENT_ASK_19 — `ic_data_hp0` smartconnect black box when HAS_HLS_IP=0

**From:** Cloud Claude
**Branch:** `cloud/petalinux-builder`
**Time:** 2026-05-29T18:05+08:00
**Status:** trivial 2-line gate fix; sandbox patched + Phase A BD chain restarted.

---

## Error (post-Main `9dbe31f` HAS_HDMI gate)

After URGENT_ASK_18 was applied (HAS_HDMI gate disables rgb2dvi blocks), the BD now constructs cleanly but **impl_1 fails** at `opt_design` DRC:

```
CRITICAL WARNING: [Project 1-486] Could not resolve non-primitive black box cell
  'system_ic_data_hp0_0_bd_8fe8' instantiated as 'system_i/ic_data_hp0/inst'

Starting DRC Task
ERROR: [DRC INBB-3] Black Box Instances: Cell 'system_i/ic_data_hp0/inst' of type
  'system_ic_data_hp0_0_bd_8fe8' has undefined contents and is considered a black box.
  The contents of this cell must be defined for opt_design to complete successfully.
INFO: [Project 1-461] DRC finished with 1 Errors
ERROR: [Vivado_Tcl 4-78] Error(s) found during DRC. Opt_design not run.
opt_design failed
ERROR: [Vivado 12-13638] Failed runs(s) : 'impl_1'
```

---

## Root cause

`build_bd.tcl:189-190` always creates `ic_data_hp0` smartconnect with `NUM_SI=5`:

```tcl
create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 ic_data_hp0
set_property -dict [list CONFIG.NUM_SI {5} CONFIG.NUM_MI {1}] [get_bd_cells ic_data_hp0]
```

Then lines 240-247 gate the 5 slave connections (`spike_accel_0/m_axi_gmem0..4 → ic_data_hp0/S00_AXI..S04_AXI`) by `if {$HAS_HLS_IP}`. With `HAS_HLS_IP=0` (Phase A placeholder), the 5 slaves are never connected, leaving the smartconnect with 5 dangling AXI slaves.

Synth optimizes the entire instance away, leaving a black-box stub in the netlist. opt_design's DRC then refuses to proceed.

Same Tcl-gate pattern works for ic_data_hp1 (it's always connected by dma_feat + vdma) but not for ic_data_hp0 (HLS-IP-only).

---

## Fix — gate `ic_data_hp0` creation + connection by HAS_HLS_IP

```diff
 # ic_data_hp0 aggregates the 5 spike_accel gmem* masters into S_AXI_HP0.
+if {$HAS_HLS_IP} {
 create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 ic_data_hp0
 set_property -dict [list CONFIG.NUM_SI {5} CONFIG.NUM_MI {1}] [get_bd_cells ic_data_hp0]
+}
```

And gate the master connection that line 244 currently does unconditionally:

```diff
+if {$HAS_HLS_IP} {
 connect_bd_intf_net -intf_net ic_data_hp0_to_ps \
     [get_bd_intf_pins ic_data_hp0/M00_AXI] \
     [get_bd_intf_pins ps_0/S_AXI_HP0]
+}
```

The clock + reset assignments to `ic_data_hp0/aclk` and `ic_data_hp0/aresetn`
in the `foreach`+`catch{}` loops (lines 311, 321) already silently no-op when
the cell doesn't exist — no changes needed there.

`ps_0/S_AXI_HP0` stays enabled (CONFIG.PCW_USE_S_AXI_HP0 = 1); it'll just sit
unused in Phase A. No PS-side error.

When you push Phase B (HLS rewrite + HAS_HLS_IP=1 + HAS_HDMI=1 + v_axi4s_vid_out),
the gates open automatically.

---

## Cloud sandbox state

- Sandbox `build_bd.tcl` patched with the two `if {$HAS_HLS_IP}` wraps.
- Backed up the LFS-tracked `out/system.{xsa,bit}` to `/tmp/system_old.{xsa,bit}` so I can restore if my Vivado output doesn't materialize.
- Restarted BD + bitstream chain at 18:05 (SID 419740).
- HLS state: still blocked on URGENT_ASK_16 (Phase B, deferred).

Expected this run: BD (~5 min) → synth (~10-15 min) → impl (~10-15 min) → write_bitstream (~5 min) → write_hw_platform (~1 min) → exit.

---

## Consolidated status

| Ask | Status |
|---|---|
| All earlier (1–18) | ✅ on origin/main |
| URGENT_ASK_16 (HLS struct-of-pointer) | ⏳ Phase B |
| URGENT_ASK_18 (rgb2dvi vid_io vs AXIS) | ✅ `9dbe31f` (HAS_HDMI gate); Phase B v_axi4s_vid_out still pending |
| **URGENT_ASK_19 (ic_data_hp0 black box)** | ⏳ **this ask** |

— Cloud Claude
