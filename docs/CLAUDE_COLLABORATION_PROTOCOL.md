# Claude ↔ Claude 异步协作协议

> 通过 git repo 实现两台机器上的 Claude Code session 异步通信。

## 角色

| 名称 | 机器 | branch | 职责 |
|---|---|---|---|
| **Main Claude** | 5060 Laptop (主开发机) | `main` | A/C/D 系列 Agent + 训练 + 算法 + 软件 + 调度 |
| **Remote Claude** | Vivado 2024.1 (新机器) | `vivado/synth-runner` | B1/B2 Agent + 综合 + bitstream |

## 通信通道（异步，通过 git）

```
runs/main_machine/          ← Main Claude 写状态/请求 给 Remote Claude
runs/remote_machine/        ← Remote Claude 写状态/回复 给 Main Claude
runs/main_machine/REPLIES_FROM_REMOTE.md     ← Remote 给 Main 的明确回复（被 Main 读）
runs/remote_machine/REPLIES_FROM_MAIN.md     ← Main 给 Remote 的明确回复（被 Remote 读）
```

## 工作流

### Remote Claude 接手时

1. `git pull origin vivado/synth-runner`
2. 读 `docs/REMOTE_CLAUDE_HANDOFF.md`
3. 写 `runs/remote_machine/HANDOFF_ACKNOWLEDGED.md` ACK
4. git commit + push
5. 开始 Step 1

### Remote Claude 完成 Step N

1. 写 `runs/remote_machine/step{N}_{name}_report.md` 按 schema
2. git add 产物 + report
3. git commit + push origin vivado/synth-runner
4. 继续 Step N+1（不等 Main 回复，除非 BLOCKER）

### Remote Claude 撞 Blocker

1. 写 `runs/remote_machine/URGENT_ASK.md`（含错误 trace + 你的判断 + 选项 A/B/C）
2. git commit + push **立即**
3. **停手等回复**
4. 周期 `git pull origin vivado/synth-runner` 看 `REPLIES_FROM_MAIN.md`
5. Main 回复后按指示继续

### Main Claude 同步频率

每完成自己的 sprint，或 user 问"Remote Claude 进度如何"时：
1. `git fetch fork`
2. `git log --oneline fork/vivado/synth-runner ^main | head -20` 看新 commit
3. `git show fork/vivado/synth-runner:runs/remote_machine/HANDOFF_ACKNOWLEDGED.md`
4. `git show fork/vivado/synth-runner:runs/remote_machine/step{N}_*.md` 读 report
5. 如有 URGENT_ASK.md → 优先回复
6. 写 `runs/remote_machine/REPLIES_FROM_MAIN.md`（在 main branch 写然后 cherry-pick 到 vivado/synth-runner，或直接在 vivado/synth-runner branch 写）
7. git push

## Report schema (Remote Claude 必跟)

```markdown
# Step N — <name>

## Status: SUCCESS / FAIL / PARTIAL / BLOCKED
## Wall time: <minutes>
## Started: <ISO 8601>
## Completed: <ISO 8601>

## Commands run
\`\`\`
<verbatim cmd sequence>
\`\`\`

## Outputs
| Path | Size | Note |
|---|---|---|
| hw/hls/build/tiny_fpga_top.xo | 25 MB | LFS |
| hw/hls/reports/utilization.rpt | 8 KB | text |
| ... | ... | ... |

## Key metrics (synth/timing 必填，其他可选)
- DSP: 64 / 220 (29%)
- BRAM36: 12 / 140 (8.6%)
- LUT: 6234 / 53200 (11.7%)
- WNS: +2.341 ns @ 10ns target

## Issues
- 2024.1 deprecated pragma WARN (50 sites) → 入 M2-W2 backlog issue
- (or "none")

## Next step
- Step N+1: <name> (ETA <min>)
- (or "Awaiting Main Claude reply on URGENT_ASK.md")
```

## URGENT_ASK.md schema

```markdown
# Urgent Ask from Remote Claude — <one-line summary>

## Context
- Step: N
- 当前 git HEAD: <hash>
- Wall time so far: <min>

## What happened
<错误 trace 全文 / 异常 stdout 50 行>

## My diagnosis
<你的猜测，最多 3 个 options>

## Options I'm considering
- A: <option> (cost: ..., risk: ...)
- B: <option>
- C: <option>

## What I'm doing while waiting
- (nothing destructive, just polling)

## Awaiting reply by
- 越快越好 / 24h OK
```

## REPLIES_FROM_MAIN.md schema

```markdown
# Replies from Main Claude

## 2026-05-12T15:30 — Reply to URGENT_ASK (timing fail)

Re: WNS = -1.5 ns at step 4. This is R1 risk.

Action: do NOT retry. Write risk_R1_timing.md with top-10 longest paths.
I'll cherry-pick relevant pragma changes on main branch this evening,
merge into vivado/synth-runner, you re-pull and re-run Step 3.

— Main Claude
```

## 冲突避免

| 文件类别 | Main owns | Remote owns | 规则 |
|---|---|---|---|
| `tools/*` | ✅ | ❌ | Remote read-only |
| `sw/*` | ✅ | ❌ | Remote read-only |
| `hw/hls/src/` | ✅（B1 owner） | ❌ | Remote 不改 cpp |
| `hw/hls/build/`, `reports/` | ❌ | ✅ | Main read-only |
| `hw/vivado/build_bd.tcl` | ✅ (B2 owner) | ❌ | Remote 不改 tcl |
| `hw/vivado/out/`, `ip_repo/spike_accel/` | ❌ | ✅ | Main read-only |
| `runs/main_machine/` | ✅ | read-only | Remote 仅 read |
| `runs/remote_machine/` | read-only | ✅ | Main 仅 read |
| `docs/CONTRACTS.md` | ✅ | ❌ | Remote 提议在 docs/CONTRACTS_proposed_*.md |
| `docs/AGENT_PLAYBOOKS/B*.md` | ❌ | ✅（status/owner only） | Both read-only on body |
| `docs/AGENT_PLAYBOOKS/{A,C,D}*.md` | ✅ | ❌ | Remote read-only |
| `.github/workflows/` | ✅ (D2 owner) | ❌ | Remote 不动 CI |
| `.gitattributes`, `.gitignore` | ✅ | ❌ | Main 决定 |

## 合并周期

- M2-W1 起每周一 Main Claude 跑 `git merge vivado/synth-runner` 到 main
- Conflict 通常发生在 `docs/reports/M{n}_report.md`（双方都更新）→ 文本级手动 merge
- 综合产物（.xo, .bit）单向 vivado/synth-runner → main，无冲突

## 关闭周期

- M3 W1 起远程机器跑 self-hosted runner，CI 自动化 → 这份 protocol 退役
- 在那之前所有交接走 git 异步
