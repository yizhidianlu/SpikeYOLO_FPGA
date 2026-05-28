SUMMARY = "SpikeYOLO FPGA-accelerated end-to-end demo (C3)"
DESCRIPTION = "Bundles libspike_accel.so + spike_accel_demo + runtime.yaml"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

# Sources are kept in this repo; the recipe copies them in via a sibling fetch
# script (sw/petalinux/scripts/fetch_app_sources.sh) before building.
SRC_URI = "file://CMakeLists.txt \
           file://sdk/ \
           file://app/ \
           file://firmware/tiny_fpga_int8.bin \
           file://run_on_board.sh"

S = "${WORKDIR}"

inherit cmake pkgconfig

DEPENDS = "libdrm v4l-utils"

# Runtime deps: this bundle recipe builds both sdk/ and app/ in one CMake
# project (see fetch_app_sources.sh's generated CMakeLists.txt), so the
# libspike-accel.so it produces is auto-tracked by bitbake's shlibs
# handler.  No explicit RDEPENDS on libspike-accel — there is no sibling
# recipe to PROVIDE it, and listing it here would halt the dep resolver
# before do_package_qa fills in the SONAME (Cloud Claude URGENT_ASK_4
# dbd70eb, 2026-05-28).

EXTRA_OECMAKE = "-DSA_BUILD_TESTS=OFF -DSA_BUILD_STUB=OFF -DSA_APP_NO_V4L2=OFF -DSA_APP_NO_DRM=OFF"

do_install:append() {
    install -d ${D}/lib/firmware
    install -m 0644 ${S}/firmware/tiny_fpga_int8.bin ${D}/lib/firmware/
    install -d ${D}/opt
    install -m 0755 ${S}/run_on_board.sh ${D}/opt/
    # C3 ships runtime.yaml; create the etc dir so packaging works even if the
    # file is not yet present (will be overlaid by C3 in a later sprint).
    install -d ${D}${sysconfdir}/spike-accel/
    if [ -f ${S}/runtime.yaml ]; then \
        install -m 0644 ${S}/runtime.yaml ${D}${sysconfdir}/spike-accel/runtime.yaml; \
    fi
}

FILES:${PN} += "/lib/firmware/tiny_fpga_int8.bin /opt/run_on_board.sh"
FILES:${PN} += "${sysconfdir}/spike-accel/runtime.yaml"
