---
id: A2
name: bit_exact_reference
group: A
milestones: [M1, M2]
inputs_glob:
  - "tools/fpga/numpy_reference.py"
  - "ultralytics/nn/modules/yolo_spikformer.py"
  - "ultralytics/nn/modules/yolo_spikformer_bin.py"
  - "models/tiny_fpga_int8.npz"
  - "datasets/coco/val2017/**"
outputs_glob:
  - "tools/verify/**/*.py"
  - "tests/golden/layer_*.npz"
  - "tests/golden/coco_val100.json"
  - "tests/test_bit_exact.py"
  - "tests/test_cosim.py"
contracts:
  produces: [C2, C6]
  consumes: [C1]
acceptance_tests:
  - "pytest tests/test_bit_exact.py -v"
  - "python tools/verify/torch_vs_numpy.py --tolerance 0"
  - "ls tests/golden/layer_*.npz | wc -l"          # 期望 ≥ 11
status: in_progress
owner: "A2-session-2026-05-11-W5"
---

# A2 Bit-Exact Reference Agent Playbook

## Mission

把 `tools/fpga/numpy_reference.py` 扩展为完整的 11 层 bit-exact NumPy 黄金参考，
建立 **PyTorch ↔ NumPy ↔ HLS C-sim** 三路一致性回归，产出契约 2、6 所需的全部
golden 张量。

## 现状

`tools/fpga/numpy_reference.py` 已具备：

- `expand_cumulative` (二值脉冲展开)
- `mem_update` (I-LIF)
- `conv2d_int` / `conv2d_bn`
- `ms_downsampling` / `ms_standard_conv`
- `sep_conv` / `ms_all_conv_block`
- `spike_sppf`
- `TinyFpgaNet`

**需要做的**：

1. 验证 `TinyFpgaNet.forward` 端到端与 PyTorch `yolo_spikformer_bin.py` 完全一致
2. 给每层加 hook，dump 出 `tests/golden/layer_*.npz`
3. 写 `tools/verify/numpy_vs_hls.py` 用作 HLS C-sim 比对
4. 实现 100 张 val 图的 `coco_val100.json` 生成器

## 工作流

### Phase 1: 端到端对齐（M1 Week 1-2）

```bash
# 1. 加载 A1 的 .npz
python tools/verify/torch_vs_numpy.py \
    --pt models/tiny_fpga_fp32_retrained.pt \
    --npz models/tiny_fpga_int8.npz \
    --img tests/fixtures/sample_image.jpg \
    --layer-wise --dump tests/golden/
```

实现 `tools/verify/torch_vs_numpy.py`：

```python
def main():
    # 1. 加载 PyTorch tiny_fpga 模型 + .pt 权重
    # 2. 加载 NumPy TinyFpgaNet + .npz 权重
    # 3. forward 一张图，逐层比对
    # 4. PyTorch 端要量化到 INT8（用 A1 的 fake-quant），否则不公平
    # 5. assert max abs diff == 0 (INT 域)
    # 6. 如果 --dump，把每层 input/output 存为 tests/golden/layer_XX.npz
```

**关键技术点**：PyTorch 的 BN 折叠必须用 A1 的同一套 `fold_bn.py` 实现，否则
浮点运算顺序差异会导致最后 1-bit 不一致。

### Phase 2: Golden 张量批量提取（M1 Week 3 - M2 Week 2）

实现 `tools/verify/extract_golden.py`：

```bash
python tools/verify/extract_golden.py \
    --npz models/tiny_fpga_int8.npz \
    --num-images 100 \
    --output-dir tests/golden/
```

输出：

- `tests/golden/layer_00_stem.npz`
- `tests/golden/layer_01_acb1.npz`
- ...
- `tests/golden/layer_11_detect.npz`

每个 .npz 含**多张图**的 input/output 张量（key 命名 `input_000`, `output_000`,
`input_001`, …），避免单张图过拟合到 testbench。

