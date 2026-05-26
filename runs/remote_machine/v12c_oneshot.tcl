# v12c_oneshot.tcl — BD + bitstream in one Vivado session to avoid the
# fresh-project IPCACHE crash on launch_runs.
catch { set_param ip.useCacheStrategy 0 }
catch { set_param ip.checkLicense 0 }
catch { set_param ip.useIpCache 0 }
catch { set_param project.disableIPCache 1 }
catch { set_param general.maxThreads 1 }
# Try to prevent the IPCACHE thread pool entirely.
catch { set_param ip.detectCheckIpCache 0 }
catch { set_param ip.skipCacheValidation 1 }

source C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/hw/vivado/build_bd.tcl

# Now project is in-memory. Run the bitstream phase manually without
# closing/reopening.
puts "ONESHOT: BD done, starting synth+impl in same session"

# Open BD and refresh IP catalog state
update_ip_catalog
report_ip_status

# Disable IP cache entirely
catch { config_ip_cache -disable_cache }

# Launch runs
launch_runs synth_1 -jobs 1
wait_on_run synth_1

launch_runs impl_1 -to_step write_bitstream -jobs 1
wait_on_run impl_1

# Reports
open_run impl_1
report_timing_summary -file C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/hw/vivado/reports/timing_summary.rpt
report_utilization     -file C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/hw/vivado/reports/utilization.rpt

# Export
set OUT_DIR C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/hw/vivado/out
set IMPL_DIR [file join $OUT_DIR spike_zybo.runs impl_1]
catch {file copy -force [file join $IMPL_DIR system_wrapper.bit] [file join $OUT_DIR system.bit]}
write_hw_platform -fixed -force -file [file join $OUT_DIR system.xsa]

puts "ONESHOT DONE"
exit 0
