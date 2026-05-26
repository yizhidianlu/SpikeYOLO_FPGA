# app_build_only.tcl — just build the existing app project, see what happens
setws C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/vitis_workspace
puts "running app build…"
set rc [catch {app build -name spike_accel_w9_smoke} result]
puts "rc=$rc"
puts "result=$result"
puts "done"
exit 0
