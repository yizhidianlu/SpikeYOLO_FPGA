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

# Note: LIC_FILES_CHKSUM is the md5 of the upstream LICENSE file at this
# SRCREV. If it changes upstream, bitbake prints the new hash — copy it
# here and re-run. The placeholder below is a guess pending verification
# on first cloud-VM build.
LIC_FILES_CHKSUM = "file://LICENSE;md5=58e54c03ca7f821dd3967e2a2cd1596e"

inherit module

SRC_URI = "git://github.com/ikwzm/udmabuf.git;protocol=https;branch=master \
           file://u-dma-buf-init.conf"
SRCREV = "v4.4.0"

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
