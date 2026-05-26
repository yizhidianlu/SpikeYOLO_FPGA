# Urgent Ask — M3 PBT deploy work order missing

## TL;DR

User instructed me to execute the M3 deployment work order at `runs/main_machine/M3_pbt_deploy_request.md` and load `models/tiny_fpga_int8_pbt.bin`. **Neither file exists** in the repo after pulling latest origin/main (HEAD `5da6155`).

Latest commits on `origin/main` (top 5):
```
5da6155 fix(distill): A2-W11 mAP gap root-cause + 5-class subset retrain path
0dc5bb5 feat(sw+ci): W9 byte-exact baremetal toolchain + COCO aria2 helper
0d9d0f9 report: M2-W2 timing closure PASS milestone (bcff93a)
f0d6c8a feat(sw): W9 PTQ INT8 end-to-end smoke test scaffolding
01ecd58 docs(README): rewrite for SpikeYOLO_FPGA project (ZYBO Z7-20 deployment)
```

No commit mentions "pbt". No file matches `*pbt*` glob anywhere in the tree (checked).

## What I expected vs what I see

| Expected | Actual |
|---|---|
| `runs/main_machine/M3_pbt_deploy_request.md` | Not present. Only A2/A3/M2 files there. |
| `models/tiny_fpga_int8_pbt.bin` | Not present. Only `tiny_fpga_int8.bin`, `tiny_fpga_int8_v6.bin`. |
| `models/tiny_fpga_int8_real.bin` (referenced by current xsdb_setup.tcl line 11+33) | Also not present. |

## What I successfully did

- Merged `origin/main` into `vivado/synth-runner` (`a46d938`). Brought in:
  - sw/baremetal/spike_accel_w9_smoke/ (README + src/main.c + xsdb_setup.tcl)
  - tools/ scripts (gen_w9_golden, train2017 retrain path, etc.)
  - ultralytics/ data configs

## What I cannot do without the missing files

- Cannot run W9 byte-exact smoke (need `tiny_fpga_int8_pbt.bin` to flash to DDR via xsdb)
- Cannot patch xsdb_setup.tcl correctly without the work order specifying the exact .bin filename and DDR offsets
- Cannot capture board FNV-1a32 hash because no smoke binary will load

## Standing by

Per CLAUDE_COLLABORATION_PROTOCOL.md, holding here until Main pushes:
1. `runs/main_machine/M3_pbt_deploy_request.md` with the full work order
2. `models/tiny_fpga_int8_pbt.bin` (PBT-quantized INT8 weights, ~1.3 MB based on v6 sibling size)

Vivado runner is otherwise idle. v12b 1080p bitstream from M3 final (commit `c5ca631` on `vivado/synth-runner`) is intact and ready for board deploy as soon as the work order arrives.

— Remote Claude, 2026-05-15T12:35:00+08:00
