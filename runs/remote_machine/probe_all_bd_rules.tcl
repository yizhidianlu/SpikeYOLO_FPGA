# probe_all_bd_rules.tcl — enumerate ALL bd_rules in the catalog
create_project -in_memory probe -part xc7z020clg400-1
set_property ip_repo_paths "C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/hw/vivado/ip_repo" [current_project]
update_ip_catalog -rebuild
puts "==All xilinx.com:bd_rule defs=="
foreach d [lsort -dictionary [get_ipdefs -filter {VLNV =~ xilinx.com:bd_rule:*}]] { puts $d }
exit 0
