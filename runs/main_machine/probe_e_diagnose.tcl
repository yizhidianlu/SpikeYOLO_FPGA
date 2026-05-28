# probe_e_diagnose.tcl — JTAG halt bisection. Find where halt breaks.
#
# Three phases run in sequence; each tries to halt the CPU under a different
# configuration. The pattern of pass/fail tells us whether the failure is
# cable/host, v12c bitstream, or JTAG frequency.
#
# Owner: Main Claude (writes), Remote runs.
# Usage on Remote:
#   xsdb -interactive
#   xsct% source runs/main_machine/probe_e_diagnose.tcl
#
# Capture stdout to runs/remote_machine/probe_e.log and commit.

puts "================================================================"
puts " probe_e PHASE 1 — halt with NO bitstream loaded (cold connect)"
puts "================================================================"
connect
targets -set -filter {name =~ "*Cortex-A9 MPCore #0*"}
puts "==state pre-halt=="
state
puts "==attempt halt (no bit loaded)=="
if {[catch {stop} _err]} {
    puts "PHASE1 STOP FAIL: $_err"
    set p1_pass 0
} else {
    puts "PHASE1 STOP OK"
    set p1_pass 1
    catch {puts "PC = [rrd pc]"}
}
catch {con}

puts ""
puts "================================================================"
puts " probe_e PHASE 2 — halt at reduced JTAG frequency"
puts "================================================================"
puts "==disconnect=="
catch {disconnect}
puts "==reconnect with lower freq=="
# 1 MHz is a quarter of typical default; reveals DAP-clock timing margin
connect
jtag targets
# best-effort frequency adjust (XSDB API: 'jtag frequency')
catch {jtag frequency 1000000} _f
puts "jtag freq result: $_f"
targets -set -filter {name =~ "*Cortex-A9 MPCore #0*"}
puts "==attempt halt @ 1MHz=="
if {[catch {stop} _err]} {
    puts "PHASE2 STOP FAIL: $_err"
    set p2_pass 0
} else {
    puts "PHASE2 STOP OK"
    set p2_pass 1
    catch {puts "PC = [rrd pc]"}
}
catch {con}

puts ""
puts "================================================================"
puts " probe_e PHASE 3 — halt AFTER load v12c (control: confirm regression)"
puts "================================================================"
catch {disconnect}
connect
targets -set -filter {name =~ "*Cortex-A9 MPCore #0*"}
puts "==load v12c bit=="
if {[catch {fpga -file C:/Users/jielu/Desktop/Workspace/SpikeYOLO_FPGA/hw/vivado/out/system.bit} _berr]} {
    puts "PHASE3 fpga FAIL: $_berr  (try the alternate fork path below)"
    catch {fpga -file C:/Users/jielu/Desktop/Project/SpikeYOLO/hw/vivado/out/system.bit}
}
puts "==attempt halt (post v12c)=="
if {[catch {stop} _err]} {
    puts "PHASE3 STOP FAIL: $_err"
    set p3_pass 0
} else {
    puts "PHASE3 STOP OK"
    set p3_pass 1
    catch {puts "PC = [rrd pc]"}
}

puts ""
puts "================================================================"
puts " probe_e SUMMARY"
puts "================================================================"
puts "PHASE1 (no bit, default freq):     [expr {$p1_pass ? "PASS" : "FAIL"}]"
puts "PHASE2 (no bit, 1MHz freq):        [expr {$p2_pass ? "PASS" : "FAIL"}]"
puts "PHASE3 (v12c bit, default freq):   [expr {$p3_pass ? "PASS" : "FAIL"}]"
puts ""
puts "DIAGNOSIS RULES:"
puts "  P1 PASS, P3 FAIL  -> v12c bitstream pollutes PS-DAP -> bisect BD/constraints"
puts "  P1 FAIL, P2 PASS  -> JTAG freq mismatch -> permanently lower in xsdb_setup.tcl"
puts "  P1 FAIL, P2 FAIL  -> cable / hw_server / host issue -> try other cable / other host"
puts "  P1 PASS, P3 PASS  -> intermittent (try repeated; check thermal / power)"
exit 0
