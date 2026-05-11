---
id: D2
name: ci_cd
group: D
milestones: [M1, M2, M3, M4, M5, M6]
inputs_glob:
  - "tests/**"
  - "tools/ci/**"
outputs_glob:
  - ".github/workflows/**"
  - "tools/ci/**"
  - "docs/CONTRACTS_CHANGELOG.md"
contracts:
  produces: []
  consumes: []
acceptance_tests:
  - "yamllint .github/workflows/"
  - "gh workflow run numpy_regress.yml --ref main"
  - "gh run list --workflow=board_nightly.yml --limit 7"   # 最近 7 天 nightly 健康度
status: in_progress
owner: "D2-session-2026-05-11"
---

# D2 CI/CD Agent Playbook

## Mission

建立并维护 GitHub Actions 自动化流水线，**强制 PR 门禁**保证算法、HLS、板上
回归三层防线，以及 nightly 板上回归告警。让人不必盯进度，CI 替团队跑监督。

## 关键技术决策

| 维度 | 选择 | 理由 |
|---|---|---|
| CI 平台 | GitHub Actions | 团队熟悉 + 与 PR 流程集成 |
| 板上测试 | self-hosted runner（连 ZYBO 的 PC） | GitHub-hosted 无法访问硬件 |
| HLS 综合 | 跳过完整综合，只跑 csim/cosim | 综合慢且需要 Vivado license |
| nightly | 每天凌晨 3 点跑完整 board 回归 | 与 PR 检查分开，不阻塞 dev |
| 失败响应 | 自动开 issue + at 对应 Agent | 替代会议沟通 |

## 工作流

### Workflow 1: numpy_regress.yml（每 PR 必跑）

```yaml
name: NumPy Bit-Exact Regression
on: [pull_request, push]
jobs:
  test:
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v4
        with: { lfs: true }    # tests/golden/*.npz 用 LFS
      - uses: actions/setup-python@v5
        with: { python-version: "3.10" }
      - run: pip install -r requirements.txt
      - run: pytest tests/test_bit_exact.py -v --junit-xml=junit.xml
      - run: pytest tests/test_weight_pack.py -v
      - run: pytest tests/test_address_map.py -v
      - uses: actions/upload-artifact@v4
        if: failure()
        with: { name: junit-numpy, path: junit.xml }
```

### Workflow 2: hls_smoke.yml（PR 触发 hw/ 改动）

```yaml
name: HLS Smoke
on:
  pull_request:
    paths: ["hw/hls/**", "tools/quant/**", "tools/verify/**", "tests/golden/**"]
jobs:
  csim:
    runs-on: [self-hosted, vivado]    # 需要 Vitis HLS license
    steps:
      - uses: actions/checkout@v4
        with: { lfs: true }
      - run: |
          source /opt/Xilinx/Vitis_HLS/2023.2/settings64.sh
          cd hw/hls && vitis_hls -f run_csim.tcl
      - run: python tools/verify/numpy_vs_hls.py --all-layers
      - uses: actions/upload-artifact@v4
        if: failure()
        with: { name: hls-reports, path: hw/hls/reports/ }
```

### Workflow 3: board_nightly.yml（每天 03:00 UTC）

```yaml
name: Board Nightly Regression
on:
  schedule:
    - cron: "0 3 * * *"
  workflow_dispatch:
jobs:
  board_test:
    runs-on: [self-hosted, zybo]    # PC 连 ZYBO 的机器
    steps:
      - uses: actions/checkout@v4
      - run: bash scripts/wake_board.sh           # 远程上电
      - run: bash tests/regression/run_full.sh --full
      - run: python tools/perf/fps_bench.py --board zybo --duration 300 --min-fps 30
      - run: python tests/regression/coco_val_on_board.py --board zybo --pass-rate 0.95
      - name: Upload reports
        if: always()
        uses: actions/upload-artifact@v4
        with: { name: nightly-${{ github.run_id }}, path: runs/ }
      - name: Open issue on failure
        if: failure()
        run: |
          gh issue create \
            --title "[nightly] Board regression failed run #${{ github.run_id }}" \
            --label "risk:R3,risk:R5" \
            --body-file runs/regression_latest/summary.md \
            --assignee @c3,@d1
```

