# SpikeYOLO → ZYBO Z7-20 FPGA Deployment

> **Real-time SNN-based object detection on Xilinx Zynq-7000 (Z-7020).**
> USB camera → spike accelerator → HDMI 1080p output @ 30+ FPS,
> COCO mAP degradation ≤ 1%.

---

## Quick links

| 文档 | 用途 | 读者 |
|---|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 5 分钟看懂整体系统 | 所有人 |
| [`docs/CONTRACTS.md`](docs/CONTRACTS.md) | 6 条 Agent 间接口契约 | 所有 Agent |
| [`docs/AGENT_PLAYBOOKS/`](docs/AGENT_PLAYBOOKS/) | 10 份 sub-agent 自治启动包 | 对应 Agent |
| [`docs/RISK_RULES.yaml`](docs/RISK_RULES.yaml) | CI 失败自动分类规则 | D2 + 风险责任人 |
| [`.claude/plans/spikeyolo-zynq-7000-zybo-fpga-agent-radiant-unicorn.md`](.claude/plans/spikeyolo-zynq-7000-zybo-fpga-agent-radiant-unicorn.md) | 顶层 plan（gantt + 风险预案） | PM / 评审者 |
| [`docs/reports/`](docs/reports/) | 月度验收报告（D1 自动生成） | PM / 评审者 |

---

## 项目硬约束

```
板子      Digilent ZYBO Z7-20 (Xilinx Z-7020 SoC)
          53 200 LUT / 220 DSP / 4.9 Mb BRAM / 1 GB DDR3
输入      USB UVC camera @ 640×480
输出      HDMI 1080p@60 with bbox overlay
推理      tiny_fpga: 256×256 input, 单尺度 P4, INT8 weight + INT4 activation
性能      ≥ 30 FPS (10 min stable, jitter < 5%)
精度      COCO val mAP50-95 degradation ≤ 1.0%
工具链    Vitis HLS 2023.2 + Vivado + Petalinux + C/C++
周期      6 个月, 3–5 人团队
```

---

## 多 Agent 团队总览

```
Group A (Model)          Group B (Hardware)        Group C (System SW)    Group D (Verify)
─────────────────        ───────────────────       ───────────────────    ────────────────
A1 Quantization          B1 HLS Kernel             C1 Petalinux           D1 Verification
A2 Bit-Exact Ref         B2 System Architect       C2 Driver & SDK        D2 CI/CD
                         B3 RTL Tuning (M5+)       C3 Application
```

详见 [`docs/AGENT_PLAYBOOKS/README.md`](docs/AGENT_PLAYBOOKS/README.md)。

---

## 启动一个 sub-agent 的标准方式

```
你是 Agent <ID>（见 docs/AGENT_PLAYBOOKS/<ID>_<name>.md）。
读你的 playbook、ARCHITECTURE.md、以及 CONTRACTS.md 中你涉及的契约，
按 workflow 推进当前里程碑的 deliverable，遵守 acceptance_tests 中的验收命令。
若卡住 / 触发风险，按 playbook 中 risk_handlers 分支处理。
```

每份 playbook 顶部 YAML front-matter 已锁定：
- 输入文件 glob
- 输出文件 glob
- 涉及的契约
- 验收命令
- 当前里程碑

读完一份 playbook 即可独立工作，**无需了解其他 Agent 的内部细节**。

---

## 6 个月里程碑

| 月份 | 截止 | 关键 deliverable |
|---|---|---|
| **M1** | 2026-06-10 | 量化对齐 + NumPy ref 完善 + 首个 HLS 算子 C-sim 通过 |
| **M2** | 2026-07-10 | HLS 全 11 层综合 + Vivado HDMI 彩条 + Petalinux 启动 USB cam |
| **M3** | 2026-08-10 | FPGA 单帧静态图 bit-exact + SDK alpha |
| **M4** | 2026-09-10 | 完整 USB → HDMI pipeline，≥ 10 FPS |
| **M5** | 2026-10-10 | 150 MHz 闭合 + 脉冲跳零 + 25–30 FPS |
| **M6** | 2026-11-10 | **30+ FPS 产品级 + mAP ≤ 1% 下降 + v1.0 tag** |

---

## 目录结构

```
SpikeYOLO/
├── ARCHITECTURE.md, CONTRACTS.md, AGENT_PLAYBOOKS/  ← 文档（本目录是入口）
├── ultralytics/                                     ← PyTorch 训练侧（复用）
├── realtime_detect.py                               ← GPU 端 pipeline 参考
├── models/                                          ← FP32 + INT8 权重
├── tools/
│   ├── fpga/numpy_reference.py                      ← HLS 黄金参考（B1 line-for-line 翻译源）
│   ├── quant/    (A1)   ├── verify/  (A2)
│   ├── ci/       (D2)   └── perf/    (D1)
├── hw/
│   ├── hls/      (B1)   ├── vivado/  (B2)          ├── rtl/  (B3, M5+)
├── sw/
│   ├── petalinux/(C1)   ├── driver/  (C2)
│   ├── sdk/      (C2)   └── app/     (C3)
├── tests/
│   ├── golden/   (A2)   ├── regression/(D1)        └── perf/ (D1)
├── docs/
│   ├── ARCHITECTURE.md      ← 系统总览
│   ├── CONTRACTS.md         ← 6 条接口契约
│   ├── RISK_RULES.yaml      ← 风险路由
│   ├── AGENT_PLAYBOOKS/     ← 10 份 sub-agent 启动包
│   └── reports/             ← D1 月报
└── .github/workflows/       ← 3 个 CI workflow + 风险 dispatcher
```

---

## CI 门禁

| Workflow | 触发 | 责任 Agent |
|---|---|---|
| `numpy_regress.yml` | 每个 PR | A1, A2 |
| `hls_smoke.yml` | hw/ 改动 PR | B1 |
| `board_nightly.yml` | 每天 03:00 UTC | C3, D1 |
| `risk_dispatcher.yml` | 任何 workflow 失败 | D2 |

PR 路径：
- 改 `tools/fpga/` 或 `ultralytics/nn/modules/yolo_spikformer*.py` → 触发 `numpy_regress`
- 改 `hw/hls/` 或 `tools/quant/` → 触发 `numpy_regress` + `hls_smoke`
- 改 `sw/` 或 `hw/vivado/` → CI 不动，等 nightly 板上回归

---

## 如何贡献（每个 Agent）

1. `git checkout -b <agent_id>/<feature>` 例如 `a1/ptq-msemin-calib`
2. 在自己的 owned 目录内推进，遵守 playbook 工作流
3. 跑通本地 acceptance_tests
4. PR 标题：`[<Agent ID>] M<n>: <短描述>`，例如 `[A1] M1: PTQ baseline run`
5. 等 CI 全绿 → 自动通知契约相关 reviewer
6. 风险触发时按 [`docs/RISK_RULES.yaml`](docs/RISK_RULES.yaml) 自动 routing，不要手动绕过

---

## 联系与历史

- 顶层 plan（含详细 gantt / 风险 / 资源预算）：[`.claude/plans/spikeyolo-zynq-7000-zybo-fpga-agent-radiant-unicorn.md`](.claude/plans/spikeyolo-zynq-7000-zybo-fpga-agent-radiant-unicorn.md)
- 契约变更记录：[`docs/CONTRACTS_CHANGELOG.md`](docs/CONTRACTS_CHANGELOG.md)
- 月报：[`docs/reports/`](docs/reports/)（D1 每月自动生成）
