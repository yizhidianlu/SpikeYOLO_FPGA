# runs/remote_machine/dump_util_breakdown.tcl
# Open synth_1 checkpoint, dump hierarchical utilization + post-synth WNS
# for Main's R2 handler-selection decision.

set OUT_DIR "C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/hw/vivado/out"
set RPTS    "C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/runs/remote_machine"

open_project [file join $OUT_DIR spike_zybo.xpr]
open_run synth_1

report_utilization     -hierarchical -file [file join $RPTS post_synth_util_hier.rpt]
report_timing_summary  -file          [file join $RPTS post_synth_timing.rpt] -delay_type max
report_utilization     -file          [file join $RPTS post_synth_util_flat.rpt]

puts "DUMP DONE"
exit 0
