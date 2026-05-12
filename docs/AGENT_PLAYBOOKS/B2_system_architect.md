---
id: B2
name: system_architect
group: B
milestones: [M2, M3, M4, M5]
inputs_glob:
  - "hw/hls/build/tiny_fpga_top.xo"
  - "hw/hls/build/tiny_fpga_regmap.yaml"
outputs_glob:
  - "hw/vivado/build_bd.tcl"
  - "hw/vivado/build_bitstream.tcl"
  - "hw/vivado/constraints/zybo_z7_20.xdc"
  - "hw/vivado/out/system.bit"
  - "hw/vivado/out/system.hwh"
  - "hw/vivado/out/address_map.yaml"
  - "hw/vivado/reports/**/*"
contracts:
  produces: [C4]
  consumes: [C3]
acceptance_tests:
  - "vivado -mode batch -source hw/vivado/build_bd.tcl"
  - "vivado -mode batch -source hw/vivado/build_bitstream.tcl"
  - "python tools/ci/check_timing.py hw/vivado/reports/timing_summary.rpt --wns-min 0"
  - "python tools/ci/check_utilization.py hw/vivado/reports/utilization.rpt"
status: pending
owner: ""
---

# B2 System Architect Agent Playbook

> **Decision log**: HDMI Tx IP selection is locked to Digilent rgb2dvi v1.4 —
> see [`docs/decisions/0001_hdmi_tx_selection.md`](../decisions/0001_hdmi_tx_selection.md).
> All BD scripts and `address_map.yaml` reflect this choice. Future B2 sessions
> should add a new ADR under `docs/decisions/` rather than mutating this section.

## Mission

用 Vivado Block Design 把 B1 的 HLS IP、AXI DMA、VDMA、Xilinx HDMI TX、PS、
DDR3 控制器串成完整 SoC，实现并产出比特流，时序闭合 100 → 150 MHz。

## 关键技术决策

| 维度 | 选择 | 理由 |
|---|---|---|
| Vivado 版本 | 2024.1 | 与 Vitis HLS / Petalinux 对齐 |
| 时钟规划 | PL 双时钟域：100 MHz (M4) + 200 MHz HDMI pixel | HDMI 1080p@60 需要 148.5 MHz pixel clock |
| HDMI IP | Digilent dvi2rgb + rgb2dvi 或 Xilinx Video PHY | Digilent 在 ZYBO 上社区维护更稳 |
| AXI 互联 | AXI Smartconnect（自动 ID 转换） | 比手动 AXI Interconnect 简单且时序好 |
| 中断 | PS GIC IRQ 61/62/63（PL IRQ0/1/2） | 与 address_map.yaml 锁定 |
| DDR3 配置 | 32-bit @ 533 MHz，4 port AXI-HP | HP 端口给 PL 用，GP 给 AXI-Lite |

## 工作流

### Phase 1: 最小 BD + HDMI 彩条（M2 Week 1-2）

```tcl
# hw/vivado/build_bd.tcl
create_project tiny_fpga_zybo ./out -part xc7z020clg400-1 -force
set_property board_part digilentinc.com:zybo-z7-20:part0:1.0 [current_project]

create_bd_design system

# 1. 加 PS
create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 ps_0
apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 \
    -config { make_external "FIXED_IO, DDR" apply_board_preset "1" } [get_bd_cells ps_0]
set_property -dict [list \
    CONFIG.PCW_USE_HIGH_OCM {0} \
    CONFIG.PCW_USE_M_AXI_GP0 {1} \
    CONFIG.PCW_USE_S_AXI_HP0 {1} \
    CONFIG.PCW_USE_S_AXI_HP1 {1} \
    CONFIG.PCW_USE_FABRIC_INTERRUPT {1} \
    CONFIG.PCW_IRQ_F2P_INTR {1} \
] [get_bd_cells ps_0]

# 2. 加 spike_accel IP (B1 输出)
add_files hw/hls/build/tiny_fpga_top.xo
create_bd_cell -type ip -vlnv xilinx.com:hls:tiny_fpga_top:1.0 spike_accel_0

# 3. 加 HDMI TX (Digilent rgb2dvi)
create_bd_cell -type ip -vlnv digilentinc.com:ip:rgb2dvi:1.4 rgb2dvi_0
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_vdma:6.3 vdma_disp

# 4. 加 AXI Smartconnect
create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 ic_data
create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 ic_ctrl

# 5. 连线（自动 + 手动）
apply_bd_automation -rule xilinx.com:bd_rule:axi4 \
    -config { Clk_master "Auto" Clk_slave "Auto" Master "/ps_0/M_AXI_GP0" Slave "/spike_accel_0/s_axi_control" } \
    [get_bd_intf_pins spike_accel_0/s_axi_control]

# ... (省略 VDMA / rgb2dvi 自动连线)

# 6. 地址映射（锁定到 address_map.yaml）
assign_bd_address -offset 0x43C00000 -range 0x10000 -target_address_space /ps_0/Data \
    [get_bd_addr_segs spike_accel_0/s_axi_control/Reg]
# ...

save_bd_design
write_bd_tcl -force out/system_bd_dump.tcl
```

