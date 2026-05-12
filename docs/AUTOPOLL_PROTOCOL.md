# Claude ↔ Claude 自动 Polling 协议（去人工中转）

> 双边 Claude Code session 用 `/loop` skill 周期 git fetch + 自动检测对方新消息 + 自动响应。**用户只需启动两个 loop，后续完全自动**。

## 启动方式（最后一次手动操作）

### 主开发机（5060 Laptop）— 此 Claude session

用户在 Main Claude session 里输入：

```
/loop 3m
```

然后 Claude 会问你 loop 任务是什么。**复制粘贴下面的任务描述**：

````
你是 Main Claude (Algorithm-Trainer, 主开发机)。任务：自动 polling 远程 Claude 进度。

每次唤醒按下面 7 步做：

1. `cd C:\Users\jielu\Desktop\Project\SpikeYOLO`
2. `git fetch fork 2>&1 | tail -2` — 拉远程最新
3. `git log --oneline fork/vivado/synth-runner ^main 2>&1 | head -10` — 看 Remote 新 commit
4. 如有**新 URGENT_ASK_N.md** (N > 你上次回应的):
   - `git show fork/vivado/synth-runner:runs/remote_machine/URGENT_ASK_N.md` 完整读
   - 设计 fix（按 4-Agent owns 矩阵：仅可改 main 拥有的 tools/sw/hw/hls/src 等）
   - 切到 vivado/synth-runner branch：`git checkout vivado/synth-runner && git stash && git pull --rebase fork vivado/synth-runner && git stash pop`
   - apply fix 到对应文件
   - 在 `runs/remote_machine/REPLIES_FROM_MAIN.md` 末尾 append 一段（含 timestamp + URGENT_ASK_N 编号 + patch 内容 + 接下来）
   - `git add` patched 文件 + REPLIES → `git commit -m "fix(...): respond to URGENT_ASK_N"`
   - `git push fork vivado/synth-runner`
   - 切回 main: `git checkout main`
5. 如**Remote 推了 stepN_*_report.md (N=1..6)** 完成某 step:
   - 读报告关键 metric（DSP/BRAM/LUT/WNS for synth；PASS count for csim）
   - 如全 PASS → 不响应，等下一个 wakeup
   - 如触发 R1 (WNS<0) / R2 (resource over) → 设计 fix（同步 4 above）
6. 如**Remote 推了 step6 final report**（all done）：
   - 总结 .xo + .bit 产物 + utilization + timing
   - 写 `runs/main_machine/M2_W1_synth_complete.md` 总结
   - `git add` + `git commit` + `git push`
   - 退出 loop（说 "Step 6 complete, stopping loop"）
7. 同时**周期 check 本机 A1 W8 训练 + COCO 下载**：
   - `bash tools/ci/check_distill_progress.sh 2>&1 | head -10`
   - `bash tools/ci/check_download_progress.sh 2>&1 | head -10`
   - 如训练完成 → 起 W9 PTQ+eval agent
   - 如下载完成 → 通知 user 切真训到 train2017

每次唤醒**简短报告**（≤ 100 字）：当前 git HEAD + 远程是否有新 commit + 你做了啥。
````

启动后 Main Claude 每 3 min 自动跑这些事。**你（user）不用再手动复制粘贴消息给两边**，可以离开。

### 远程机器（Vivado 2024.1）— Remote Claude session

在远程机器的 Claude Code session 里输入：

```
/loop 3m
```

任务描述（**复制粘贴**）：

````
你是 Remote Claude (Vivado-Runner, B1+B2 runner)。任务：自动 polling + 推进 Step 1-6。

每次唤醒按下面 8 步做：

1. `cd C:\Users\jielu\Desktop\Workspace\SpikeYOLO_FPGA`
2. `git fetch origin 2>&1 | tail -2`
3. `git log --oneline origin/vivado/synth-runner ^HEAD 2>&1 | head -5` — 看 Main 推了啥
4. 如有新 commit:
   - `git pull origin vivado/synth-runner` （fast-forward）
   - 读 `runs/remote_machine/REPLIES_FROM_MAIN.md` **末段**（你上次没读过的）
   - 看 Main 是否给了 fix / 指令
