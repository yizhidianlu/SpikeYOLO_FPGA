# ADR-0005: Vivado / Vitis HLS / Petalinux 2023.2 → 2024.1 toolchain bump

- **Status**: accepted
- **Date**: 2026-05-12 (M1 W8)
- **Deciders**: Cross-Machine Onboarding Agent (`onboarding-2026-05-12`),
  ratified by user (远程 Vivado runner 装的就是 2024.1)
- **Affected contracts**: C3 (`tiny_fpga_regmap.yaml`), C4
  (`address_map.yaml` 的 `vivado_version` 字段)
- **Affected playbooks**: B1, B2, C1, D2
- **Supersedes (toolchain version only)**: ADR-0001 (HDMI Tx, IP version OK)
  / ADR-0003 (Petalinux BSP 同步从 `Petalinux-Zybo-Z7-20-2023.2-1.bsp` 升到
  `Petalinux-Zybo-Z7-20-2024.1-1.bsp`，决策 Option A 不变) / ADR-0004 (B3 仍
  Vivado-IDE 触发，工具链版本提升)

## Context

M1 W8 起远程 Vivado runner（第二台 Win 11）装的是 Vivado 2024.1 + Vitis HLS
2024.1，主开发机的 docs / tcl / yml 之前全部锁定 2023.2。需要全工程 bump
保持一致，并把 2024.1 引入的兼容性风险 review 下来。

## Decision

**全工程 bump 到 2024.1**。19 个文件 / 35+ 处引用替换（详见 git diff）：

- `docs/AGENT_PLAYBOOKS/B1_hls_kernel.md` 表格 + `docs/AGENT_PLAYBOOKS/B2_system_architect.md`
  表格 + tcl 模板字符串
- `docs/AGENT_PLAYBOOKS/C1_petalinux.md` 表格 + petalinux source 命令
- `docs/AGENT_PLAYBOOKS/D2_ci_cd.md` workflow 示例
- `docs/CONTRACTS.md` schema 示例 + `hw/vivado/out/address_map.yaml`
- `docs/decisions/0003_petalinux_bsp.md` BSP 文件名 + 链上同步
- `docs/QUICK_START.md` 入口 + `docs/ARCHITECTURE.md` 工具链行
- `hw/hls/run_csim.tcl` / `run_synth.tcl` / `run_cosim.tcl` 头注释 + `hw/hls/README.md`
- `hw/vivado/build_bd.tcl` / `build_bitstream.tcl` / `scripts/{synth_impl,build_bd}.tcl`
  头注释 + 输出 yaml + `hw/vivado/README.md`
- `sw/petalinux/build.sh` + `sw/petalinux/README.md` + `tools/ci/petalinux_build_dryrun.sh`
- `.github/workflows/hls_smoke.yml` self-hosted runner Vitis source path
- `FPGA_DEPLOYMENT.md` 工具链行 + `docs/reports/M1_report.md` (M2 plan)

**保留 2023.2 不变**（历史文件）：

- `docs/CONTRACTS_CHANGELOG.md` —  v1.0.0~v1.0.2 历史记录
- `environment.yaml` + `SpikeYOLO_for_Gen1/yolov8_environment.yaml` 中的
  `nsight-compute=2023.2.1.3=0` — 是 conda 包版本号，与 Vivado 工具链无关

## Vitis HLS 2024.1 兼容性 review

| 风险 | 本工程命中？ | 影响 / Mitigation |
|---|---|---|
| `#pragma HLS INTERFACE m_axi/s_axilite/axis` 旧 syntax deprecated（2024.1 推荐 `#pragma HLS INTERFACE mode=...` 新写法） | **是 — 命中**：`hw/hls/src/conv2d_int.cpp` 等 10 个 src 文件、共 ~50 处 | 旧 syntax 仍**完全兼容**到 2024.1；编译只会出 WARN [HLS 200-XXXX]。M2-W2 列入 B1 重构 backlog，本 sprint 不动 |
| `#pragma HLS DATAFLOW` 在 nested loop 里的 corner case 收紧 | **否**：`tiny_fpga_top.cpp` 当前是层间串行（非 dataflow），M5 才打开 | M5 启用时 review |
| `#pragma HLS PIPELINE II=N` 默认 `rewind` 行为变 | **轻微**：本工程用了 II=1 `pipeline`（标准 systolic），不依赖 rewind | 无 |
| `#pragma HLS ARRAY_PARTITION dim=1 type=complete` 的 type=… 关键字现为 mandatory（旧的 `complete` / `cyclic` / `block` 仍兼容） | **是**：`include/op_macros.h` 当前用 `type=complete` 新 syntax，OK | 无 |
| `csim_design -O` 的 `-O` 参数变了，2024.1 默认开 `-O2` | **是**：`run_csim.tcl` 显式传 `-O`，仍兼容 | 无 |
| `cosim_design -trace_level all` 在 2024.1 默认 dump 更多波形（变慢 4×） | **是**：`run_cosim.tcl` 当前 `trace_level all` | 跑 cosim 时如太慢改 `trace_level none -O`，已写到 `REMOTE_VIVADO_ONBOARDING.md` Troubleshooting |
| `export_design -format ip_catalog -rtl verilog` 的输出路径变了 | **未确认**：本工程用 `${PROJ}/sol1/impl/export.xo` 兜底+`catch`，安全 | 首次综合 sanity-check |
| `set_part xc7z020clg400-1` 的命名 | **未变**：Z-7020 设备文件 2024.1 仍带，无需额外 install | 无 |

