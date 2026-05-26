# sw/baremetal/spike_accel_w9_smoke/build_w9_smoke.tcl
#
# Automated XSCT-driven build of the W9 PTQ INT8 baremetal smoke ELF.
# Replaces the GUI-only sequence documented in README.md §1–§2.
#
# Usage (from repo root):
#   xsct sw/baremetal/spike_accel_w9_smoke/build_w9_smoke.tcl
#
# Outputs:
#   vitis_workspace/spike_accel_w9_smoke/Debug/spike_accel_w9_smoke.elf
#   vitis_workspace/spike_zybo_baremetal_plat/.../ps7_init.tcl  (auto-gen from XSA)

set ::PROJ_ROOT [file normalize [file join [file dirname [info script]] ".." ".." ".."]]
puts "PROJ_ROOT = $::PROJ_ROOT"

set ::WS  [file join $::PROJ_ROOT vitis_workspace]
set ::XSA [file join $::PROJ_ROOT hw vivado out system.xsa]
set ::SRC [file join $::PROJ_ROOT sw baremetal spike_accel_w9_smoke src]

if {![file exists $::XSA]} { error "missing XSA: $::XSA" }
if {![file isdirectory $::SRC]} { error "missing src dir: $::SRC" }

file mkdir $::WS
setws $::WS

# ---- 1. Platform from XSA (one-time per XSA) -----------------------------
if {[catch {platform list -dict} _err]} {
    puts "WARN: platform list failed: $_err"
}
puts "\[build\] creating platform spike_zybo_baremetal_plat"
if {[catch {
    platform create -name spike_zybo_baremetal_plat \
                    -hw $::XSA -os standalone -proc ps7_cortexa9_0
} _err]} {
    # If platform already exists, ignore and continue.
    puts "WARN: platform create: $_err (continuing if already exists)"
}
platform active spike_zybo_baremetal_plat
puts "\[build\] generating platform"
platform generate

# ---- 2. App project ------------------------------------------------------
puts "\[build\] creating app spike_accel_w9_smoke"
if {[catch {
    app create -name spike_accel_w9_smoke \
               -platform spike_zybo_baremetal_plat \
               -domain standalone_domain \
               -template {Empty Application(C)}
} _err]} {
    puts "WARN: app create: $_err (continuing if already exists)"
}

# Import source files via soft-link so future edits in sw/baremetal/.../src
# propagate without re-copy.
puts "\[build\] importing src/"
if {[catch {
    importsources -name spike_accel_w9_smoke -path $::SRC -soft-link
} _err]} {
    puts "WARN: importsources soft-link failed ($_err); retrying without soft-link"
    importsources -name spike_accel_w9_smoke -path $::SRC
}

# ---- 3. Build ------------------------------------------------------------
puts "\[build\] app build…"
app build -name spike_accel_w9_smoke

# ---- 4. Verify outputs ---------------------------------------------------
set ::ELF [file join $::WS spike_accel_w9_smoke Debug spike_accel_w9_smoke.elf]
if {[file exists $::ELF]} {
    puts "============================================================"
    puts "\[build\] PASS — ELF at: $::ELF"
    puts "  size: [file size $::ELF] bytes"
    puts "============================================================"
} else {
    error "\[build\] FAIL — ELF not produced: $::ELF"
}

exit 0
