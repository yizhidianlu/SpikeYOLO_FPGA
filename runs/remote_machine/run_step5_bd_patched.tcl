# runs/remote_machine/run_step5_bd_patched.tcl
#
# Workaround: hw/vivado/build_bd.tcl sets BOARD_PART = ":1.0" but Digilent
# vivado-boards `new/board_files/zybo-z7-20/A.0/board.xml` declares
# <file_version>1.2</file_version> → Vivado get_board_parts returns
# `digilentinc.com:zybo-z7-20:part0:1.2`. Confirmed via diag_get_board_parts.tcl.
#
# Cannot modify hw/vivado/build_bd.tcl per Remote-Claude ownership rules.
# This wrapper reads the script, string-maps ":1.0" → ":1.2", then evals.
# Path expressions using [file dirname [info script]] are rewritten to point
# at the original hw/vivado/ directory so OUT_DIR / HLS_DIR / CONSTR_DIR /
# IP_REPO_DIR all resolve correctly.

set HW_VIVADO_DIR  "C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/hw/vivado"
set BUILD_BD_PATH  "$HW_VIVADO_DIR/build_bd.tcl"

set fh [open $BUILD_BD_PATH r]
set content [read $fh]
close $fh

# Patch 1: bump BOARD_PART version
set content [string map [list "digilentinc.com:zybo-z7-20:part0:1.0" "digilentinc.com:zybo-z7-20:part0:1.2"] $content]

# Patch 2: pin [file dirname [info script]] expansions back to hw/vivado/
set content [string map [list {[file dirname [info script]]} $HW_VIVADO_DIR] $content]

puts "INFO: run_step5_bd_patched.tcl — sourcing patched build_bd.tcl"
puts "INFO:   BOARD_PART :1.0 -> :1.2"
puts "INFO:   [file dirname [info script]] pinned to $HW_VIVADO_DIR"

eval $content