### Phase 3: NumPy ↔ HLS 比对工具（M2 Week 1-3）

实现 `tools/verify/numpy_vs_hls.py`：

```bash
python tools/verify/numpy_vs_hls.py \
    --layer 0 \
    --hls-output hw/hls/build/csim_layer_00_out.bin \
    --golden tests/golden/layer_00_stem.npz \
    --report runs/cosim_diff_layer_00.json
```

支持：

- 二进制 binary blob 对比（HLS 输出的 .bin）
- 逐元素 hex diff 输出（用于调试）
- 失败时 dump 前 10 个 mismatch index + 值

### Phase 4: COCO val100 基准（M4 Week 3）

实现 `tests/golden/coco_val100.json` 生成：

```bash
python tools/verify/gen_coco_val100.py \
    --val-dir datasets/coco/val2017 \
    --weights models/tiny_fpga_int8.npz \
    --num 100 \
    --output tests/golden/coco_val100.json
```

按契约 6 schema 输出。选图策略：每类至少 1 张，剩余按图像复杂度（GT 框数）均匀采样。

### Phase 5: pytest 套件（M1 Week 4 持续维护）

实现 `tests/test_bit_exact.py`：

```python
@pytest.mark.parametrize("layer_idx", range(12))
def test_numpy_matches_pytorch(layer_idx):
    golden = np.load(f"tests/golden/layer_{layer_idx:02d}_*.npz")
    pt_out = run_pytorch_layer(layer_idx, golden['input_000'])
    np_out = run_numpy_layer(layer_idx, golden['input_000'])
    assert np.array_equal(pt_out, np_out)
```

CI 必跑：D2 在 `numpy_regress.yml` 中接入。

## 关键文件

| 文件 | 用途 | 状态 |
|---|---|---|
| `tools/fpga/numpy_reference.py` | 主战场，扩展现有实现 | 复用扩展 |
| `tools/verify/torch_vs_numpy.py` | 三路对齐验证 | 新建 |
| `tools/verify/numpy_vs_hls.py` | HLS 比对 | 新建 |
| `tools/verify/extract_golden.py` | 黄金张量批量导出 | 新建 |
| `tools/verify/gen_coco_val100.py` | val100 基准生成 | 新建 |
| `tests/test_bit_exact.py` | 主回归测试 | 新建 |
| `tests/test_cosim.py` | C-sim ↔ NumPy 接入 | 新建 |
| `tests/golden/layer_*.npz` | 主交付物 | 新建 |
| `tests/golden/coco_val100.json` | 主交付物 | 新建 |

## Risk Handlers

| 风险 | 触发 | 处理 |
|---|---|---|
| **R6 C-sim ↔ Co-sim 不一致** | golden 比对 fail | (a) 检查 ap_axiu side-band 信号; (b) array_partition 改 cyclic; (c) datatypes 改 ap_int<32> 显式 |
| **NumPy ↔ PyTorch 浮点差异** | max abs diff > 0 in INT 域 | 强制 PyTorch BN 折叠走 A1 的 `fold_bn.py`，禁用 torch.compile / cuDNN |
| **golden 张量过大** | 单 .npz > 50 MB | 用 `np.savez_compressed`；多图分块 |

## 交接给 B1 的清单

✅ `tests/golden/layer_{00..11}_*.npz` 全部存在  
✅ 每个 .npz 至少含 10 张图的 input/output  
✅ `pytest tests/test_bit_exact.py` 全 pass  
✅ `tools/verify/numpy_vs_hls.py --help` 跑通

## 参考资料

- `tools/fpga/numpy_reference.py` 全文（这是主战场）
- `ultralytics/nn/modules/yolo_spikformer_bin.py`（中间层 hook 参考）
- `ultralytics/nn/modules/block.py` 中 SpikeDetect 检测头（A2 要正确处理输出 INT8 解码）
