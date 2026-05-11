---
id: A1
name: quantization
group: A
milestones: [M1, M5]
inputs_glob:
  - "models/SpikeYOLO_23.1M_T1D4.pt"            # teacher: 23M FP32, T=1, D=4
  - "models/tiny_fpga_fp32.pt"                  # student init (若已有)
  - "ultralytics/cfg/models/v8/snn_yolov8_tiny_fpga.yaml"
  - "ultralytics/nn/modules/yolo_spikformer.py"
  - "ultralytics/nn/modules/yolo_spikformer_bin.py"
  - "convert_integer_to_binary.py"
  - "datasets/coco/train2017/**"                # 蒸馏训练集
  - "datasets/coco/val2017/**"
outputs_glob:
  - "tools/quant/**/*.py"
  - "tools/quant/**/*.cpp"
  - "tools/quant/distill_config.yaml"
  - "models/tiny_fpga_fp32_distilled.pt"        # Phase 1.5 蒸馏产物
  - "models/tiny_fpga_fp32_retrained.pt"        # 别名 / 兼容老脚本
  - "models/tiny_fpga_int8.npz"
  - "models/tiny_fpga_int8.bin"
  - "models/tiny_fpga_calibration.json"
  - "runs/distill/distill_log.csv"
  - "runs/distill/distill_summary.json"
contracts:
  produces: [C1]
  consumes: []
acceptance_tests:
  - "pytest tests/test_weight_pack.py -v"
  - "pytest tests/test_fold_bn.py -v"
  - "python tools/quant/distill_from_teacher.py --validate models/tiny_fpga_fp32_distilled.pt --min-map 18.0"
  - "python tools/quant/eval_quant_map.py --weights models/tiny_fpga_int8.npz --target-degradation 1.0"
  - "python tools/quant/weight_packer.py --validate models/tiny_fpga_int8.npz"
status: in_progress
owner: "A1-session-2026-05-11"
---

# A1 Quantization Agent Playbook

## Mission

把已训好的 SpikeYOLO 模型（FP32）量化为 **INT8 权重 + INT4 激活**（MultiSpike4），
按 PE 阵列 tile 序打包成 `tiny_fpga_int8.npz`，并在 COCO val2017 上保证 mAP50-95
**下降 ≤ 1.0%** 相对于 tiny_fpga FP32 baseline。

## 关键技术决策

| 决策 | 选择 | 理由 |
|---|---|---|
| 量化粒度 | **per-channel 权重 + per-tensor 激活** | 激活已 clamp 到 [0,4]，per-tensor 足够；权重 per-channel 显著提升精度 |
| BN 处理 | **训练后融合到 conv（fold_bn）** | HLS 不必处理 BN，权重直接吸收 scale；fold 后保留 `out_shift` 为 INT8 right-shift |
| 校准方法 | **MSE-min on 100 张 train 子集** | 比 KL-div 简单且稳，与 SNN 整数运算更契合 |
| 量化感知训练 | **首选 PTQ，PTQ 失败回退 QAT** | 已有 FP32 权重，PTQ 是主路径；QAT 仅当 R4 触发 |
| 首层例外 | **stem 输入是 INT8 RGB，不经 LIF/MultiSpike** | 与 `numpy_reference.py` 中 `first_layer=True` 分支一致 |

## 工作流

### Phase 1: Baseline 验证（Week 1）

1. 加载 `models/SpikeYOLO_23.1M_T1D4.pt`，确认是完整 SpikeYOLO（D=4 多尺度 head），**不是** tiny_fpga
2. 用 `snn_yolov8_tiny_fpga.yaml` 构造 tiny_fpga 模型骨架（深0.25 / 宽0.1875 / 单尺度 P4 / T=1 / D=4）
3. 评估两个 baseline 在 COCO val2017 mAP50-95：
   - `mAP_teacher_fp32`     ← `SpikeYOLO_23.1M_T1D4.pt`（**作为 Phase 1.5 的精度上限参考**）
   - `mAP_student_init_fp32` ← `tiny_fpga_fp32.pt`（如已存在；否则随机初始化模型 forward 一次确认 shape）
4. 把两个数字写入 `runs/baseline_summary.json`，A2 与 D1 都会引用

### Phase 1.5: 知识蒸馏（**M1 Week 2，本里程碑核心新增**）

