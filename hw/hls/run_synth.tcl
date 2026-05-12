# hw/hls/run_synth.tcl — Vitis HLS C-synthesis flow for tiny_fpga_top.
#
# Produces the per-kernel utilization + timing reports D1 / D2 consume:
#
#   hw/hls/reports/utilization.rpt   <- post-csynth resource summary
#   hw/hls/reports/timing.csv        <- worst-case slack table
#   hw/hls/build/<TOP>.xo            <- kernel object passed to B2 (M2-W1)
#
# Risk gates (docs/RISK_RULES.yaml):
#   R1 (timing collapse) : WNS < 0 ns @ 100 MHz fires.
#   R2 (resource burst)  : any resource > 75% (warn) or > 90% (block).
#
# Usage:
#   source /opt/Xilinx/Vitis_HLS/2024.1/settings64.sh
#   vitis_hls -f run_synth.tcl
#
# Long-running (~25 min on a Ryzen 7 5800X). Skip in PR CI; run on the
# B1-self-hosted runner / nightly job.

set PART       xc7z020clg400-1
set CLK_PERIOD 10                       ;# 100 MHz initial M4 target
set REPORT_DIR reports
set BUILD_DIR  build

file mkdir ${REPORT_DIR}
file mkdir ${BUILD_DIR}

# Each entry: {top  source_files}
# Top-most first so failures on the headline kernel surface early.
set TARGETS [list \
    [list sa_tiny_fpga_top     "src/tiny_fpga_top.cpp src/ms_downsampling.cpp src/ms_all_conv_block.cpp src/sep_conv.cpp src/spike_sppf.cpp src/detect_head.cpp src/conv2d_bn.cpp src/conv2d_int.cpp src/lif_expand.cpp src/maxpool_or.cpp"] \
    [list sa_ms_downsampling   "src/ms_downsampling.cpp src/conv2d_bn.cpp src/conv2d_int.cpp src/lif_expand.cpp"] \
    [list sa_ms_all_conv_block "src/ms_all_conv_block.cpp src/sep_conv.cpp src/conv2d_bn.cpp src/conv2d_int.cpp src/lif_expand.cpp"] \
    [list sa_spike_sppf        "src/spike_sppf.cpp src/conv2d_bn.cpp src/conv2d_int.cpp src/lif_expand.cpp src/maxpool_or.cpp"] \
    [list sa_detect_head       "src/detect_head.cpp"] \
]

foreach entry $TARGETS {
    set TOP  [lindex $entry 0]
    set SRCS [lindex $entry 1]
    set PROJ "synth_${TOP}"

    puts "== synth ${TOP} ============================================="
    open_project -reset ${PROJ}
    set_top ${TOP}
    foreach f $SRCS { add_files $f -cflags "-Iinclude -DSA_USE_HLS" }

    open_solution -reset sol1 -flow_target vivado
    set_part ${PART}
    create_clock -period ${CLK_PERIOD} -name default

    csynth_design

    # Hierarchical resource breakdown (D2 RISK_RULES R2 input).
    catch { report_utilization -hierarchical \
        -file "${REPORT_DIR}/${TOP}_utilization.rpt" }
    # Setup-path timing report (D2 RISK_RULES R1 input).
    catch { report_timing -setup -path 10 \
        -file "${REPORT_DIR}/${TOP}_timing.csv" }

    # Reports — Vitis HLS writes them under <PROJ>/sol1/syn/report/.
    # Copy the headline ones into hw/hls/reports/<TOP>.* so D1's monthly
    # collector + D2's RISK_RULES gate can find them at a stable path.
    set RPT_SRC "${PROJ}/sol1/syn/report/${TOP}_csynth.rpt"
    if {[file exists ${RPT_SRC}]} {
        file copy -force ${RPT_SRC} "${REPORT_DIR}/${TOP}_csynth.rpt"
    }

    # Aggregated utilization summary (all tops merged into one rpt for D1).
    set UTIL_SRC "${PROJ}/sol1/syn/report/csynth.rpt"
    if {[file exists ${UTIL_SRC}]} {
        if {${TOP} eq "sa_tiny_fpga_top"} {
            file copy -force ${UTIL_SRC} "${REPORT_DIR}/utilization.rpt"
        }
    }

    # Timing CSV — Vitis HLS doesn't emit CSV directly; we synthesise one
    # by parsing the .rpt header. For now we just copy timing_summary.rpt
    # if it exists; M2 will add a Python post-processor that computes WNS
    # and writes timing.csv compatible with tools/ci/check_timing.py.
    set TIM_SRC "${PROJ}/sol1/impl/report/verilog/${TOP}_timing_summary_routed.rpt"
    if {[file exists ${TIM_SRC}]} {
        file copy -force ${TIM_SRC} "${REPORT_DIR}/${TOP}_timing.rpt"
    }

    # Package the .xo — B2's IP integrator pulls these in.
    # For sa_tiny_fpga_top we always export (headline IP for Contract 3).
    # Leaf kernels get a best-effort export; B2 only needs the top .xo.
    if {![file exists "${PROJ}/sol1/impl/export.xo"]} {
        catch { export_design -format ip_catalog -rtl verilog \
            -output "${BUILD_DIR}/${TOP}.xo" }
    }
    if {[file exists "${PROJ}/sol1/impl/export.xo"]} {
        file copy -force "${PROJ}/sol1/impl/export.xo" \
            "${BUILD_DIR}/${TOP}.xo"
    }

    close_project
}

# Synthesise an aggregate timing.csv for D2's gate (one row per kernel).
set FH [open "${REPORT_DIR}/timing.csv" w]
puts $FH "kernel,target_period_ns,achieved_period_ns,wns_ns"
foreach entry $TARGETS {
    set TOP [lindex $entry 0]
    set RPT "synth_${TOP}/sol1/syn/report/${TOP}_csynth.rpt"
    if {![file exists ${RPT}]} { continue }
    # Crude regex parse; B1's report parser proper lands in M2 W1.
    set fh [open $RPT r]
    set body [read $fh]
    close $fh
    set achieved -1.0
    set wns -1.0
    if {[regexp {Estimated Clock Period\s*\|\s*([0-9.]+)} $body _ achieved]} { }
    if {[regexp {Worst Slack\s*\|\s*([\-0-9.]+)} $body _ wns]} { }
    puts $FH "${TOP},${CLK_PERIOD},${achieved},${wns}"
}
close $FH

puts "SYNTH SCRIPT DONE — reports under ${REPORT_DIR}/, .xo under ${BUILD_DIR}/"
exit 0
