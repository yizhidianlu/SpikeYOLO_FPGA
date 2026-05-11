---
id: B1
name: hls_kernel
group: B
milestones: [M1, M2, M3, M4, M5]
inputs_glob:
  - "tools/fpga/numpy_reference.py"
  - "tests/golden/layer_*.npz"
  - "models/tiny_fpga_int8.npz"
outputs_glob:
  - "hw/hls/src/**/*.cpp"
  - "hw/hls/src/**/*.h"
  - "hw/hls/include/**/*.h"
  - "hw/hls/sim/**/*"
  - "hw/hls/build/tiny_fpga_top.xo"
  - "hw/hls/build/tiny_fpga_regmap.yaml"
  - "hw/hls/run_csim.tcl"
  - "hw/hls/run_cosim.tcl"
contracts:
  produces: [C3]
  consumes: [C1, C2]
acceptance_tests:
  - "cd hw/hls && vitis_hls -f run_csim.tcl"
  - "cd hw/hls && vitis_hls -f run_cosim.tcl"
  - "python tools/verify/numpy_vs_hls.py --all-layers"
  - "python tools/ci/check_resource_budget.py hw/hls/reports/utilization.rpt"
status: in_progress
owner: "B1-session-2026-05-11-W4"
---

# B1 HLS Kernel Agent Playbook

## Mission

把 `tools/fpga/numpy_reference.py` **line-for-line** 翻译为可综合的 Vitis HLS C++，
打包成单一顶层 IP `tiny_fpga_top`，满足 ZYBO Z7-20 资源预算与 30 FPS 性能目标。

## 关键技术决策

| 维度 | 选择 | 理由 |
|---|---|---|
| HLS 版本 | Vitis HLS 2023.2 | 与 Vivado / Petalinux 版本对齐 |
| 顶层接口 | s_axilite（控制） + m_axi（DDR3）+ AXI-Stream（可选层间） | 简化 BD，避开过多 stream depth 调优 |
| 数据类型 | `ap_int<8>` / `ap_int<32>` 显式 | 避免编译器隐式扩展导致面积膨胀 |
| 流水线 | 内层循环 II=1，外层 dataflow | 标准 systolic 模板 |
| 资源 | PE 阵列 16×8 systolic（128 DSP） | 留 70-90 DSP 给 LIF/SPPF/检测头 |
| 时钟目标 | M4 @ 100 MHz, M5 @ 150 MHz | M5 抬频前先用 retiming 工具 |

## 模块拆分（与 numpy_reference.py 一一对应）

```
hw/hls/src/
├── conv2d_int.cpp          ← numpy_reference.py:conv2d_int
├── conv2d_bn.cpp           ← numpy_reference.py:conv2d_bn
├── lif_expand.cpp          ← numpy_reference.py:mem_update + expand_cumulative
├── ms_downsample.cpp       ← numpy_reference.py:ms_downsampling
├── ms_standard_conv.cpp    ← numpy_reference.py:ms_standard_conv
├── sep_conv.cpp            ← numpy_reference.py:sep_conv
├── ms_all_conv_block.cpp   ← numpy_reference.py:ms_all_conv_block
├── spike_sppf.cpp          ← numpy_reference.py:spike_sppf
├── detect_head.cpp         ← yolo_spikformer.py:SpikeDetect (新写)
└── tiny_fpga_top.cpp       ← numpy_reference.py:TinyFpgaNet.forward
```

## 工作流

### Phase 1: 单算子 C-sim（M1 Week 3-4）

**优先级**：先打通 `conv2d_int` + `conv2d_bn` + `lif_expand` + `ms_downsample`，
够跑 layer 00（stem）。

