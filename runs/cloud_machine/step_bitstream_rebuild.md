# Step Bitstream Rebuild — Phase A (DDR fix) — Status: **SUCCESS, READY TO FLASH**

**Cloud:** ecs-user@47.116.52.72
**Branch:** `cloud/petalinux-builder`
**Completed:** 2026-05-30T10:38+08:00 (Phase A: DDR validation only; Phase B PL = placeholder)

---

## TL;DR

Lane-3 DDR DQS skew fixed in XSA → new ps7_init.c → new Petalinux .wic. Flash + boot — UART should now talk. PL is placeholder (no spike_accel/HDMI yet); that comes in Phase B.

---

## Vivado Stage 3.5 diag — DDR fix confirmed in XSA

`hw/vivado/out/system.xsa` extracted + `system.hwh` greppd:

```
PCW_UIPARAM_DDR_DQS_TO_CLK_DELAY_0:  -0.050    (unchanged, working lane)
PCW_UIPARAM_DDR_DQS_TO_CLK_DELAY_1:  -0.044    (unchanged, working lane)
PCW_UIPARAM_DDR_DQS_TO_CLK_DELAY_2:  -0.035    (unchanged, working lane)
PCW_UIPARAM_DDR_DQS_TO_CLK_DELAY_3:   0.000    ← fix: was -0.100, now centered
PCW_UIPARAM_DDR_BOARD_DELAY0..3:      0.221/0.222/0.217/0.244  (preset, untouched)
PCW_UIPARAM_DDR_PARTNO:               MT41K256M16 RE-125  (preset K-die 1.35V; correct for board)
```

Timing closed cleanly:
```
WNS = +2.325 ns   (clk_fpga_0)
TNS =  0.000      (no failing endpoints)
WHS = +0.015 ns   (no hold violations)
```

