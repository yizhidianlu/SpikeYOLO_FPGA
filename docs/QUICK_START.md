# SpikeYOLO → ZYBO Z7-20 FPGA — Quick Start

> 30 秒读懂；5 分钟动手。

## 这是什么

SpikeYOLO 23M teacher 蒸馏到 tiny_fpga student（256×256，宽度 0.1875，单尺度 P4），
经 INT8 权重 + INT4 激活 PTQ，翻译成 HLS C++（Vitis HLS 2023.x），部署到 Digilent
ZYBO Z7-20（Xilinx Z-7020 SoC）上的 USB UVC 摄像头 → FPGA 加速 → HDMI 1080p
本机显示 pipeline。目标：**≥30 FPS，mAP 下降 ≤ 1%**。

## 当前里程碑

- **M1** (2026-05-10 → 2026-06-10): layer_00 stem byte-identical 端到端通过 (achieved W4)
  + 4 / 11 block ops host_csim 通过 + tiny_fpga_top 端到端 DUT-vs-GOLDEN byte-identical
- **M2-M6** 见 `docs/ARCHITECTURE.md` §5（M2 全 11 层综合 / HDMI 彩条 / Petalinux USB；
  M6 30+ FPS 产品级 v1.0 tag）

## 5 分钟动手

```bash
git clone <repo> && cd SpikeYOLO
conda activate spikeyolo                       # 已有 env（torch 2.7 + cu128 + ultralytics 8.0.197）
bash tools/ci/local_validate.sh                # 6 步：CLI lint + golden 提取 + pytest + host_csim
pytest tests/test_bit_exact.py -v              # 期望 49 / 49 PASS（A2 W5）
```

## 团队 (10 Agent)

| ID | Owner (W5) | Status | 当前里程碑 | Playbook |
|---|---|---|---|---|
| A1 Quantization | (pending session) | sanity 5ep in progress | M1 | [A1_quantization.md](AGENT_PLAYBOOKS/A1_quantization.md) |
| A2 Bit-Exact | A2-session-2026-05-11-W5 | in_progress | M1–M2 | [A2_bit_exact_reference.md](AGENT_PLAYBOOKS/A2_bit_exact_reference.md) |
| B1 HLS Kernel | B1-session-2026-05-11-W5 | in_progress | M1–M5 | [B1_hls_kernel.md](AGENT_PLAYBOOKS/B1_hls_kernel.md) |
| B2 System Arch | (pending session) | pending | M2–M5 | [B2_system_architect.md](AGENT_PLAYBOOKS/B2_system_architect.md) |
| B3 RTL Tuning | B3-session-2026-05-11 | prep_done | M5 | [B3_rtl_tuning.md](AGENT_PLAYBOOKS/B3_rtl_tuning.md) |
| C1 Petalinux | C1-session-2026-05-11 | in_progress | M2–M3 | [C1_petalinux.md](AGENT_PLAYBOOKS/C1_petalinux.md) |
| C2 Driver/SDK | C2-session-2026-05-11-W5 | in_progress (v1.1.0) | M3–M4 | [C2_driver_sdk.md](AGENT_PLAYBOOKS/C2_driver_sdk.md) |
| C3 Application | C3-session-2026-05-11-W5 | in_progress | M4–M6 | [C3_application.md](AGENT_PLAYBOOKS/C3_application.md) |
| D1 Verification | D1-session-2026-05-11 | in_progress | M1–M6 | [D1_verification.md](AGENT_PLAYBOOKS/D1_verification.md) |
| D2 CI/CD | D2-session-2026-05-11 | in_progress | M1–M6 | [D2_ci_cd.md](AGENT_PLAYBOOKS/D2_ci_cd.md) |

W5 active: 8 / 10 agent。M1 端到端 byte-identical achieved；pytest 49 / 49 PASS；
A1 sanity 5ep 训练进行中。

## 关键产物地图

| Want to... | Look at... |
|---|---|
| 看蒸馏 loss 曲线 | `runs/distill/sanity_5ep_log.csv` |
| 看 host_csim 结果 | `runs/B1_W4_report.md` |
| 看 fps_bench (GPU) | `runs/perf/fps_bench_gpu.json` (10.93 ms / 92.55 FPS) |
| 看 self-consistency | `runs/numpy_self_consistency_full.json` (12 / 12 PASS) |
| 看月报 | `docs/reports/M1_report.md` |
| 跑 CI 自检 | `bash tools/ci/local_validate.sh` |
| 跑全回归 | `bash tests/regression/run_full.sh` |
| 看 contract 变更 | `docs/CONTRACTS_CHANGELOG.md` |
| 看 ADR | `ls docs/decisions/` (0001 HDMI / 0002 算力 / 0003 BSP / 0004 B3) |
| 看 baseline 三联 | `runs/baseline_summary.json` |

## 阻塞事项 (2026-05-11)

1. **R8 算力 RFC** ack 待 user 决定（ADR-0002）— 30-epoch real distill 卡在这里
2. **B2 self-hosted Vivado runner** 未上线 — 首次 BD synth 仍等 M2-W1
3. **Vitis HLS cosim runner** 未配 — `run_csim.tcl` skeleton ready 但 vitis_hls 不在本机
4. **Z-7020 板子物理可达性** — board_nightly job 等 M3 接入

## 链接

- [ARCHITECTURE.md](ARCHITECTURE.md) — 系统总览（数据流 / 时序预算 / 目录索引）
- [CONTRACTS.md](CONTRACTS.md) — 6 个 Agent 间机器可读契约
- [AGENT_PLAYBOOKS/README.md](AGENT_PLAYBOOKS/README.md) — 10 个 Agent 启动包索引
- [RISK_RULES.yaml](RISK_RULES.yaml) — R1–R8 风险自动 dispatch
- [FPGA_DEPLOYMENT.md](../FPGA_DEPLOYMENT.md) — 最早期入口文档（仍可读）