5. **当前 step 状态**：用 `cat runs/remote_machine/.current_step 2>/dev/null` 看。如不存在 → step=1。
6. **如当前 step 已完成**（已写 stepN_report.md）→ 推进到下一步：
   - Step 1 csim → done (10/10 PASS at 0b3df61)
   - Step 2 cosim → skipped (Main agreed)
   - Step 3 synth → blocked by URGENT_ASK_3 → 等 Main fix
   - Step 4 resource gate → 等 Step 3 .xo
   - Step 5 Vivado BD + bitstream → 等 Step 3 .xo
   - Step 6 git push final → 等 Step 5 .bit
   每完成一步写 `step{N}_*_report.md` + `git add -A runs/remote_machine/` + commit + push
7. **如 step 跑中（vitis_hls 在后台跑）**：
   - check vitis_hls 后台 process 状态：`Get-Job` (PowerShell) 或 stdout log tail
   - 如还在跑：写 wakeup 报告 "step N still running, ETA ..." 然后退出本次 loop
   - 如刚跑完：解析 result → 写 stepN_report.md → push → 推进下一步
8. **撞 blocker**:
   - 写 `runs/remote_machine/URGENT_ASK_{N+1}.md` (递增编号)
   - `git add runs/remote_machine/URGENT_ASK_N.md` (因 .gitignore 已 fix，不用 -f)
   - commit + push
   - 退出 loop 当前 wakeup（等 Main 回复 REPLIES）

每次唤醒**简短报告**（≤ 100 字）：当前 step + 进度 + push 了啥。

特殊触发：
- 如 Step 6 完成 → 不再 push，退出 loop "M2-W1 synth pipeline complete"
- 如同一 blocker 你写了 2 个 URGENT_ASK 且 Main 没回 → 停 loop 等用户介入
````

启动后 Remote Claude 每 3 min 自动检 Main 回复 + 跑下一 step + 撞墙写 URGENT_ASK。

## 工作流示意

```
Time    Main Claude              fork repo            Remote Claude
─────   ─────────────            ────────             ─────────────
T+0     (loop start)             commit X (Main fix)  (loop start)
T+0     git push                 ───────────────►     
T+3     poll: nothing new                             poll: see commit X
                                                      git pull
                                                      apply fix → run Step
                                 ◄──── commit Y       git push (step done)
T+6     poll: see commit Y       
        read step report
        no action needed         
T+9     poll: nothing new                             poll: continue Step
                                                      撞 blocker
                                                      write URGENT_ASK_N
                                 ◄──── commit Z       git push
T+12    poll: see commit Z       
        read URGENT_ASK_N        
        design fix
        commit + push            ──── commit W ────►  
T+15                                                  poll: see commit W
                                                      git pull
                                                      apply Main fix
                                                      retry step
```

## 边界 — 不会出错的安全网

| 风险 | 防护 |
|---|---|
| Main 死循环改文件 | 每次只 fix 在响应新 URGENT_ASK 时；非新 URGENT_ASK 不动 |
| Remote 撞同一 bug 2 次 | URGENT_ASK 编号递增；同名 ask 写 2 次 → stop loop |
| 两边同时写同一文件 | Main only writes `hw/`, `tools/`, `runs/main_machine/`; Remote only writes `hw/build/`, `hw/vivado/out/`, `runs/remote_machine/` (per ownership matrix) |
| Push 冲突 | `git pull --rebase` 自动处理；冲突时 stop loop 等用户 |
| 训练崩 | check_distill_progress.sh 检测 → Main 不修训练（不是 loop owner），仅通知 user |
| 无限 loop | 每次唤醒 ≤ 100 字报告；user 看到无效循环可 Ctrl+C 停 loop |

## 停止 loop

任一边输入：

```
/loop stop
```

或者按 Ctrl+C 中断。

## 终态 — Step 6 完成自动停

Remote Claude 写 `step6_final_report.md` + push 后**自动退出 loop**。Main Claude 检测到 step6 commit → 写 `runs/main_machine/M2_W1_synth_complete.md` 总结 → **自动退出 loop**。

完成后 user 在两边各看到 "loop stopped, M2-W1 done" 通知。

— Main Claude (主开发机, 2026-05-12T16:30)
