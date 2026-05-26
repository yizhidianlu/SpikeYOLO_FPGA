# build_w9_smoke_jtag.tcl — build the UART-bypass variant of W9 smoke.
# Imports ONLY main_jtag_only.c (not main.c) to avoid duplicate `main` symbols.
setws C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/vitis_workspace
platform active spike_zybo_baremetal_plat
# Remove the old app entirely so importsources rebuilds clean.
if {[catch {app remove -name spike_accel_w9_smoke} _err]} {
    puts "WARN: app remove: $_err (continuing)"
}
file delete -force C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/vitis_workspace/spike_accel_w9_smoke
file delete -force C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/vitis_workspace/spike_accel_w9_smoke_system

app create -name spike_accel_w9_smoke \
           -platform spike_zybo_baremetal_plat \
           -domain standalone_domain \
           -template {Empty Application(C)}

# Import only the JTAG-only main + the platform stub. Skip main.c (duplicate main()).
importsources -name spike_accel_w9_smoke \
              -path C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/sw/baremetal/spike_accel_w9_smoke/src/main_jtag_only.c

# Re-add platform.c stub (needed for init_platform / cleanup_platform).
set _wsdir C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/vitis_workspace/spike_accel_w9_smoke/src
set _platform_src $_wsdir/platform.c
if {![file exists $_platform_src]} {
    set fh [open $_platform_src w]
    puts $fh "#include \"xil_cache.h\""
    puts $fh ""
    puts $fh "void init_platform(void)    { Xil_ICacheEnable(); Xil_DCacheEnable(); }"
    puts $fh "void cleanup_platform(void) { Xil_DCacheDisable(); Xil_ICacheDisable(); }"
    close $fh
}

app build -name spike_accel_w9_smoke

set ::ELF C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/vitis_workspace/spike_accel_w9_smoke/Debug/spike_accel_w9_smoke.elf
if {[file exists $::ELF]} {
    puts "============================================================"
    puts "BUILD PASS — ELF (UART-bypass): $::ELF"
    puts "  size: [file size $::ELF] bytes"
    puts "============================================================"
} else {
    error "BUILD FAIL — ELF not produced"
}
exit 0
