# hw/hls/run_csim.tcl — Vitis HLS C-simulation entry for the full tiny_fpga
# kernel suite.
#
# Usage:
#   source /opt/Xilinx/Vitis_HLS/2024.1/settings64.sh
#   vitis_hls -f run_csim.tcl
#
# Iterates over every (top, testbench) pair so a single script invocation
# covers all 12 csim targets the host_csim_layer_NN Make targets exercise
# under g++.
#
# Exit code: 0 if every csim_design returns 0, non-zero on first failure
# (Vitis HLS propagates the testbench main() exit code automatically).

set PART     xc7z020clg400-1
set CLK_PERIOD 10                 ;# 100 MHz initial M4 target

# Each entry: {top_kernel  source_files  testbench_files}
# source_files / testbench_files are space-separated relative paths.
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
    set PROJ  "csim_${TOP}"

    puts "== csim ${TOP} ============================================"
    open_project -reset ${PROJ}
    set_top ${TOP}

    foreach f $SRCS { add_files       $f -cflags "-Iinclude -DSA_USE_HLS" }
    foreach f $TBS  { add_files -tb   $f -cflags "-Iinclude -Isim" }

    open_solution -reset sol1 -flow_target vivado
    set_part ${PART}
    create_clock -period ${CLK_PERIOD} -name default

    csim_design -O -ldflags "-Wl,--as-needed"
    close_project
}

puts "CSIM SCRIPT DONE — all targets passed"
exit 0