### Phase 2: 综合 + 实现（M2 Week 3-4）

```tcl
# hw/vivado/build_bitstream.tcl
open_project out/tiny_fpga_zybo.xpr
make_wrapper -files [get_files system.bd] -top
add_files -norecurse out/tiny_fpga_zybo.gen/sources_1/bd/system/hdl/system_wrapper.v
update_compile_order

read_xdc constraints/zybo_z7_20.xdc

launch_runs synth_1 -jobs 8
wait_on_run synth_1
launch_runs impl_1 -to_step write_bitstream -jobs 8
wait_on_run impl_1

# 时序检查
report_timing_summary -file reports/timing_summary.rpt
report_utilization -file reports/utilization.rpt

# 导出
file copy -force out/tiny_fpga_zybo.runs/impl_1/system_wrapper.bit out/system.bit
write_hw_platform -fixed -force -file out/system.xsa
```

`hw/vivado/constraints/zybo_z7_20.xdc`：

```
# ZYBO Z7-20 HDMI TX pins (J11)
set_property PACKAGE_PIN H16 [get_ports {hdmi_clk_p}]
set_property IOSTANDARD TMDS_33 [get_ports {hdmi_clk_p}]
# ... (从 Digilent 官方 master xdc 拷贝)
```

### Phase 3: 自动生成 address_map.yaml（M3 Week 1）

```tcl
# 在 build_bitstream.tcl 末尾追加
set fp [open out/address_map.yaml w]
puts $fp "soc: zynq-7020\nboard: zybo-z7-20\nvivado_version: \"2024.1\""
puts $fp "peripherals:"
foreach seg [get_bd_addr_segs -of [get_bd_addr_spaces /ps_0/Data]] {
    set name [get_property NAME $seg]
    set base [get_property OFFSET $seg]
    set size [get_property RANGE $seg]
    puts $fp "  $name:\n    base: $base\n    size: $size"
}
close $fp
```

### Phase 4: 150 MHz 抬频（M5 Week 1-2）

1. 在 BD 中加 MMCM 输出 150 MHz 时钟域
2. 重新跑 implementation
3. 若 WNS < 0：先尝试 `set_property STRATEGY Performance_ExtraTimingOpt [get_runs impl_1]`
4. 仍失败 → 升级 R1 → 触发 B3

## 关键文件

| 文件 | 用途 | 状态 |
|---|---|---|
| `hw/vivado/build_bd.tcl` | BD 创建脚本 | 新建 |
| `hw/vivado/build_bitstream.tcl` | 综合实现脚本 | 新建 |
| `hw/vivado/constraints/zybo_z7_20.xdc` | 引脚约束 | 新建（基于 Digilent 模板） |
| `hw/vivado/out/system.bit` | 比特流 | 新建 |
| `hw/vivado/out/system.hwh` | 硬件描述 | 新建 |
| `hw/vivado/out/address_map.yaml` | 契约 4 | 新建 |
| `hw/vivado/reports/timing_summary.rpt` | 时序报告 | 新建 |
| `hw/vivado/reports/utilization.rpt` | 资源报告 | 新建 |

## Risk Handlers

| 风险 | 触发 | 处理 |
|---|---|---|
| **R1 时序无法收敛** | timing_summary WNS < 0 | (a) `Performance_ExtraTimingOpt` 策略; (b) physical_opt_design; (c) 加 register stage 在 BD； (d) 升级 B3 |
| **R3 DDR3 带宽抢占** | DDR3 latency > 200 cycles | (a) 改用 4 个 HP 端口分流; (b) VDMA tdata 改 32-bit (1080p RGB565); (c) HDMI 降至 720p |
| **HDMI IP 不输出** | HDMI 屏幕黑屏 | (a) Logic Analyzer 抓 hdmi_clk; (b) 检查 EDID 读取; (c) 切到 dvi2rgb passthrough mode |

## 交接给 C1/C2 的清单

✅ `out/system.bit` + `out/system.hwh` 存在  
✅ `out/address_map.yaml` 符合契约 4  
✅ M4 验收：100 MHz 时序闭合 + HDMI 1080p 彩条输出可见  
✅ M5 验收：150 MHz 时序闭合

## 参考资料

- Digilent ZYBO Z7-20 Reference Manual
- Xilinx PG059 AXI Interconnect
- Xilinx UG994 Designing IP Subsystems Using IP Integrator
- digilent.com/reference 中的 ZYBO HDMI demo 工程
