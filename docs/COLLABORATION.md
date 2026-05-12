# 跨机器协作分支策略

M1 W8 起 SpikeYOLO 同时跑在两台 Windows 11 机器上：主开发机做算法 / 软件，
新机器装 Vivado 2024.1 + Vitis HLS 2024.1 做综合 / BD。本文锁定分支
约定，避免改动碰撞。

## 角色与机器

| 机器 | OS | 作用 | owns |
|---|---|---|---|
| 主开发机 (5060 Laptop) | Win 11 | A1/A2/C/D 算法 + 软件 + CI | `tools/`, `models/`, `sw/`, `runs/`, `tests/`, `docs/AGENT_PLAYBOOKS/{A,C,D}*` |
| Vivado runner (新机器) | Win 11 + Vivado 2024.1 + Vitis HLS 2024.1 | B1 / B2 综合 + BD + bitstream | `hw/`, `hw/hls/build/`, `hw/vivado/out/`, `*.xo`, `*.bit`, `*.hwh`, `docs/AGENT_PLAYBOOKS/B*` |

## 分支

| 分支 | 主推机器 | 内容 | 合并节奏 |
|---|---|---|---|
| `main` | 主开发机 | 全工程 source-of-truth | 是合并目标 |
| `vivado/synth-runner` | Vivado runner | 综合产物 + B1/B2 hw/ 改动 | 每周一 / M2-W1 起每周 PR → main |
| `vivado/<sprint-tag>` *(可选)* | Vivado runner | 单次 sprint 实验 | 该 sprint 结束 squash 进 vivado/synth-runner |

## 工作流

### 主开发机

```bash
# 日常算法/软件
git checkout main
# ... 改 tools/ sw/ tests/ docs/
git push origin main

# 周期同步综合产物
git pull origin vivado/synth-runner -X theirs       # hw/ 冲突偏向 runner
# ... 评估新 .xo / utilization.rpt / timing.csv
```

### Vivado runner

```bash
# 每个 sprint 第一步
git checkout vivado/synth-runner
git pull origin main                                # 同步主开发机改动
# (例如 B1 改了 op_macros.h、A1 出了新权重)

# ... 跑 B1/B2 8 步 (见 docs/REMOTE_VIVADO_ONBOARDING.md)

git add hw/hls/build/*.xo \
        hw/hls/reports/ \
        hw/vivado/out/system.bit \
        hw/vivado/out/system.hwh \
        hw/vivado/out/address_map.yaml \
        hw/vivado/reports/
git commit -m "feat: B1+B2 sprint <date> — first real synth"
git push origin vivado/synth-runner
```

## Conflict 策略

| 文件域 | 主开发机修改 | Vivado runner 修改 |
|---|---|---|
| `tools/`, `models/`, `sw/`, `runs/`, `tests/` | 直 push main | **不应**修改；如需改，发 PR 到 main |
| `hw/hls/src/`, `hw/hls/include/`, `hw/hls/sim/` | 偶尔 (B1 共写) | 主推 |
| `hw/hls/build/`, `hw/vivado/out/`, `hw/vivado/reports/` | **绝不修改** | 主推 (LFS 走) |
| `hw/vivado/build_bd.tcl`, `build_bitstream.tcl`, `scripts/` | **绝不修改** | 主推 |
| `docs/AGENT_PLAYBOOKS/A,C,D*` | 主推 | **绝不修改** |
| `docs/AGENT_PLAYBOOKS/B*`, `docs/decisions/000{1,3,4,5}*` | 偶尔 (D1 月报) | 主推 |
| `docs/CONTRACTS.md`, `CONTRACTS_CHANGELOG.md` | 任一方 → PR | 任一方 → PR |
| `.github/workflows/`, `tools/ci/` | 主推 (D2) | 偶尔 (B 改 self-hosted runner label) |
| `.gitignore`, `.gitattributes` | 任一方 → PR | 任一方 → PR |

任一方改对方 owned 文件 → **不直接 push**，先开 PR review。

## CI 配合

D2 三个 workflow（`numpy_regress.yml` 主开发机 GitHub-hosted、`hls_smoke.yml`
Vivado runner self-hosted、`board_nightly.yml` ZYBO 板子接入后）已经在
`actions/checkout@v4` 启用 `lfs: true`，新分支 push 后自动跑：

- main 推送 → numpy_regress + hls_smoke (host_csim tier)
- vivado/synth-runner 推送 → numpy_regress (forward-compat) + hls_smoke
  (full Vitis tier，self-hosted runner)
- 周一 03:00 UTC → board_nightly (M3 后)

## Sub-Agent session 规则

- A1 / A2 / C / D session 在主开发机起，**绝不**操作 Vivado runner 上的 hw/ 输出
- B1 / B2 session 在 Vivado runner 起；如临时在主开发机 prep（比如改 .cpp
  source 但不跑 vitis_hls），改完 push 到 main，由 Vivado runner pull 后真综合

## References

- `docs/REMOTE_VIVADO_ONBOARDING.md` — Vivado runner 5 分钟动手
- `docs/GIT_LFS_SETUP.md` — 综合产物的 LFS 流转
- `docs/decisions/0005_vivado_2024_1_bump.md` — 2024.1 bump 兼容性 review
- `docs/SELFHOSTED_RUNNER_SETUP.md` — GitHub Actions self-hosted runner (M2-W1+)
