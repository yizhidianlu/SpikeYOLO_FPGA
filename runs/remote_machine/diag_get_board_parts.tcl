# Diagnostic: list every board_part Vivado recognizes from our cloned vivado-boards
set BOARDS [file normalize "[file dirname [info script]]/../../hw/vivado/ip_repo/digilent/vivado-boards/new/board_files"]
set_param board.repoPaths [list $BOARDS]
puts "INFO: board.repoPaths = $BOARDS"
puts "INFO: --- get_board_parts matching zybo ---"
foreach bp [get_board_parts -quiet -filter {NAME =~ "*zybo*"}] {
    puts "    $bp"
}
puts "INFO: ---"
exit 0
