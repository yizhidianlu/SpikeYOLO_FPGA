# Pull in our kernel-config fragment.
SRC_URI:append = " file://user_kernel.cfg"
FILESEXTRAPATHS:prepend := "${THISDIR}/files:"
