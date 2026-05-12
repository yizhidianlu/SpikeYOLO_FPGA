# M1 Monthly Report

- Window: 2026-05-11 → 2026-06-10 (current snapshot 2026-05-11, end-of-W3)
- Owner: D1 System Verification — `D1-session-2026-05-11`
- Generated: 2026-05-11 (manual draft; tools/ci/gen_milestone_report.py wireup deferred to M2)

---

## 1. Executive Summary

- layer_00 stem byte-identical end-to-end: B1 host_csim DUT vs A2 GOLDEN OK 98 304 elems on real A1 INT8 weights (`runs/B1_W2_report.md`). Three more block ops (sep_conv / ms_all_conv_block / spike_sppf) added W3, all four targets PASS byte-identical (`runs/B1_W3_report.md`).
- mAP baseline locked: teacher SpikeYOLO_23.1M_T1D4 = 45.35% mAP50-95 @ 640×640 on COCO val2017; student tiny_fpga init = 0.00% @ 256×256 (Kaiming, expected).
- Risk R8 (distillation compute budget) is the single open blocker; held pending the algorithm-budget RFC issued alongside this report (`docs/decisions/0002_compute_budget_distillation.md`).
- Contracts evolved twice: v1.0.1 (SPPF / head_reduce channel widths) and v1.0.2 (.npz regen after SepRepConv pad-bug fix). New `.npz` sha256 `d5385c05de1930d05d08202c96d4ae681db904c3d97ea19047f524ce8baa365a`.
- M2 enters with green data path on 4 of 11 layers, full A2 golden coverage (12/12), Vivado BD scaffolds in place, and CI auto-gating on every PR.

## 2. Per-Agent Progress

### A1 Quantization
- Phase-1.5 distill skeleton landed (`distill_config.yaml`, `distill_losses.py`, `teacher_adapter.py`, `distill_from_teacher.py`).
- Phase-1 baseline produced: `runs/baseline_summary.json` populated for teacher + student-init.
- W3 bug fixes: SepRepConv inner-3×3 pad → 1 (L04/L11/L18/L27); 5D→4D tap squeeze on student feats; ultralytics DetectionTrainer subclass wired with hook-managed teacher feats.
- Open: 30-epoch real distill run still gated on R8 budget decision. `student_distilled` mAP remains null.
- Key files: `tools/quant/{run_ptq.py, distill_from_teacher.py, eval_baseline_triple.py}`; `models/tiny_fpga_int8.{npz,bin}`.

### A2 Bit-Exact Reference
- 12 golden layers regenerated from real A1 INT8 weights; `golden_index.json` records `weights_source: a1_int8_npz` + sha256 + `pad_autocorrected: true` (will flip to false after consuming the v1.0.2 regen).
- `tests/test_bit_exact.py` — 37 parametrised cases (12 numpy self-consistency + 1 schema + 12 contract shapes + 12 npz required-keys), 37/37 PASS in 4.47 s.
- COCO val100 generator (`tools/verify/gen_coco_val100.py`) writes Contract-6 schema; smoke fixture `coco_val100_smoke.json` (5 imgs).
- Key files: `tools/verify/{extract_golden.py, gen_coco_val100.py}`; `tests/golden/layer_*.npz`.

### B1 HLS Kernel
- Layer 00 stem operator + minimal `.npy` reader (`hw/hls/sim/npz_reader.{h,cpp}`) → host_csim PASS byte-identical on real A1 weights (W2).
- W3: `sep_conv.cpp`, `ms_all_conv_block.cpp`, `spike_sppf.cpp` + their TBs — host_csim_layer_{00,01,03,08} all PASS DUT vs REF and DUT vs GOLDEN.
- Resource paper-estimate: 64 DSP / 48 KB BRAM peak scratch (well under 154 DSP / Z-7020 BRAM ceiling).
- Open: detect_head + tiny_fpga_top deferred to M2-W1; vitis_hls cosim deferred to M2 (host runner not yet provisioned).
- Key files: `hw/hls/src/{ms_downsampling, sep_conv, ms_all_conv_block, spike_sppf}.cpp`; `hw/hls/Makefile`.

