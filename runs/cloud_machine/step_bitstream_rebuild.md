# Step Bitstream Rebuild — Phase A Iteration 3 (FSBL escape-hatch + golden BD)

# ⚠️ ⚠️  DEBUG BRING-UP IMAGE — UNSAFE FOR PRODUCTION  ⚠️ ⚠️

Built per Main `cb0fc91` reframe (2026-05-31): config IS golden byte-for-byte,
the seed-tap iterations were tuning a knob training overwrites at every boot.
This image SKIPS FSBL's DDR self-test so we reach a TRAINED, quiescent DDR
controller for the decisive bench tests (POST-TRAIN slave regs + 0x55-vs-0xAA
symmetry + memtest from Linux). **Do NOT use for production — re-enable
DDRInitCheck once root cause is fixed.**

**Cloud:** ecs-user@47.116.52.72
**Branch:** `cloud/petalinux-builder`
**Completed:** 2026-05-31T15:08+08:00 (rebuild #5)

---

## What changed from #4

| Component | #4 (DQS_3=-0.050) | **#5 (escape-hatch + golden)** |
|---|---|---|
| `build_bd.tcl` §1b | DQS_3 = -0.050 override | **NO override** — golden preset stands |
| ps7_init.c DQS_3 seed | -0.050 | -0.100 (Digilent golden) |
| BOARD_DELAY3 | 0.244 (golden, unchanged) | 0.244 (golden, unchanged) |
| FSBL source | stock | **patched** — DDRInitCheck() call removed |
| TRAIN_WRITE_LEVEL/READ_GATE/DATA_EYE | 1/1/1 (all on) | 1/1/1 (unchanged) |

---

## Stage 3.5 — golden config confirmed in new XSA

```
PCW_UIPARAM_DDR_DQS_TO_CLK_DELAY_0:  -0.050    (preset)
PCW_UIPARAM_DDR_DQS_TO_CLK_DELAY_1:  -0.044    (preset)
PCW_UIPARAM_DDR_DQS_TO_CLK_DELAY_2:  -0.035    (preset)
PCW_UIPARAM_DDR_DQS_TO_CLK_DELAY_3:  -0.100    ← back to golden (Main's reframe)
PCW_UIPARAM_DDR_BOARD_DELAY3:         0.244    (preset, unchanged)
PCW_UIPARAM_DDR_PARTNO:               MT41K256M16 RE-125  (K-die 1.35V — correct)
fifo_we lane3 (0xF800614C):           0x35     (uniform with lanes 0/1/2 — confirms Main's transcription correction; no "0x140 outlier")
```

Vivado output: `system.bit` 1.4 MB, `system.xsa` 449 KB. Timing closed (WNS positive).

---

## FSBL patch — applied and verified in elf

**Patch path:**
```
sw/petalinux/project-spec/meta-user/recipes-bsp/fsbl-firmware/
    fsbl-firmware_%.bbappend
    files/skip-ddr-init-check.patch
```

**bitbake do_patch:** `recipe fsbl-firmware-2024.1+gitAUTOINC+b173d24682-r0: task do_patch: Succeeded` ✓

**Elf verification (the gating check):**
```
$ arm-none-eabi-objdump -d zynq_fsbl.elf | grep "bl.*<DDRInitCheck>"
(no output — DDRInitCheck call REMOVED)

$ arm-none-eabi-objdump -t zynq_fsbl.elf | grep "DDRInitCheck"
00001434 g     F .text	0000003c DDRInitCheck      ← symbol exists but unused
00000578 g     F .text	00000004 FsblHookFallback  ← still in binary, called from other fallback paths only
```

**No `bl <DDRInitCheck>` instruction anywhere in main()** — the call site at the old 0x10260 (the FSBL 0x578 trigger from rebuild #4) is gone. main()'s other `bl <FsblHookFallback>` callers (0x1258, 0x1278, 0x12b0) are non-DDR fallback paths (bitstream/partition load failures); they only fire on other faults.

Note: the patch also adds a `fsbl_printf` warning string, but production FSBL builds compile fsbl_printf calls out (DEBUG_GENERAL undefined in release). The warning won't appear on UART, but **the behavioral change — bypassing DDRInitCheck → FsblHookFallback — IS in effect**.

---

## Petalinux #5 — final artefacts (NEW shas)

`/home/ecs-user/SpikeYOLO_FPGA/sw/petalinux/spikeyolo_petalinux/images/linux/`:

| File | Size | sha256 |
|---|---:|---|
| **BOOT.BIN** | 1.2 MB | `695eaa7ff9e9e0d458465c111e8c7cd9969da432ad9e277bad3650c599f989af` |
| image.ub | 4.9 MB | `a0eddd5b81aed5b9cd7359df36f44380497571fa36496de995b67476ef215684` |
| **petalinux-sdimage.wic** | 6.1 GB | `07539ddb52897ea8369486a24f542ad66dd3128a5c603cac6f48ea8c76e901f5` |

| Build | wic sha | Note |
|---|---|---|
| #3 | `16560b97…` | DQS_3=0.000 — overshot too late |
| #4 | `fe16df43…` | DQS_3=-0.050 — wrong knob (training overwrites) |
| **#5** | **`07539ddb…`** | **golden + FSBL escape-hatch** |

Wic sha differs from #4 (different FSBL elf bytes due to patch) — verifies the patched build came through. image.ub identical because kernel didn't change.

`/lib/firmware/` content (cpio extract):
```
system.bit.bin       1,370,432 B  ← new placeholder PL from #5
tiny_fpga_int8.bin   1,343,776 B
```

---

## User instructions

### Option 2 — Flash + boot (the decisive test)

```bash
# Retrieve THE NEW wic (6.1 GB, sha 07539ddb…):
scp ecs-user@47.116.52.72:/home/ecs-user/SpikeYOLO_FPGA/sw/petalinux/spikeyolo_petalinux/images/linux/petalinux-sdimage.wic .

# Verify sha:
sha256sum petalinux-sdimage.wic
# 07539ddb52897ea8369486a24f542ad66dd3128a5c603cac6f48ea8c76e901f5

# Flash (verify /dev/sdX with lsblk!):
sudo dd if=petalinux-sdimage.wic of=/dev/sdX bs=4M conv=fsync status=progress
sync

# ZYBO: JP5=SD, insert SD, power on, COM3 @ 115200-8-N-1
```

**Expected outcome:** FSBL skips its DDR self-test → loads u-boot → kernel → login (because the same hardware path that booted FSBL → would-have-hit-DDRInitCheck-fallback can now reach u-boot/Linux even if mixed-pattern reads on byte-3 still mismatch).

### If UART speaks (u-boot prompt, kernel log, login):

Run the decisive bench tests **once Linux is up**, per Main 2026-05-31:

1. **POST-TRAIN slave register dump (4 byte lanes):**
   ```bash
   # As root on the board:
   devmem 0xF800612C 32    # DLL slave byte 0  (post-train)
   devmem 0xF8006130 32    # DLL slave byte 1
   devmem 0xF8006134 32    # DLL slave byte 2
   devmem 0xF8006138 32    # DLL slave byte 3   ← compare vs seed 0x288
   devmem 0xF8006140 32    # fifo_we byte 0
   devmem 0xF8006144 32    # fifo_we byte 1
   devmem 0xF8006148 32    # fifo_we byte 2
   devmem 0xF800614C 32    # fifo_we byte 3   ← compare vs seed 0x35
   devmem 0xF8006154 32 ; devmem 0xF8006158 32 ; devmem 0xF800615C 32   # write-side
   devmem 0xF8006168 32 ; devmem 0xF800616C 32 ; devmem 0xF8006170 32   # write-side
   ```
   - lane3 moved away from seed (0x288) toward 0/1/2 region → training locked → seed-tweak fix would never have stuck
   - lane3 still pinned at 0x288 while 0/1/2 moved → training couldn't lock lane3 → a seed fix MIGHT be durable

2. **0x55-vs-0xAA byte-3 symmetry test** (the killer):
   ```bash
   devmem 0x00100000 32 0x55000000 ; devmem 0x00100000 32
   devmem 0x00100000 32 0xAA000000 ; devmem 0x00100000 32
   ```
   - 0x55 survives, 0xAA collapses to 0xFF → non-symmetric 1-bias → PHYSICAL lane-3 fault, mathematically unfixable in software
   - Both survive → not lane-3 bit-stuck → escape-hatch revealed config WAS the issue (training reached good answer after DDRInitCheck was skipped early but the in-FSBL test had been false-failing)
   - Both collapse → wider lane-3 problem

3. **Memtest** (a few MB):
   ```bash
   memtester 16M 1
   # Or u-boot mtest 0x10000000 0x14000000
   ```

Push the results to `runs/cloud_machine/escape_hatch_bench.log` (user side) or paste in chat — Main and I will pick the next step from there.

### If UART STILL silent after flashing #5:

That'd be unexpected (escape-hatch should let FSBL through). Re-check:
1. COM port (FT2232 ChA vs ChB — try the other one)
2. JP5 SD vs JTAG
3. SD card seated, PG/DONE LEDs

If hardware checks out and #5 still silent → escape-hatch didn't take. URGENT_ASK.

---

## Stage / blocker summary

| Stage | Result |
|---|---|
| Source rebased to Main `945e2cc` (§1b NO override) | ✅ |
| FSBL bbappend + patch authored | ✅ `meta-user/recipes-bsp/fsbl-firmware/` |
| Vivado BD #5 golden | ✅ XSA verified DQS_3=-0.100, fifo_we=0x35 uniform |
| Petalinux #5 with FSBL patch | ✅ do_patch Succeeded, `bl <DDRInitCheck>` removed from elf |
| Packaging (BOOT.BIN + wic) | ✅ wic sha 07539ddb… |
| Step report v3 (this file) | ✅ |

| Open URGENT_ASKs (NOT blocking #5 flash test) | Status |
|---|---|
| URGENT_ASK_16 (HLS struct-of-pointer) | ⏸ Phase B |
| URGENT_ASK_18 (rgb2dvi vid_io vs AXIS) | ⏸ Phase B (HAS_HDMI gate in source) |

---

## sstate cache state

```
spikeyolo_petalinux/                 ~12 GB
  build/sstate-cache/                ~2.8 GB (now includes patched FSBL)
  build/downloads/                   ~800 MB (incl. udmabuf mirror)
  components/yocto/                  ~120 MB
```

— Cloud Claude, 2026-05-31T15:10+08:00
