---
id: C1
name: petalinux
group: C
milestones: [M2, M3]
inputs_glob:
  - "hw/vivado/out/system.bit"
  - "hw/vivado/out/system.hwh"
  - "hw/vivado/out/system.xsa"
  - "hw/vivado/out/address_map.yaml"
outputs_glob:
  - "sw/petalinux/project-spec/configs/config"
  - "sw/petalinux/project-spec/meta-user/recipes-apps/**"
  - "sw/petalinux/project-spec/meta-user/recipes-kernel/**"
  - "sw/petalinux/build.sh"
  - "sw/petalinux/images/linux/BOOT.BIN"
  - "sw/petalinux/images/linux/image.ub"
  - "sw/petalinux/images/linux/rootfs.tar.gz"
contracts:
  produces: []
  consumes: [C4]
acceptance_tests:
  - "bash sw/petalinux/build.sh"
  - "ls -lh sw/petalinux/images/linux/BOOT.BIN sw/petalinux/images/linux/image.ub"
  - "scripts/test_boot.sh"  # 启动 < 30s + USB cam + HDMI 检查
status: in_progress
owner: "C1-session-2026-05-11"
---

# C1 Petalinux Agent Playbook

## Mission

基于 B2 输出的硬件平台 `system.xsa` 构建 Petalinux 2024.1 SD 卡镜像，
集成 USB UVC 摄像头驱动、HDMI DRM/framebuffer、AXI DMA 内核模块、
V4L2 用户空间工具，启动后能立即跑 spike_accel 应用。

## 关键技术决策

| 维度 | 选择 | 理由 |
|---|---|---|
| Petalinux 版本 | 2024.1 | 与 Vivado 对齐 |
| 内核 | linux-xlnx 2024.1 LTS（6.1 系列） | 稳定 + 官方维护 |
| Rootfs | minimal + busybox + 选装包 | 减启动时间 + 减 SD 体积 |
| 网络 | 默认 DHCP eth0 + sshd | 调试用 |
| 显示栈 | DRM/KMS（不用 fbdev legacy） | 现代 + zero-copy |
| 启动方式 | SD 卡 BOOT.BIN + image.ub | ZYBO 默认 |

## 工作流

### Phase 1: 项目初始化（M2 Week 1）

```bash
# sw/petalinux/build.sh
#!/bin/bash
set -e
source /opt/petalinux-v2024.1/settings.sh

if [ ! -d "spikeyolo_petalinux" ]; then
    petalinux-create -t project --template zynq -n spikeyolo_petalinux
fi
cd spikeyolo_petalinux

# 导入 B2 硬件平台
petalinux-config --get-hw-description=../../../hw/vivado/out/ --silentconfig
```

### Phase 2: 配置定制（M2 Week 1-2）

`project-spec/configs/config` 关键项：

```
# 启用 SD 卡启动
CONFIG_SUBSYSTEM_PRIMARY_SD_PSU_SD_1_SELECT=y
CONFIG_SUBSYSTEM_BOOTARGS_AUTO=y
CONFIG_SUBSYSTEM_ROOTFS_SD=y

# rootfs 配置
CONFIG_SUBSYSTEM_ROOTFS_INITRAMFS=n
CONFIG_SUBSYSTEM_ROOTFS_EXT4=y
```

`project-spec/meta-user/recipes-kernel/linux/linux-xlnx_%.bbappend`：

```bitbake
SRC_URI += "file://user_kernel.cfg"
```

`project-spec/meta-user/recipes-kernel/linux/linux-xlnx/user_kernel.cfg`：

```
# UVC USB camera
CONFIG_USB_VIDEO_CLASS=y
CONFIG_MEDIA_USB_SUPPORT=y
CONFIG_USB_GSPCA=y
CONFIG_V4L_PLATFORM_DRIVERS=y

# DRM/KMS
CONFIG_DRM=y
CONFIG_DRM_XLNX=y
CONFIG_FB=n  # 禁用 fbdev legacy
CONFIG_FRAMEBUFFER_CONSOLE=n

# Xilinx AXI DMA
CONFIG_XILINX_DMA=y
CONFIG_XILINX_VDMA=y

# UIO（用户空间访问 spike_accel）
CONFIG_UIO=y
CONFIG_UIO_PDRV_GENIRQ=y

# CMA pool for DMA buffers
CONFIG_CMA=y
CONFIG_CMA_SIZE_MBYTES=256

# 调试
CONFIG_DYNAMIC_DEBUG=y
```

`project-spec/meta-user/recipes-bsp/device-tree/files/system-user.dtsi`：