### B2 System Architect
- HDMI Tx ADR-0001 chose Digilent rgb2dvi v1.4 (board-matched, BSD, 1080p@60). `hw/vivado/out/address_map.yaml` populated with the 4 peripheral records and IRQs (61/62/63/64) per Contract 4.
- `hw/vivado/scripts/{build_bd.tcl, synth_impl.tcl}` skeletons in place; no Vivado batch run yet.
- Open: vendor `digilentinc.com:ip:rgb2dvi:1.4` into `hw/vivado/ip_repo/`; first real synthesis in M2-W1; needs B1 to publish `tiny_fpga_top.xo` + `tiny_fpga_regmap.yaml`.
- Key files: `hw/vivado/scripts/build_bd.tcl`; `hw/vivado/out/address_map.yaml`; `docs/decisions/0001_hdmi_tx_selection.md`.

### D2 CI/CD
- 4 GitHub workflows: `numpy_regress.yml`, `hls_smoke.yml`, `board_nightly.yml`, `risk_dispatcher.yml`. PR gate latency ≤ 4 min on default branch (torch only on `quant-change` label).
- `RISK_RULES.yaml` — 8 rules R1..R8 with regex patterns, assignees, and handler hints; default fallback to D2.
- `tools/ci/{dispatch_risk_issue.py, run_host_csim.py, explode_npz.py, gen_dts.py, check_utilization.py, check_timing.py, gen_sep_conv_smoke.py}` — all CI helpers.
- Open: self-hosted ZYBO runner for `board_nightly` and Vitis runner for cosim tier — not provisioned until M3.
- Key files: `.github/workflows/*.yml`; `docs/RISK_RULES.yaml`; `tools/ci/dispatch_risk_issue.py`.

## 3. Acceptance Gate Status

- Contract 1 (A1 → B1, weight .npz): PASS. v1.0.2; sha256 `d5385c05de1930d05d08202c96d4ae681db904c3d97ea19047f524ce8baa365a`. Loaded by B1 host_csim and A2 reference, both bit-exact.
- Contract 2 (A2 → B1, golden tensors): PASS. 12/12 layers extracted; 37/37 bit_exact regression cases green; v1.0.1 layer table aligned to .npz reality.
- Contract 3 (B1 → B2, IP + regmap): PENDING M2. Needs `tiny_fpga_top.xo` + `tiny_fpga_regmap.yaml`. Block ops 4/11 done; detect_head + top-level wrapper outstanding.
- Contract 4 (B2 → C2, address_map.yaml): SCAFFOLD. Peripheral table populated, bitstream/hwh paths placeholder until first real synthesis (M2-W4).
- Contract 5 (C2 → C3, SDK ABI): NOT STARTED (M3).
- Contract 6 (A2 → C3/D1, COCO val100 JSON): SMOKE ONLY. 5-image fixture in place; full 100-image pass deferred until detect head decoder ships (C3, M4).

## 4. Key Metrics

- mAP_teacher_fp32 (640×640, COCO val2017, 5000 imgs) = 45.35% mAP50-95
- mAP_student_init (256×256, Kaiming) = 0.00% mAP50-95 (expected)
- mAP_student_distilled = null (gated on R8)
- HLS host_csim coverage = 4 / 11 layers (00, 01, 03, 08), all byte-identical
- HLS resource paper-estimate = 64 DSP / 48 KB BRAM peak (budget 154 DSP / 240 BRAM)
- CI latency (numpy_regress on default branch) ≤ 4 min
- A2 bit_exact regression = 37/37 PASS
- Contracts changelog entries this month: 2 (v1.0.1, v1.0.2)

