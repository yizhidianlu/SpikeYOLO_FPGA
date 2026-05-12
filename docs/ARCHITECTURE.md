# SpikeYOLO → ZYBO Z7-20 端到端架构

## 1. 总体目标

把已训练好的 SpikeYOLO（YOLOv8 + I-LIF 脉冲神经元）部署到 Digilent ZYBO Z7-20
（Xilinx Z-7020 SoC）开发板上，实现 **USB 摄像头 → 实时检测 → HDMI 1080p
本机显示** 的完整产品级 pipeline。

**硬约束**：

| 维度 | 值 |
|---|---|
| 目标帧率 | ≥ 30 FPS（稳定 10 min，抖动 < 5%） |
| 精度 | COCO val mAP50-95 下降 ≤ 1.0%（相对 PyTorch FP32 baseline） |
| 模型 | tiny_fpga 变体：256×256 输入、宽度 0.1875、单尺度 P4 检测 |
| 量化 | INT8 权重 + INT4 激活（MultiSpike4，膜电位 clamp 到 [0,4]） |
| 时间步 | T = 1（单时间步直接推理，无 ANN-SNN 转换） |
| 工具链 | Vitis HLS 2024.1 + Vivado + Petalinux + C/C++ |
| 周期 | 6 个月，3–5 人团队 |

---

## 2. 系统架构

```
+--------------------------------------------------------------+
| ZYBO Z7-20                                                   |
|                                                              |
|  +----------------------+   AXI-HP    +---------------+     |
|  | PS (Cortex-A9 x2)    |<----------->| DDR3 (1 GB)   |     |
|  |  - Petalinux         |             | * cam frame   |     |
|  |  - V4L2 / OpenCV     |             | * weight pool |     |
|  |  - libspike_accel    |             | * framebuffer |     |
|  +----------+-----------+             +-------+-------+     |
|             | AXI-Lite (config)               ^             |
|             | AXI-Stream (data)               |             |
|             v                                 |             |
|  +----------+-----------+    AXI-MM           |             |
|  | PL (FPGA fabric)     |<---------------------+            |
|  |                      |                                    |
|  |  +----------------+  |  +----------------+               |
|  |  | spike_accel    |  |  | VDMA           |               |
|  |  | (HLS IP)       |  |  | + HDMI TX IP   |---HDMI out--->|
|  |  |  PE 16x8       |  |  | 1080p@60       |               |
|  |  |  + LIF + SPPF  |  |  +----------------+               |
|  |  +----------------+  |                                    |
|  +----------------------+                                    |
+--------------------------------------------------------------+

         ^                                          |
         | USB UVC camera                           v
         +------ /dev/video0 (V4L2)         HDMI display
```

### 2.1 PS 端（Processing System / ARM Cortex-A9）

负责**控制平面与软实时任务**：

1. **采集**：通过 V4L2 从 USB UVC 摄像头拿 YUYV/MJPEG 帧（默认 640×480@30）
2. **预处理**：letterbox 缩放到 256×256，YUV→RGB→INT8 量化，写到 DDR3 输入 buffer
3. **调度**：通过 AXI-Lite 配置加速器寄存器（层 id、输入/输出 base 地址、shape），启动加速器，等中断
4. **后处理**：从 DDR3 读 INT8 输出张量，跑 NMS（INT8/FP32 混合），坐标还原
5. **显示**：把检测框画到 framebuffer 上（OpenCV draw on `/dev/fb0` 或 DRM dumb buffer），VDMA 通过 HDMI 输出

### 2.2 PL 端（Programmable Logic / FPGA fabric）

负责**计算密集型 SNN 推理**：

1. **spike_accel IP**（B1 输出，HLS C++）：tiny_fpga 全部 11 层算子封装为单一顶层 IP
   - PE 阵列：Tcout=16 × Tcin=8（128 DSP）systolic
   - LIF + MultiSpike4 + 4-substep 二值展开内嵌
   - AXI-Stream 输入（权重 256-bit、激活 256-bit），AXI-Stream 输出（128-bit INT8）
   - 完成中断 → PS

