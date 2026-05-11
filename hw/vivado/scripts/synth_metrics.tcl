# hw/vivado/scripts/synth_metrics.tcl
#
# Run AFTER `vivado -mode batch -source scripts/synth_impl.tcl` opens the
# project, or stand-alone against an existing out/spike_zybo.xpr.
#
# Emits four artefacts under hw/vivado/out/:
#   utilization.rpt        — hierarchical, human-readable (D1 monthly report)
#   timing_summary.rpt     — full timing summary (D1 monthly report)
#   timing_setup_top10.rpt — worst-10 setup paths for B1/B2/B3 triage
#   timing.csv             — single-row {wns,tns,whs,fmax} CSV — D2 CI gate
#                            consumed by RISK_RULES.yaml R1 / R2 dispatcher
#
# Usage (stand-alone):
#   vivado -mode batch -source scripts/synth_metrics.tcl

set OUT_DIR [file normalize "[file dirname [info script]]/../out"]

# If we were sourced after synth_impl.tcl the project is already open;
# otherwise open it ourselves.
if {[catch {current_project}]} {
    open_project [file join $OUT_DIR spike_zybo.xpr]
}

# Ensure synth_1 is opened so report_* sees the netlist.
if {[catch {current_design}]} {
    open_run synth_1
}

report_utilization -hierarchical -file [file join $OUT_DIR utilization.rpt]
report_timing_summary -delay_type max -file [file join $OUT_DIR timing_summary.rpt]
report_timing -setup -max_paths 10 -file [file join $OUT_DIR timing_setup_top10.rpt]

# Compact CSV the CI risk dispatcher (R1 / R2) can grep.
set fp [open [file join $OUT_DIR timing.csv] w]
puts $fp "metric,value,unit"
set wns_path [get_timing_paths -setup -max_paths 1]
set wns [expr {[llength $wns_path] > 0 ? [get_property SLACK $wns_path] : 0.0}]
set whs_path [get_timing_paths -hold -max_paths 1]
set whs [expr {[llength $whs_path] > 0 ? [get_property SLACK $whs_path] : 0.0}]

# pl_clk0 nominal period — keep in sync with PCW_FPGA0_PERIPHERAL_FREQMHZ.
set t_clk_ns 10.0
set fmax_mhz [expr {1000.0 / ($t_clk_ns - $wns)}]

puts $fp "wns,$wns,ns"
puts $fp "whs,$whs,ns"
puts $fp "fmax,$fmax_mhz,MHz"

# Headline LUT/DSP/BRAM utilization for the D1 monthly dashboard.
foreach {key sel} {luts SLICE_LUTS dsps DSPS bram_36k RAMB36 bram_18k RAMB18} {
    set used [llength [get_cells -hierarchical -filter "PRIMITIVE_TYPE =~ ${sel}.*"]]
    puts $fp "$key,$used,count"
}
close $fp

puts "[synth_metrics] wrote utilization.rpt, timing_summary.rpt, timing_setup_top10.rpt, timing.csv to $OUT_DIR"