## 5. Risk Register

Status of the 8 rules in `docs/RISK_RULES.yaml` as of 2026-05-11:

- R1 timing_not_closed — DORMANT. No HLS synth this month; first WNS reading expected M2-W2.
- R2 resource_over_z7020 — DORMANT. Paper budget 64 DSP < 154; revisit after PE-array integration in M2.
- R3 ddr3_bandwidth — DORMANT. No board traffic this month; first DDR stall reading from `board_nightly` post-M3.
- R4 map_drop_over_1pct — NOT YET TRIGGERABLE. mAP delta gate fires only when `student_distilled` is non-null.
- R5 usb_uvc_drops — DORMANT. UVC integration is C3 / M4.
- R6 cosim_csim_diverge — DORMANT. Cosim runner not yet provisioned.
- R7 petalinux_no_uvc — DORMANT. Petalinux build is C1 / M2.
- R8 distill_not_converging — OPEN PRECURSOR. Distill loop not yet run because compute budget is unresolved; see `docs/decisions/0002_compute_budget_distillation.md`. R8 fires only on `distill_map < 18.0`, so it cannot trigger until we actually train.

Out-of-table risks tracked in ADRs:
- HDMI IP fallback (Xilinx HDMI 1.4 TX free tier) — documented in ADR-0001, not numbered.

## 6. Contracts Changelog

Two entries this month (full text in `docs/CONTRACTS_CHANGELOG.md`):

- v1.0.1 — Contract 2 layer table L122-127 corrected for SPPF cv2 (192→48, not 192→96) and head_reduce (48→48, not 192→48). Verified by walking real `tiny_fpga_fp32.pt` under width=0.1875.
- v1.0.2 — Contract 1 .npz regenerated after SepRepConv 3×3-dwconv pad bug fixed (L04/L11/L18/L27 now `pad=1`). Schema unchanged; on-disk values changed. New sha256 `d5385c05...`.

## 7. M2 Plan

- A1: 30-epoch distill on whichever compute path the user approves in the RFC (target mAP_student_distilled ≥ 18.0, R8 acceptance). Then re-run PTQ → regenerate `.npz` (will become Contract v1.0.3 if shape changes). Local `--epochs 1` sanity check first.
- A2: re-run `extract_golden.py` against the post-distill `.npz`; expect new `weights_sha256` and `pad_autocorrected: false`. Extend `coco_val100` to real 100 images once C3 detect head decoder lands.
- B1: detect_head (Layer 11) + `tiny_fpga_top.cpp` orchestration; first `vitis_hls` synth + cosim run; publish `tiny_fpga_top.xo` + `tiny_fpga_regmap.yaml` for B2.
- B2: vendor `rgb2dvi` IP; run first `vivado -mode batch` BD build + bitstream; populate real bitstream/hwh paths in `address_map.yaml`; AXI-VIP smoke against B1 .xo.
- C1: Petalinux 2024.1 BSP, `image.ub` + `BOOT.BIN`, USB UVC kernel config (CONFIG_USB_VIDEO_CLASS=y).
- D1: this month's deliverables — wire `tools/ci/gen_milestone_report.py` so M2 report is auto-generated from CI artifacts; expand `tools/perf/fps_bench.py` from skeleton to real GPU mode (board mode still stub until M3); add `coco_val_on_board.py`. Coordinate with all Agents on monthly data-feed schema.
- D2: queue-age cleanup script for self-hosted runners; provision Vitis runner once Vitis license sorted; nightly board runner specced for M3.

## §8 Live metrics snapshot — 2026-05-11

