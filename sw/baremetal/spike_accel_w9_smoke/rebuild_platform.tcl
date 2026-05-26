# rebuild_platform.tcl — point existing platform at new system.xsa, regen,
# rebuild app.
setws C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/vitis_workspace
platform active spike_zybo_baremetal_plat
# Update HW spec from new XSA
catch {
    platform config -updatehw C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/hw/vivado/out/system.xsa
}
platform generate
app build -name spike_accel_w9_smoke
exit 0
