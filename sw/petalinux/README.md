# sw/petalinux — Linux image (C1 Agent)

**Owner**: C1 Petalinux Agent — see [`docs/AGENT_PLAYBOOKS/C1_petalinux.md`](../../docs/AGENT_PLAYBOOKS/C1_petalinux.md)

## Purpose

Petalinux 2024.1 SD card image for ZYBO Z7-20 with USB UVC + DRM/KMS + AXI DMA + UIO + CMA. Hosts C2 driver/SDK and C3 application.

## Layout

```
build.sh                       one-shot build script
project-spec/
  configs/config               main Petalinux config
  meta-user/
    recipes-apps/              spike-accel-app recipe
    recipes-kernel/linux/      user_kernel.cfg (UVC, DRM, CMA, UIO)
    recipes-bsp/device-tree/   system-user.dtsi (includes uio_config.dts from C2)
images/linux/                  BOOT.BIN, image.ub, petalinux-sdimage.wic
```

## Build

```bash
source /opt/petalinux-v2024.1/settings.sh
bash build.sh    # depends on ../../hw/vivado/out/system.xsa
```

## Flash SD card

```bash
sudo dd if=images/linux/petalinux-sdimage.wic of=/dev/sdX bs=4M status=progress conv=fsync
```

## Acceptance gates

- Board boots to login prompt in < 30 s
- SSH works
- `v4l2-ctl --list-formats-ext` lists USB camera
- `/dev/dri/card0` and `/dev/uio0` both exist

## References

- Xilinx UG1144 PetaLinux Tools Documentation Reference Guide
- Digilent github PetaLinux BSP for ZYBO Z7-20
