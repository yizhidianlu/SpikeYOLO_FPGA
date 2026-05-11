# Agent Playbook 索引

每个 Playbook 是一个 Claude Code sub-agent 的**自治启动包**。读完一份 playbook
即可独立工作，无需了解其他 Agent 的内部细节，只通过 [`CONTRACTS.md`](../CONTRACTS.md)
中的契约与上下游 hand off。

## 启动 sub-agent 的标准方式

```
你是 Agent <ID>（见 docs/AGENT_PLAYBOOKS/<ID>_<name>.md）。
阅读你的 playbook、ARCHITECTURE.md、CONTRACTS.md 中你涉及的契约，
按 workflow 推进当前里程碑的 deliverable，遵守 acceptance_tests 中的验收命令。
若卡住 / 触发风险，按 playbook 中 risk_handlers 分支处理。
```

## Playbook 列表

| ID | 文件 | Group | 当前里程碑 |
|---|---|---|---|
| **A1** | [`A1_quantization.md`](A1_quantization.md) | A. 模型与精度 | M1 |
| **A2** | [`A2_bit_exact_reference.md`](A2_bit_exact_reference.md) | A. 模型与精度 | M1 |
| **B1** | [`B1_hls_kernel.md`](B1_hls_kernel.md) | B. 硬件加速 | M1–M5 |
| **B2** | [`B2_system_architect.md`](B2_system_architect.md) | B. 硬件加速 | M2–M5 |
| **B3** | [`B3_rtl_tuning.md`](B3_rtl_tuning.md) | B. 硬件加速 | M5 |
| **C1** | [`C1_petalinux.md`](C1_petalinux.md) | C. 系统软件 | M2 |
| **C2** | [`C2_driver_sdk.md`](C2_driver_sdk.md) | C. 系统软件 | M3 |
| **C3** | [`C3_application.md`](C3_application.md) | C. 系统软件 | M4–M6 |
| **D1** | [`D1_verification.md`](D1_verification.md) | D. 验证集成 | M1–M6 |
| **D2** | [`D2_ci_cd.md`](D2_ci_cd.md) | D. 验证集成 | M1 |

## Playbook 通用 schema

每份 playbook 顶部有 YAML front-matter，机器可解析：

```yaml
---
id: A1
name: quantization
group: A
milestones: [M1, M5]                # 本 Agent 活跃的里程碑
inputs_glob:                         # 我读什么
  - "models/SpikeYOLO_*.pt"
  - "ultralytics/cfg/models/v8/snn_yolov8_tiny_fpga.yaml"
outputs_glob:                        # 我写什么
  - "tools/quant/**/*.py"
  - "models/tiny_fpga_int8.{npz,bin}"
contracts:                           # 我参与的契约
  produces: [C1]
  consumes: []
acceptance_tests:                    # 验收命令
  - "pytest tests/test_weight_pack.py"
  - "python tools/quant/eval_quant_map.py --target 1.0"
status: pending                      # pending | in_progress | completed
owner: ""                            # 待具体 Claude session 认领
---
```

## 并发与依赖

```
M1                M2                M3                M4                M5                M6
--                --                --                --                --                --
A1 (PTQ+pack)
A2 (golden ext)
B1 (HLS L0,L1) -> B1 (全 11 层) -> B1 (PE 阵列扩展) -> B1 (跳零优化)
                   B2 (BD+HDMI) -> B2 (实现 100MHz) -> B2 (150MHz)
                   C1 (镜像)    -> C2 (SDK alpha)  -> C3 (10 FPS)  -> C3 (25-30 FPS) -> C3 (30+ FPS)
                                                                       B3 (SV 优化)
D1, D2 横切，月末自动出报告
```

## 通用工作流（所有 Agent 共用）

1. **每天开始**：`git pull`，看 `docs/reports/M<current>_report.md` 是否有自己的红字
2. **按 playbook workflow 推进**当前 milestone 的 deliverable
3. **每完成一个文件**：跑对应 acceptance_test，本地 pass 后 push PR
4. **PR 标题**：`[<Agent ID>] M<n>: <短描述>`，例如 `[A1] M1: PTQ baseline run`
5. **遇到风险**：检查 plan 的 R1-R7 列表，按对应 risk_handler 分支
6. **里程碑末**：D1 跑 `tests/regression/run_full.sh`，结果进 `docs/reports/M<n>_report.md`

## 沟通规则

- **不开会**：所有跨 Agent 沟通用 GitHub PR review 评论 + issue
- **不口头约定契约**：契约变更必走 [`CONTRACTS.md`](../CONTRACTS.md) PR
- **失败明示**：跑挂的测试不要绕过，挂着到 `risk:R<n>` issue 里
