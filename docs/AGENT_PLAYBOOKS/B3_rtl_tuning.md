---
id: B3
name: rtl_tuning
group: B
milestones: [M5]
inputs_glob:
  - "hw/hls/build/tiny_fpga_top.xo"
  - "hw/hls/reports/timing.csv"
  - "hw/vivado/reports/timing_summary.rpt"
outputs_glob:
  - "hw/rtl/src/**/*.sv"
  - "hw/rtl/sim/**/*.sv"
  - "hw/rtl/verify/uvm_*/**"
  - "hw/rtl/scripts/run_verilator.sh"
contracts:
  produces: []
  consumes: [C3]
acceptance_tests:
  - "verilator --lint-only hw/rtl/src/pe_array.sv"
  - "bash hw/rtl/scripts/run_verilator.sh"
  - "python tools/ci/check_timing.py hw/vivado/reports/timing_summary.rpt --wns-min 0.5"
status: prep_done
owner: "B3-session-2026-05-11"
m5_trigger_ref: "docs/decisions/0004_b3_m5_trigger.md"
---

# B3 RTL Tuning Agent Playbook

## Mission

**仅在 M5 启用**。当 B1 HLS 综合无法在 150 MHz 闭合时序时，把关键瓶颈算子
（PE 阵列 inner loop、popcount tree、LIF 跳零控制）手写为 SystemVerilog 替换
HLS 综合产物，目标 Fmax ≥ 160 MHz。

## 启动判定

**只有当以下任一条件触发才启动 B3**：

1. B2 报告：`hw/vivado/reports/timing_summary.rpt` WNS < 0 @ 150 MHz
2. B1 报告：HLS 综合后 `report_timing` 关键路径 > 6.67 ns
3. 触发风险 R1 升级到 (c) 分支

如未触发，B3 保持 `status: pending` 不动作。

## 关键技术决策

| 维度 | 选择 | 理由 |
|---|---|---|
| HDL | SystemVerilog 2012 | Verilator 与 Vivado 都支持 |
| 仿真 | Verilator + cocotb | 开源、快、可在 CI 跑 |
| 验证方法 | cycle-accurate 与 B1 HLS RTL 比对 | 不重写算法，只优化时序 |
| 范围 | 仅 PE 阵列 inner + popcount + LIF 状态机 | 其他模块仍走 HLS |

## 候选优化点（按 ROI 排序）

### 1. PE 阵列 inner loop（最高 ROI）

HLS 综合的 16×8 systolic 阵列可能因为 MAC 链不够规整导致时序差。手写版：

```systemverilog
// hw/rtl/src/pe_array.sv
module pe_array #(
    parameter int CO_TILE = 16,
    parameter int CI_TILE = 8
)(
    input  logic                  clk,
    input  logic                  rst_n,
    input  logic                  en,
    input  logic signed [7:0]     act_in [CI_TILE],    // INT8 spike (二值时 0/1)
    input  logic signed [7:0]     w_in   [CO_TILE][CI_TILE],
    output logic signed [31:0]    acc_out[CO_TILE]
);
    // 流水线 stage 1: 部分积
    logic signed [15:0] partial [CO_TILE][CI_TILE];
    always_ff @(posedge clk) begin
        if (en) for (int co = 0; co < CO_TILE; co++)
                 for (int ci = 0; ci < CI_TILE; ci++)
                    partial[co][ci] <= $signed(act_in[ci]) * $signed(w_in[co][ci]);
    end

    // 流水线 stage 2-4: 加法树（log2(8)=3 级）
    logic signed [19:0] sum_lvl1 [CO_TILE][CI_TILE/2];
    logic signed [21:0] sum_lvl2 [CO_TILE][CI_TILE/4];
    logic signed [23:0] sum_lvl3 [CO_TILE];
    // ... 标准加法树
endmodule
```

DSP48E1 SIMD 模式两路 INT8 MAC：