```cpp
// hw/hls/include/dtypes.h
#ifndef DTYPES_H
#define DTYPES_H
#include <ap_int.h>
#include <hls_stream.h>
using i8  = ap_int<8>;
using i32 = ap_int<32>;
using u8  = ap_uint<8>;
constexpr int T_STEPS  = 1;           // tiny_fpga T=1
constexpr int N_SUB    = 4;           // MultiSpike4 substep count
constexpr int Co_TILE  = 16;
constexpr int Ci_TILE  = 8;
#endif
```

```cpp
// hw/hls/src/conv2d_int.cpp - line-for-line port of numpy_reference.conv2d_int
extern "C" void conv2d_int(
    const i8 spike_in[N_SUB][Ci_TILE][/*H*/64][/*W*/64],
    const i8 weight  [Co_TILE][Ci_TILE][/*K*/7][/*K*/7],
    i32       acc_out[Co_TILE][/*H_out*/16][/*W_out*/16],
    int stride, int pad)
{
#pragma HLS INTERFACE m_axi port=spike_in offset=slave bundle=gmem
#pragma HLS INTERFACE m_axi port=weight   offset=slave bundle=gmem
#pragma HLS INTERFACE m_axi port=acc_out  offset=slave bundle=gmem
#pragma HLS INTERFACE s_axilite port=stride
#pragma HLS INTERFACE s_axilite port=pad
#pragma HLS INTERFACE s_axilite port=return

    // ... (line-for-line from numpy_reference)
    // 关键: 内层 4-fold unroll + array_partition 让 PE 阵列编译出来
}
```

**第一个 C-sim 测试**：

```tcl
# hw/hls/run_csim.tcl
open_project tiny_fpga
set_top conv2d_int
add_files src/conv2d_int.cpp
add_files -tb sim/tb_conv2d_int.cpp
add_files -tb sim/load_golden.cpp
open_solution sol1 -flow_target vivado
set_part xc7z020clg400-1
create_clock -period 10 -name default
csim_design -ldflags "-lz"
exit
```

```cpp
// hw/hls/sim/tb_conv2d_int.cpp
#include "load_golden.h"
int main() {
    auto g = load_golden("tests/golden/layer_00_stem.npz");
    i8 *hls_out = run_conv2d_int(g.input, g.weight, ...);
    return memcmp(hls_out, g.output, g.output_size) == 0 ? 0 : 1;
}
```

### Phase 2: 全算子综合（M2 Week 1-3）

按依赖顺序：`conv2d_int` → `conv2d_bn` → `lif_expand` → `ms_downsample` →
`ms_standard_conv` → `sep_conv` → `ms_all_conv_block` → `spike_sppf` → `detect_head` → `tiny_fpga_top`。

每个模块都要有 `tb_<name>.cpp`，从对应 golden 张量 load 数据，跑 csim 与 cosim。

**dataflow 编排**（在 `tiny_fpga_top.cpp`）：

```cpp
extern "C" void tiny_fpga_top(
    const u8 *img_in,          // 256x256x3 INT8
    int8_t   *feat_out,        // (nc+4)x16x16
    int       layer_id,        // 0..11 调度单层 / -1 跑全网络
    const i8 *weights)         // /lib/firmware/tiny_fpga_int8.bin 内容
{
#pragma HLS INTERFACE m_axi port=img_in    offset=slave bundle=gmem0 depth=196608
#pragma HLS INTERFACE m_axi port=feat_out  offset=slave bundle=gmem1 depth=21504
#pragma HLS INTERFACE m_axi port=weights   offset=slave bundle=gmem2 depth=2000000
#pragma HLS INTERFACE s_axilite port=layer_id
#pragma HLS INTERFACE s_axilite port=return
#pragma HLS DATAFLOW

    // M2 阶段：层间串行（不 dataflow），保证正确性
    // M5 阶段：改 dataflow + ping-pong buffer

    static i32 buf_a[1024*1024];     // L1 stem 输出 max 96*64*64=393K
    static i32 buf_b[1024*1024];
    // ... 各层调用
}
```

### Phase 3: PE 阵列与稀疏跳零（M5 Week 1-3）

