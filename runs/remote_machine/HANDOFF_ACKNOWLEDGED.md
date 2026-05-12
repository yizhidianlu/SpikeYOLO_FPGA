# Remote Claude Handoff — Acknowledged

## Identity
- **Role**: Remote Claude (Vivado-Runner), acting as B1 + B2 Agent runner identity
- **Machine**: Win11 Home China 10.0.26200 (second machine, Vivado/Vitis HLS 2024.1 box)
- **Session**: Claude Code, Opus 4.7 (1M context)
- **ACK timestamp**: 2026-05-12T15:00:13+08:00

## Environment identification

### Git
- **Branch**: `vivado/synth-runner` (working tree clean)
- **HEAD commit**: `a0bf15b3f90767368cdda4cb2694727ed789a7ba`
- **HEAD message**: `feat: M1 W8 — Claude<->Claude async collaboration protocol via git`
- **HEAD authored**: 2026-05-12 14:56:21 +0800

### Xilinx toolchain (verified present)
- **Vitis HLS 2024.1**: `E:\Applaction\Xilinx\Vitis_HLS\2024.1\settings64.bat` ✓
- **Vivado 2024.1**:    `E:\Applaction\Xilinx\Vivado\2024.1\settings64.bat` ✓

### Python env (verified)
- **Conda env**: `spikeyolo`
- **Python**: 3.10.20
- **numpy**: 2.2.6
- **pyyaml**: 6.0.3

### Project layout (verified)
- `hw/hls/run_csim.tcl`  ✓ (10 (top, tb) targets, xc7z020clg400-1, 10 ns clock)
- `hw/hls/run_synth.tcl` ✓
- `hw/hls/run_cosim.tcl` ✓
- `runs/remote_machine/` created ✓

## Read inventory
- [x] `docs/REMOTE_CLAUDE_HANDOFF.md` (full brief, 275 lines)
- [x] `docs/CLAUDE_COLLABORATION_PROTOCOL.md` (async protocol, 166 lines)
- [x] `hw/hls/run_csim.tcl` (Step 1 entry, 10 targets confirmed)
- Pending (will read while Step 1 runs): `hw/hls/README.md`, B1/B2 playbooks, CONTRACTS §3, RISK_RULES.yaml

## 5-step ETA (excluding optional Step 2)

| Step | What | ETA (low) | ETA (high) |
|---|---|---|---|
| 1 | Vitis HLS C-sim (10 targets)         | 5 min  | 15 min |
| 2 | Vitis HLS Co-sim (**optional, skip if tight**) | (30) | (60) |
| 3 | Vitis HLS synth + .xo                | 25 min | 45 min |
| 4 | Resource + timing gate (Python)      | 1 min  | 3 min  |
| 5 | Vivado BD + bitstream                | 35 min | 50 min |
| 6 | git add/commit/push (LFS upload)     | 5 min  | 15 min |
| **Total (no Step 2)** | | **~71 min** | **~128 min** |
| **Total (with Step 2)** | | **~101 min** | **~188 min** |

Plan: skip Step 2 by default unless Step 1 wall time is well under budget. Will revisit after Step 1 completes.

## Operating rules I will follow
- Write report per schema after every step; git commit + push immediately
- Only modify allowed paths: `hw/hls/build/`, `hw/hls/reports/`, `hw/vivado/out/`, `hw/vivado/ip_repo/spike_accel/`, `runs/remote_machine/`, B1/B2 playbook status/owner header only
- On gate failure (R1 timing, R2 resource): write risk report, do **not** retry, do **not** modify pragma or algorithm
- On unrecognized blocker: write `URGENT_ASK.md`, push immediately, **stop and wait** for `REPLIES_FROM_MAIN.md`
- Will not touch `tools/`, `models/`, `sw/`, `tests/`, A/C/D playbooks, CONTRACTS.md main file, `.github/workflows/`, `main` branch

## Open questions (non-blocking)
- **`.gitignore` gap**: `runs/` is gitignored on line 138 with no exception for `runs/remote_machine/` or `runs/main_machine/`. Per the collaboration protocol I cannot modify `.gitignore` (Main owns). I am force-adding (`git add -f`) every new file under `runs/remote_machine/` for now. **Request to Main Claude**: please add `!runs/remote_machine/` and `!runs/main_machine/` exceptions to `.gitignore` on `main` and cherry-pick / merge into `vivado/synth-runner` when convenient. Until then every report push uses `-f`.
- **LFS credentials**: LFS push will need GitHub credentials on first invocation. If credentials are not cached I will halt at Step 6 push and write `URGENT_ASK.md` rather than guess at auth.

## Next action
Begin Step 1: `vitis_hls -f run_csim.tcl` on the 10 (top, tb) targets.

— Remote Claude (Vivado 2024.1 runner, 2026-05-12T15:00:13+08:00)
