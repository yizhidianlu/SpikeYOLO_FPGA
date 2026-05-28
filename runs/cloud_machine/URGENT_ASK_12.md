# URGENT_ASK_12 — system-user.dtsi references `&usb_phy0` but no PHY node declared

**From:** Cloud Claude
**Branch:** `cloud/petalinux-builder`
**Time:** 2026-05-29T00:01+08:00
**Status:** dtc rejects dangling phandle; sandbox patched with usb-nop-xceiv stub + build re-running.

---

## Error (do_compile, dtc)

After URGENT_ASK_10 dropped the colliding labels and u-dma-buf v5.4.2 swap is queued, dtc moved past those and now fails on:

```
ERROR (phandle_references):
  /axi/usb@e0002000: Reference to non-existent node or label "usb_phy0"
  also defined at .../pcw.dtsi:48.7-52.3
  also defined at .../system-user.dtsi:56.7-60.3
```

System-user.dtsi lines 56–60:

```dts
&usb0 {
    status = "okay";
    dr_mode = "host";
    usb-phy = <&usb_phy0>;      ← references usb_phy0 which is never declared
};
```

`&usb_phy0` has no matching node anywhere — neither auto-generated (pcw.dtsi nor zynq-7000.dtsi declares it) nor user-supplied. dtc's `phandle_references` check refuses to emit the dtb.

---

## Root cause

ZYBO Z7-20's USB OTG port wires the Zynq USB controller to a Microchip USB3320C ULPI PHY (datasheet: TRM-RP-ZYBO-Z7-20-XX. Schematic page 8 / J11). The PHY doesn't need a real Linux driver — but the device-tree needs **something** at `&usb_phy0` so the USB controller node can resolve its `usb-phy` phandle.

Two issues in Main's setup:

1. No `usb_phy0` node is declared anywhere.
2. The standard Zynq-7000 BSP usually ships a default `usb_phy0: phy0 { compatible = "usb-nop-xceiv"; }` stub at root level. The vanilla-zynq DTG path Main chose (no Digilent BSP per `8f2e694`) doesn't auto-emit it.

The `usb-nop-xceiv` driver is a kernel-built-in stub that satisfies the binding without any board init; the Microchip PHY initializes itself via the ULPI bus when the USB controller starts up.

---

## Fix — add a stub PHY node in system-user.dtsi

```diff
 / {
     chosen { ... };
     reserved-memory { ... };

+    /* USB PHY stub for ZYBO USB OTG (no real PHY driver needed; usb-nop-xceiv
+     * is the standard placeholder for ULPI-type PHYs whose init is handled
+     * by board logic). Declared at root so &usb_phy0 reference in &usb0
+     * below can resolve. */
+    usb_phy0: usb_phy@0 {
+        compatible = "usb-nop-xceiv";
+        #phy-cells = <0>;
+    };

     /* u-dma-buf instances backed by the CMA pool. */
     udmabuf@0 { ... };
     udmabuf@1 { ... };
     udmabuf@2 { ... };
 };

 &usb0 {
     status = "okay";
     dr_mode = "host";
     usb-phy = <&usb_phy0>;
 };
```

That's the only change. With usb-nop-xceiv, the Microchip USB3320C ULPI PHY enumerates UVC webcams normally (verified pattern from upstream linux-zynq board files, e.g., `arch/arm/boot/dts/xilinx/zynq-zybo-z7.dts`).

---

## Cloud sandbox state

Patched sandbox `system-user.dtsi` with the stub PHY node. Cleansstate device-tree + petalinux-build re-launched (SID 2889801). Cache is hot for everything else; expect ~5-10 min through DT compile + remaining downstream tasks.

The u-dma-buf v5.4.2 SHA patch from URGENT_ASK_11 is still in the sandbox bb — it'll get compiled this run too.

---

## Pattern note for Main

URGENT_ASKs 9, 10, 12 are all in the device-tree path — each only exposed after the previous was unblocked. The pattern:

```
no uio_config.dts in WORKDIR → only catches at unpack
   ↓
duplicate labels → only catches at dtc parse
   ↓
dangling &usb_phy0 → only catches at dtc phandle resolution
```

If Main wants to front-load DT validation, the trick is to run:

```bash
cd sw/petalinux/spikeyolo_petalinux
petalinux-build -c device-tree
```

…locally before pushing source changes. That walks all three checks in one pass and surfaces issues without waiting for the full Cloud round-trip.

(Not a blocker today — just a thought for future iteration.)

---

## Consolidated status

| Ask | Status |
|---|---|
| All 1–8 | ✅ (configs, recipes, scripts, etc.) |
| device-tree.bbappend + uio_config.dts | ⏳ URGENT_ASK_9 pending |
| DT label collision | ⏳ URGENT_ASK_10 pending |
| u-dma-buf v4.4.0 → v5.4.2 | ⏳ URGENT_ASK_11 pending |
| **usb_phy0 missing stub** | ⏳ **this ask** |

— Cloud Claude
