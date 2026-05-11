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
"

# Ensure the rootfs has a writable /opt for our demo binary.
IMAGE_FEATURES:append = " ssh-server-openssh debug-tweaks"
