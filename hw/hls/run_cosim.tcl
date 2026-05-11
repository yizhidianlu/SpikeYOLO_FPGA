# hw/hls/run_cosim.tcl — full C/RTL co-simulation flow for every leaf and
# block kernel plus sa_tiny_fpga_top.
#
# SLOW: ~10 min per kernel (10 kernels -> ~1.5 h end-to-end on a Ryzen 7
# 5800X). Trigger only when:
#   - a PR carries label `cosim`
#   - locally before tagging an M2 release
#   - investigating a C-sim vs RTL divergence
#
# Usage:
#   source /opt/Xilinx/Vitis_HLS/2023.2/settings64.sh
#   vitis_hls -f run_cosim.tcl
#
# Exit code: 0 if every cosim_design returns 0; non-zero on first failure
# (Vitis HLS propagates the testbench main() exit code automatically).

set PART       xc7z020clg400-1
set CLK_PERIOD 10                       ;# 100 MHz initial M4 target

# Mirrors run_csim.tcl TARGETS — same (top, srcs, tbs) tuples so the cosim
# proves out the exact RTL that csim verified.
set TARGETS [list \
    [list sa_conv2d_int        "src/conv2d_int.cpp"                                                                           "sim/tb_conv2d_int.cpp sim/npz_reader.cpp"] \
    [list sa_conv2d_bn         "src/conv2d_bn.cpp src/conv2d_int.cpp"                                                          "sim/tb_conv2d_bn.cpp"] \
    [list sa_lif_expand        "src/lif_expand.cpp"                                                                            "sim/tb_lif_expand.cpp"] \
    [list sa_maxpool_or        "src/maxpool_or.cpp"                                                                            "sim/tb_maxpool_or.cpp"] \
    [list sa_ms_downsampling   "src/ms_downsampling.cpp src/conv2d_bn.cpp src/conv2d_int.cpp src/lif_expand.cpp"               "sim/tb_ms_downsampling.cpp sim/npz_reader.cpp"] \
    [list sa_sep_conv          "src/sep_conv.cpp src/conv2d_bn.cpp src/conv2d_int.cpp src/lif_expand.cpp"                       "sim/tb_sep_conv.cpp sim/npz_reader.cpp"] \
    [list sa_ms_all_conv_block "src/ms_all_conv_block.cpp src/sep_conv.cpp src/conv2d_bn.cpp src/conv2d_int.cpp src/lif_expand.cpp" "sim/tb_ms_all_conv_block.cpp sim/npz_reader.cpp"] \
    [list sa_spike_sppf        "src/spike_sppf.cpp src/conv2d_bn.cpp src/conv2d_int.cpp src/lif_expand.cpp src/maxpool_or.cpp"  "sim/tb_spike_sppf.cpp sim/npz_reader.cpp"] \
    [list sa_detect_head       "src/detect_head.cpp"                                                                           "sim/tb_detect_head.cpp sim/npz_reader.cpp"] \
    [list sa_tiny_fpga_top     "src/tiny_fpga_top.cpp src/ms_downsampling.cpp src/ms_all_conv_block.cpp src/sep_conv.cpp src/spike_sppf.cpp src/detect_head.cpp src/conv2d_bn.cpp src/conv2d_int.cpp src/lif_expand.cpp src/maxpool_or.cpp" "sim/tb_tiny_fpga_top.cpp sim/npz_reader.cpp"] \
]

foreach entry $TARGETS {
    set TOP   [lindex $entry 0]
    set SRCS  [lindex $entry 1]
    set TBS   [lindex $entry 2]
    set PROJ  "cosim_${TOP}"

    puts "== cosim ${TOP} ============================================="
    open_project -reset ${PROJ}
    set_top ${TOP}

    foreach f $SRCS { add_files       $f -cflags "-Iinclude -DSA_USE_HLS" }
    foreach f $TBS  { add_files -tb   $f -cflags "-Iinclude -Isim" }

    open_solution -reset sol1_cosim -flow_target vivado
    set_part ${PART}
    create_clock -period ${CLK_PERIOD} -name default

    # 1. C-sim gate first — if this fails RTL cannot possibly be right.
    csim_design -O -ldflags "-Wl,--as-needed"

    # 2. Synthesise to RTL.
    csynth_design

    # 3. Co-simulate (Verilog RTL + the same testbench).
    #    -trace_level all writes a .wdb that Vitis HLS GUI can replay.
    cosim_design -rtl verilog -trace_level all -O

    close_project
}

puts "COSIM SCRIPT DONE — all 10 kernels passed cosim"
exit 0
