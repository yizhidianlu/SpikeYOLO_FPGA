# 远程 Vivado 2024.1 机器 — 5 分钟动手

> 目标：让第二台 Windows 11 + Vivado 2024.1 + Vitis HLS 2024.1 机器在 5
> 分钟内 clone 工程、source 工具链、跑通 host_csim sanity；30 分钟跑通
> 真 vitis_hls C-sim；2 小时完成首次 .xo + .bit 综合并推回。

## Step 0: 环境前提

- Windows 11，64 位，**至少 32 GB RAM**（Vivado impl 阶段吃满）
- Vivado 2024.1 + Vitis HLS 2024.1 + Petalinux 2024.1 安装
  （默认 `D:\Xilinx\` — 下面命令按这个路径写，自行调整）
- Git for Windows 2.40+ + Git LFS 3.4+
- Miniconda3 with Python 3.10
- ~50 GB 空余磁盘（Vivado project ~5 GB / .xo + .bit / reports / scratch）
- (可选) MSYS2 or `m2w64-gcc` 给 host_csim 用

## Step 1: Clone repo + LFS

打开 `cmd.exe` 或 PowerShell：

```cmd
cd C:\Users\<you>\Workspace
git lfs install
git clone https://github.com/yizhidianlu/SpikeYOLO_FPGA.git
cd SpikeYOLO_FPGA
git lfs pull
git checkout -b vivado/synth-runner          & rem 长期分支，见 docs/COLLABORATION.md
git push -u origin vivado/synth-runner       & rem 第一次推上去
```

## Step 2: 工具链 source

每次新开 cmd 窗口都要做（写成 `setup_env.bat` 放桌面也行）：

```cmd
call D:\Xilinx\Vivado\2024.1\settings64.bat
call D:\Xilinx\Vitis_HLS\2024.1\settings64.bat
vivado -version       & rem 期望 v2024.1
vitis_hls -version    & rem 期望 v2024.1
```

## Step 3: Conda env (轻量)

仅给 `tools/ci/explode_npz.py`、`check_utilization.py`、`check_timing.py` 用。
**不需要 torch / ultralytics 在这台机器**（算法侧仍在主开发机）。

```cmd
conda create -n spikeyolo python=3.10 -y
conda activate spikeyolo
pip install numpy pyyaml
```

## Step 4: Digilent vivado-library submodule

```cmd
bash hw\vivado\scripts\setup_ip_repo.sh
rem 期望 hw/vivado/ip_repo/digilent/vivado-library/ip/ 下有 23 个 IP，包括 rgb2dvi / dvi2rgb / axi_dynclk
dir hw\vivado\ip_repo\digilent\vivado-library\ip
```

## Step 5: host_csim sanity（5 layer + top）

需要 `g++`（MSYS2 / mingw / `m2w64-gcc` conda 包）。一次性安装：

```cmd
conda install -c msys2 m2w64-gcc m2w64-make -y
set CXX=g++
mingw32-make -C hw/hls host_csim_layer_00 host_csim_layer_01 ^
                       host_csim_layer_03 host_csim_layer_08 ^
                       host_csim_layer_11 host_csim_top
```

期望 `CSIM PASS` 出现 6 次。如失败，先排查 g++ 5.x ICE
（hw/hls/README.md 已 known-issues 列出 workaround）。

## Step 6: 真 vitis_hls C-sim（~5 min）

```cmd
cd hw\hls
vitis_hls -f run_csim.tcl
rem 期望 10 个 (top, tb) pair 全 PASS（Vitis 把 main() 退出码透传）
cd ..\..
```

## Step 7: 真 vitis_hls Co-sim（~1.5 h，可选）

仅在调查 C-sim ↔ RTL 不一致时跑：

```cmd
cd hw\hls
vitis_hls -f run_cosim.tcl
cd ..\..
```

## Step 8: 真综合 + .xo 输出（~25 min）

```cmd
cd hw\hls
vitis_hls -f run_synth.tcl
rem 检查报告
type reports\timing.csv
python ..\..\tools\ci\check_utilization.py reports\utilization.rpt
python ..\..\tools\ci\check_timing.py reports\timing.csv
rem .xo 落在 hw/hls/build/sa_tiny_fpga_top.xo
dir build\*.xo
cd ..\..
```

R1 / R2 风险触发条件（D2 RISK_RULES.yaml）：

- 任一资源 > 75% (warn) / > 90% (block) → R2，回 B1 调 PE 阵列
- WNS < 0 ns @ 100 MHz → R1，先试 `II=2` 再升级 B3

## Step 9: Vivado BD + bitstream（~45 min）

```cmd
copy hw\hls\build\sa_tiny_fpga_top.xo  hw\vivado\ip_repo\spike_accel\
copy hw\hls\build\tiny_fpga_regmap.yaml hw\vivado\ip_repo\spike_accel\

