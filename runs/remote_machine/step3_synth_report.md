# Step 3 — Vitis HLS C-synthesis (attempt 2, Option α applied)

## Status: BLOCKED (0/5 csynth targets completed, second attempt)
## Wall time: ~1 min per attempt (~2 min total across both attempts)
## Re-run started: 2026-05-12T16:00:09+08:00
## Re-run aborted: 2026-05-12T16:01:08+08:00

## Commands run

```cmd
git pull origin vivado/synth-runner   # pulled 62e1e19 (Option α DISAGGREGATE)
cd hw/hls
vitis_hls -f run_synth.tcl            # same HLS 214-298 — Option α insufficient
```

## Results per target

| # | Top                  | csynth status | Note |
|---|----------------------|----------------|------|
| 1 | sa_tiny_fpga_top     | **ERROR**     | Same `HLS 214-298` at line 148 — DISAGGREGATE pragma at line 155 doesn't apply to function arguments |
| 2 | sa_ms_downsampling   | not run       | foreach abort |
| 3 | sa_ms_all_conv_block | not run       | (same) |
| 4 | sa_spike_sppf        | not run       | (same) |
| 5 | sa_detect_head       | not run       | (same) |

## Diagnosis

`#pragma HLS DISAGGREGATE variable=L` applies to **local struct variables**, not function arguments. Per Xilinx UG1399 (2024.1), DISAGGREGATE is intended to break apart struct loads/stores that cause memory access pattern problems for local variables. The error `HLS 214-298` fires during source-analysis phase, before any interface or DISAGGREGATE pragma takes effect.

Plan β (refactor `const sa_layer_weights_t *L` → 3 pointer args) is what's actually needed. URGENT_ASK_3.md filed.

## Outputs

| Path | Size | Note |
|---|---:|---|
| `runs/remote_machine/step3_synth_stdout.log` | ~22 KB | Identical to attempt 1 log; overwritten on re-run |
| `hw/hls/build/` | (empty) | no .xo |
| `hw/hls/reports/` | (empty) | no rpt |
| `hw/hls/synth_sa_tiny_fpga_top/` | ~few MB | csynth proj; gitignored |

## Next step

Awaiting Main Claude's Plan β patch via `REPLIES_FROM_MAIN.md`. After re-pull I will re-run `vitis_hls -f run_synth.tcl`. Other pipeline steps remain blocked.
