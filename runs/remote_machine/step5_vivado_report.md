# Step 5 — Vivado BD + bitstream (BLOCKED at BD)

## Status: BLOCKED — Digilent vivado-boards (board_files repo) not installed
## Wall time: ~30 s (failed at line 33 of build_bd.tcl)
## Started: 2026-05-12T17:38:26+08:00

## Commands run

```cmd
:: prerequisite copy
copy hw\hls\build\sa_tiny_fpga_top.zip hw\vivado\ip_repo\spike_accel\sa_tiny_fpga_top.xo

:: chain (attempted)
call E:\Applaction\Xilinx\Vivado\2024.1\settings64.bat
cd hw\vivado
vivado -mode batch -source build_bd.tcl   :: FAILED
:: build_bitstream.tcl never reached
```

## Error

```
ERROR: [Board 49-71] The board_part definition was not found for
digilentinc.com:zybo-z7-20:part0:1.0 ...
```

Vivado's board catalog at `E:\Applaction\Xilinx\Vivado\2024.1\data\boards\` has only `board_schemas/` + `board_interface_preferences.xml` — no actual board_files. The Digilent vivado-boards repo isn't fetched by `setup_ip_repo.sh` (which only handles vivado-library = IPs, not boards).

See `URGENT_ASK_7.md` for analysis + 4 options.

## Outputs

| Path | Note |
|---|---|
| `hw/vivado/ip_repo/spike_accel/sa_tiny_fpga_top.xo` | copied from build/ (156 KB), Vivado would read on next attempt |
| `runs/remote_machine/step5_vivado_stdout.log` | error trace, 2 KB |

## Next step

Awaiting board.repoPaths resolution per URGENT_ASK_7. Likely fix: Option α (Main updates setup_ip_repo.sh to also submodule vivado-boards), or Option β (user authorizes clone, Remote writes wrapper TCL).
