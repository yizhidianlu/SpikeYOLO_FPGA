# Agent 间接口契约定稿

本文件锁定所有 Agent 间的交付物格式。**任何变更须经 PR 修改本文件 + 同步更新
对应 `tests/test_contract_<n>.py` 校验脚本**，禁止口头约定。

```
契约总览
==========
契约 1   A1 Quantization     → B1 HLS Kernel           权重打包 .npz
契约 2   A2 Bit-Exact Ref    → B1 HLS Kernel           逐层黄金张量 .npz
契约 3   B1 HLS Kernel       → B2 System Architect     IP 寄存器表 + AXI
契约 4   B2 System Architect → C2 Driver & SDK         地址映射 + 设备树
契约 5   C2 Driver & SDK     → C3 Application          C SDK API + ABI
契约 6   A2 Bit-Exact Ref    → C3 Application & D1     板上 mAP 回归基准
```

---

## 契约 1：A1 Quantization → B1 HLS Kernel（权重打包）

### 数据格式

**文件**：`models/tiny_fpga_int8.npz`（开发期）→ `/lib/firmware/tiny_fpga_int8.bin`（板上 raw）

**键名 schema**：

```
L{layer_idx:02d}.w           int8   [Co_tile=16, Ci_tile=8, K, K, Co_outer, Ci_outer]
L{layer_idx:02d}.bias        int32  [C_out]
L{layer_idx:02d}.out_shift   int8   [C_out]     # 融合 BN 后的 right-shift
L{layer_idx:02d}.stride      int8   scalar
L{layer_idx:02d}.pad         int8   scalar
L{layer_idx:02d}.groups      int8   scalar      # 1=常规 conv，>1=DW conv
L{layer_idx:02d}.first_layer bool   scalar      # stem 第一层标记（输入 INT8 而非 binary）
L{layer_idx:02d}.kind        str    enum {"conv2d_bn", "ms_downsample", "sep_conv", "maxpool", "sppf", "detect"}
```

**权重 tile 序排布规则**（line-for-line 一致于 `tools/quant/weight_packer.py`）：

```python
# 原始 PyTorch 权重 shape: [C_out, C_in, K, K]
# 重排后:
w_packed[Co_t, Ci_t, kh, kw, Co_o, Ci_o] = w_raw[Co_t + Co_o*16, Ci_t + Ci_o*8, kh, kw]
# 其中 Co_outer = ceil(C_out/16), Ci_outer = ceil(C_in/8)，不足补 0
```

**首层例外**（stem）：`first_layer=True` 时，激活非 binary，直接是 INT8 RGB 图像
（[-128, 127]），无 4-substep 展开。

### 板上 .bin 格式

按 layer 顺序拼接以下 record，每 record 16-byte aligned：

```
struct LayerRecord {
    uint8_t  layer_idx;
    uint8_t  kind_enum;      // 对应 .kind 字符串编码
    uint8_t  stride;
    uint8_t  pad;
    uint8_t  groups;
    uint8_t  first_layer;
    uint16_t k;              // kernel size, 通常 1/3/7
    uint16_t c_in;
    uint16_t c_out;
    uint32_t weight_bytes;   // 后续 weight blob 字节数
    uint32_t bias_bytes;     // 后续 bias blob 字节数 = c_out * 4
    uint32_t shift_bytes;    // 后续 out_shift blob 字节数 = c_out
    // 紧接着：weight blob (int8, weight_bytes) + bias blob (int32) + shift blob (int8)
};
```

### 验证

```bash
# A1 拥有的双实现 byte-identical 测试
pytest tests/test_weight_pack.py::test_pack_unpack_roundtrip
pytest tests/test_weight_pack.py::test_python_vs_cpp_byte_identical

# 量化误差测试（与 PyTorch state_dict dequant 对比）
pytest tests/test_weight_pack.py::test_dequant_l1_error_zero
```

### 验收阈值

- pack / unpack roundtrip：MD5 一致
- Python 实现 vs C++ 实现：byte-for-byte 一致
- dequant 与 PyTorch state_dict 逐通道 cosine sim ≥ 0.999、L1 误差 = 0（INT 域）

### 交付节点

**M1 Week 3**（2026-05-31）

---

## 契约 2：A2 Bit-Exact Reference → B1 HLS Kernel（逐层黄金张量）

### 数据格式

