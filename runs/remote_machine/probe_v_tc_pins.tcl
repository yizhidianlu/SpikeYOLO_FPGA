# probe_v_tc_pins.tcl — open the partially-built BD from v4 and list
# the actual sub-pin names of v_tc_0/vtiming_out + check rgb2dvi pin set.

set OUT_DIR "C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/hw/vivado/out"
open_project [file join $OUT_DIR spike_zybo.xpr]
open_bd_design [file join $OUT_DIR spike_zybo.srcs sources_1 bd system system.bd]

puts "==v_tc_0 pins=="
foreach p [get_bd_pins -of [get_bd_cells v_tc_0]] { puts $p }
puts "==v_tc_0 intf pins=="
foreach p [get_bd_intf_pins -of [get_bd_cells v_tc_0]] { puts $p }
puts "==vid_out pins=="
foreach p [get_bd_pins -of [get_bd_cells vid_out]] { puts $p }
puts "==rgb2dvi_0 pins=="
foreach p [get_bd_pins -of [get_bd_cells rgb2dvi_0]] { puts $p }
puts "==rgb2dvi_0 intf pins=="
foreach p [get_bd_intf_pins -of [get_bd_cells rgb2dvi_0]] { puts $p }
puts "==ps_0/FCLK_CLK1 freq=="
puts [get_property CONFIG.FREQ_HZ [get_bd_pins ps_0/FCLK_CLK1]]
exit 0
