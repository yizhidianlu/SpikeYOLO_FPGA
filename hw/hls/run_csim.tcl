# hw/hls/run_csim.tcl — Vitis HLS C-simulation entry for sa_conv2d_int.
#
# Usage:
#   source /opt/Xilinx/Vitis_HLS/2023.2/settings64.sh
#   vitis_hls -f run_csim.tcl
#
# Expands to:
#   1. create / re-open project "sa_kernels"
#   2. set top to sa_conv2d_int
#   3. add design + testbench files
#   4. csim_design
#   5. exit on success / fail propagation

set PROJ      sa_kernels
set SOLUTION  sol1
set PART      xc7z020clg400-1
set TOP       sa_conv2d_int

open_project -reset ${PROJ}
set_top ${TOP}

add_files src/conv2d_int.cpp -cflags "-Iinclude -DSA_USE_HLS"
add_files -tb sim/tb_conv2d_int.cpp -cflags "-Iinclude -Isim"
add_files -tb sim/reference.hpp     -cflags "-Iinclude -Isim"

open_solution -reset ${SOLUTION} -flow_target vivado
set_part ${PART}
create_clock -period 10 -name default       ;# 100 MHz target for M4

# C-sim only (no synth here -- run_cosim.tcl handles RTL co-sim).
csim_design -O -ldflags "-Wl,--as-needed"

# Vitis HLS exits non-zero automatically if testbench main() returns non-zero
puts "CSIM SCRIPT DONE"
exit 0
