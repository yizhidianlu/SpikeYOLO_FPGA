# SpikeYOLO CI Guide

Owner: **D2 (CI/CD)** — see `docs/AGENT_PLAYBOOKS/D2_ci_cd.md` for the full playbook.
Last updated: M1 W7 (2026-05-12).

## 1. Four workflows at a glance

| Workflow | Trigger | Runner | Owners | Runtime |
|---|---|---|---|---|
| `numpy_regress.yml` | PR + push to `main` (paths: `tools/**`, `tests/**`, `models/**`, `ultralytics/nn/modules/yolo_spikformer*.py`) | `ubuntu-22.04` (hosted) | A1, A2, D2 | 2-4 min cold / <1 min warm |
| `hls_smoke.yml` | PR touching `hw/hls/**`, `tools/quant/**`, `tools/verify/**`, `tests/golden/**` | hosted `host_csim` + `[self-hosted, vivado]` cosim | B1, B3, A2 | 5-8 min |
| `board_nightly.yml` | cron `0 3 * * *` UTC + `0 4 1 * *` monthly + `workflow_dispatch` | `[self-hosted, zybo]` / `ubuntu-22.04` monthly | C3, D1, D2 | 10-30 min |
| `risk_dispatcher.yml` | `workflow_run.failure` on the above 3 | `ubuntu-22.04` | D2 + per-rule owner | <30 s |

Path filters live at the top of each workflow — update them when you add new owned files.

## 2. Pre-PR dev gate — `local_validate.sh`

```bash
bash tools/ci/local_validate.sh
```

9 host-side gates mirroring `numpy_regress.yml` + `hls_smoke.yml` (skips docker / self-hosted). Green here ⇒ green PR.

1. CLI `--help` lazy-import smoke
2. Regenerate `tests/golden/*` from `models/tiny_fpga_int8.npz`
3. `pytest tests/test_bit_exact.py` (A2 acceptance)
4. `golden_index.json` schema (12 layers, real weights)
5. `make host_csim_layer_00` (SKIP if no g++/make)
6. `test_address_map.py` + `test_weight_pack.py`
7. **`numpy_vs_hls.py --self-consistency`** (A2 W5, 12/12)
8. **`sw/sdk/examples/build/hello_open`** (C2 W6 — SKIP if not built)
9. **`tools/perf/latency_breakdown.py --mode simulate`** (D1 W5, headroom_pct > 0)

**Run before every `git push`.**

## 3. Heavier dry-run — `run_workflows_locally.sh`

[nektos/act](https://github.com/nektos/act) spins up an ubuntu container mirroring the hosted runner:

```bash
bash tools/ci/run_workflows_locally.sh numpy_regress.yml pull_request
bash tools/ci/run_workflows_locally.sh hls_smoke.yml    pull_request
```

Requires Docker + `act`. Self-hosted jobs (`board_test`, `vitis_csim`) skip automatically.

## 4. Long-run monitoring — distill watchdog

`tools/ci/monitor_distill_local.{sh,ps1}` is a 5-min watchdog for the A1 distill PID:

```bash
bash tools/ci/monitor_distill_local.sh           # human read
bash tools/ci/monitor_distill_local.sh --md      # markdown table for README / 月报
bash tools/ci/monitor_distill_local.sh --notify  # cron mode (writes monitor_alerts.log)
```

Reports PID alive, step / total, loss(det), **30-row regression slope** (collapse warn at slope ≥ +0.05), **it/s speed** (delta across invocations — needs ≥2 runs), **ETA**, GPU telemetry. Install cron / schtasks via `bash tools/ci/setup_distill_cron.sh`. Outputs: `monitor_state.txt` (last 5 stdout lines on death), `monitor_alerts.log` (STALE/DEAD/COLLAPSE, `--notify` only), `monitor_speed_state.txt` (cross-invocation state).

## 5. Failure debugging — `risk_dispatcher` auto-issue

When numpy_regress / hls_smoke / board_nightly fails on `main`, `risk_dispatcher.yml` parses logs via `docs/RISK_RULES.yaml` (R1..R7), opens a GitHub issue with `risk:R<n>` label, at-mentions the Agent. Workflow:

1. Read auto-opened issue title (risk ID + workflow run).
2. Grab logs from the `runs/regression_*/...` artifact link.
3. Cross-reference `docs/RISK_RULES.yaml` for the 3 bulleted mitigations per rule.
4. New failure mode? Add a rule and ping D2.

## 6. Artifact retention

| Artifact | Retention |
|---|---|
| `numpy-regress-<run_id>` (junit + self-consistency JSON) | 14 days |
| `hls-smoke-<run_id>` (host_csim logs + cosim VCD) | 7 days |
| `nightly-<run_id>` (perf + coco results) | 30 days |
| `monthly-snapshot-YYYYMM` (monthly cron) | 90 days |

Need it longer? Download locally to `runs/` (gitignored), team Drive syncs monthly.

## 7. Cheatsheet per Agent

| Agent | Files → trigger | Pre-PR check |
|---|---|---|
| A1 quant | `tools/quant/**`, `models/**` | `local_validate.sh` |
| A2 bit-exact | `tools/verify/**`, `tests/test_bit_exact.py`, `tests/golden/**` | `local_validate.sh` + `pytest tests/` |
| B1 HLS | `hw/hls/**` | `make -C hw/hls host_csim_top` + `local_validate.sh` |
| B2 sys arch | `hw/sys/**`, `address_map.yaml` | `python tools/ci/check_resource_budget.py` |
| C2 SDK | `sw/sdk/**` | `cmake --build sw/sdk/examples/build` + `local_validate.sh` |
| C3 app | `sw/app/**` | `local_validate.sh` |
| D1 verify | `tests/regression/**`, `tools/perf/**` | `bash tests/regression/run_full.sh` |
| D2 CI/CD | `.github/workflows/**`, `tools/ci/**`, `RISK_RULES.yaml` | yaml.safe_load + `local_validate.sh` |
