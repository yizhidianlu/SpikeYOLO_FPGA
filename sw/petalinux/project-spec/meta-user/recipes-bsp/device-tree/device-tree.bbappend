# Pull in the C1-owned PL device-tree fragment alongside system-user.dtsi.
# system-user.dtsi is auto-fetched by Petalinux from the same files/ dir;
# spike-accel.dtsi is custom and must be declared explicitly so it lands in
# ${WORKDIR}/ where the /include/ "spike-accel.dtsi" line in system-user.dtsi
# can resolve it.

SRC_URI:append = " file://spike-accel.dtsi"
FILESEXTRAPATHS:prepend := "${THISDIR}/files:"
