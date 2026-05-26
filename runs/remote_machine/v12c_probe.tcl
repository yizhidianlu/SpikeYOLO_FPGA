# Probe v12c UART1 alive + check PC after running ELF.
connect
targets -set -filter {name =~ "*Cortex-A9 MPCore #0*"}
rst -system
after 200
fpga -file C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/hw/vivado/out/system.bit
source C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/vitis_workspace/spike_zybo_baremetal_plat/hw/ps7_init.tcl
ps7_init
ps7_post_config

stop
puts "==PRE-ELF UART1 alive probe=="
foreach {name addr} {
    APER_CLK_CTRL_BIT21  0xF800014C
    MIO_PIN_48           0xF8000730
    MIO_PIN_49           0xF8000734
    UART1_CR             0xE0001000
    UART1_BAUDGEN        0xE0001018
    UART1_SR             0xE000102C
} { catch { puts "$name @ $addr: [mrd $addr]" } }

dow C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/vitis_workspace/spike_accel_w9_smoke/Debug/spike_accel_w9_smoke.elf
puts "PC after dow: [rrd pc]"

con
after 8000

# CPU should be in a defined state now. Try halt.
catch { stop }
puts "==POST-RUN=="
puts "PC after 8s con: [rrd pc]"
catch { puts "UART1 SR: [mrd 0xE000102C]" }
exit 0
