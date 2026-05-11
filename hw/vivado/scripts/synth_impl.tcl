# hw/vivado/scripts/synth_impl.tcl
#
# Vivado 2023.2 batch entry point — runs synthesis, implementation,
# write_bitstream, and emits hw/vivado/out/address_map.yaml (Contract 4).
# Wraps hw/vivado/build_bitstream.tcl so callers under scripts/ have a single
# co-located pair (build_bd.tcl + synth_impl.tcl).
#
# Pre-req:
#   vivado -mode batch -source hw/vivado/scripts/build_bd.tcl
#   (creates out/spike_zybo.xpr)
#
# Usage:
#   source /opt/Xilinx/Vivado/2023.2/settings64.sh
#   vivado -mode batch -source hw/vivado/scripts/synth_impl.tcl
#
# The wrapped script:
#   - opens out/spike_zybo.xpr
#   - launches synth_1, then impl_1 -to_step write_bitstream
#   - dumps timing_summary.rpt, utilization.rpt, power.rpt under reports/
#   - copies the bitstream into out/system.bit and writes system.xsa
#   - emits out/address_map.yaml with the live BD address segments
#
# TODO M2-W3: add `set_property STRATEGY Performance_ExtraTimingOpt
#             [get_runs impl_1]` if WNS < 0 ns at 100 MHz.
# TODO M5-W1: bump CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ to 150 in build_bd.tcl
#             then rerun this script (R1 handler chain documented in playbook).

set SCRIPT_DIR [file normalize [file dirname [info script]]]
set TOP_BIT    [file normalize [file join $SCRIPT_DIR .. build_bitstream.tcl]]

if {![file exists $TOP_BIT]} {
    puts "FATAL: top-level build_bitstream.tcl not found at $TOP_BIT"
    exit 1
}

puts "============================================================"
puts "[scripts/synth_impl.tcl] sourcing $TOP_BIT"
puts "============================================================"
source $TOP_BIT
