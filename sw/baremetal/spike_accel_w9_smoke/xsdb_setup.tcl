# sw/baremetal/spike_accel_w9_smoke/xsdb_setup.tcl
#
# XSDB automation for the W9 PTQ INT8 byte-exact smoke test on ZYBO Z7-20.
#
# Path:  Vivado HW Manager JTAG  →  ARM Cortex-A9 #0  →  baremetal elf
#
# Pre-requisites on the Windows host:
#   1. Vivado 2024.1 + Vitis 2024.1 installed.
#   2. ZYBO Z7-20 powered, USB-JTAG connected, SW0 = JTAG boot mode.
#   3. hw/vivado/out/system.bit   present (Git LFS pulled).
#   4. models/tiny_fpga_int8_real.bin present (1343776 bytes).
#   5. Vitis project built: build/spike_accel_w9_smoke.elf
#
# Usage from Vitis xsct (or the Vivado Tcl Console after `source` of xsdb):
#   xsct> source xsdb_setup.tcl
#   xsct> w9_smoke_run
#
# What it does:
#   a. Connect to the JTAG hw_server.
#   b. Reset PS, write system.bit to the PL fabric.
#   c. Initialize PS DDR via the .pre-elf ps7_init helper.
#   d. mwr -bin the weights into DDR @ 0x10000000.
#   e. Download spike_accel_w9_smoke.elf, set PC = _start, continue.
#   f. Tail the UART (115200 8N1) — caller is responsible for hooking PuTTY/Tera Term.

# ---- Paths (override before sourcing if your tree differs) ----
if {![info exists ::W9_PROJ_ROOT]} {
    # When sourced from this directory, the repo root is two dirs up.
    set ::W9_PROJ_ROOT [file normalize [file join [file dirname [info script]] ".." ".." ".."]]
}
set ::W9_BIT        [file join $::W9_PROJ_ROOT hw vivado out system.bit]
set ::W9_HDF        [file join $::W9_PROJ_ROOT hw vivado out system.xsa]
set ::W9_WEIGHTS    [file join $::W9_PROJ_ROOT models tiny_fpga_int8_pbt.bin]
# Default expects an in-tree vitis_workspace/. If your workspace lives elsewhere
# (e.g. D:/vitis_workspace/), override before w9_smoke_run by:
#     set ::W9_ELF "D:/vitis_workspace/spike_accel_w9_smoke/Debug/spike_accel_w9_smoke.elf"
set ::W9_ELF        [file join $::W9_PROJ_ROOT sw baremetal spike_accel_w9_smoke vitis_workspace spike_accel_w9_smoke Debug spike_accel_w9_smoke.elf]
set ::W9_PS7_INIT   [file join $::W9_PROJ_ROOT sw baremetal spike_accel_w9_smoke ps7_init.tcl]

set ::W9_WEIGHTS_ADDR  0x10000000
set ::W9_WEIGHTS_BYTES 1343776

proc w9_smoke_run {} {
    puts ""
    puts "============================================================"
    puts "[w9-smoke] xsdb automation start"
    puts "  proj root : $::W9_PROJ_ROOT"
    puts "  bitstream : $::W9_BIT"
    puts "  weights   : $::W9_WEIGHTS ($::W9_WEIGHTS_BYTES bytes @ $::W9_WEIGHTS_ADDR)"
    puts "  elf       : $::W9_ELF"
    puts "============================================================"

    # 1. Sanity check
    foreach f [list $::W9_BIT $::W9_WEIGHTS $::W9_ELF] {
        if {![file exists $f]} {
            error "[w9-smoke] missing file: $f"
        }
    }

    # 2. Connect to JTAG server (assumes hw_server is already running locally)
    connect

    # 3. Target the ARM Cortex-A9 #0
    targets -set -filter {name =~ "*Cortex-A9 #0*"}

    # 4. Reset and program the PL
    rst -system
    after 200
    puts "[w9-smoke] programming bitstream..."
    fpga -file $::W9_BIT

    # 5. Init PS DDR via ps7_init (Vitis generates this from XSA; you can
    #    alternatively source the platform-provided psu_init helper).
    if {[file exists $::W9_PS7_INIT]} {
        puts "[w9-smoke] sourcing ps7_init.tcl..."
        source $::W9_PS7_INIT
        ps7_init
        ps7_post_config
    } else {
        puts "[w9-smoke] WARN: ps7_init.tcl not found — falling back to BSP init"
    }

    # 6. Load weights blob into DDR (PL DMA region)
    puts "[w9-smoke] loading weights into DDR @ $::W9_WEIGHTS_ADDR..."
    mwr -bin -file $::W9_WEIGHTS $::W9_WEIGHTS_ADDR [expr $::W9_WEIGHTS_BYTES / 4]

    # Spot-check: read back first 16 bytes so user can sanity-compare with host hexdump
    puts "[w9-smoke] DDR @ $::W9_WEIGHTS_ADDR readback (4x u32):"
    set vals [mrd -force $::W9_WEIGHTS_ADDR 4]
    puts "  $vals"

    # 7. Download the elf and let it rip
    puts "[w9-smoke] downloading elf..."
    dow $::W9_ELF
    puts "[w9-smoke] elf loaded, PC = [print -e]"
    puts "[w9-smoke] >>> con — watch your UART terminal for results"
    con
}

# Convenience: a one-shot read-back of the output region (post-run forensics)
proc w9_dump_output {{path "feat_out_baremetal.bin"}} {
    set addr 0x10840000
    set bytes 21504
    mrd -bin -file $path $addr [expr $bytes / 4]
    puts "[w9-smoke] dumped $bytes bytes from $addr to $path"
}

puts "[w9-smoke] xsdb_setup.tcl loaded. Type:  w9_smoke_run   to start."
puts "[w9-smoke]                   or:  w9_dump_output ?path?   after a successful run."