### 公用工具脚本 `tools/ci/`

| 脚本 | 用途 |
|---|---|
| `run_hls_csim.sh` | 封装 Vitis HLS csim 调用 |
| `scp_to_board.py` | 把 SDK / app / weights 同步到板子 |
| `gen_dts.py` | 从 address_map.yaml 生成 uio_config.dts |
| `check_timing.py` | 解析 timing_summary.rpt 提取 WNS |
| `check_utilization.py` | 解析 utilization.rpt 验证资源预算 |
| `check_resource_budget.py` | 综合多项 budget 检查 |
| `gen_milestone_report.py` | 月报生成器（D1 共用） |
| `dispatch_risk_issue.py` | 触发风险时自动开 issue |

## 自动风险路由

```yaml
# .github/workflows/risk_dispatcher.yml
# 当任何 workflow 失败，根据失败模式打 risk:R<n> 标签
on:
  workflow_run:
    workflows: ["NumPy Bit-Exact Regression", "HLS Smoke", "Board Nightly"]
    types: [completed]
jobs:
  classify:
    if: ${{ github.event.workflow_run.conclusion == 'failure' }}
    runs-on: ubuntu-22.04
    steps:
      - run: python tools/ci/dispatch_risk_issue.py \
              --workflow-run ${{ github.event.workflow_run.id }} \
              --rule-set docs/RISK_RULES.yaml
```

`docs/RISK_RULES.yaml`：

```yaml
- match: "timing_summary.*WNS.*-"
  risk: R1
  assignee: [B1, B2, B3]
- match: "utilization.*>= 90%"
  risk: R2
  assignee: [B1]
- match: "fps_mean < 30"
  risk: R3
  assignee: [B2, C3]
- match: "mAP diff > 1.0"
  risk: R4
  assignee: [A1, A2]
- match: "USB.*dropped > 5"
  risk: R5
  assignee: [C1, C3]
- match: "cosim.*fail"
  risk: R6
  assignee: [B1, A2]
- match: "video0.*not found"
  risk: R7
  assignee: [C1]
```

## 关键文件

| 文件 | 用途 | 状态 |
|---|---|---|
| `.github/workflows/numpy_regress.yml` | PR 算法回归 | 新建 |
| `.github/workflows/hls_smoke.yml` | PR HLS 冒烟 | 新建 |
| `.github/workflows/board_nightly.yml` | 每日板上回归 | 新建 |
| `.github/workflows/risk_dispatcher.yml` | 失败自动 issue | 新建 |
| `docs/RISK_RULES.yaml` | 风险路由规则 | 新建 |
| `tools/ci/*.py` | 公用脚本 | 新建 |
| `docs/CONTRACTS_CHANGELOG.md` | 契约变更记录 | 新建 |
| `scripts/wake_board.sh` | 远程板子上电 | 新建 |

## Risk Handlers

| 风险 | 触发 | 处理 |
|---|---|---|
| **self-hosted runner 离线** | nightly 一直 queued | (a) 检查 runner 健康; (b) 改用人工触发; (c) 联系硬件管理员 |
| **HLS license 用尽** | hls_smoke fail with "license error" | (a) 配 license queue 排队; (b) 限制并发 1 |
| **LFS quota 超** | git LFS 拉不下来 | (a) 黄金张量分仓; (b) 压缩 .npz |

## 验收清单

✅ 3 个 workflow 都能成功跑一次  
✅ PR 路径合理（修 hw/hls/ 触发 hls_smoke，修 tools/quant/ 触发 numpy_regress）  
✅ nightly 7 天连续 success ≥ 5 天  
✅ 风险路由测试：人为引入失败，验证 issue 自动开 + 标签正确

## 参考资料

- GitHub Actions 文档
- self-hosted runner 部署指南
- Vitis HLS license 配置
