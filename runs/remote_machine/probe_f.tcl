# probe_f.tcl — rst -dap-srst full DAP reset, then halt.
connect
targets -set -filter {name =~ "*Cortex-A9 MPCore #0*"}
puts "==state pre-srst=="
state
puts "==rst -dap-srst=="
catch {rst -dap} _err
puts "rst -dap: $_err"
after 200
catch {rst -srst} _err
puts "rst result: $_err"
after 200
puts "==state post-srst=="
state
puts "==attempt halt=="
if {[catch {stop} _err]} {
    puts "F STOP FAIL: $_err"
} else {
    puts "F STOP OK"
    catch {puts "PC = [rrd pc]"}
}
exit 0