**为什么必须做蒸馏**：tiny_fpga 容量约为 teacher 的 1/23，从头训练会损失 ~5-8 mAP 点；
而 ZYBO Z7-20 上 30 FPS 的硬约束逼着我们只能用 tiny_fpga。蒸馏在 FP32 域把
mAP 顶上去，给后续 PTQ 的 1.0% 退化预算腾出空间。

**Teacher / Student 拓扑对齐**：

| 维度 | Teacher (23M) | Student (tiny_fpga) | 对齐方式 |
|---|---|---|---|
| 时间步 T | 1 | 1 | 完全一致，无需转换 |
| 脉冲位宽 D (MultiSpike4) | 4 | 4 | 完全一致，二值脉冲张量同 dtype |
| 通道宽度 | 全宽 | 0.1875× | **1×1 conv 适配器**把 teacher 投影到 student 通道数 |
| 检测头 | P3+P4+P5 三尺度 | 单 P4（stride 16） | 仅在 P4 (stride 16) 对齐 cls/reg logits |
| 输入分辨率 | 640×640 | 256×256 | teacher 重训一次 256×256 forward 得 P4 输出（**或** 用 teacher 在 640 forward 后对 P4 张量 avgpool 到 16×16） |

**蒸馏 loss**（实现于 `tools/quant/distill_from_teacher.py`）：

```python
total_loss = (
    1.0 * det_loss(student_pred, gt)                                 # YOLO 标准检测损失
  + 1.5 * kd_logits_loss(student_p4_logits, teacher_p4_logits)        # 检测头 KD（cls KL + reg L1）
  + 0.5 * feat_align_loss(student_feats, teacher_feats_via_adapter)   # 中间特征蒸馏
  + 0.3 * spike_rate_loss(student_spike, teacher_spike)               # SNN 专属：脉冲发放率对齐
)
```

**特征对齐点**（与 `numpy_reference.py` 层 ID 对齐）：

| Student 层 | 含义 | Teacher 对应层 | adapter |
|---|---|---|---|
| `layer_05_ds2.out` | stride 16, 96 ch | teacher backbone P4-in | 1×1 conv: `teacher_ch → 96` |
| `layer_07_acb3b.out` | stride 16 refined, 96 ch | teacher backbone P4-out | 1×1 conv |
| `layer_08_sppf.out` | SPPF 输出, 192 ch | teacher SPPF | 1×1 conv: `teacher_sppf_ch → 192` |

`spike_rate_loss` 对每层 LIF 后二值张量取 `mean(spike == 1)` 求 L1，强制学生
脉冲稀疏度向 teacher 靠拢 —— **这是 SNN 蒸馏与 ANN 蒸馏的唯一本质差异**。

**训练配方**（baseline，可在 `tools/quant/distill_config.yaml` 调）：

```yaml
optimizer:    AdamW
lr:           5e-4
lr_schedule:  cosine
weight_decay: 1e-4
epochs:       30                  # 收敛约 50 GPU-hour @ A100
batch_size:   64
warmup_epochs: 3
loss_weights:
  det:        1.0
  kd_logits:  1.5
  feat_align: 0.5
  spike_rate: 0.3
data:
  train_set:  datasets/coco/train2017
  val_every:  2
  imgsz:      256
freeze_teacher: true
adapter_init:   "1x1 conv, kaiming"
seed:           42
```

**入口**：

```bash
python tools/quant/distill_from_teacher.py \
    --teacher models/SpikeYOLO_23.1M_T1D4.pt \
    --student-cfg ultralytics/cfg/models/v8/snn_yolov8_tiny_fpga.yaml \
    --student-init models/tiny_fpga_fp32.pt \
    --config tools/quant/distill_config.yaml \
    --out models/tiny_fpga_fp32_distilled.pt \
    --log runs/distill/distill_log.csv

# 验证（CI gate）
python tools/quant/distill_from_teacher.py \
    --validate models/tiny_fpga_fp32_distilled.pt \
    --min-map 18.0   # 退出码 1 if mAP50-95 < 18.0
```

**产物**：

- `models/tiny_fpga_fp32_distilled.pt`（Phase 2 PTQ 的输入，软链接 / 拷贝为 `tiny_fpga_fp32_retrained.pt` 兼容老脚本）
- `runs/distill/distill_log.csv`（每 epoch loss 各分量 + val mAP）
- `runs/distill/distill_summary.json`（最终 mAP / 提升幅度 / teacher 与 student mAP）

