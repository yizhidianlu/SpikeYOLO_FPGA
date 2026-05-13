# Step 5+6 — Vivado BD + impl (BD/synth OK, impl FAILED R2)

## Status

| Phase | Status | Wall time |
|---|---|---|
| BD construction (build_bd.tcl)  | **OK**  | ~30 s |
| IP generation (sub-IP synths)   | **OK**  | ~3-5 min (parallel) |
| Main `synth_1`                  | **OK**  | 19 min 09 s |
| Implementation `impl_1`         | **FAIL** (R2)  | 5 min 48 s before place_design abort |
| Bitstream `write_bitstream`     | not reached | n/a |

`hw/vivado/out/system.bit` does **not** exist.

## Issues that blocked attempts 1-7

| # | Fix applied | Result |
|---|---|---|
| 1 | vanilla | board_part :1.0 not found |
| 2 | Main ff78be1 (vivado-boards submodule + board.repoPaths) | board_part :1.0 still not found (file_version = 1.2) |
| 3 | Remote `:1.0 → :1.2` patched wrapper | xilinx.com:hls:sa_tiny_fpga_top:1.0 not found (.xo not recognized) |
| 4 | Extract .zip to ip_repo/spike_accel/sa_tiny_fpga_top/ | CWD bug (cd hw\vivado failed) |
| 5 | `cd /d` absolute | HAS_HLS_IP=0 (.xo file removed); + rgb2dvi s_axis_video pin missing |
| 6 | Main d8ffdd8 (Option γ HDMI dropped) | HLS-est m_axi 0 → URGENT_ASK_9 → REGRESSION |
| 7 | Main e340928 (macro shadow fix, port → _port) + re-csynth | m_axi works! BD OK! impl place_design fails R2 |

## Workarounds Remote applied (still in `runs/remote_machine/`)

- `run_step5_bd_patched.tcl` — string-maps build_bd.tcl `:1.0` → `:1.2`
- `run_step6_bt_patched.tcl` — corrected `update_ip_catalog -disable_ip ... -repo_path ...` (Main's d8ffdd8 used wrong flag `-delete_ipdef`); + `-jobs 1` + `set_param ip.useIpCache 0` to dodge IPCACHE thread crash
- `diag_get_board_parts.tcl` — empirical VLNV discovery

## Headline result: R2 fires hard with empirical data

```
[Place 30-487] The packing of instances into the device could not be obeyed.
  total slices: 13300
  available  : 4741 (post-PS reserve)
  required   : 10614  (224% of available)

Control sets: 1590
LUTs: 54339 combined / 65250 total (cap 53200)
FFs : 60999 (cap 106400, 57%)
```

See `risk_R2_resource.md` for analysis + recommended handlers (PE shrink 16×8 → 8×8, or time-multiplex). No retry per protocol; awaiting B1 architectural fix.

## What did succeed (preserved)

- **Step 1 csim 10/10 PASS** at `0b3df61` (byte-identical end-to-end)
- **Step 3 m_axi-correct IP** at `1ff4ae8` (5 m_axi_gmem* masters present)
- **Vivado BD constructed** (`hw/vivado/out/system.bd` saved, system.hwh exported)
- **synth_1 completed** (~19 min) — proves all upstream is sound; only place fails
- **synth_1 post-synth checkpoint** at `hw/vivado/out/spike_zybo.runs/synth_1/system_wrapper.dcp`

## Step 6 status

Skipped. No .bit / .hwh final products. Push of intermediate artifacts (.xo, .zip, reports) is up-to-date at HEAD.

## Next step

Awaiting Main's R2 handler (PE shrink or time-multiplex) per `risk_R2_resource.md`. Continuing AUTOPOLL loop.