Generated by D1 W4-followup sprint:
- fps_bench gpu mode (tiny_fpga_fp32.pt @ 256×256, RTX 5060 Laptop, 600 frames + 20 warm-up, CUDA events): ms_avg = 10.926 ms, ms_p50 = 10.525 ms, ms_p99 = 15.360 ms, fps_avg = 92.55 FPS, fps_p1 = 65.11 FPS, jitter = 11.475 %, dropped = 0. Raw: `runs/perf/fps_bench_gpu.json`. (Reference only — FP32 cuda upper bound; board KPI is FPS @ INT8 @ Z-7020 in M4+.)
- baseline mAP: teacher 45.35 %, student_init 0.00 %, student_distilled pending compute (gated on R8 / ADR-0002 ack). Persisted in `runs/baseline_summary.json` against the v1.0 schema (model + map50_95 + input_size + dataset + source per slot, plus `summary.expected_distill_floor = 18.0`).
- run_full.sh: 0 FAIL / 4 steps — 1_numpy_bit_exact PASS, 2_host_csim_4layers SKIP (g++/make not on PATH on this PC; CI provides toolchain), 3_quant_map_gate PASS (soft-warn until distill closes), 4_baseline_triple PASS via `--from-cache`. Log: `runs/perf/run_full_log.txt`.
- pytest test_bit_exact: 37 / 37 PASS in 3.88 s (A2 golden coverage, 12 numpy self-consistency + 1 schema + 12 contract shapes + 12 .npz required-keys).
- host_csim full chain (layers 00 / 01 / 03 / 08, plus the 11-layer paper-budget chain): all byte-identical DUT-vs-GOLDEN per `runs/B1_W4_report.md`.

W5 prep additions (D1 W5 sprint, 2026-05-12):
- A2 W5 self-consistency: 12 / 12 PASS (`runs/numpy_self_consistency_full.json`, weights sha256 `d5385c05…365a`); pytest now **49 / 49** (37 W4 + 12 new self-consistency cases, `tests/test_bit_exact.py` 9.76 s).
- C3 W5 推算 board FPS: sequential `total_ms ≈ 81 ms → ~12 FPS`; three-stage `effective_fps ≈ 1/max(stage_*) ≈ 1/35 ≈ 28 FPS` (~2.3× speedup, M5 25–30 FPS reachable without bitstream changes).
- B1 W4 paper-estimate resources (post tiny_fpga_top): DSP 64 / on-chip BRAM ~32 KB / LUT ~6 K — Z-7020 budget 154 DSP / 560 KB BRAM / 53 K LUT (utilization < 30 %).
- B2 W5 IP repo: vendored Digilent `vivado-library` submodule, 23 IPs imported including `rgb2dvi` / `axi_dynclk` / `dvi2rgb`; `build_bd.tcl` data-plane fully wired (9 explicit + 5-loop + 5 control + 15 fanout nets).
- C2 W5 SDK v1.1.0: `sa_set_layer_id` / `sa_set_layer_mask` APIs landed; `sa_infer` timeout semantics aligned to CONTRACTS authority (0/-1/>0); `sa_perf_t` ABI fence-commented + 2 tail-only diag fields.
- A1 sanity 5-epoch training: in progress at step 140 (PID 15548 ALIVE; latest `loss_total=196.66`, `loss_det=4.255`); ETA ~22-25 min total per W4 kickoff measurement (1.52 it/s). Final mAP TBD once final `_distilled_sanity5.pt` emits.
- W5 active agents: 8 / 10 (A2 / B1 / B3 / C1 / C2 / C3 / D1 / D2 in_progress; A1 sanity-only, no W5 report yet; B2 pending session). D1 / D2 / C1 reports filed W5.
- New tool: `tools/perf/latency_breakdown.py --mode simulate` (D1 W5) — emits per-stage budget from ARCHITECTURE §2.3: total 29 ms avg → 34.5 FPS, 12.1 % headroom over 33 ms, bottleneck = infer (18 ms / 56 FPS-eq).
- `run_full.sh` now 5 steps (added `1b_numpy_self_consistency`); end-to-end **0 FAIL / 5 steps** on this PC, log `runs/perf/run_full_log.txt`.