**验收**：

| 指标 | 阈值 | 失败处理 |
|---|---|---|
| `mAP_student_distilled` ≥ 18.0% | 必须达到 | 触发 R8（见下） |
| `mAP_student_distilled` − `mAP_student_scratch` ≥ +2.0 | 蒸馏值得做 | 若 < +2，重审 adapter / loss 权重 |
| `mAP_student_distilled` ≤ `mAP_teacher` × 0.65 | 健全性检查 | 超出说明 teacher 有问题 |

**与下游 Agent 的同步**：

- 通知 **A2**：蒸馏后的 student `state_dict` 是 PTQ 输入；A2 从这个 `.pt` 抽中间层 hook 写黄金张量
- 通知 **D1**：`mAP_student_distilled` 写入 M1 月报，作为 mAP 退化 1.0% 的 baseline
- 不影响 **B1/B2**：他们消费的是 PTQ 后的 `.npz`，与蒸馏过程解耦

### Phase 2: PTQ（Week 2-3）

实现 `tools/quant/run_ptq.py`：

```python
# 算法骨架
def run_ptq(model_pt, calib_imgs, save_path):
    model = load_model(model_pt)
    # 1. 注册 forward hook 收集每层激活直方图
    hooks = register_activation_collectors(model)
    # 2. 跑 100 张 calibration 图
    for img in calib_imgs:
        model(img)
    # 3. 对每个 conv 计算 weight scale (per-channel, MSE-min)
    # 4. 对每个 LIF 输出计算 activation scale (per-tensor, fixed to [0,4])
    # 5. 折叠 BN 到 conv: w_new = w * bn.gamma / sqrt(bn.var); b_new = ...
    # 6. 计算 out_shift = round(log2(act_scale * w_scale / out_scale))
    # 7. 保存 npz：每层 {w_int8, bias_int32, out_shift_int8, ...}
```

参考实现 `tools/fpga/numpy_reference.py:conv2d_bn` 中如何应用 out_shift。

### Phase 3: 权重打包（Week 3）

实现 `tools/quant/weight_packer.py`：

```python
def pack_weights(npz_in, npz_out):
    # 重排 [C_out, C_in, K, K] -> [Co_tile=16, Ci_tile=8, K, K, Co_outer, Ci_outer]
    # 不足 16/8 倍数的层补 0
    # 输出严格符合契约 1 的 schema
```

同步实现 `tools/quant/weight_packer_test.cpp`（**Single Source of Truth 双实现**）：
- 用 GoogleTest 框架
- 输入相同 .npz，输出 byte-identical .bin
- CI 自动跑 `pytest tests/test_weight_pack.py::test_python_vs_cpp_byte_identical`

### Phase 4: 精度评估（Week 3-4）

实现 `tools/quant/eval_quant_map.py`：

```bash
python tools/quant/eval_quant_map.py \
    --weights models/tiny_fpga_int8.npz \
    --val-set datasets/coco/val2017 \
    --baseline mAP_baseline_fp32 \
    --target-degradation 1.0
```

输出：

- `runs/eval_quant_map.json`：每类 AP + mAP50 + mAP50-95
- 退出码：mAP 下降 > 1.0% → 退出码 1（CI fail）

### Phase 5: QAT 回退（仅 R4 触发时）

如果 Phase 4 失败：

1. 实现 `tools/quant/qat_finetune.py`：用 `torch.ao.quantization` fake-quant
2. 重训 5-10 epoch，保持其他超参不变
3. 重新跑 Phase 3、4
4. 仍失败 → 升级 R4：stem + 检测头保留 INT16，其余 INT8

## 关键文件