```dts
/include/ "uio_config.dts"   /* 由 tools/ci/gen_dts.py 自动生成 */

&i2c0 {
    status = "okay";
};

&usb0 {
    status = "okay";
    dr_mode = "host";        /* USB UVC 必须 host 模式 */
};
```

`project-spec/meta-user/recipes-core/images/petalinux-image-minimal.bbappend`：

```bitbake
IMAGE_INSTALL:append = " \
    v4l-utils \
    libdrm \
    libdrm-tests \
    libgpiod \
    cmake \
    gdb \
    htop \
    iproute2 \
    openssh \
    openssh-sftp-server \
    spike-accel-app \
"
```

### Phase 3: 集成 spike_accel SDK + App（M3 Week 1-2）

```bash
# 拉 C2/C3 产物作为 Yocto recipe
petalinux-create -t apps --template c++ --name spike-accel-app --enable
```

`project-spec/meta-user/recipes-apps/spike-accel-app/spike-accel-app.bb`：

```bitbake
SUMMARY = "SpikeYOLO FPGA accelerated demo"
LICENSE = "MIT"

SRC_URI = "file://CMakeLists.txt \
           file://main.cpp \
           file://preproc.cpp \
           file://postproc_nms.cpp \
           file://drm_display.cpp \
           file://v4l2_capture.cpp"

S = "${WORKDIR}"
inherit cmake

DEPENDS += "libdrm v4l-utils libspike-accel"

FILES_${PN} += "/lib/firmware/tiny_fpga_int8.bin"
```

### Phase 4: 烧录与板上自检（M2 Week 4 - M3 Week 1）

```bash
# 烧录 SD 卡（PC 上操作）
sudo dd if=images/linux/petalinux-sdimage.wic of=/dev/sdX bs=4M status=progress conv=fsync

# 板上自检
ssh root@zybo "uname -a && v4l2-ctl --list-formats-ext && ls /dev/dri/"
```

期望输出：

```
Linux zybo 5.15.x #1 SMP ...
ioctl: VIDIOC_ENUM_FMT
        Type: Video Capture
        [0]: 'YUYV' (YUYV 4:2:2)
                Size: Discrete 640x480
                        Interval: Discrete 0.033s (30.000 fps)
/dev/dri/card0
/dev/dri/renderD128
```

## 关键文件

| 文件 | 用途 | 状态 |
|---|---|---|
| `sw/petalinux/build.sh` | 一键构建脚本 | 新建 |
| `sw/petalinux/project-spec/configs/config` | Petalinux 配置 | 新建 |
| `sw/petalinux/project-spec/meta-user/recipes-kernel/linux/user_kernel.cfg` | 内核 config | 新建 |
| `sw/petalinux/project-spec/meta-user/recipes-bsp/device-tree/files/system-user.dtsi` | 设备树 | 新建（含 uio_config.dts） |
| `sw/petalinux/project-spec/meta-user/recipes-apps/spike-accel-app/spike-accel-app.bb` | 应用 recipe | 新建 |
| `sw/petalinux/images/linux/BOOT.BIN` | 启动镜像 | 新建 |
| `sw/petalinux/images/linux/image.ub` | 内核 + dtb + rootfs | 新建 |
| `sw/petalinux/images/linux/petalinux-sdimage.wic` | 完整 SD 卡镜像 | 新建 |

## Risk Handlers

| 风险 | 触发 | 处理 |
|---|---|---|
| **R7 USB UVC 不识别** | `/dev/video0` 不出现 | (a) 重编内核确认 `CONFIG_USB_VIDEO_CLASS=y`; (b) 检查 `dr_mode = "host"` 设备树; (c) 切换主线 Yocto 而非 Petalinux |
| **DRM 没初始化** | `/dev/dri/card0` 不出现 | (a) 检查 HDMI IP 在 system.bit 中存在; (b) 加载 `xlnx_drm.ko` 手工 modprobe |
| **CMA 不足** | `dmesg` 报 `cma alloc failed` | (a) `CMA_SIZE_MBYTES=512`; (b) 检查应用没漏 free |
| **启动时间 > 30s** | systemd-analyze blame | (a) 禁不必要服务（systemd-networkd-wait-online）; (b) initramfs 加速 |

## 交接给 C2/C3 的清单

✅ SD 卡能 boot 到登录提示符  
✅ SSH 可登录  
✅ `v4l2-ctl` 看到 USB cam  
✅ `/dev/dri/card0` 存在  
✅ `/dev/uio0` (spike_accel) 存在  
✅ 启动 < 30 s

## 参考资料

- Xilinx UG1144 PetaLinux Tools Documentation Reference Guide
- Digilent github PetaLinux BSP for ZYBO Z7-20
- linux/Documentation/admin-guide/cma_debugfs.rst