cd hw\vivado
vivado -mode batch -source build_bd.tcl
vivado -mode batch -source build_bitstream.tcl
vivado -mode batch -source scripts/synth_metrics.tcl

rem 检查
dir out\system.bit out\system.hwh out\system.xsa out\address_map.yaml
type reports\timing_summary.rpt | findstr /R "WNS"
cd ..\..
```

## Step 10: 推产物回 GitHub

```cmd
git add hw/hls/build/sa_tiny_fpga_top.xo ^
        hw/hls/reports/ ^
        hw/vivado/out/system.bit ^
        hw/vivado/out/system.hwh ^
        hw/vivado/out/system.xsa ^
        hw/vivado/out/address_map.yaml ^
        hw/vivado/reports/
git commit -m "feat: B1+B2 first real synth on Vivado 2024.1"
git push origin vivado/synth-runner
rem LFS 自动 upload (.xo .bit .hwh .xsa)
```

主开发机这边：

```cmd
git pull origin vivado/synth-runner -X theirs
git lfs pull
rem 现在主开发机也有 .bit 可以跑 board emulation / D1 monthly
```

## Troubleshooting

### Vivado 2024.1 vs 2023.2 已知差异

| 症状 | 原因 | 解决 |
|---|---|---|
| `WARNING: [HLS 200-XXXX] pragma HLS INTERFACE m_axi mode=...` | 2024.1 推荐新 syntax | 当前代码用旧 syntax，仍兼容；可后续重构 |
| `IP catalog out of date` | 2024.1 强制 re-index | `setup_ip_repo.sh` 已自动跑 `update_ip_catalog`，再不行手动 `vivado -mode batch` 后跑 `update_ip_catalog -rebuild` |
| `processing_system7_0` not found | 罕见 — 2024.1 仍支持 Z-7020 | 检查 `set BOARD_PART digilentinc.com:zybo-z7-20:part0:1.0` 这一行的 board_part 是否 install |
| `rgb2dvi:1.4` 找不到 | Digilent vivado-library 没拉 | 重跑 `setup_ip_repo.sh`；或手动 `git submodule update --init --recursive` |
| `Implementation Strategy XYZ deprecated` | 2024.1 部分老策略名变了 | 默认 `Vivado Implementation Defaults` 仍在；如有自定义策略需 review |
| `csim_design` 输出 `cannot find ap_int.h` | 2024.1 头文件路径变化 | 检查 `XILINX_HLS` env 是否 set；`vitis_hls -version` 应显示 v2024.1 |
| Co-sim 突然变慢 4× | 2024.1 默认 trace_level 改了 | `cosim_design -trace_level none -O` 关掉波形 |

如要临时 fallback 到 2023.2：把 `D:\Xilinx\Vitis_HLS\2024.1\settings64.bat`
换成 `D:\Xilinx\Vitis_HLS\2023.2\settings64.bat`；本工程脚本已经测试过两边
都能跑（见 `docs/decisions/0005_vivado_2024_1_bump.md`）。

### Git LFS quota 触顶

如果 `git push` 报 `LFS: Your push was rejected ... budget`：

1. 先 `git lfs ls-files | wc -l` 看对象数
2. 大文件（> 100 MB 单个）建议**只在 release tag 上传**
3. `petalinux-sdimage.wic`（200 MB）和 `*.dcp` 默认走 LFS，但**可选**：
   commit 前 `git rm --cached path/to/foo.wic` 再加进 .gitignore
4. 详见 `docs/GIT_LFS_SETUP.md`

### MSYS2 + Conda PATH 冲突

PowerShell 启动后 conda env 优先级高于 MSYS2，`g++` 可能找不到。Workaround：

```cmd
where g++       & rem 应该指向 conda env\Library\mingw-w64\bin\g++.exe
set PATH=C:\msys64\mingw64\bin;%PATH%   & rem 强行用 MSYS2 g++
```

## Next steps

- M2-W1: 跑 Step 6-9 出第一份真 .bit
- M2-W2: 把 Vivado runner 注册成 GitHub self-hosted runner（见
  `docs/SELFHOSTED_RUNNER_SETUP.md`），让 hls_smoke.yml 自动跑
- M3-W1: 接 ZYBO 板子，跑 `tools/ci/scp_to_board.py` + `board_nightly.yml`

## References

- `docs/QUICK_START.md` — 工程 30 秒读懂
- `docs/COLLABORATION.md` — 跨机器分支策略
- `docs/GIT_LFS_SETUP.md` — LFS 流转
- `docs/decisions/0005_vivado_2024_1_bump.md` — 2024.1 兼容性 review
- `hw/hls/README.md` — B1 八步 TL;DR
- `hw/vivado/README.md` — B2 BD setup
