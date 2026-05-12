# B1 HLS report templates

M1 W6 deliverable. Predefines the output schema produced by the M2 synthesis
flow so D2's hls_smoke.yml + R1 / R2 gates can be wired up before vitis_hls
actually runs on a self-hosted runner.

Vitis HLS synthesis (`run_synth.tcl` -> `csynth_design`) produces the
following files under `hw/hls/reports/`, one row per kernel:

- `reports/utilization.rpt` — `report_utilization -hierarchical` output,
  per-kernel DSP / BRAM_18K / LUT / FF actuals + totals row.
- `reports/timing.csv` — one row per kernel:
  `kernel,target_period_ns,achieved_period_ns,wns_ns`. 10 kernels + the
  top dispatcher (tiny_fpga_top) = 11 rows.
- `build/tiny_fpga_top.xo` — packed via `export_design -format ip_catalog`,
  delivered to B2 at `hw/vivado/ip_repo/spike_accel/`.

## D2 R1 / R2 auto gate (`docs/RISK_RULES.yaml`)

- R2 (resource over budget): DSP > 154 (Z-7020 220 * 70% cap) ->
  `check_resource_budget.py` exits 1 -> CI fail. BRAM_36K > 105
  (140 * 75%) and LUT > 31_800 (53_200 * 60%) trigger the same gate.
- R1 (timing fail): any `timing.csv` row with `wns_ns < 0` -> fail.

## Manual review checklist (post-csynth)

- [ ] Every leaf kernel inner loop hits II=1 (HLS PIPELINE II=1, auto-applied)
- [ ] PE array 16x8 unrolled (HLS ARRAY_PARTITION dim=1 type=complete plus
      UNROLL factor=8 on the C_in axis)
- [ ] No CRITICAL WARNING lines in the synth log
- [ ] regmap.yaml matches Contract 3 v1.0.x (LAYER_ID @ 0x10,
      LAYER_MASK @ 0x14, pointer offsets shifted per v1.0.3)
- [ ] tiny_fpga_top.xo is consumable by `hw/vivado/build_bd.tcl` `read_ip`
- [ ] cosim WNS vs csynth WNS gap < 15 % (else R6 triggers)
