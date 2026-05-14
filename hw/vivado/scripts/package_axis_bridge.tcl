# hw/vivado/scripts/package_axis_bridge.tcl
#
# Package the in-tree Verilog adapter `hw/vivado/rtl/axis_to_video_bridge.v`
# as a proper IP-XACT IP under `hw/vivado/ip_repo/axis_to_video_bridge/`.
# build_bd.tcl then consumes it via:
#
#   create_bd_cell -type ip -vlnv user:user:axis_to_video_bridge:1.0 vid_out
#
# Why we need this (URGENT_ASK_25): Vivado 2024.1 on Windows SIGSEGVs
# when the bridge is instantiated via `create_bd_cell -type module
# -reference` even with full X_INTERFACE_INFO/PARAMETER attributes
# (URGENT_ASK_19/22 path, fixed for FREQ_HZ but a deeper crash path
# remains). The IP-XACT route uses the same code path as our spike_accel
# .xo and rgb2dvi IP and is stable.
#
# Usage:
#   source /opt/Xilinx/Vivado/2024.1/settings64.sh
#   vivado -mode batch -source hw/vivado/scripts/package_axis_bridge.tcl
#
# Idempotent: re-run after edits to axis_to_video_bridge.v to refresh the
# packaged IP. Output goes to hw/vivado/ip_repo/axis_to_video_bridge/.

set HW_VIVADO_DIR [file normalize "[file dirname [info script]]/.."]
set RTL_FILE      [file normalize "${HW_VIVADO_DIR}/rtl/axis_to_video_bridge.v"]
set IP_REPO_DIR   [file normalize "${HW_VIVADO_DIR}/ip_repo/axis_to_video_bridge"]
set TMP_PROJ_DIR  "${IP_REPO_DIR}/_packaging"
set PART          xc7z020clg400-1

if {![file exists $RTL_FILE]} {
    puts "ERROR: Verilog source not found: $RTL_FILE"
    exit 1
}

# Clean previous packaging artifacts (idempotent re-run support).
if {[file isdirectory $TMP_PROJ_DIR]} { file delete -force $TMP_PROJ_DIR }
file mkdir $IP_REPO_DIR

# Copy the RTL into the IP repo so the packaged component bundles its own
# source (IP-XACT convention; consumers don't need to add_files separately).
file copy -force $RTL_FILE "${IP_REPO_DIR}/axis_to_video_bridge.v"

# Throw-away project just for the packaging operation.
create_project -force pkg_axis_to_video_bridge $TMP_PROJ_DIR -part $PART
add_files -norecurse "${IP_REPO_DIR}/axis_to_video_bridge.v"
set_property top axis_to_video_bridge [current_fileset]
update_compile_order -fileset sources_1

# Run IP-XACT packager. Vendor/library "user/user" matches Xilinx convention
# for in-house IPs. Taxonomy /AXI_Infrastructure groups it with other
# AXI bridge IPs in the IP catalog browser.
ipx::package_project \
    -root_dir       $IP_REPO_DIR \
    -vendor         user \
    -library        user \
    -taxonomy       "/AXI_Infrastructure" \
    -import_files \
    -set_current    true \
    -force

# Tighten core metadata so it shows up nicely in IP catalog.
set _core [ipx::current_core]
set_property name              axis_to_video_bridge $_core
set_property version           1.0                  $_core
set_property core_revision     1                    $_core
set_property display_name      "AXIS to Video Bridge (in-tree replacement for v_axis_to_video_out)" $_core
set_property description       "M3 HDMI: VDMA AXI4-Stream RGB -> rgb2dvi parallel video. Single-clock domain (148.5 MHz pixel). Replaces missing xilinx.com:ip:v_axis_to_video_out:4.0 from Vivado 2024.1 installs without Video & Image Processing IP Suite. URGENT_ASK_18/19/22/25." $_core
set_property vendor_display_name "SpikeYOLO_FPGA"   $_core
set_property company_url       "https://github.com/yizhidianlu/SpikeYOLO_FPGA" $_core

ipx::create_xgui_files $_core
ipx::update_checksums  $_core
ipx::save_core         $_core
ipx::unload_core       $_core

close_project

# Cleanup temp project. The IP definition (component.xml + RTL) stays.
file delete -force $TMP_PROJ_DIR

puts "============================================================"
puts "OK  axis_to_video_bridge IP packaged at:"
puts "    ${IP_REPO_DIR}/component.xml"
puts ""
puts "VLNV: user:user:axis_to_video_bridge:1.0"
puts ""
puts "Next:  vivado -mode batch -source hw/vivado/build_bd.tcl"
puts "       (build_bd.tcl auto-discovers IPs under hw/vivado/ip_repo/*)"
puts "============================================================"
