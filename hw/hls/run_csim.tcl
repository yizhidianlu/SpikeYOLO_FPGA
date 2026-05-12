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

# --- CWD-resilient path setup (Vitis HLS launches csim binary from
# csim_<top>/sol1/csim/build/, i.e. 5 levels below repo root). Testbenches
# that read tests/golden/exploded/... and models/exploded/... need
# absolute paths via env vars.
#
# NOTE: Script is invoked via `cd hw/hls && vitis_hls -f run_csim.tcl`,
# so TCL CWD = hw/hls/, hence ../.. is the repo root.
# (v1 used [file normalize ..] which resolved to <repo>/hw — fixed per
# Remote Claude REPLIES_FROM_REMOTE.md 2026-05-12T15:48.)
set REPO_ROOT  [file normalize ../..]
set WEIGHT_DIR [file join $REPO_ROOT models exploded]
set GOLDEN_ROOT [file join $REPO_ROOT tests golden exploded]

# Per-target golden-dir lookup (covers the 4 tbs that read SA_GOLDEN_DIR:
# tb_ms_downsampling / tb_ms_all_conv_block / tb_spike_sppf / tb_detect_head;
# others use dummy/hardcoded data — set anyway as a safe default).
array set GOLDEN_BY_TOP {
    sa_conv2d_int        "tests/golden/exploded/layer_00_stem"
    sa_conv2d_bn         "tests/golden/exploded/layer_00_stem"
    sa_lif_expand        "tests/golden/exploded/layer_00_stem"
    sa_maxpool_or        "tests/golden/exploded/layer_08_sppf"
    sa_ms_downsampling   "tests/golden/exploded/layer_00_stem"
    sa_sep_conv          "hw/hls/sim/golden_local/sep_conv_smoke"
    sa_ms_all_conv_block "tests/golden/exploded/layer_01_acb1"
    sa_spike_sppf        "tests/golden/exploded/layer_08_sppf"
    sa_detect_head       "tests/golden/exploded/layer_11_detect"
    sa_tiny_fpga_top     "tests/golden/exploded"
}

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

    # Set absolute-path env vars so testbench main() resolves data files
    # regardless of csim_design's deep CWD.
    set ::env(SA_REPO_ROOT)   $REPO_ROOT
    set ::env(SA_WEIGHT_DIR)  $WEIGHT_DIR
    set ::env(SA_GOLDEN_ROOT) $GOLDEN_ROOT
    if {[info exists GOLDEN_BY_TOP($TOP)]} {
        set abs_golden [file join $REPO_ROOT $GOLDEN_BY_TOP($TOP)]
        set ::env(SA_GOLDEN_DIR)     $abs_golden
        set ::env(SA_SEP_GOLDEN_DIR) $abs_golden
    }
    puts "   SA_REPO_ROOT  = $::env(SA_REPO_ROOT)"
    puts "   SA_WEIGHT_DIR = $::env(SA_WEIGHT_DIR)"
    puts "   SA_GOLDEN_DIR = $::env(SA_GOLDEN_DIR)"

    csim_design -O -ldflags "-Wl,--as-needed"
    close_project
}

puts "CSIM SCRIPT DONE — all targets passed"
exit 0