**文件**：`tests/golden/layer_{idx:02d}_{name}.npz`

**键名 schema**：

```
input         int8/int32   形状视该层类型而定（见下）
output        int8/int32
params_hash   str          上游 .npz 的 SHA256（用于检测权重漂移）
input_shape   tuple[int]
output_shape  tuple[int]
kind          str          对应契约 1 的 .kind
```

**层 ID 映射**（与 `snn_yolov8_tiny_fpga.yaml` 一致）：

```
layer_00_stem               stem MS_DownSampling   (3, 256, 256) -> (24, 64, 64)
layer_01_acb1               MS_AllConvBlock        (24, 64, 64)   -> (24, 64, 64)
layer_02_ds1                MS_DownSampling        (24, 64, 64)   -> (48, 32, 32)
layer_03_acb2a              MS_AllConvBlock        (48, 32, 32)   -> (48, 32, 32)
layer_04_acb2b              MS_AllConvBlock        (48, 32, 32)   -> (48, 32, 32)
layer_05_ds2                MS_DownSampling        (48, 32, 32)   -> (96, 16, 16)
layer_06_acb3a              MS_AllConvBlock        (96, 16, 16)   -> (96, 16, 16)
layer_07_acb3b              MS_AllConvBlock        (96, 16, 16)   -> (96, 16, 16)
layer_08_sppf               SpikeSPPF              (96, 16, 16)   -> (48, 16, 16)
layer_09_head_reduce        MS_StandardConv 1x1    (48, 16, 16)   -> (48, 16, 16)
layer_10_head_refine        MS_AllConvBlock        (48, 16, 16)   -> (48, 16, 16)
layer_11_detect             SpikeDetect            (48, 16, 16)   -> (nc+4)x16x16 INT8
```

binary spike 输入张量含时间步维度：shape `(T*4, C, H, W)` int8 ∈ {0,1}。

### 验证

```bash
pytest tests/test_bit_exact.py::test_numpy_matches_pytorch  # PyTorch ↔ NumPy
# B1 HLS C-sim testbench
cd hw/hls && vitis_hls -f run_csim.tcl  # 内部自动 load_golden() 比对
```

### 验收阈值

- NumPy ↔ PyTorch：逐元素 max abs diff = 0（INT 域）；100 张 val 图检测框 IoU ≥ 0.999
- HLS C-sim ↔ NumPy：逐元素 = 0，**CI gate 必须 100% pass**

### 交付节点

- **M1 Week 4**（2026-06-07）：layer_00、layer_01
- **M2 Week 2**（2026-06-21）：全 11 层

---

## 契约 3：B1 HLS Kernel → B2 System Architect（IP + 寄存器表）

### IP 交付物

- `hw/hls/build/tiny_fpga_top.xo`（Vitis 标准打包）
- `hw/hls/build/tiny_fpga_regmap.yaml`（寄存器表）

### regmap.yaml schema

```yaml
ip_name: spike_accel_top
version: "1.0"
clock_period_ns: 10.0     # M4: 10 ns (100 MHz); M5: 6.67 ns (150 MHz)

axi_lite:
  base: 0x0000            # 相对偏移；B2 在 BD 中映射到绝对地址
  size: 0x10000
  registers:
    - { addr: 0x00, name: CTRL,        bits: { 0: ap_start, 1: ap_done, 2: ap_idle, 3: ap_ready, 7: auto_restart } }
    - { addr: 0x04, name: GIE,         bits: { 0: global_irq_en } }
    - { addr: 0x08, name: IER,         bits: { 0: ap_done_irq_en, 1: ap_ready_irq_en } }
    - { addr: 0x0C, name: ISR,         bits: { 0: ap_done_isr, 1: ap_ready_isr } }
    - { addr: 0x10, name: LAYER_ID,    desc: "0..11" }
    - { addr: 0x14, name: H,           desc: "feature map height" }
    - { addr: 0x18, name: W,           desc: "feature map width" }
    - { addr: 0x1C, name: C_IN,        desc: "input channels" }
    - { addr: 0x20, name: C_OUT,       desc: "output channels" }
    - { addr: 0x24, name: IN_PTR_LO,   desc: "DDR3 input buffer lo32" }
    - { addr: 0x28, name: IN_PTR_HI }
    - { addr: 0x2C, name: OUT_PTR_LO }
    - { addr: 0x30, name: OUT_PTR_HI }
    - { addr: 0x34, name: W_PTR_LO,    desc: "weight pool lo32" }
    - { addr: 0x38, name: W_PTR_HI }

axi_stream:
  s_axis_feat:    { width_bits: 256, has_tlast: true,  has_tkeep: true,  packing: "INT8 interleave [Ci_tile=8] x 32 lanes" }
  s_axis_weight:  { width_bits: 256, has_tlast: true,  has_tkeep: false, packing: "INT8 tile序 (见契约1)" }
  m_axis_feat:    { width_bits: 128, has_tlast: true,  has_tkeep: true,  packing: "INT8 [Co_tile=16] x 8 lanes" }

axi_mm_master:
  m_axi_gmem:     { data_width: 64, addr_width: 32, max_burst: 256, num_outstanding: 16 }

interrupts:
  - { name: ap_done, sensitivity: level_high }

resource_budget:
  dsp48:  ≤ 154   # 70% of 220
  lut:    ≤ 31920 # 60% of 53200
  bram36: ≤ 105   # 75% of 140

timing:
  m4_target_mhz: 100
  m5_target_mhz: 150
```

