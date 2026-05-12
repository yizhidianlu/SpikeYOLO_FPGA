# runs/remote_machine/run_csim_one_target.tcl
#
# Workaround driver for Remote Claude Option C in URGENT_ASK.md. Reads
# per-target params from env vars (OPT_C_TOP / OPT_C_SRCS_CSV / OPT_C_TBS_CSV)
# instead of -tclargs — Vitis HLS 2024.1's -tclargs is fragile under
# `cmd /c "..."` quoting (argv[0] resolved to "-f" in testing). Env vars
# survive the cmd boundary intact.
#
# The PowerShell driver (run_all_csim.ps1) also sets SA_GOLDEN_DIR /
# SA_WEIGHT_DIR / SA_GOLDEN_ROOT / SA_SEP_GOLDEN_DIR to **absolute** paths so
# the testbenches' env_or() bypasses relative-path resolution from the deep
# csim build dir.
#
# Do NOT modify hw/hls/run_csim.tcl or testbench source — Option A in
# URGENT_ASK.md is B1 owner's responsibility.

if {![info exists ::env(OPT_C_TOP)] ||
    ![info exists ::env(OPT_C_SRCS_CSV)] ||
    ![info exists ::env(OPT_C_TBS_CSV)]} {
    puts "ERROR: missing OPT_C_TOP / OPT_C_SRCS_CSV / OPT_C_TBS_CSV env vars"
    exit 1
}

set TOP       $::env(OPT_C_TOP)
set SRCS_CSV  $::env(OPT_C_SRCS_CSV)
set TBS_CSV   $::env(OPT_C_TBS_CSV)

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
puts "== SRCS = $SRCS"
puts "== TBS  = $TBS"

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