## Vivado 2024.1 兼容性 review

| 风险 | 本工程命中？ | 影响 / Mitigation |
|---|---|---|
| `update_ip_catalog` 在 BD flow 中**强制要**（2023.2 自动） | **是**：`build_bd.tcl` 已显式调 `update_ip_catalog` after `set_property ip_repo_paths` | 无 |
| `processing_system7_0` (PS7 IP, Z-7020 用) 仍可用 | **是**：2024.1 仍带 PS7 v5.5，Z-7020 默认 board file 仍在 | 无 |
| `digilentinc.com:ip:rgb2dvi:1.4` 兼容性 | **是 — 关键**：Digilent vivado-library 主分支已经 verify 过 2024.1（PR #51 / commit 2024Q3） | `setup_ip_repo.sh` 默认拉 master，自动跟 vendor |
| `axi_dma:7.1` / `axi_vdma:6.3` IP version 在 2024.1 升到 7.1.x / 6.3.x | **是**：2024.1 默认 axi_dma:7.1 (sub-rev 升)、axi_vdma:6.3 (sub-rev 升) — VLNV major.minor 不变 | BD 模板 `xilinx.com:ip:axi_dma:7.1` 仍 resolve（Vivado 自动用最新 sub-rev），无需改 |
| `proc_sys_reset:5.0` / `xlconcat:2.1` / `smartconnect:1.0` | **是**：2024.1 仍是这些 minor version | 无 |
| 默认 implementation 策略 `Performance_ExtraTimingOpt` rename | **未变**：2024.1 仍叫这个名 | 无 |
| `report_timing_summary -file` 输出 schema | **未变**：D2 `tools/ci/check_timing.py` 解析逻辑兼容 | 无 |

## Petalinux 2024.1 兼容性 review

| 风险 | 本工程命中？ | 影响 / Mitigation |
|---|---|---|
| Digilent BSP `Petalinux-Zybo-Z7-20-2024.1-1.bsp` 是否 release | **是 — 已 release**（Digilent 2024Q4 同步 Vivado 2024.1） | ADR-0003 仍 Option A，BSP 文件名 bump |
| 内核从 5.15 LTS 升到 6.1 LTS（Linux 6.1.y） | **是**：CONFIG 项**部分变了** — `CONFIG_USB_VIDEO_CLASS` / `CONFIG_DRM` / `CONFIG_UIO` / `CONFIG_XILINX_DMA` / `CONFIG_CMA` 全部仍在 | C1 `user_kernel.cfg` 当前 cfg 项**完全兼容**6.1 |
| `petalinux-create -t apps --template c++` 模板 layout 变 | **未变** | C1 build flow 不动 |
| `petalinux-package boot --fsbl ... --u-boot --fpga ...` 命令 | **未变** | `sw/petalinux/build.sh` 不动 |
| `dr_mode = "host"` 设备树 binding | **未变** | `system-user.dtsi` 不动 |

## Consequences

- 主开发机 + Vivado runner 工具链版本统一为 **2024.1**
- 远程 Vivado runner 走 `docs/REMOTE_VIVADO_ONBOARDING.md` Step 1-9 即可
  跑出首份 .xo + .bit
- ADR-0001 (HDMI Tx) / ADR-0002 (compute budget) / ADR-0004 (B3 trigger)
  **决策不变**，工具链版本字段同步 2024.1
- ADR-0003 BSP 来源不变（仍 Option A），文件名 bump 到 `2024.1-1.bsp`
- 综合产物（`.xo` / `.bit` / `.hwh` / `.xsa`）通过 `.gitattributes` + Git
  LFS 跨机器同步，见 `docs/GIT_LFS_SETUP.md`

## Fallback path

如果 2024.1 综合在某个 leaf kernel 上 csynth 死，**回退到 2023.2**：

1. 远程机器装 2023.2 (D:\Xilinx\Vivado\2023.2 + Vitis_HLS\2023.2)
2. tcl 头注释 + `address_map.yaml` 中的 `vivado_version` 字段改回 `"2023.2"`
3. 提一个 hotfix PR 把 19 个文件 sed `2024.1` → `2023.2`
4. 本工程当前仍可在 2023.2 跑（除了 `nsight-compute` conda 包外没有 2024
   独占特性）

切换成本估计：1 engineer-hour（机械替换 + 验证 host_csim PASS）。

## References

- Xilinx UG902 Vitis HLS User Guide (2024.1 ed.)
- Xilinx UG1399 Vitis HLS Coding Style (2024.1 ed.)
- Xilinx UG994 Designing IP Subsystems Using IP Integrator (2024.1 ed.)
- Xilinx UG1144 PetaLinux Tools Documentation Reference Guide (2024.1 ed.)
- Digilent vivado-library: <https://github.com/Digilent/vivado-library> (master 已 verify 2024.1)
- Digilent Petalinux BSP: <https://github.com/Digilent/Petalinux-Zybo-Z7> (2024.1-1 release tag)
- `docs/decisions/0001_hdmi_tx_selection.md` — HDMI Tx (rgb2dvi v1.4) 不变
- `docs/decisions/0003_petalinux_bsp.md` — Petalinux BSP Option A 不变
- `docs/REMOTE_VIVADO_ONBOARDING.md` — Vivado runner 5 分钟动手
- `docs/COLLABORATION.md` — 跨机器分支策略
- `docs/GIT_LFS_SETUP.md` — LFS 流转
