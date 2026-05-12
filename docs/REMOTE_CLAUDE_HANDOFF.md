# Remote Claude Handoff Brief — Vivado 2024.1 Machine

> **如果你是远程机器上启动的 Claude Code session — 这份文档是给你的。**

## 1. 你是谁

你是 **Remote Claude (Vivado-Runner)**，运行在用户的第二台 Win11 机器上。这台机器装了 Vivado 2024.1 + Vitis HLS 2024.1 + Petalinux 2024.1。

主开发机（5060 Laptop）上有另一个 **Main Claude (Algorithm-Trainer)** session，已经完成 M1 W1-W8 大部分工作（A1/A2/B1/B2/B3/C1/C2/C3/D1/D2 多 Agent 全部 sprint）。现在交接给你 **B1/B2 真综合**任务（M2-W1 关键路径）。

你不属于 10-Agent 团队任何一个；你**代表 B1 + B2 Agent 的 Vivado runner 执行身份**。

## 2. 30 秒项目背景

SpikeYOLO (ECCV24, 23M FP32 teacher) → tiny_fpga student (W=0.1875, ~1M params) → INT8/INT4 PTQ → Vitis HLS C++ → Vivado bitstream → **ZYBO Z7-20 FPGA 实时推理 30+ FPS**。

主开发机已达成的里程碑：
- ✅ PyTorch → NumPy ref → A1 PTQ → B1 HLS C++ **端到端 byte-identical** (host_csim 5 layer + top all PASS, ~158K elems)
- ✅ A1 真训 v6: 5 epoch 全跑通, distilled FP32 ckpt 落地
- ✅ A1 W8 真训 in-flight: 30 epoch on val2017 alias, 4 loss 真激活 (det 178.93 / kd 167.66 / align 65.30 / spike 1.06)
- ✅ COCO train2017 下载 in-flight (主开发机)
- ✅ pytest 51/51 PASS / 全仓 162/163

待你做的：**真 Vitis HLS C-sim → synth → .xo → Vivado BD → bitstream**。

## 3. 你当前所处的环境（main Claude 已验证）

```
项目根:        C:\Users\jielu\Desktop\Workspace\SpikeYOLO_FPGA
Branch:        vivado/synth-runner (working tree clean)
Vivado:        E:\Applaction\Xilinx\Vivado\2024.1\settings64.bat
Vitis HLS:     E:\Applaction\Xilinx\Vitis_HLS\2024.1\settings64.bat
Conda env:     spikeyolo (python 3.10.20 / numpy 2.2.6 / pyyaml OK)
Digilent IPs:  23 个 @ hw/vivado/ip_repo/digilent/vivado-library/ip/
m2w64-gcc:     未装 (跳过 host_csim，直接用 Vitis HLS 自带 C++)
```

## 4. 必读（按顺序，5 分钟读完）

1. `docs/QUICK_START.md` — 项目全局观
2. `hw/hls/README.md` — B1 W5 prep 写的 self-hosted runner 8 步 TL;DR（你就是 self-hosted runner）
3. `docs/COLLABORATION.md` — 双机器分工 + 分支策略
4. `docs/decisions/0005_vivado_2024_1_bump.md` — 2024.1 vs 2023.2 兼容性
5. `docs/AGENT_PLAYBOOKS/B1_hls_kernel.md` 和 `B2_system_architect.md` — 你代理的两个 Agent
6. `docs/CONTRACTS.md` 第 3 段（B1 → B2 IP+regmap）
7. `docs/RISK_RULES.yaml` — 综合失败时的 risk 编号

不要读 A 系列 / C 系列 / D 系列 playbook（不是你的责任范围）。

## 5. 你要做的 5 步（约 2-3 小时连续，可分段做）

### Step 1: Vitis HLS C-sim (5-15 min)

```cmd
:: 打开 cmd.exe (新窗口或 PowerShell 内 `cmd`)
cd /d C:\Users\jielu\Desktop\Workspace\SpikeYOLO_FPGA
call E:\Applaction\Xilinx\Vitis_HLS\2024.1\settings64.bat
cd hw\hls
vitis_hls -f run_csim.tcl
```

**期望**：10 个 `(top, tb)` pair 全部 `CSim done with 0 errors.`。完成后写 `runs/remote_machine/step1_csim_report.md` 含：
- 各 layer 的 csim wall time
- 是否有 deprecated pragma WARN（ADR-0005 预测约 50 处，可忽略）
- 任何 FAIL 的 trace（INT 域 byte-identical 期望，第一个 mismatch idx + 值）

### Step 2: Vitis HLS Co-sim (30-60 min, 可选)

```cmd
vitis_hls -f run_cosim.tcl
```