### 验证

```bash
# B2 拿到 .xo 后跑 Vivado AXI Verification IP 协议检查
vivado -mode batch -source hw/vivado/scripts/axi_protocol_check.tcl
# B1 提供配套 SV testbench
xsim hw/hls/sim/tb_axi_top.sv
```

### 验收阈值

- AXI 协议检查 0 warning 0 error
- 综合后 `report_timing` WNS ≥ 0
- 综合后 `report_utilization` 资源占用符合 `resource_budget`

### 交付节点

**M2 Week 4**（2026-07-05）

---

## 契约 4：B2 System Architect → C2 Driver（地址映射 + 设备树）

### address_map.yaml schema

```yaml
soc: zynq-7020
board: zybo-z7-20
vivado_version: "2023.2"
bitstream: out/system.bit
hwh: out/system.hwh

peripherals:
  spike_accel:
    base: 0x43C00000
    size: 0x10000
    irq: 61           # PL IRQ 0 = 61
    compat: "xlnx,spike-accel-1.0"
    clocks: [ "pl_clk0" ]
    bus: axi-lite

  axi_dma_feat:
    base: 0x40400000
    size: 0x10000
    irq: 62
    compat: "xlnx,axi-dma-7.1"

  vdma_disp:
    base: 0x43000000
    size: 0x10000
    irq: 63
    compat: "xlnx,axi-vdma-6.3"

  hdmi_tx:
    base: 0x43C10000
    size: 0x10000
    compat: "digilent,axi-hdmi"

memory:
  ddr3:
    total_mb: 1024
    reserved_for_cma: 256   # contiguous memory pool for DMA buffers
```

### 自动生成 uio_config.dts

```bash
python tools/ci/gen_dts.py \
    --addr-map hw/vivado/out/address_map.yaml \
    --output sw/driver/uio_config.dts
```

### 验证

```bash
pytest tests/test_address_map.py::test_dts_regenerable    # gen_dts.py 输出 diff = 0
pytest tests/test_address_map.py::test_no_overlap          # 地址段不重叠
```

### 验收阈值

- `gen_dts.py` 重生成 vs 仓库内 `.dts` diff = 0
- 所有 peripheral 地址段不重叠
- 中断号 ∈ [61, 95]（PL IRQ 范围）

### 交付节点

**M3 Week 1**（2026-07-12）

---

## 契约 5：C2 Driver & SDK → C3 Application（SDK API + ABI）

### 头文件 `sw/sdk/include/spike_accel.h`

