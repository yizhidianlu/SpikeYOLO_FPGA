# hw/hls/run_cosim.tcl — full C/RTL co-simulation flow.
#
# Slow (~30+ min). Run only when:
#   - a PR is labeled `cosim`
#   - locally before tagging M2 release
#
# Usage: vitis_hls -f run_cosim.tcl

set PROJ      sa_kernels
set SOLUTION  sol1_cosim
set PART      xc7z020clg400-1
set TOP       sa_conv2d_int

open_project -reset ${PROJ}
set_top ${TOP}

add_files src/conv2d_int.cpp -cflags "-Iinclude -DSA_USE_HLS"
add_files -tb sim/tb_conv2d_int.cpp -cflags "-Iinclude -Isim"
add_files -tb sim/reference.hpp     -cflags "-Iinclude -Isim"

open_solution -reset ${SOLUTION} -flow_target vivado
set_part ${PART}
create_clock -period 10 -name default

# 1. C-sim sanity gate
csim_design -O

# 2. C synthesis
csynth_design

# 3. Co-simulation
cosim_design -trace_level all -O

# 4. Reports
report_timing -file timing.csv
report_utilization -file utilization.rpt

puts "COSIM SCRIPT DONE"
exit 0