2. **AXI DMA**：PS 端权重 / 激活 ↔ PL 加速器之间的高吞吐数据搬运（≥ 1.2 GB/s）

3. **VDMA + Digilent rgb2dvi v1.4**：DDR3 framebuffer → HDMI 1080p@60 直出。
   选型决议见 [`decisions/0001_hdmi_tx_selection.md`](decisions/0001_hdmi_tx_selection.md)
   （DVI 信号、无 audio，与 ZYBO 板载 PHY 完美匹配；M5 时序闭合失败时回退 Xilinx
   HDMI 1.4 TX 自由 license 版本）

### 2.3 数据流（30 FPS 一帧的完整时间预算 ≈ 33 ms）

```
t=0    PS: V4L2 取帧 (frame N, 640x480 YUV)                    ~3 ms
t=3    PS: 预处理 + DMA 写入 DDR3 (256x256x3 INT8)              ~4 ms
t=7    PL: spike_accel 启动 (config via AXI-Lite)             <0.1 ms
t=7    PL: 11 层 SNN 推理 (DMA + PE 阵列流水)                  ~18 ms
t=25   PS: 中断后读输出 INT8 张量                              ~1 ms
t=26   PS: NMS + 坐标还原                                       ~2 ms
t=28   PS: framebuffer draw bbox + OSD                          ~2 ms
t=30   VDMA: 自动刷新到 HDMI                                    <1 ms
                                                              -------
                                                       帧间隔 ~33 ms
```

**并发优化**（M5+ 启用）：PS 端预处理与 PL 推理 ping-pong 双缓冲，时钟提到 150 MHz
后 PL 推理可压到 ~12 ms，整帧降至 ~22 ms，留下 11 ms 余量给 30 FPS 稳定运行。

---

## 3. 多 Agent 团队 (10 个 LLM Sub-Agent)

详见 [`AGENT_PLAYBOOKS/`](AGENT_PLAYBOOKS/) 与 [`CONTRACTS.md`](CONTRACTS.md)。

| Group | Agent | 角色 |
|---|---|---|
| **A. 模型与精度** | A1 Quantization | PTQ + QAT，INT8/INT4 权重打包 |
|  | A2 Bit-Exact Reference | NumPy 黄金参考 + 三路一致性回归 |
| **B. 硬件加速** | B1 HLS Kernel | Vitis HLS 算子 IP |
|  | B2 System Architect | Vivado BD + AXI 互联 + HDMI TX |
|  | B3 RTL Tuning | M5+ 关键路径手写 SystemVerilog |
| **C. 系统软件** | C1 Petalinux | SD 卡镜像 + 驱动集成 |
|  | C2 Driver & SDK | UIO/dma-buf + C++ SDK |
|  | C3 Application | 端到端 demo（V4L2 → 加速器 → HDMI） |
| **D. 验证集成** | D1 System Verification | mAP / FPS 回归 + 月报 |
|  | D2 CI/CD | GitHub Actions + nightly board test |

**协作机制**：

- 所有 Agent 间交付物均为机器可读文件（.npz / .yaml / .bin / .xo / .bit / .h）
- 每个交付物配 `tests/test_contract_<n>.py` 自动校验
- CI（D2）强制 PR 门禁：算法变更必先过 NumPy 回归，硬件变更必先过 C-sim/Co-sim
- 风险触发自动开 issue 打 `risk:R<n>` 标签

---

## 4. 关键文件索引

### 复用现有资产