```c
#ifndef SPIKE_ACCEL_H
#define SPIKE_ACCEL_H

#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

#define SA_API_VERSION_MAJOR 1
#define SA_API_VERSION_MINOR 0

typedef struct sa_handle_s* sa_handle_t;

typedef enum {
    SA_OK              =  0,
    SA_ERR_OPEN        = -1,
    SA_ERR_NO_DEVICE   = -2,
    SA_ERR_WEIGHT_LOAD = -3,
    SA_ERR_DMA         = -4,
    SA_ERR_TIMEOUT     = -5,
    SA_ERR_INVALID_ARG = -6,
} sa_status_t;

typedef struct {
    uint16_t input_h;       // 期望 256
    uint16_t input_w;       // 期望 256
    uint8_t  input_c;       // 期望 3 (RGB INT8)
    uint8_t  num_classes;   // 期望 80 (COCO)
    uint16_t output_h;      // 期望 16
    uint16_t output_w;      // 期望 16
    uint8_t  output_stride; // 期望 16
} sa_model_info_t;

sa_status_t sa_open(sa_handle_t* handle);
sa_status_t sa_close(sa_handle_t handle);

sa_status_t sa_load_weights(sa_handle_t handle, const char* bin_path);
sa_status_t sa_get_model_info(sa_handle_t handle, sa_model_info_t* info);

// img_in  : INT8 RGB, NCHW, [-128, 127]  size = 3*256*256
// feat_out: INT8 raw detect head output  size = (nc+4)*16*16
// timeout_ms: 0 = blocking, -1 = wait forever
sa_status_t sa_infer(sa_handle_t handle,
                     const int8_t* img_in,
                     int8_t* feat_out,
                     int timeout_ms);

// 异步 API（M5+，配合双缓冲）
typedef void (*sa_callback_t)(sa_handle_t h, sa_status_t s, void* user);
sa_status_t sa_infer_async(sa_handle_t handle,
                           const int8_t* img_in,
                           int8_t* feat_out,
                           sa_callback_t cb,
                           void* user);

// 性能监控
typedef struct {
    uint64_t cycles_compute;
    uint64_t cycles_dma_in;
    uint64_t cycles_dma_out;
    uint32_t frames_completed;
    uint32_t frames_dropped;
} sa_perf_t;
sa_status_t sa_get_perf(sa_handle_t handle, sa_perf_t* out);

#ifdef __cplusplus
}
#endif

#endif
```

### ABI 锁定

- 共享库：`/usr/lib/libspike_accel.so`，soname `libspike_accel.so.1`
- semver 1.x 内 ABI 不破坏；2.x 始符号变更
- `abidiff` 守门：每次 PR 比较 baseline ABI dump

### 验证

```bash
# 单元测试
sw/sdk/tests/test_api_contract       # sa_open/close/load/infer roundtrip
sw/sdk/tests/test_dma_loopback       # DMA 1MB 单次 <1ms, 100k 次无 leak

# ABI 检查
abidiff sw/sdk/baseline/libspike_accel.so.1 sw/sdk/build/libspike_accel.so.1
```

### 验收阈值

- 全部单元测试 pass
- `abidiff` 输出无 incompatible change
- valgrind 100k 次推理无 leak

### 交付节点

**M3 Week 3**（2026-07-26）

---

## 契约 6：A2 Bit-Exact Reference → C3 & D1（板上 mAP 回归基准）

### 数据格式

**文件**：`tests/golden/coco_val100.json`

```json
{
  "schema_version": "1.0",
  "model": "tiny_fpga_int8",
  "weights_sha256": "...",
  "image_dir": "datasets/coco/val2017",
  "image_ids": [139, 285, 632, ...],  // 100 张代表性图
  "predictions": {
    "139": [
      { "cls": 0, "bbox": [x1, y1, x2, y2], "conf": 0.87 },
      ...
    ],
    "285": [ ... ]
  },
  "metadata": {
    "input_size": 256,
    "stride": 16,
    "nms_iou_threshold": 0.45,
    "conf_threshold": 0.25
  }
}
```

### 验证

```bash
# 板上
python tests/regression/coco_val_on_board.py \
    --golden tests/golden/coco_val100.json \
    --board-out runs/board_coco_val100.json \
    --iou-threshold 0.99 \
    --pass-rate 0.95
```

### 验收阈值

- 100 张图中 ≥ 95% 的图：板上每个检测框与黄金对应框 IoU ≥ 0.99 且类别一致
- 该测试用作 M4 验收门 + D2 board_nightly 回归

### 交付节点

**M4 Week 4**（2026-09-06）

---

## 契约变更流程

1. 拟变更 Agent 在 GitHub 开 PR 修改本文件 + 对应 `tests/test_contract_<n>.py`
2. 标 reviewer：契约上下游两端的 Agent + D1
3. CI 必须先跑新契约测试 PASS 才能 merge
4. Merge 后 D2 在 `docs/CONTRACTS_CHANGELOG.md` 自动记录
