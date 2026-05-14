# probe_broken_bd_rules.tcl — find ALL bd_rules whose helper TCL files
# don't exist on disk in this Vivado install.
#
# Strategy: enumerate every bd_rule entry, check the rules-dir TCL files
# referenced under E:/Applaction/Xilinx/Vivado/2024.1/data/rsb/design_assist/block/<name>/

create_project -in_memory probe -part xc7z020clg400-1
set_property ip_repo_paths "C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/hw/vivado/ip_repo" [current_project]
update_ip_catalog -rebuild

set RSB_DIR "E:/Applaction/Xilinx/Vivado/2024.1/data/rsb/design_assist/block"
set broken {}
puts "==Scanning bd_rule defs=="
foreach def [lsort -dictionary [get_ipdefs -filter {VLNV =~ xilinx.com:bd_rule:*}]] {
    # def is "xilinx.com:bd_rule:NAME:VER"
    set parts [split $def ":"]
    set rule_name [lindex $parts 2]
    set rule_dir "$RSB_DIR/$rule_name"
    set has_rules_tcl [file exists "$rule_dir/rules.tcl"]
    set has_bd_tcl    [file exists "$rule_dir/bd.tcl"]
    if {!$has_rules_tcl && !$has_bd_tcl} {
        puts "MISSING_ALL $def — no rules.tcl AND no bd.tcl at $rule_dir"
        lappend broken $def
    } elseif {[file isdirectory $rule_dir] && !$has_rules_tcl && !$has_bd_tcl} {
        puts "MISSING_BOTH $def"
        lappend broken $def
    }
}
puts "==SUMMARY: [llength $broken] broken bd_rule defs=="
foreach b $broken { puts $b }
exit 0
