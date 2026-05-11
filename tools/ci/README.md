# tools/ci — Shared CI utilities (D2 Agent)

**Owner**: D2 CI/CD Agent — see [`docs/AGENT_PLAYBOOKS/D2_ci_cd.md`](../../docs/AGENT_PLAYBOOKS/D2_ci_cd.md)

## Purpose

Helper scripts shared by `.github/workflows/*.yml`. Single source of truth for environment setup, board sync, report parsing, and risk classification.

## Layout

```
run_hls_csim.sh            Wrap Vitis HLS C-simulation
scp_to_board.py            Sync built artifacts to ZYBO over SSH
gen_dts.py                 address_map.yaml → uio_config.dts (consumed by C2)
check_timing.py            Parse timing_summary.rpt, gate on WNS ≥ threshold
check_utilization.py       Parse utilization.rpt, gate on resource budget
check_resource_budget.py   Multi-metric resource gate (DSP/LUT/BRAM)
gen_milestone_report.py    Generate docs/reports/M<n>_report.md
dispatch_risk_issue.py     Classify CI failure → open GitHub issue with risk label
```

## Used by

- `.github/workflows/numpy_regress.yml`
- `.github/workflows/hls_smoke.yml`
- `.github/workflows/board_nightly.yml`
- `.github/workflows/risk_dispatcher.yml`
- D1 manual milestone report generation

## Conventions

- Pure Python 3.10+, no exotic dependencies (use stdlib + PyYAML + click)
- Every script has `--help` and exit codes that CI can `if: failure()` branch on
- No board-specific paths hard-coded — pass via flags or env vars

## References

- [`docs/RISK_RULES.yaml`](../../docs/RISK_RULES.yaml) — risk classifier rules
- [`docs/CONTRACTS.md`](../../docs/CONTRACTS.md) — Contract 4 (address map)
