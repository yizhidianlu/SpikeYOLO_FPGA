# Path B Board Integration — Petalinux Runbook

**Goal**: Boot ZYBO Z7-20 to Petalinux, run `spike_accel_demo`, see person/bus/train bboxes on HDMI from a USB webcam.

**Status**: Main-side prep done; build itself requires Linux + Petalinux 2024.1 SDK (see "Handoff Point" below).

---

## What Main already wired up (this branch, commit eb93bcd + this runbook)

| Layer | Change | File |
|---|---|---|
| NMS allowlist | `{0, 5, 6}` only — kill 77-class noise | `sw/app/src/main.cpp`, `postproc_nms.{h,cpp}` |
| HDMI overlay | PERSON / BUS / TRAIN text + colour-coded boxes | `sw/app/src/hdmi_overlay.{h,cpp}` |
| Petalinux recipe weights | Default to PBT (overridable via `SA_WEIGHTS_BIN`) | `sw/petalinux/scripts/fetch_app_sources.sh` |
| runtime.yaml lineage | SHA bumped to PBT `dc3786d6…` | `sw/app/configs/runtime.yaml` |
| PBT eval evidence | person 26% / bus 36% / train 38% AP50-95 @ ep20 | `runs/main_machine/pbt_ep20_eval.{json,log}` |
| Host fnv1a32 anchor (ramp) | `0x7474fd3c` for v12c + PBT — board hash unreachable per M3 close, kept as ground truth | (in commit msg `12ef7e0`) |

Tests: `python -m pytest tests/test_postproc_nms.py` → 17/17 pass (5 new allowlist cases).

---

## Handoff Point — needs a Linux host with Petalinux 2024.1 SDK

The Petalinux build itself can only run on Linux. Required:

- Xilinx Petalinux 2024.1 installed at `/opt/petalinux-v2024.1/` (or equivalent path; `source <path>/settings.sh`)
- ~50 GB free disk (BSP + downloads + sstate cache)
- `hw/vivado/out/system.xsa` from the v12c build — **currently only on the Remote (Vivado) machine; not in git**. Either:
  - Copy from Remote machine via `scp` / shared drive, OR
  - Re-export from Vivado on whatever machine runs the build
- Optional but recommended: Digilent ZYBO-Z7-20 BSP from <https://github.com/Digilent/Petalinux-Zybo-Z7-20> (ADR-0003 Option A)

If running on **Remote** (already has Vivado + system.xsa): install Petalinux SDK on that machine and do the build there.

If running on a **fresh Linux box**: copy the repo + system.xsa, install SDK, then follow steps below.

---

## Steps (on the Linux host with SDK)

### 1. Sanity-check inputs

```bash
cd /path/to/SpikeYOLO
git pull origin main                          # ensure this runbook + recipes are present
ls hw/vivado/out/system.xsa                   # must exist (copy from Remote if missing)
ls models/tiny_fpga_int8_pbt.bin              # 1343776 bytes; sha256 = dc3786d6...
source /opt/petalinux-v2024.1/settings.sh
petalinux-config --version                    # confirm 2024.1
```

### 2. Build

```bash
cd sw/petalinux

# First-time only, with Digilent BSP (recommended):
export PETALINUX_BSP=/path/to/Petalinux-Zybo-Z7-20-2024.1.bsp
./build.sh

# Or vanilla Zynq template (no display node out-of-the-box; needs more dtsi work):
./build.sh

# Incremental rebuild after source-only changes:
./build.sh --fast
```

Build artefacts land in `sw/petalinux/spikeyolo_petalinux/images/linux/`:

- `BOOT.BIN` — FSBL + u-boot + bitstream
- `image.ub` — kernel + dtb + rootfs
- `petalinux-sdimage.wic` — full SD card image

### 3. Flash SD card (any host with an SD writer)

```bash
# Find the SD card device first — DO NOT guess; verify with lsblk before dd
lsblk
sudo dd if=sw/petalinux/spikeyolo_petalinux/images/linux/petalinux-sdimage.wic \
        of=/dev/sdX bs=4M conv=fsync status=progress
sync
```

`/dev/sdX` must be the SD card, NOT the host's main disk — `dd` is unrecoverable.