| 文件 | 用途 | 状态 |
|---|---|---|
| `tools/quant/distill_from_teacher.py` | **Phase 1.5 蒸馏主入口** | 新建 |
| `tools/quant/distill_config.yaml` | 蒸馏超参 | 新建 |
| `tools/quant/distill_losses.py` | KD logits / feat align / spike rate loss | 新建 |
| `tools/quant/teacher_adapter.py` | 1×1 conv adapter 把 teacher 通道投影到 student | 新建 |
| `tools/quant/run_ptq.py` | PTQ 主流程 | 新建 |
| `tools/quant/fold_bn.py` | BN→conv 折叠 | 新建 |
| `tools/quant/qat_finetune.py` | QAT 回退脚本 | 新建（仅 R4） |
| `tools/quant/weight_packer.py` | Python 打包 | 新建 |
| `tools/quant/weight_packer_test.cpp` | C++ 打包（验证 byte-identical） | 新建 |
| `tools/quant/eval_quant_map.py` | mAP 评估 | 新建 |
| `tests/test_weight_pack.py` | 契约 1 自动验证 | 新建 |
| `models/tiny_fpga_fp32_distilled.pt` | Phase 1.5 主交付物 | 新建 |
| `models/tiny_fpga_int8.npz` | Phase 3 主交付物 | 新建 |
| `tools/fpga/numpy_reference.py` | 参考：conv2d_bn 数值流 | 复用 |
| `convert_integer_to_binary.py` | 参考：expand_tensor_cumulative | 复用 |

## Risk Handlers

| 风险 | 触发 | 处理 |
|---|---|---|
| **R4 mAP 下降 > 1%** | `eval_quant_map.py` 退出码 1 | (a) Phase 5 QAT; (b) stem/head INT16; (c) 升级到 D1 协商精度阈值放宽 |
| **R8 蒸馏不收敛** | 30 epoch 后 `mAP_student_distilled` < 18.0 | (a) 把 spike_rate_loss 权重从 0.3 → 0.0（先放掉脉冲对齐约束）；(b) feat_align 仅保留 layer_08 sppf 一个对齐点；(c) 加大 student 容量到宽 0.25（与 B1 协商资源预算上调） |
| **R9 蒸馏 vs scratch 提升 < 2 mAP** | 蒸馏白做 | (a) 检查 adapter 初始化：用 teacher pretrained head 的 1×1 平均值做 warm-start；(b) 改 channel align 从 1×1 投影到 cosine-similarity-based channel selection（取 teacher 中与 student 最相似的 channel 子集） |
| **R10 teacher 输入分辨率不匹配** | teacher 是 640×640 训的，256×256 forward 时 mAP 暴跌 | 不要直接 256 forward；走 "teacher 在 640 forward → P4 张量 avgpool 4× 到 16×16" 的路径，已在 distill_config.yaml `teacher_inference_mode: avgpool_from_640` 默认启用 |
| **校准图选择不当** | PTQ mAP 不稳，多次运行结果差 > 0.5% | 用 COCO val 子采样 100 张，固定 random seed = 42 |
| **fold_bn 数值溢出** | cosine sim < 0.999 | per-channel scale 不要超 INT32 范围；用 `numpy_reference.py` 验证 |

## 交接清单

### 给 A2（Phase 1.5 完成时）

✅ `models/tiny_fpga_fp32_distilled.pt` 存在  
✅ `runs/distill/distill_summary.json` 中 `mAP_student_distilled` ≥ 18.0  
✅ 通知 A2 改用蒸馏后的 `.pt` 抽中间层 hook（替代 `tiny_fpga_fp32.pt`）

### 给 B1（Phase 3 完成时）

✅ `models/tiny_fpga_int8.npz` 存在  
✅ `pytest tests/test_weight_pack.py` 全 pass  
✅ `python tools/quant/eval_quant_map.py` mAP 下降 ≤ 1.0%（相对蒸馏后 student baseline）  
✅ 权重 SHA256 记入 `docs/reports/M1_report.md`  
✅ 与 B1 同步：通知 layer 00、01 的张量 dtype / shape

### 给 D1（M1 月报）

✅ `runs/baseline_summary.json` 中三个数字：`mAP_teacher_fp32` / `mAP_student_init_fp32` / `mAP_student_distilled`  
✅ `runs/distill/distill_log.csv`（loss 曲线）

## 参考资料

- `tools/fpga/numpy_reference.py` 行 75-85 (`mem_update`) 与 行 230-280 (`conv2d_bn`)
- `ultralytics/nn/modules/yolo_spikformer_bin.py` 行 43-70 (`expand_tensor_cumulative`)
- Xilinx UG1037 Vivado AXI 指南（理解 256-bit pack 顺序）
- 蒸馏参考：FitNets (Romero 2014, intermediate feature hint) + Distilling YOLO (Mehta 2018, detection-head KD) + KD for SNN (Kushawaha 2021, spike-rate alignment)
