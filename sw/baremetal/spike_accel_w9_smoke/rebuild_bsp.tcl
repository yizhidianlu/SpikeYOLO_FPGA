# rebuild_bsp.tcl — re-generate BSP after boot.S edit
setws C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/vitis_workspace
platform active spike_zybo_baremetal_plat
platform generate
app build -name spike_accel_w9_smoke
exit 0
