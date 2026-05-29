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
    u-dma-buf \
    spike-accel-app \
    fpga-firmware \
    fpga-manager-script \
"

# fpga-firmware ships system.bit.bin to /lib/firmware + programs the PL at
# boot via load-fpga.service; fpga-manager-script provides the fpgautil
# binary it calls (Cloud Claude uart_diag 869000a Bug A/B fix).

# Ensure the rootfs has a writable /opt for our demo binary.
IMAGE_FEATURES:append = " ssh-server-openssh debug-tweaks"
