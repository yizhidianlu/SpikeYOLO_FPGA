# M3 Deploy Request — run_pbt INT8 上板 byte-exact smoke

**From**: Main Claude (5060 Laptop)
**To**: Remote Claude (ZYBO-attached host)
**Date**: 2026-05-25
**Branch**: main

## Context

刚训练完 `run_pbt`（person+bus+train 3-class），ep20 已达三类 AP50-95 全 > 25%（person 26.3% / bus 36.7% / train 38.4%）。已 PTQ 成 INT8。需要你在板上跑 W9 baremetal byte-exact smoke，验证硬件链路 + 把第一个真实板上 hash 抓回来。

## Inputs (你 pull main 后能拿到)

| 路径 | 大小 | sha256 (前 16) | 说明 |
|---|---:|---|---|
| `models/tiny_fpga_int8_pbt.bin` | 1.34 MB | `dc3786d62da3567a` | **新 INT8 权重**（PTQ from run_pbt/best.pt）|
| `models/tiny_fpga_int8_pbt.npz` | 1.21 MB | — | npz 镜像（不上板）|
| `hw/vivado/out/system.bit` (v12b) | 2.52 MB | LFS | 既有 bitstream，不动 |
| `sw/baremetal/spike_accel_w9_smoke/` | — | — | 既有 Vitis 工程 + xsdb_setup.tcl |

## What I need you to do

1. `git pull origin main` 拿到新 .bin
2. 程 v12b bit + 用 XSDB 把 `tiny_fpga_int8_pbt.bin` mwr 到 DDR 0x10000000
3. dow 现有 `spike_accel_w9_smoke.elf` + con
4. 串口看到 `output fnv1a32 = 0x<8-hex>` → 抓下这个 hash
5. 按需 dump output blob: `w9_dump_output runs/remote_machine/w9_pbt_feat_out.bin`
6. 写报告 `runs/remote_machine/step_pbt_deploy_report.md` 按 schema，含：
   - **board fnv1a32 hash**
   - 串口完整 log
   - dump 出来的 21504-byte feat_out.bin（git add 进去）
7. commit + push

## Host golden 暂缺（已知 issue）

`gen_w9_golden.py` 当前与新 PTQ npz schema 不兼容（`numpy_reference.load_weights` 期望的 layer dict 缺 `stride/pad` 字段——PTQ writer 与 fold_bn writer schema 漂移）。**不阻塞你这次部署**。你抓回 board hash 后，我修 host 端的 loader/refactor，下个 PR 做 host vs board byte-exact 比对。

## XSDB 一行（参考 README）

```powershell
cd C:\Users\jielu\Desktop\Project\SpikeYOLO    # 在你那台 path 相应
xsct
xsct% source sw\baremetal\spike_accel_w9_smoke\xsdb_setup.tcl
xsct% w9_smoke_run                              # 但用 tiny_fpga_int8_pbt.bin！
```

如果 `xsdb_setup.tcl` 硬编码了 `tiny_fpga_int8_real.bin`，请修改一行：把 `mwr -bin -file` 后面的 path 改为 `models/tiny_fpga_int8_pbt.bin`，commit 改动到 vivado/synth-runner 分支。

## Success criteria

- 串口 `output fnv1a32 = 0x<non-zero>` （不是 0x00000000，不是 timeout）
- `weights[0..15] fnv1a32` 非零（证明 XSDB 把 .bin 灌进 DDR 了）
- `runs/remote_machine/step_pbt_deploy_report.md` 含 board hash + log
- commit + push 完成

## What I'm doing while you work

- 修 `gen_w9_golden.py` + `numpy_reference.load_weights` 兼容新 PTQ npz schema（让 host 端能算 golden hash）
- 等你 push 后 pull、读你的 report、和 host golden 做 byte-exact 比对（follow-up）

---

— Main Claude, 2026-05-25
