# runs/remote_machine/run_step6_timing_perf_explore.tcl
#
# M2-W2 timing closure: retry impl_1 with Performance_Explore strategy.
# v7 baseline: WNS -0.764 ns, TNS -35.489 ns, 172/134900 endpoints fail.
# Performance_Explore typically buys 0.5-1.0 ns over Vivado Defaults.

set PROJECT spike_zybo
set HW_VIVADO_DIR "C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/hw/vivado"
set OUT_DIR  "$HW_VIVADO_DIR/out"
set REPORTS  "$HW_VIVADO_DIR/reports"
set REMOTE   "C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/runs/remote_machine"

open_project [file join $OUT_DIR ${PROJECT}.xpr]

# Strategy switch (writes back to .xpr metadata).
set_property strategy Performance_Explore [get_runs impl_1]
puts "INFO: impl_1 strategy set to Performance_Explore"

# IPCACHE workarounds (consistent with baseline wrapper).
catch { set_param ip.useCacheStrategy 0 }
catch { set_param ip.checkLicense 0 }
catch { set_param ip.useIpCache 0 }
catch { set_param project.disableIPCache 1 }

# Reset only impl_1 — synth_1 + sub-IP synth from v7 are still valid.
catch { reset_run impl_1 }

# ===== Impl =====
launch_runs impl_1 -to_step write_bitstream -jobs 1
wait_on_run impl_1

# ===== Reports (overwrite v7 baseline; keep v7 in step6_bt_v7.log for diff). =====
open_run impl_1
report_timing_summary -file [file join $REMOTE timing_summary_perf_explore.rpt]
report_utilization     -file [file join $REMOTE utilization_perf_explore.rpt]

# Also overwrite hw/vivado/reports/ if write_bitstream succeeded.
if {[file exists [file join $OUT_DIR ${PROJECT}.runs impl_1 system_wrapper.bit]]} {
    report_timing_summary -file [file join $REPORTS timing_summary.rpt]
    report_utilization     -file [file join $REPORTS utilization.rpt]
    catch { report_power   -file [file join $REPORTS power.rpt] }
    catch {file copy -force [file join $OUT_DIR ${PROJECT}.runs impl_1 system_wrapper.bit] [file join $OUT_DIR system.bit]}
    catch {file copy -force [file join $OUT_DIR ${PROJECT}.runs impl_1 system_wrapper.ltx] [file join $OUT_DIR system.ltx]}
    write_hw_platform -fixed -force -file [file join $OUT_DIR system.xsa]
    puts "INFO: bitstream + XSA refreshed with Performance_Explore"
} else {
    puts "WARN: write_bitstream did not produce .bit (likely timing-driven abort or place fail)"
}

puts "============================================================"
puts "M2-W2 PATH A (Performance_Explore) DONE"
puts "============================================================"
