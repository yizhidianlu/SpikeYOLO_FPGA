# probe_video_ips.tcl — list ALL installed video IPs
create_project -in_memory probe -part xc7z020clg400-1
set_property ip_repo_paths "C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/hw/vivado/ip_repo" [current_project]
update_ip_catalog -rebuild
puts "==All xilinx.com:ip:v_*=="
foreach d [lsort -dictionary [get_ipdefs -filter {VLNV =~ xilinx.com:ip:v_*}]] { puts $d }
puts "==All xilinx.com:ip:axis_*=="
foreach d [lsort -dictionary [get_ipdefs -filter {VLNV =~ xilinx.com:ip:axis_*}]] { puts $d }
puts "==All xilinx.com:ip:*vid*=="
foreach d [lsort -dictionary [get_ipdefs -filter {VLNV =~ xilinx.com:ip:*vid*}]] { puts $d }
puts "==All digilentinc.com=="
foreach d [lsort -dictionary [get_ipdefs -filter {VLNV =~ digilentinc.com:*}]] { puts $d }
exit 0