```systemverilog
// 利用 DSP48E1 INMODE/ALUMODE 实现单 DSP 双 INT8 MAC（pre-add 模式）
DSP48E1 #(
    .USE_SIMD("TWO24")     // 双 24-bit 加法器
) dsp_inst (...);
```

### 2. Popcount tree（二值 spike 优化）

当激活全是 binary {0,1}，MAC 退化为加法。Popcount + 选择性累加比 HLS 默认实现快：

```systemverilog
// hw/rtl/src/popcount_tree.sv
module popcount_tree #(parameter int WIDTH = 32) (
    input  logic [WIDTH-1:0] x,
    output logic [$clog2(WIDTH+1)-1:0] count
);
    // 8/16/32-input 加法树
endmodule
```

### 3. LIF 跳零控制（小但累积明显）

```systemverilog
// hw/rtl/src/lif_skip_ctrl.sv
// 若整个 spike vector 全为 0，断言 skip 信号，跳过整个 PE 周期
module lif_skip_ctrl (...);
    assign skip = (|act_in[0] || |act_in[1] || ... ) == 1'b0;
endmodule
```

## 工作流

### Phase 1: 测试基线（M5 Week 1）

1. 从 B1 HLS 综合后的 RTL（在 `hw/hls/build/.../verilog/`）抽出对应模块
2. 用 Verilator 跑一遍，记录 cycle count + 周期 testbench 输出
3. 这是后续手写版的**绑定参考**

### Phase 2: 手写 SV（M5 Week 2-3）

按上述候选优化点逐个重写。每个模块单独 testbench：

```bash
# hw/rtl/scripts/run_verilator.sh
verilator -Wall --cc --exe --build \
    --top-module pe_array \
    -I../src \
    sim/tb_pe_array.cpp src/pe_array.sv
./obj_dir/Vpe_array
```

### Phase 3: 集成回 Vivado（M5 Week 3-4）

1. 在 `hw/vivado/build_bd.tcl` 里把 spike_accel IP 中的对应子模块替换为 SV 文件
2. 重新跑 implementation
3. 检查 `report_timing` Fmax ≥ 160 MHz、`report_utilization` LUT 节省 ≥ 15%

## 关键文件

| 文件 | 用途 | 状态 |
|---|---|---|
| `hw/rtl/src/pe_array.sv` | 16×8 systolic 阵列 | 新建（仅 M5） |
| `hw/rtl/src/popcount_tree.sv` | 加法树优化 | 新建（仅 M5） |
| `hw/rtl/src/lif_skip_ctrl.sv` | 跳零控制 | 新建（仅 M5） |
| `hw/rtl/sim/tb_pe_array.sv` | testbench | 新建 |
| `hw/rtl/scripts/run_verilator.sh` | 仿真脚本 | 新建 |
| `hw/rtl/verify/uvm_top/` | UVM 验证环境 | 新建（可选） |

## Risk Handlers

| 风险 | 触发 | 处理 |
|---|---|---|
| **手写 RTL 与 HLS 不一致** | Verilator 仿真输出与 HLS RTL 不匹配 | (a) cycle-by-cycle dump 比对; (b) 逐 stage 注释掉重写; (c) 降级到改 HLS pragma |
| **Vivado 不识别 SV 模块** | implementation 报错 | (a) 改 .v 兼容（去 logic / interface 关键字）; (b) 检查 ip_user_files 包含路径 |
| **DSP SIMD 模式约束失败** | 综合 DSP 数没减半 | (a) 显式 instantiate DSP48E1 而非依赖推断; (b) 用 (* use_dsp = "yes" *) attribute |

## 验收清单

✅ `verilator --lint-only` 0 warning  
✅ `run_verilator.sh` testbench 与 HLS RTL cycle-accurate 匹配  
✅ Vivado implementation Fmax ≥ 160 MHz  
✅ LUT 总用量节省 ≥ 15%（vs M4 baseline）

## 参考资料

- Xilinx UG479 7 Series DSP48E1 Slice User Guide
- Verilator Manual
- "Synthesis of Arithmetic Circuits" (CS book)
- B1 HLS 综合输出的 .v 文件作为参考实现