| 文件 | 角色 | 拥有 Agent |
|---|---|---|
| `tools/fpga/numpy_reference.py` | HLS C++ 翻译蓝本（line-for-line）+ 黄金参考 | A2 主战场 |
| `ultralytics/nn/modules/yolo_spikformer.py` | PyTorch 训练侧 SNN 算子定义 | A1 输入 |
| `ultralytics/nn/modules/yolo_spikformer_bin.py` | 二值化推理 + 中间层 hook | A2 |
| `ultralytics/cfg/models/v8/snn_yolov8_tiny_fpga.yaml` | 模型架构定义 | A1, A2, B1 |
| `convert_integer_to_binary.py` | `expand_tensor_cumulative` 算法参考 | A1 |
| `realtime_detect.py` | letterbox/NMS/可视化逻辑参考 | C3 |
| `models/SpikeYOLO_23.1M_T1D4.pt` | FP32 baseline 权重 | A1 |

### 新建目录（按 Agent 归属）

| 目录 | 拥有 Agent | 关键产物 |
|---|---|---|
| `tools/quant/` | A1 | `run_ptq.py`, `fold_bn.py`, `qat_finetune.py`, `weight_packer.py` |
| `tools/verify/` | A2 | `torch_vs_numpy.py`, `numpy_vs_hls.py`, `extract_golden.py` |
| `tools/ci/` | D2 | `run_hls_csim.sh`, `scp_to_board.py`, `gen_dts.py` |
| `tools/perf/` | D1 | `fps_bench.py`, `ddr_bw_monitor.py` |
| `hw/hls/` | B1 | `src/*.cpp`, `build/tiny_fpga_top.xo`, `regmap.yaml` |
| `hw/vivado/` | B2 | `build_bd.tcl`, `out/system.bit`, `out/address_map.yaml` |
| `hw/rtl/` | B3 (M5+) | `src/pe_array.sv`, `src/popcount_tree.sv` |
| `sw/petalinux/` | C1 | `BOOT.BIN`, `image.ub` |
| `sw/driver/` | C2 | `spike_accel.ko`, `uio_config.dts` |
| `sw/sdk/` | C2 | `include/spike_accel.h`, `libspike_accel.so` |
| `sw/app/` | C3 | `src/main.cpp`, `scripts/run_on_board.sh` |
| `tests/golden/` | A2, D1 | `layer_{00..10}_*.npz`, `coco_val100.json` |
| `tests/regression/` | D1 | `run_full.sh`, `coco_val_on_board.py` |
| `docs/AGENT_PLAYBOOKS/` | All | 每 Agent 一份自治 spec |
| `.github/workflows/` | D2 | 3 个 CI workflow |

---

## 5. 里程碑速览

| 月份 | 截止 | 关键 deliverable |
|---|---|---|
| **M1** | 2026-06-10 | 量化对齐 + NumPy 参考完善 + 首个 HLS 算子 C-sim 通过 |
| **M2** | 2026-07-10 | HLS 全 11 层综合通过 + Vivado HDMI 彩条 + Petalinux 启动 USB cam |
| **M3** | 2026-08-10 | FPGA 单帧静态图推理 bit-exact + SDK alpha |
| **M4** | 2026-09-10 | 完整 USB cam → HDMI pipeline 跑通，≥ 10 FPS |
| **M5** | 2026-10-10 | 150 MHz 时序闭合 + 脉冲跳零 + 25–30 FPS |
| **M6** | 2026-11-10 | **30+ FPS 产品级 + mAP 下降 ≤ 1% + v1.0 tag** |

详细甘特图、依赖、回退预案见 [plan 文件](../../.claude/plans/spikeyolo-zynq-7000-zybo-fpga-agent-radiant-unicorn.md)。

---

## 6. 进入项目的快速入口

新接手 Agent 阅读顺序：

1. 本文件（5 分钟）— 全局观
2. [`CONTRACTS.md`](CONTRACTS.md)（10 分钟）— 我的交付物长什么样
3. [`AGENT_PLAYBOOKS/<我的ID>.md`](AGENT_PLAYBOOKS/)（30 分钟）— 我的工作
4. 复用资产源码（按 Agent 自行选）

人类项目经理监控：

1. `docs/reports/M<n>_report.md` — 月报（D1 自动生成）
2. GitHub Actions 仪表盘 — PR 健康度（D2 维护）
3. `tests/perf/*.json` — 性能演进
