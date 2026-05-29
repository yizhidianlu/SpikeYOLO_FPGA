# Rebuild #2 verify — fpga-firmware chain end-to-end OK; HOLD flashing

**From:** Cloud Claude
**Time:** 2026-05-29T15:18+08:00
**Status:** Rebuild #2 .wic generated; chain verified; **NOT for flashing** per Main's `b422501` (still has RE-125 ps7_init → would FSBL DDR-hang on board).

---

## End-to-end chain verified

`/home/ecs-user/SpikeYOLO_FPGA/sw/petalinux/spikeyolo_petalinux/images/linux/`:

```
BOOT.BIN                1.2 MB
petalinux-sdimage.wic   6.1 GB
sha256(wic) = f644e4d572ccc9484b4cbcce42d4098ec92d74766728cc5770dca37471ac0b89
```

(Differs from rebuild #1's `12ee0bb6…` because rootfs now contains
`system.bit.bin` + `load-fpga.service` — that's the expected delta from the
new fpga-firmware recipe.)

Rootfs contents (cpio extract of `rootfs.cpio.gz`):

| Path | Size | Owner / source |
|---|---:|---|
| `/lib/firmware/system.bit.bin` | 2,524,672 B | fpga-firmware recipe (bootgen .bit→.bit.bin) |
| `/lib/firmware/tiny_fpga_int8.bin` | 1,343,776 B | spike-accel-app (PBT weights) |
| `/etc/systemd/system/sysinit.target.wants/load-fpga.service` | symlink → `/lib/systemd/system/load-fpga.service` | systemd auto-enable wired up |

So when the board eventually boots (after Remote's HA-125 XSA fix), this
rootfs would:
1. Reach `sysinit.target`
2. Run `load-fpga.service` (oneshot)
3. Invoke `fpgautil -b /lib/firmware/system.bit.bin -f Full`
4. PL programmed → spike-accel/UIO/HDMI drivers can probe

---

## Decision per Main `b422501`

**HOLD** sending this .wic to the user. Still has the RE-125 ps7_init →
FSBL byte-lane-3 read-training fails → 0x578 hang, same as rebuild #1.
No point burning an SD for it.

---

## What I'm waiting for

Remote's HA-125 DDR-corrected `system.xsa` + `system.bit` to land on `vivado/synth-runner` → Main cherry-picks to `main` → I:

```bash
git fetch origin && git rebase origin/main
# sstate stays warm; only fsbl, u-boot, device-tree rebuild (new ps7_init)
cd sw/petalinux && ./build.sh
```

Rebuild #3 ETA after XSA lands: ~10-15 min (only ps7_init-derived recipes
need to re-run; rootfs/kernel/u-dma-buf/spike-accel-app etc. all cached).

That .wic is the one the user flashes.

---

## Cache state (for snapshot planning)

`spikeyolo_petalinux/` total: ~10–12 GB on /tools (room for ≥3 more rebuilds before disk pressure on the 290 GB free)
`spikeyolo_petalinux/build/sstate-cache/`: ~2.5 GB hot
`spikeyolo_petalinux/components/yocto/`: ~120 MB (one-shot SDK extract)
`spikeyolo_petalinux/build/downloads/`: ~800 MB (incl. ikwzm/udmabuf mirror)

Keep all of this — rebuild #3 with new ps7_init will reuse 99%.

— Cloud Claude
