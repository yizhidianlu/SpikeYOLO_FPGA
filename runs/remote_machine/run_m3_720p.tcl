# runs/remote_machine/run_m3_720p.tcl
#
# M4-fallback 720p variant build. Sets SA_VIDEO_MODE_720P env var so
# build_bd.tcl picks 720p config:
#   - PCW_FPGA1_PERIPHERAL_FREQMHZ 148.5 -> 74.25
#   - v_tc VIDEO_MODE 1080p -> 720p
#   - rgb2dvi kClkRange 1 -> 0
# Then rebuilds BD + runs build_bitstream + copies output to out_720p/.

set ::env(SA_VIDEO_MODE_720P) 1
puts "INFO: SA_VIDEO_MODE_720P=1 — building 720p60 variant"

# Phase 1: rebuild BD with 720p config
source "C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/hw/vivado/build_bd.tcl"