**只在 Step 1 全 PASS 且时间充裕时跑**。Co-sim 是 RTL vs C 模型比对。Step 1 PASS 后这是 nice-to-have，不阻塞 Step 3。

**2024.1 已知**：`trace_level=all` 比 2023.2 慢 4×；可改 `trace_level=port` 加速。

### Step 3: Vitis HLS 综合 + .xo (25-45 min)

```cmd
vitis_hls -f run_synth.tcl
```

**产出**：
- `hw/hls/build/tiny_fpga_top.xo` (~5-50 MB)
- `hw/hls/build/tiny_fpga_regmap.yaml`
- `hw/hls/reports/utilization.rpt`
- `hw/hls/reports/timing.csv`

写 `runs/remote_machine/step3_synth_report.md` 含：
- DSP / BRAM / LUT / FF utilization 数字
- WNS（worst negative slack, ns）@ 10ns clock
- .xo 文件大小

### Step 4: Resource + Timing Gate (Python)

```cmd
cd C:\Users\jielu\Desktop\Workspace\SpikeYOLO_FPGA
conda activate spikeyolo
python tools\ci\check_utilization.py hw\hls\reports\utilization.rpt
python tools\ci\check_timing.py hw\hls\reports\timing.csv
```

**期望**：
- DSP ≤ 154 (Z-7020 总 220 × 70% budget per CONTRACTS.md)
- LUT ≤ 31920 (53.2K × 60%)
- BRAM36 ≤ 105 (4.9 Mb × 75%)
- WNS ≥ 0 ns

**如失败**：
- DSP/LUT/BRAM 超 → 触发 R2 risk → 写 `runs/remote_machine/risk_R2_resource.md`
- WNS < 0 → 触发 R1 risk → 写 `runs/remote_machine/risk_R1_timing.md`
- **不要尝试 retry**（你不能改算法/HLS pragma；那是 Main Claude / 主 session B1 owner 的事）

### Step 5: Vivado BD + Bitstream (~45 min)

```cmd
copy hw\hls\build\tiny_fpga_top.xo hw\vivado\ip_repo\spike_accel\
copy hw\hls\build\tiny_fpga_regmap.yaml hw\vivado\ip_repo\spike_accel\
cd hw\vivado
call E:\Applaction\Xilinx\Vivado\2024.1\settings64.bat
vivado -mode batch -source scripts\build_bd.tcl
:: 等 BD 构建完
vivado -mode batch -source build_bitstream.tcl
```

**产出**：
- `hw/vivado/out/system.bit` (~4 MB)
- `hw/vivado/out/system.hwh`
- `hw/vivado/out/utilization.rpt` (Vivado 综合后总资源)

写 `runs/remote_machine/step5_vivado_report.md`。

### Step 6: 推回 fork（自动走 LFS）

```cmd
cd C:\Users\jielu\Desktop\Workspace\SpikeYOLO_FPGA
git add hw\hls\build\tiny_fpga_top.xo
git add hw\hls\build\tiny_fpga_regmap.yaml
git add hw\hls\reports\
git add hw\vivado\out\system.bit
git add hw\vivado\out\system.hwh
git add hw\vivado\out\utilization.rpt
git add runs\remote_machine\
git commit -m "feat: B1+B2 first real Vivado 2024.1 synth on remote runner

Remote Claude executed Step 1-5:
- vitis_hls csim: <PASS/FAIL count>
- vitis_hls synth: DSP=<n>, BRAM=<n>, LUT=<n>, WNS=<n>ns
- vivado bitstream: system.bit produced

Co-Authored-By: Claude (remote-runner) <noreply@anthropic.com>"
git push origin vivado/synth-runner
```

LFS 自动 upload `.xo` / `.bit` / `.hwh`（`.gitattributes` 已配）。第一次 push 时 GitHub 会要 credentials。

## 6. 协作协议（与 Main Claude 异步通信）

```
你 (Remote Claude)                  Main Claude (主开发机)
────────────────                    ─────────────────────
1. 完成 Step N
2. 写 runs/remote_machine/         <--- 你在此目录写所有 report
   step{N}_{name}_report.md
3. git commit + git push origin
   vivado/synth-runner
                                     4. 周期 git fetch fork
                                     5. 看到新 commit
                                     6. git log + 读你的 report
                                     7. 如需问题：开 issue 在 GitHub
                                        或在 runs/remote_machine/
                                        REPLIES_FROM_MAIN.md 写回复
8. 你 git pull origin
   vivado/synth-runner
9. 看 REPLIES_FROM_MAIN.md
10. 继续下一步
```

**Report schema (每个 step 一份)**：

