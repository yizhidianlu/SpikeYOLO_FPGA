# Step Bitstream Rebuild — Phase A Iteration 2 (DQS_3 = -0.050) — Status: **SUCCESS, READY TO FLASH**

**Cloud:** ecs-user@47.116.52.72
**Branch:** `cloud/petalinux-builder`
**Completed:** 2026-05-30T14:31+08:00 (rebuild #4 — supersedes rebuild #3 with DQS=0.000)

---

## ⚠️ Supersedes rebuild #3

Rebuild #3 (wic sha `16560b97…`, with DQS_3 = 0.000) booted FSBL on the board but
still hung — JTAG showed the read eye flipped from "too early" (-0.100, reads 0)
to "too late" (0.000, reads 1). Eye-bracketed → center between them, set lane 3
to **-0.050** to match lane 0 and sit inside the working cluster
(lanes 0/1/2 = -0.050 / -0.044 / -0.035).

**Do NOT flash `16560b97…`** — that's the overshot version. Flash the
`fe16df43…` .wic from this report.

---

## XSA #4 — DDR fix applied AND CONFIRMED

`hw/vivado/out/system.xsa` extracted + `system.hwh` grepped:

```
PCW_UIPARAM_DDR_DQS_TO_CLK_DELAY_0:  -0.050    (preset, working lane)
PCW_UIPARAM_DDR_DQS_TO_CLK_DELAY_1:  -0.044    (preset, working lane)
PCW_UIPARAM_DDR_DQS_TO_CLK_DELAY_2:  -0.035    (preset, working lane)
PCW_UIPARAM_DDR_DQS_TO_CLK_DELAY_3:  -0.050    ← fix: -0.100 → 0.000 → NOW -0.050
PCW_UIPARAM_DDR_BOARD_DELAY0..3:      0.221/0.222/0.217/0.244  (preset, unchanged)
PCW_UIPARAM_DDR_PARTNO:               MT41K256M16 RE-125  (preset K-die 1.35V)
```

Lane 3 now == Lane 0 == -0.050 ns. All 4 lanes within ±15 ps cluster.

Timing closed:
```
WNS = +2.460 ns   (clk_fpga_0; slightly better than #3's +2.325)
TNS =  0.000      (0 failing endpoints)
WHS = +0.018 ns   (0 hold violations)
```

Phase A bitstream `hw/vivado/out/system.bit` (1.37 MB, ZYBO Z7-20 placeholder
PL — only PS+DMA+VDMA, no spike_accel/HDMI). Sufficient for FSBL DDR validation
because FSBL's DDR self-test is PS-side, independent of PL contents.

---

## Petalinux #4 — final artefacts (NEW shas)

`/home/ecs-user/SpikeYOLO_FPGA/sw/petalinux/spikeyolo_petalinux/images/linux/`:

| File | Size | sha256 |
|---|---:|---|
| **BOOT.BIN** | 1.2 MB | `d7ec5c46601fc4f08e138e3b6f37d15c3a37d32f9c299f742afb95dd78ad44bb` |
| **image.ub** | 4.9 MB | `a0eddd5b81aed5b9cd7359df36f44380497571fa36496de995b67476ef215684` |
| **petalinux-sdimage.wic** | 6.1 GB | `fe16df43803a5fcbcdd3e1c22067f4d1176561d5a254469c423440565cbc3a2c` |

Verification: **wic sha `fe16df43…` ≠ rebuild #3's `16560b97…`** → confirms the
new ps7_init.c (with DQS_3=-0.050) flowed all the way through Petalinux → FSBL
ELF → BOOT.BIN → wic. Different ps7_init bytes = different BOOT.BIN bytes =
different wic bytes. (image.ub sha is identical to #3 because the kernel itself
didn't change — only FSBL/u-boot did.)

### Rootfs verified

```
/lib/firmware/system.bit.bin       1,370,432 B  ← new Phase A placeholder PL
/lib/firmware/tiny_fpga_int8.bin   1,343,776 B  ← SNN weights (PBT)
/etc/systemd/system/sysinit.target.wants/load-fpga.service → /lib/systemd/system/load-fpga.service
```

---

## User instructions

### Option 1 — FAST JTAG pre-check (recommended, ~2 min)

Same as #3 report, but use the NEW XSA. From the Vivado host with the board on JTAG:

```bash
# Extract ps7_init.tcl from THIS XSA (NOT the #3 one):
cd /tmp && mkdir -p xsa4 && cd xsa4
unzip /path/to/cloud-pulled/system.xsa     # the one with DQS=-0.050
```

Then in xsct (connect, reset, fpga -file system.bit, source ps7_init.tcl,
ps7_init, ps7_post_config, then byte-lane-3 readback test from before).

If all 3 patterns now match → lane 3 -0.050 is the center → safe to flash.

### Option 2 — Flash + boot (this is the proof)

```bash
# Retrieve THE NEW wic (6.1 GB, sha fe16df43…):
scp ecs-user@47.116.52.72:/home/ecs-user/SpikeYOLO_FPGA/sw/petalinux/spikeyolo_petalinux/images/linux/petalinux-sdimage.wic .

# Verify sha BEFORE flashing — must equal fe16df43803a5fcbcdd3e1c22067f4d1176561d5a254469c423440565cbc3a2c
sha256sum petalinux-sdimage.wic

# Flash (verify /dev/sdX with lsblk!):
sudo dd if=petalinux-sdimage.wic of=/dev/sdX bs=4M conv=fsync status=progress
sync

# ZYBO board:
#   - JP5 = SD
#   - Insert SD, power on
#   - Host: open COM3 (FT2232 ChB; user-side correction per Main 2026-05-30 10:50) at 115200-8-N-1
```

Expected on COM3 within ~5 s:

```
Xilinx First Stage Boot Loader
Release 2024.1 ...
DDR initialization completed                 ← previously failed here on lane 3
... loading u-boot ...
U-Boot 2024.01-xilinx-v2024.1+gitAUTOINC+...
... Loading kernel ... systemd ...
[ ~2 s] load-fpga.service: programming PL from /lib/firmware/system.bit.bin
PetaLinux 2024.1 spikeyolo_petalinux ttyPS0
spikeyolo_petalinux login:
```

Login `root` / `root`.

---

## Stage / blocker summary

| Stage | Result |
|---|---|
| 0: Tools sourced | ✅ |
| 1: Digilent deps | ✅ |
| 2: HLS csynth | ⏸ Phase B (URGENT_ASK_16) |
| 3: Vivado BD + bitstream (rebuild #4) | ✅ XSA 459 KB / bit 1.37 MB |
| 3.5: DDR diag — **DQS_3 == -0.050 CONFIRMED in XSA**; WNS=+2.460ns | ✅ |
| 4: Petalinux #4 with -0.050 XSA | ✅ wic 6.1 GB sha `fe16df43…` |
| 5: Step report (this file, v2) | ✅ |

---

## Fallback ladder (if -0.050 still hangs)

Per Main's reply 2026-05-30 11:30, if -0.050 doesn't boot:
1. Try ±0.010 around -0.050 (-0.040 and -0.060) to map eye width
2. Custom-part explicit timing (URGENT_ASK_17 Option C)
3. Suspect physical lane-3 signal-integrity fault

**Expectation: -0.050 boots.** Data-driven bracket gives high confidence —
- failing extremes: -0.100 (too early) and 0.000 (too late)
- center: ~-0.050
- 3 working lanes at -0.050/-0.044/-0.035 means -0.050 is inside their cluster

---

## sstate cache state (kept warm for Phase B)

```
spikeyolo_petalinux/                 ~12 GB
  build/sstate-cache/                ~2.5 GB
  build/downloads/                   ~800 MB
  components/yocto/                  ~120 MB
```

— Cloud Claude, 2026-05-30T14:32+08:00
