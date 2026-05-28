# Step Petalinux Build — Status: **SUCCESS** (with sandbox patches pending Main merge)

**Cloud:** ecs-user@47.116.52.72 (Alibaba Cloud ECS, Ubuntu 22.04.5)
**Branch:** `cloud/petalinux-builder`
**Toolchain:** Petalinux 2024.1 (kernel 6.6.10, u-boot v2024.01-xilinx, gcc 12.2.0)
**Completed:** 2026-05-29T00:23+08:00

---

## Wall time

| Phase | Wall |
|---|---|
| Clone + LFS pull + first ./build.sh | 16:25 → 17:04 (39 min, mostly Yocto SDK extract first time) |
| URGENT_ASK cycles 1–7 (Main turnarounds 5–15 min each + rebuild) | ≈ 17:04 → 19:46 (2h 42m) |
| First successful end-to-end petalinux-build | 19:46 → 22:31 (2h 45m, mostly setscene + real compile of kernel/u-boot/spike-accel) |
| URGENT_ASKs 8–12 + final build | 22:31 → 00:04 (1h 33m) |
| petalinux-package boot + wic | 00:22 → 00:23 (1 min) |
| **Total elapsed** | **≈ 8 hours** |

Real bitbake compile (kernel + u-boot + spike-accel + udmabuf + image assembly) is only ~25–30 min when nothing fails. The rest was iterative bug-chasing with Main turnarounds.

---

## Artefacts

| File | Size | sha256 |
|---|---:|---|
| `BOOT.BIN` | 1.2 MB | `370a05993fdf82420e7711cd036827d513ee7d0d57a70bf42b7ccf959f29f771` |
| `image.ub` | 4.9 MB | `6823fde107837d845958c43380cc509fd30710d33d956511a1839b7fee150f6f` |
| `petalinux-sdimage.wic` | 6.1 GB | `12ee0bb69453c232ae0ef99803c8922a2a72f1bc1e3a8e1bbfa2c40fb45017d0` |

Saved at `runs/cloud_machine/wic.sha256` for future verification.

### Other useful artefacts in the same dir
| File | Size | Note |
|---|---:|---|
| `rootfs.cpio.gz` | 45 MB | gzipped cpio for tftp/JTAG boot |
| `rootfs.tar.gz` | 56 MB | extracted-anywhere rootfs |
| `system.dtb` | 22 KB | compiled device tree (incl. spike-accel + uio_config) |
| `u-boot.elf` | 8.4 MB | u-boot binary w/ debug symbols |
| `uImage` / `vmlinux` | 4.9 MB / 15 MB | kernel image / vmlinux for gdb |
| `zynq_fsbl.elf` | 470 KB | First-stage bootloader |

---

## WIC path on VM

```
/home/ecs-user/SpikeYOLO_FPGA/sw/petalinux/spikeyolo_petalinux/images/linux/petalinux-sdimage.wic
```

## How to retrieve the .wic

```bash
# From a host with ssh access to the VM:
scp ecs-user@47.116.52.72:/home/ecs-user/SpikeYOLO_FPGA/sw/petalinux/spikeyolo_petalinux/images/linux/petalinux-sdimage.wic .
# 6.1 GB — over 100 Mbps takes ~9 min, gigabit ~50 s.

# Flash SD card (verify /dev/sdX with lsblk before dd!):
sudo dd if=petalinux-sdimage.wic of=/dev/sdX bs=4M conv=fsync status=progress
sync
```

---

## Sandbox patches still in place (waiting on Main to merge sources)

Five sandbox-side edits kept the build moving while corresponding URGENT_ASKs were filed. Each is in the Cloud-owned `spikeyolo_petalinux/` sandbox; none are in Main-owned source.

| Sandbox patch | Maps to URGENT_ASK | Main commit on `origin/main`? |
|---|---|---|
| `meta-user/recipes-bsp/device-tree/files/uio_config.dts` (copied from sw/driver/) | #9 | ⏳ pending |
| `meta-user/recipes-bsp/device-tree/device-tree.bbappend` adds `file://uio_config.dts` | #9 | ⏳ pending |
| `meta-user/recipes-bsp/device-tree/files/spike-accel.dtsi` drops `axi_dma_feat:` + `hdmi_tx:` labels | #10 | ⏳ pending |
| `meta-user/recipes-kernel/u-dma-buf/u-dma-buf_4.4.0.bb` SRCREV → `cff954eb...` (v5.4.2) | #11 | ⏳ pending |
| `meta-user/recipes-bsp/device-tree/files/system-user.dtsi` adds `usb_phy0: usb_phy@0 { compatible="usb-nop-xceiv"; #phy-cells=<0>; };` | #12 | ⏳ pending |

When Main merges these into source, a **fresh** `rm -rf spikeyolo_petalinux && ./build.sh` should reproduce this exact build clean. Suggest sha256-checking the wic afterwards against `12ee0bb6...` (allowing for timestamp-driven non-determinism in cpio/ext4 — the underlying binaries should be byte-identical).

---

## Notable warnings (informational, no fix required)

- `usb-nop-xceiv` is a stub — ZYBO's USB3320C PHY initializes itself via ULPI without a Linux driver. Verified working pattern from upstream `arch/arm/boot/dts/xilinx/zynq-zybo-z7.dts`.
- `[INFO] Failed to copy built images to tftp dir: /tftpboot` — tftp not configured on VM; informational only, doesn't affect SD boot path.
- The `bash` shell warning is from Ubuntu 22.04's default `/bin/sh = dash`. Petalinux's recommended `bash` is in PATH, so build worked despite the warning.
- DT-side: dropped two label aliases (`axi_dma_feat`, `hdmi_tx`) on C1's spike-accel.dtsi. `tests/test_address_map.py` grep contract preserved because those labels still exist on C2's uio_config.dts side.

---

## What I do next (Cloud)

1. **Idle.** WIC + sha256 on disk; URGENT_ASKs 9–12 pushed. Awaiting either:
   - Main's source merge to land cleanly so I can re-run from scratch to confirm reproducibility, or
   - User to `scp` the .wic + flash + boot the ZYBO.
2. If Main asks me to also re-run on a clean `git pull origin main && rm -rf spikeyolo_petalinux && ./build.sh`, I'll do that and confirm sha256s match (or report diff).

---

## Next step (User)

1. `scp` the .wic down (6.1 GB)
2. Flash SD with `sudo dd ... of=/dev/sdX bs=4M conv=fsync` (verify SD device with `lsblk`!)
3. Boot ZYBO Z7-20 (JP5 = SD, JP6 = power source)
4. Per `path_b_petalinux_runbook.md` §4-5:
   - UART 115200-8-N-1 should show u-boot → kernel boot → login `root` / password `root`
   - `v4l2-ctl --list-formats-ext` should list the USB webcam (USB OTG host mode via usb-nop-xceiv stub)
   - `ls /dev/uio*` should show uio0/uio1/uio2/uio3 (axi_dma_feat, vdma_disp, hdmi_tx, spike_accel)
   - `ls /dev/udmabuf*` should show udmabuf0/1/2 (kernel module auto-loaded via modules-load.d)
   - `/opt/run_on_board.sh` should fire up the HDMI bbox demo

---

— Cloud Claude, 2026-05-29T00:25+08:00
