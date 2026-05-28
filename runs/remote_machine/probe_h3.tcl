# probe_h3.tcl — mrd -address-space APn with running CPU
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

puts "==CPU running. Try APn for DDR @ 0x10845400==:"
foreach ap {AP0 AP1 AP2 AP3} {
    set rv "<fail>"
    if {[catch {set rv [mrd -address-space $ap 0x10845400]} _err]} {
        puts "$ap: ERR $_err"
    } else {
        puts "$ap: $rv"
    }
}

puts "==status block via best AP==:"
catch { puts "status[0] = [mrd -address-space AP1 0x10845400]" }
catch { puts "status[1] = [mrd -address-space AP1 0x10845404]" }
catch { puts "status[2] = [mrd -address-space AP1 0x10845408]" }
catch { puts "status[3] = [mrd -address-space AP1 0x1084540C]" }

puts "==Dump output to file via AP1==:"
if {[catch {mrd -address-space AP1 -bin -file C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/runs/remote_machine/w9_pbt_feat_out.bin 0x10840000 [expr 21504 / 4]} _err]} {
    puts "dump via AP1 fail: $_err"
    catch { mrd -address-space AP0 -bin -file C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/runs/remote_machine/w9_pbt_feat_out.bin 0x10840000 [expr 21504 / 4] }
} else {
    puts "dump via AP1 OK"
}
exit 0