### 4. Boot the board

1. Set JP5 boot-mode jumper to **SD** (not JTAG).
2. Insert SD card. Power on. UART (FT2232 channel B) at 115200-8-N-1.
3. Expected: u-boot → kernel boot in <30 s → login prompt `root` (password `root` in default BSP).

Acceptance gates (per `sw/petalinux/README.md`):
- SSH works (`ssh root@<board_ip>`)
- `v4l2-ctl --list-formats-ext` lists the USB webcam
- `/dev/dri/card0` and `/dev/uio0` both exist

### 5. Run the demo

USB webcam → board USB-A port. HDMI cable → monitor.

```bash
ssh root@<board_ip>
/opt/run_on_board.sh
```

`run_on_board.sh` invokes:

```sh
taskset -c 1 /opt/spike_accel_demo \
    --cam-dev /dev/video0 \
    --drm-dev /dev/dri/card0 \
    --weights /lib/firmware/tiny_fpga_int8.bin \
    --cam-size 640x480
```

Expected output:
- HDMI shows the webcam feed
- Green box + "PERSON" label on any person in frame
- Blue / red boxes for bus / train (rare in indoor demo; bring a printed photo of either to verify)
- No spurious boxes from the other 77 untrained classes (NMS allowlist)
- Console logs `stage_lat: cap=… pre=… infer=… post=… disp=… total=… effective_fps=…` every 30 frames

### 6. Tune (optional)

If person detection too sensitive / too sparse:

```bash
/opt/spike_accel_demo --conf 0.35 --iou 0.50 ...      # tighter
/opt/spike_accel_demo --conf 0.20 --iou 0.40 ...      # looser
```

Defaults are `conf=0.25 iou=0.45` (set in `runtime.yaml`).

---

## Known gaps / risks (be aware before running)

1. **No board hash for byte-exact verification** — JTAG halt path is blocked by DBGEN per M3 close (commit `0c6825c`). Functional demo will run, but any "is the INT8 path bit-exact?" check has to rely on host `0x7474fd3c` ramp hash, not board.

2. **Petalinux `cmake/zynq_toolchain.cmake` is missing** — referenced in `sw/app/CMakeLists.txt` comment but not committed. Not needed for the Yocto/bitbake path (the `spike-accel-app.bb` recipe uses the Petalinux SDK's own sysroot). Only matters if you want to cross-compile `sw/app/` standalone from a non-Petalinux host.

3. **runtime.yaml `weights_sha256` is lineage-only** — SDK does not gate on it. If you swap weights via `SA_WEIGHTS_BIN`, the lineage SHA in `runtime.yaml` will be stale. Update it manually or set `SA_WEIGHTS_SHA` (would need a small recipe tweak).

4. **MSYS2 g++ 5.3 ICE on host** — `sw/app/` cannot host-build on this Windows machine's MinGW gcc (the existing `test_postproc_nms_consistency.py` already documents the skip). Petalinux SDK gcc (≥ 9) compiles cleanly.

5. **Postproc `--allow-class` CLI flag** in `postproc_nms_cli` is for unit testing. The board-side `main.cpp` hard-codes `PBT_ALLOWLIST = {0,5,6}` (cleanest since the bitstream + model are bound together for this demo). If you ever want runtime class-allow override, add a YAML field + read from `runtime.yaml`.

6. **USB camera capture mode** — `runtime.yaml` defaults to `YUYV 640x480 30fps`. Some cameras only output MJPEG; flip `input.pixfmt: MJPEG` if `v4l2-ctl --list-formats-ext` does not show YUYV.

---

## If the board demo works but you also want byte-exact later

Two paths to unblock the JTAG-halt root cause (DBGEN):

- **A** — bake `PCW_DBGEN=1` (and related debug-auth signals) into `hw/vivado/build_bd.tcl`, rebuild `v13`, retest cold-halt. This is Main + Remote shared work.
- **B** — try a different JTAG cable / different host running `hw_server` (sometimes a different USB controller side-steps the issue). Pure user-hardware work.

Both are deferred per M3 PBT close (`0c6825c`).

---

— Main Claude, 2026-05-28T15:00
