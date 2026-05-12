# Urgent Ask #7 from Remote Claude — Step 5 Vivado BD: Digilent vivado-boards repo not installed

## TL;DR

`vivado -mode batch -source build_bd.tcl` fails at `set_property board_part digilentinc.com:zybo-z7-20:part0:1.0 ...` because Vivado's local board catalog has only `board_schemas/` + `board_interface_preferences.xml` — **the ZYBO Z7-20 board definition is missing**. This is the *board* repo (definitions of pins, PS presets, DDR config), separate from the *vivado-library* repo (IPs like rgb2dvi) that the project already pulls via submodule.

## What happened

```
ERROR: [Board 49-71] The board_part definition was not found for
digilentinc.com:zybo-z7-20:part0:1.0. The project's board_part property was
not set, but the project's part property was set to xc7z020clg400-1. Valid
board_part values can be retrieved with the 'get_board_parts' Tcl command.
Check if board.repoPaths parameter is set and the board_part is installed
from the tcl app store.
```

Wall 33 lines into Vivado batch run. `VIVADO_TCL_EXIT_FAIL`.

## Verification

- `E:\Applaction\Xilinx\Vivado\2024.1\data\boards\` contains only `board_interface_preferences.xml` + `board_schemas\`. No `board_files\`.
- `hw\vivado\ip_repo\digilent\` has only `vivado-library\` (the IP repo, with 23 IPs). No `vivado-boards\`.
- `hw\vivado\scripts\setup_ip_repo.sh` fetches only `vivado-library`, not `vivado-boards`. `.gitmodules` likewise.

## Why I cannot self-resolve

Attempted `git clone --depth 1 https://github.com/Digilent/vivado-boards.git runs/remote_machine/digilent_vivado_boards`. Blocked by Claude Code auto-mode classifier with reason:

> "Agent-chosen external repo clone … user authorized HLS/Vivado synth tasks, not pulling external repos; should file URGENT_ASK rather than self-source dependencies."

This is the correct guardrail — pulling new external git repos onto the runner is a setup decision that should be human-approved, not auto-triggered by Remote.

## Options for Main / user

### Option α — Main updates `setup_ip_repo.sh` to also fetch vivado-boards

```bash
# In hw/vivado/scripts/setup_ip_repo.sh, parallel to vivado-library:
BOARDS_URL="https://github.com/Digilent/vivado-boards.git"
BOARDS_DEST="hw/vivado/ip_repo/digilent/vivado-boards"
git -C "$REPO_ROOT" submodule add -f "$BOARDS_URL" "$BOARDS_DEST"
```

Then `build_bd.tcl` line 67 (where `set_property ip_repo_paths` is set) also adds:

```tcl
set BOARD_REPO [file normalize "${IP_REPO_DIR}/digilent/vivado-boards/new/board_files"]
if {[file isdirectory $BOARD_REPO]} {
    set_param board.repoPaths [list $BOARD_REPO]
}
```

The board_files are under `<repo_root>/new/board_files/zybo-z7-20/...` in the Digilent repo layout.

**Effort**: ~10 lines, 2 files. M2-W2 backlog item already worth doing.

### Option β — User authorizes the clone, re-invoke loop

The user (or you in this chat) can:

```bash
cd C:\Users\jielu\Desktop\Workspace\SpikeYOLO_FPGA
git clone https://github.com/Digilent/vivado-boards.git hw/vivado/ip_repo/digilent/vivado-boards
git -C hw/vivado/ip_repo/digilent/vivado-boards submodule update --init --recursive
```

Then write a small wrapper TCL under `runs/remote_machine/` that does:

```tcl
set_param board.repoPaths [list "<abs-path-to>/hw/vivado/ip_repo/digilent/vivado-boards/new/board_files"]
source build_bd.tcl
```

…and re-run Step 5. Remote can run this once the clone exists.

### Option γ — Drop `board_part` from build_bd.tcl, configure PS manually

Replace `apply_bd_automation -rule processing_system7 -config { apply_board_preset 1 }` with explicit `set_property -dict` for: DDR_PINS, FCLK_CLK0=100MHz, FCLK_CLK1=148.5MHz, MIO bindings (USB UART, Ethernet, SD, ...). Significant effort, error-prone, throws away Digilent's well-tested preset. **Not recommended unless we want to be fully board-file-independent**.

### Option δ — Use Vivado's xhub board installer

```tcl
xhub::refresh_catalog [xhub::get_xstores]
xhub::install [xhub::get_xitems digilent_boards]
```

Vivado 2024.1 has an in-process app/board store. Possibly hits same firewall as git clone but worth trying.

## My recommendation

**Option α** is the cleanest long-term: brings vivado-boards under the same submodule pattern as vivado-library. Drop-in for any future fresh clone.

**Option β** is fastest right now: ~30 seconds of human-authorized clone + wrapper TCL on Remote side.

## What I'm doing

- step5 partial report + this URGENT_ASK_7 committed and pushed.
- Step 4 manual gate already PASS (committed at `57aa30f`).
- Continuing AUTOPOLL loop.
- Will not retry Step 5 without `board.repoPaths` resolution.

— Remote Claude, 2026-05-12T17:42:00+08:00
