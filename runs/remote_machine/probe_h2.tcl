# probe_h2.tcl — try Vitis 2024.1 mrd -address-space / -arm-ap variants
source C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/sw/baremetal/spike_accel_w9_smoke/xsdb_setup.tcl
set ::W9_ELF [file normalize "C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/vitis_workspace/spike_accel_w9_smoke/Debug/spike_accel_w9_smoke.elf"]
set ::W9_PS7_INIT [file normalize "C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/vitis_workspace/spike_zybo_baremetal_plat/hw/ps7_init.tcl"]
source $::W9_PS7_INIT

connect
targets -set -filter {name =~ "*Cortex-A9 MPCore #0*"}
catch {rst -dap}
after 200
catch {rst -srst}
after 500
catch {targets -set -filter {name =~ "*Cortex-A9 MPCore #0*"}}
stop

fpga -file $::W9_BIT
ps7_init
ps7_post_config
mwr -bin -file $::W9_WEIGHTS $::W9_WEIGHTS_ADDR [expr $::W9_WEIGHTS_BYTES / 4]
dow $::W9_ELF
con
after 3000

puts "==Try mrd -address-space mem==:"
foreach as {mem memory ap0 ap1 cpu phys system} {
    catch { puts "as=$as: [mrd -address-space $as 0x10845400]" } _err
}

puts "==Try mrd -arm-ap 0==:"
foreach apnum {0 1 2 3} {
    catch { puts "ap=$apnum: [mrd -arm-ap $apnum 0x10845400]" } _err
}

puts "==Try help on mrd==:"
catch { help mrd } _h
puts $_h
exit 0