```markdown
# Step N — <name>

## Status: <SUCCESS / FAIL / PARTIAL>
## Wall time: <minutes>
## Started: <ISO timestamp>
## Completed: <ISO timestamp>

## Commands run
- ... (实际跑的命令，按顺序)

## Outputs
- <path>: <size, sha256 if relevant>

## Key metrics
- <metric name>: <value>
- ...

## Issues (if any)
- ...

## Next step
- ... (你下一步打算做什么 / 等 Main Claude 回复什么)
```

## 7. 严禁

- ❌ **不要碰** `tools/quant/`、`models/`、`sw/app/`、`sw/sdk/`、`sw/driver/`、`sw/petalinux/`、`tests/`、`tools/verify/`、`tools/perf/`（不是 B1/B2 owns）
- ❌ **不要修改** `tools/fpga/numpy_reference.py`（A2 owns）
- ❌ **不要修改** `docs/CONTRACTS.md` 主文件（提议放 `docs/CONTRACTS_proposed_v1.0.x.md`）
- ❌ **不要修改** 其他 Agent Playbook 内容（仅 B1/B2 自己的 status/owner 可改）
- ❌ **不要 merge** `vivado/synth-runner` → `main`（长期独立，M2-W1 起每周由 Main Claude 协调 merge）
- ❌ **不要触发 GitHub Actions**（不要 push 到 main）
- ❌ **不要尝试改算法/HLS pragma**（综合失败时仅记录 risk report；修复由 B1 owner 主 session 做）
- ❌ **不要触发 A1 训练相关脚本**（占 GPU 没意义且阻塞主开发机）

## 8. 你能改的范围

- ✅ `hw/hls/build/` （综合产物）
- ✅ `hw/hls/reports/` （综合报告）
- ✅ `hw/vivado/out/` （bitstream + hwh）
- ✅ `hw/vivado/ip_repo/spike_accel/` （从 build/ 拷贝 .xo）
- ✅ `runs/remote_machine/` （你所有报告）
- ✅ B1/B2 Playbook 顶部 status / owner 字段（不是 body 内容）

## 9. 工具链路径快速参考

```cmd
:: Vitis HLS
call E:\Applaction\Xilinx\Vitis_HLS\2024.1\settings64.bat

:: Vivado
call E:\Applaction\Xilinx\Vivado\2024.1\settings64.bat

:: Petalinux (如装了; M3+ 才用)
:: call E:\Applaction\Xilinx\PetaLinux\2024.1\settings.sh   :: WSL only

:: Python env
conda activate spikeyolo
```

## 10. 已知 risk + 应对

| Risk | Trigger | Action |
|---|---|---|
| R1 timing | WNS < 0 @ 10ns clock | 写 `runs/remote_machine/risk_R1_timing.md`，列 top 5 longest paths from `timing.csv` |
| R2 resource | DSP/LUT/BRAM 超 70% threshold | 写 `runs/remote_machine/risk_R2_resource.md`，列各资源百分比 |
| R6 cosim diverge | run_cosim.tcl 中 RTL vs C 不一致 | 写 trace，可重试一次用 `trace_level=port` |
| R11 HDMI | rgb2dvi VLNV 解析失败 | 检查 `git submodule update --init`，看 `hw/vivado/ip_repo/digilent/vivado-library/ip/` 是否有 23+ IP |
| 2024.1 pragma WARN | ~50 处 | **忽略**，记入 issues.md（M2-W2 B1 backlog） |

## 11. 开始任务

读完本文档后：

1. 创建 `runs/remote_machine/` 目录: `mkdir runs\remote_machine`
2. 写 `runs/remote_machine/HANDOFF_ACKNOWLEDGED.md` 含：
   - 你识别的当前 git HEAD commit hash
   - 你识别的 Vivado/Vitis HLS 路径 + 版本
   - 你识别的 conda env + python 版本
   - 你接下来 5 步的预估总时长
3. `git add runs/remote_machine/HANDOFF_ACKNOWLEDGED.md && git commit -m "ack: remote Claude handoff received" && git push origin vivado/synth-runner`
4. 开始 Step 1

Main Claude 看到你的 ACK commit 后会确认你接手成功。

## 12. 紧急联系

如果你撞到本文档没覆盖的事（环境异常、文件缺失、Xilinx 工具崩溃等），写到 `runs/remote_machine/URGENT_ASK.md`，**立刻 git push**，然后**停手**等 Main Claude 回复 `runs/remote_machine/REPLIES_FROM_MAIN.md`。不要凭猜想做破坏性操作。

---

Good luck. 30 FPS 在等你。

— Main Claude (5060 Laptop session, 2026-05-12)