Phase A bitstream (`hw/vivado/out/system.bit`, 1.46 MB) is a Z7-20 design with PS-only data plane (no spike_accel — that's Phase B). Sufficient for DDR validation: the PS configures DDR via FSBL's ps7_init.c from this XSA's parameters; the PL contents are irrelevant for FSBL DDR self-test.

---

## Petalinux #3 — final artefacts

`/home/ecs-user/SpikeYOLO_FPGA/sw/petalinux/spikeyolo_petalinux/images/linux/`:

| File | Size | sha256 |
|---|---:|---|
| **BOOT.BIN** | 1.2 MB | `62e7755037f51f6b30d04523185c3751c25ffafa6c289a11dea31d31ac4a9bb2` |
| **image.ub** | 4.9 MB | `a0eddd5b81aed5b9cd7359df36f44380497571fa36496de995b67476ef215684` |
| **petalinux-sdimage.wic** | 6.1 GB | `16560b972d880c6f628e99ef5eb8586813802d9fead37c7e5b72303b3b821e0c` |

Sha differs from rebuild #2 (`f644e4d5…`) — expected: new ps7_init.c with lane-3 fix changes the FSBL byte-stream + new placeholder .bit.bin (1.46 MB) replaces the v12c .bit.bin.

### Rootfs verified

```
/lib/firmware/system.bit.bin       1,456,480 B  ← Phase A placeholder PL
/lib/firmware/tiny_fpga_int8.bin   1,343,776 B  ← SNN weights (PBT)
/etc/systemd/system/sysinit.target.wants/load-fpga.service → /lib/systemd/system/load-fpga.service
```

Boot sequence the .wic will execute:
1. ZYBO BootROM → FSBL (from BOOT.BIN)
2. FSBL runs ps7_init (now with lane-3 DQS=0.000) → DDR self-test passes → loads u-boot
3. u-boot → kernel from `image.ub` → mounts rootfs from SD partition 2
4. systemd reaches `sysinit.target` → `load-fpga.service` runs `fpgautil -b /lib/firmware/system.bit.bin -f Full` → PL programmed (with placeholder bitstream)
5. Login prompt on `ttyPS0` (UART1, MIO48/49, FT2232 ChB → COM)

---

## User instructions

### Option 1 — FAST: JTAG pre-check before flashing SD (recommended, ~2 min)

Save this as `/tmp/jtag_ddr_check.tcl` on the Vivado host, attach the board via JTAG (USB cable to FT2232 ChA), open `xsct` and:

```tcl
connect
targets -set -filter {name =~ "*Cortex-A9*#0*"}
rst -srst ; after 300            ; # let new FSBL/ps7_init configure DDR

# Manually load the new .bit and run the new ps7_init from your local build:
fpga -file /path/to/SpikeYOLO_FPGA/hw/vivado/out/system.bit
source /path/to/ps7_init.tcl     ; # from XSA extract: xsa_extract/ps7_init.tcl
ps7_init
ps7_post_config

# Byte-lane-3 readback test (the exact bytes that failed before):
mwr 0x00100000 0xAA55AA55 ; mrd 0x00100000 1     ; # expect 0xAA55AA55
mwr 0x00200000 0x12345678 ; mrd 0x00200000 1     ; # expect 0x12345678
mwr 0x00100000 0xFF000000 ; mrd 0x00100000 1     ; # expect 0xFF000000
```

If all 3 reads match → lane 3 fix confirmed → safe to flash.

(Don't have JTAG on hand? Skip to Option 2.)

### Option 2 — Flash + boot (the real proof)

From your local box (where you'll flash the SD):

```bash
# Retrieve the new .wic (6.1 GB, ~9 min over 100 Mbps, ~50 s over gigabit)
scp ecs-user@47.116.52.72:/home/ecs-user/SpikeYOLO_FPGA/sw/petalinux/spikeyolo_petalinux/images/linux/petalinux-sdimage.wic .

# Verify it matches what Cloud built:
sha256sum petalinux-sdimage.wic   # must equal 16560b97...

# Identify the SD card device (NOT your host disk!)
lsblk

# Flash:
sudo dd if=petalinux-sdimage.wic of=/dev/sdX bs=4M conv=fsync status=progress
sync

# Then on the ZYBO board:
#   - JP5 = SD (boot mode)
#   - Insert SD, power on
#   - On the host, open COM9 (FT2232 ChB) at 115200-8-N-1
```

Expected on COM9 within ~5 s of power-on:

```
Xilinx First Stage Boot Loader
Release 2024.1   Apr 24 2024  -  ...:...
DDR initialization completed
...
U-Boot 2024.01-xilinx-v2024.1+gitAUTOINC+...
...
[ 1.234567] systemd ... starting load-fpga.service
[ 2.345678] fpga_manager fpga0: writing system.bit.bin to ...
...
PetaLinux 2024.1 spikeyolo_petalinux ttyPS0
spikeyolo_petalinux login:
```

Login: `root` / password `root`.

If you see FSBL output but it stops before u-boot → DDR fix didn't fully resolve; broaden to all-4 lanes (URGENT_ASK_17 fallback).
If COM9 is still silent → recheck COM port assignment in Device Manager (FT2232 has 2 channels; ChA might be COM9, ChB the other; only ChB carries PS UART).

---

## Stage / blocker summary

| Stage | Result |
|---|---|
| 0: Tools sourced (Vivado/Vitis HLS 2024.1) | ✅ |
| 1: Digilent deps installed (vivado-library + board-files :1.2) | ✅ |
| 2: HLS csynth | ⏸ Phase B (URGENT_ASK_16 — `L` struct-of-pointer rewrite) |
| 3: Vivado BD + bitstream (placeholder spike_accel + no HDMI) | ✅ system.bit 1.46 MB |
| 3.5: DDR diag (lane3=0.000 ✓; WNS=+2.325ns ✓) | ✅ |
| 4: Petalinux #3 | ✅ wic 6.1 GB sha 16560b97… |
| 5: Step report (this file) | ✅ |

Open URGENT_ASKs (Phase B prerequisites; not blocking flash test):

- `URGENT_ASK_16` — HLS rewrite of `L` (struct-of-pointer → uint64_t addr arrays)
- `URGENT_ASK_18` — insert `v_axi4s_vid_out` + `v_tc` between vdma_disp and rgb2dvi for HDMI

When both land + Cloud reruns HLS → Vivado HAS_HDMI=1 HAS_HLS_IP=1 → Petalinux #4 → real spike_accel demo on board.

---

## sstate cache state (kept warm for Phase B)

```
spikeyolo_petalinux/                 ~12 GB
  build/sstate-cache/                ~2.5 GB
  components/yocto/                  ~120 MB
  build/downloads/                   ~800 MB (incl. udmabuf mirror — 792 KB)
```

Rebuild #4 (after Phase B fixes) ETA: ~10-15 min for HLS-aware bitstream + ~10-15 min for Petalinux re-package.

— Cloud Claude, 2026-05-30T10:40+08:00
