# Step 3 — Vitis HLS C-synthesis (attempts 1-3, all BLOCKED)

## Status: BLOCKED (3rd consecutive csynth failure on `sa_tiny_fpga_top`)

## Wall time per attempt: ~50-58 s before abort
## Latest attempt: 2026-05-12T16:23 (Plan β Variant 2 applied via 267b7e4)

## Attempts log

| # | Patch applied | Error | URGENT_ASK |
|---|----|----|----|
| 1 | (none — vanilla) | HLS 214-298: struct-of-pointers on top arg | URGENT_ASK_2 |
| 2 | Option α: `#pragma HLS DISAGGREGATE variable=L` (62e1e19) | HLS 214-298 (same) — pragma doesn't apply to function arg | URGENT_ASK_3 |
| 3 | Plan β Variant 2: `const sa_i8_t *const *L_w / L_bias / L_shift` (267b7e4) | **HLS 214-134**: pointer-to-pointer also not supported | **URGENT_ASK_4** (this commit) |

All 3 attempts abort during source-analysis phase (~50 s) at target 1/5. Targets 2-5 never run.

## Latest error (verbatim)

```
ERROR: [HLS 214-134] in function 'sa_tiny_fpga_top': Pointer to pointer is not supported for variable 'L_shift'
ERROR: [HLS 214-134] in function 'sa_tiny_fpga_top': Pointer to pointer is not supported for variable 'L_bias'
ERROR: [HLS 214-134] in function 'sa_tiny_fpga_top': Pointer to pointer is not supported for variable 'L_w'
ERROR: [HLS 200-1715] Encountered problem during source synthesis
```

## Next step

Awaiting Main's Plan β Variant 1 (flat pool + offset table) per `URGENT_ASK_4.md`. Re-poll in +3 min per AUTOPOLL.

Step 4 / 5 / 6 remain blocked.