M4 跑通后开始优化：

1. **PE 16×8 systolic 阵列**：用 `#pragma HLS ARRAY_PARTITION dim=1 type=complete` +
   `#pragma HLS UNROLL factor=8` 让综合器生成 128 个并行 MAC

2. **脉冲跳零**：

```cpp
// 二值激活 == 0 时整个 MAC 路径跳过
for (int co = 0; co < Co_TILE; co++) {
    for (int ci = 0; ci < Ci_TILE; ci++) {
        if (spike_in[ci][h][w] != 0) {                  // 跳零关键
            acc[co][h_out][w_out] += weight[co][ci];   // 二值 spike，MAC 退化为加法
        }
    }
}
```

3. **双缓冲**：

```cpp
#pragma HLS DATAFLOW
#pragma HLS STREAM variable=buf_a depth=2 type=pipo  // ping-pong
```

### Phase 4: 时钟抬升 100 → 150 MHz（M5 Week 4）

如果 M4 实现下 WNS < 0 @ 6.67ns (150 MHz)：

1. `report_timing -setup -path 10` 找最长路径
2. 路径若在 PE 阵列内，加 `#pragma HLS PIPELINE II=2`
3. 路径若在 LIF 状态机，手动插 register stage
4. 如仍失败 → 升级 R1 → 触发 B3 RTL Tuning

## 关键文件

| 文件 | 用途 | 状态 |
|---|---|---|
| `hw/hls/include/dtypes.h` | ap_int 定义 | 新建 |
| `hw/hls/include/axi_iface.h` | AXI 接口宏 | 新建 |
| `hw/hls/src/*.cpp` | 10 个算子 + 顶层 | 新建 |
| `hw/hls/sim/tb_*.cpp` | 每算子 testbench | 新建 |
| `hw/hls/sim/load_golden.cpp` | 加载 .npz | 新建 |
| `hw/hls/run_csim.tcl` | C-sim 脚本 | 新建 |
| `hw/hls/run_cosim.tcl` | Co-sim 脚本 | 新建 |
| `hw/hls/build/tiny_fpga_top.xo` | 交付 B2 | 新建 |
| `hw/hls/build/tiny_fpga_regmap.yaml` | 交付 B2（契约 3） | 新建 |
| `tools/fpga/numpy_reference.py` | line-for-line 翻译源 | 复用 |

## Risk Handlers

| 风险 | 触发 | 处理 |
|---|---|---|
| **R1 时序无法收敛 100 MHz** | WNS < 0 | (a) 关键 inner loop `II=2`; (b) PE 阵列 retiming; (c) 升级到 B3 SV 重写 |
| **R2 资源超 Z-7020** | `utilization.rpt` 任意 > 90% | (a) PE 阵列 16×8 → 8×8; (b) DW conv 用 LUT shift-add; (c) 部分层时分复用共享 PE |
| **R6 C-sim ↔ Co-sim 不一致** | `cosim_design` fail | (a) array_partition 改 cyclic; (b) datatypes 显式 ap_int<N>; (c) 检查 ap_axiu side-band |

## 交接给 B2 的清单

✅ `hw/hls/build/tiny_fpga_top.xo` 综合通过  
✅ `hw/hls/build/tiny_fpga_regmap.yaml` 符合契约 3  
✅ `hw/hls/reports/timing.csv` WNS ≥ 0  
✅ `hw/hls/reports/utilization.rpt` 全资源 ≤ 75%  
✅ Co-sim 100% 过 golden

## 参考资料

- `tools/fpga/numpy_reference.py`（主要翻译源，**几乎不需要算法设计**）
- Xilinx UG902 Vitis HLS User Guide（pragma 参考）
- Xilinx UG1399 Vitis HLS Coding Style
- `ultralytics/nn/modules/yolo_spikformer.py` 中 SpikeDetect 实现（detect_head 参考）
