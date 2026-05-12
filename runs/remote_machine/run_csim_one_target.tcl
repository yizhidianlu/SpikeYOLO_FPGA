# runs/remote_machine/run_csim_one_target.tcl
#
# Workaround driver for Remote Claude Option C in URGENT_ASK.md. Invoked once
# per target with -tclargs <TOP> <SRCS_csv> <TBS_csv>. The PowerShell driver
# (run_all_csim.ps1) sets SA_GOLDEN_DIR / SA_WEIGHT_DIR / SA_GOLDEN_ROOT /
# SA_SEP_GOLDEN_DIR to **absolute** paths before invoking vitis_hls, which the
# testbenches' env_or() picks up so relative-path resolution from the deep csim
# build dir is bypassed.
#
# Do NOT modify run_csim.tcl or testbench source — Option A in URGENT_ASK.md
# is the canonical fix and is B1 owner's responsibility.

if {[llength $argv] < 3} {
    puts "usage: vitis_hls -f run_csim_one_target.tcl -tclargs <TOP> <SRCS_csv> <TBS_csv>"
    exit 1
}

set TOP   [lindex $argv 0]
set SRCS_CSV [lindex $argv 1]
set TBS_CSV  [lindex $argv 2]

set SRCS [split $SRCS_CSV ","]
set TBS  [split $TBS_CSV ","]

set PART       xc7z020clg400-1
set CLK_PERIOD 10
set PROJ       "csim_${TOP}"

puts "== csim ${TOP} (Option-C workaround, per-target invocation) ============"
puts "== SA_GOLDEN_DIR  = $::env(SA_GOLDEN_DIR)"
puts "== SA_WEIGHT_DIR  = $::env(SA_WEIGHT_DIR)"
if {[info exists ::env(SA_GOLDEN_ROOT)]}    { puts "== SA_GOLDEN_ROOT = $::env(SA_GOLDEN_ROOT)" }
if {[info exists ::env(SA_SEP_GOLDEN_DIR)]} { puts "== SA_SEP_GOLDEN_DIR = $::env(SA_SEP_GOLDEN_DIR)" }

open_project -reset ${PROJ}
set_top ${TOP}

foreach f $SRCS { add_files     $f -cflags "-Iinclude -DSA_USE_HLS" }
foreach f $TBS  { add_files -tb $f -cflags "-Iinclude -Isim" }

open_solution -reset sol1 -flow_target vivado
set_part ${PART}
create_clock -period ${CLK_PERIOD} -name default

csim_design -O -ldflags "-Wl,--as-needed"
close_project

puts "ONE-TARGET CSIM DONE ${TOP}"
exit 0
