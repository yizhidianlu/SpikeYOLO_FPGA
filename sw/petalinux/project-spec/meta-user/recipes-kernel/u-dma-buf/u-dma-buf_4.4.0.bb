# u-dma-buf_4.4.0.bb — ikwzm/udmabuf kernel module.
#
# Required by sw/sdk/src/dma_buf.c which opens /dev/udmabuf{0,1,2} for
# weights / input / output DMA-coherent memory.  Without this module
# loaded at boot, sa_init() fails with SA_ERR_DMA_ALLOC.
#
# Sizes (must match sw/sdk/src/internal.h):
#   udmabuf0 -> SA_WEIGHT_POOL_SIZE = 8 MB
#   udmabuf1 -> SA_INPUT_BUF_SIZE   = 196 608 B (round to 256 KB)
#   udmabuf2 -> SA_OUTPUT_BUF_SIZE  =  21 504 B (round to 64 KB)
# Buffer sizes are baked into u-dma-buf-init.conf, installed under
# /etc/modules-load.d/ + /etc/modprobe.d/.
#
# Cloud Claude URGENT_ASK_3 b2056e5, 2026-05-28.

SUMMARY = "User-space mappable DMA-coherent buffer kernel module (ikwzm/udmabuf)"
HOMEPAGE = "https://github.com/ikwzm/udmabuf"
LICENSE = "BSD-2-Clause"

# LIC_FILES_CHKSUM verified via `md5sum LICENSE` after first do_fetch on
# the cloud VM (Cloud Claude URGENT_ASK_6 1ed91c2, 2026-05-28). LICENSE
# remains BSD-2-Clause; only the hash changed from the initial guess.
LIC_FILES_CHKSUM = "file://LICENSE;md5=bebf0492502927bef0741aa04d1f35f5"

inherit module

SRC_URI = "git://github.com/ikwzm/udmabuf.git;protocol=https;branch=master \
           file://u-dma-buf-init.conf"
# Peeled SHA of refs/tags/v4.4.0^{} — bitbake's strict-fetch rejects
# floating tag strings; needs a 40-char commit SHA. Verified upstream
# via `git ls-remote https://github.com/ikwzm/udmabuf.git refs/tags/v4.4.0^{}`
# (Cloud Claude URGENT_ASK_5 7bb6971, 2026-05-28).
SRCREV = "c1e008a3b82f6f835196c9905d0dfdb3497f88aa"

S = "${WORKDIR}/git"

# Install the /etc/modules-load.d/ entry so udmabuf loads at every boot,
# plus /etc/modprobe.d/ options that allocate the right buffer sizes.
do_install:append() {
    install -d ${D}${sysconfdir}/modules-load.d
    install -d ${D}${sysconfdir}/modprobe.d
    echo "u-dma-buf" > ${D}${sysconfdir}/modules-load.d/u-dma-buf.conf
    install -m 0644 ${WORKDIR}/u-dma-buf-init.conf \
        ${D}${sysconfdir}/modprobe.d/u-dma-buf.conf
}

FILES:${PN} += " \
    ${sysconfdir}/modules-load.d/u-dma-buf.conf \
    ${sysconfdir}/modprobe.d/u-dma-buf.conf \
"

RPROVIDES:${PN} = "u-dma-buf"
KERNEL_MODULE_AUTOLOAD += "u-dma-buf"
