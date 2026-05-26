# A2-W11 — 5-class Subset 路线决策记录 (2026-05-15)

## TL;DR

放弃 80-class 全量精度路线，**走 5-class subset 演示路线**：
`person / cell phone / cup / bottle / book`。

理由：
- 1.16M tiny_fpga 在 COCO 80-class @ 256 imgsz 容量天花板 12-20% mAP50-95（详见 `A2_mAP_gap_diagnosis.md`）
- 即使修了 distill bug + 完美训练，全量 80-class demo 视觉效果也是"每帧检出 2-5 个目标"
- 退到 5-class subset → 1.16M 容量大幅宽松 → 估计 30-50% mAP@5class → demo 视觉效果直观

## class 选择理由

5-class 组合：

| ID | class | COCO train2017 instances | demo 场景中是否可获得 |
|---:|---|---:|---|
| 0 | person | 257,253 | ✅ 摄像头自然有 |
| 39 | bottle | 24,070 | ✅ 矿泉水瓶 |
| 41 | cup | 23,977 | ✅ 马克杯 |
| 67 | cell phone | 6,587 | ✅ 手机 |
| 73 | book | 24,342 | ✅ 书 / 杂志 |

选择依据：
1. **高频类**：person 是 instance 数最多的类（必检）；其他四类在 COCO 中也各有 20K+ instances（cell phone 偏少但仍可学）
2. **桌面办公场景适配**：用户在书桌前演示时，这 5 类都触手可及
3. **视觉区分度高**：5 个类别形状/大小差异大，不容易互相混淆，对 1.16M 容量模型友好
4. **demo 故事好讲**：「这是一个能在 FPGA 实时识别常见桌面物品的低功耗 SNN 检测器」

## 实现策略：不动 HLS / Vivado / nc=80

**关键设计选择**：训练 yaml 保持 `nc=80` 不变，detection head 仍输出 80 维。通过 **label filter** 让 5 类外的所有 instances 在训练集中消失。

**为什么不直接 nc=5**：
- HLS IP `hw/hls/include/dtypes.h` 把 `SA_NC=80` 写死，改 nc 需要重 csynth + 重 Vivado bitstream（~1 h + LUT/DSP 可能 overflow，因为当前已 75.7% LUT / 90% DSP）
- v12b bitstream 已经 R2 PASS，M3 已 close — 不动
- PTQ + weight_packer 是 shape-adaptive 的，nc=80 不变也能跑

**模型自然学到什么**：
- 5 类的 detection head channel 学到合理 conf score
- 其他 75 类的 channel 在训练集中**完全没看过任何 instance** → 学会 "always background"（conf score 趋近 0）
- 推理时这 75 维 channel 实际上对 NMS 没贡献

**软件后处理强制 class filter**（兜底，防止 75 维误触发）：
- `sw/app/src/postproc_nms.cpp` NMS 时把 75 维 conf 直接 mask 成 0
- 只接受 5 个 class id 的 detection 进入 final bbox 列表
- 这步是 Phase C C4 工作

## 预期精度（粗略估算）

| 阶段 | 模型 / 训练 | 估计 mAP@5class | 备注 |
|---|---|---:|---|
| 现状（80-class random init distill 21ep） | tiny_fpga 1.16M | 1.6% (80-class) | basline，全混乱 |
| Phase A (supervised pretrain 30ep, no distill) | tiny_fpga 1.16M, real init | 20-35 % | 5 类容量集中后预期跳升 |
| Phase B (with distill from teacher, optional) | 同上 + KD | 30-50 % | +5-15% 来自 KD 提示 |

具体数字要等 Phase A 结果。如 Phase A 达到 ≥ 25% → 进 Phase B；< 15% 就跳到 PTQ + 板上验证（Phase C）。

## 时间盒

- Phase A: 5-class instance 量约为全量 ~30% （主要 person 占大头），训练 wall time 估计 **4-7 h GPU**（比 80-class 全量训练快很多）
- 修 bug + 写脚本：~1 h
- 总：≤ 8 h 拿到第一个真实可部署 ckpt

## Demo 视觉效果预期

桌面场景实拍：
- 用户坐在摄像头前 → 框 person ✓
- 桌上一杯咖啡 → 框 cup ✓
- 旁边一个手机 → 框 cell phone（容易，但可能 conf 较低因训练样本少）
- 一本书 → 框 book ✓
- 一瓶矿泉水 → 框 bottle ✓

预期每帧 3-5 个 bbox，bbox 抖动 ≤ 5 pixel/frame，类别正确率 ≥ 80%。**视觉效果远好于 80-class 全量 mAP 1.6% 时"基本不检出任何东西"的局面**。

——记于 2026-05-15，A2-W11
