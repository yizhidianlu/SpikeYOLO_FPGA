# A2-W11 mAP Gap Diagnosis (2026-05-15)

## TL;DR

**Distill 21 epoch 后 tiny_fpga mAP50-95 = 1.6% (teacher 31.5% @ 256)** — gap 真因不是 distill 配置不好或训练不够长，而是**三个独立 bug 叠加**：

1. **Silent random-init fallback** (主因): `_build_student` 的 try/except 静默吞掉 size mismatch，distill 实际从随机初始化起跑 21 epoch
2. **"tiny_fpga_fp32.pt" 命名误导**: 这个文件实为 23M teacher 的副本，不是 1.16M tiny_fpga，load 必然 size mismatch
3. **没有 supervised pretrain entry point**: 项目没有产生过真正的 tiny_fpga FP32 baseline ckpt，所有 distill 假定的"pretrained init"从来不存在

修复方向：fix bug + 写 supervised pretrain 脚本 + 走 5-class subset 路线（详见 `polished-watching-deer.md` plan）。

---

## 诊断证据

### 实验 A vs D（关键 bombshell）

| label | imgsz | mAP50 | mAP50-95 | P | R | params |
|---|---:|---:|---:|---:|---:|---:|
| A teacher SpikeYOLO_23.1M_T1D4 @ 256 | 256 | 0.454 | 31.5 % | 0.628 | 0.420 | 23.15 M |
| **D "tinyfpga base FP32"** (`models/tiny_fpga_fp32.pt`) | **256** | **0.454** | **31.5 %** | **0.628** | **0.420** | **23.15 M ⚠** |

**A 和 D 数字完全相同**——`tiny_fpga_fp32.pt` 跟 teacher 是同一个文件（或精确副本），不是 1.16M tiny_fpga FP32。

Ultralytics summary log 直接 dump 出 architecture：
```
D_tinyfpga_baseFP : snn_YOLOv8s summary           — 621 layers, 23,153,024 params, 136.9 GFLOPs ← 23M
C_tinyfpga_random : snn_YOLOv8_tiny_fpga summary  — 190 layers,  1,155,240 params,   8.4 GFLOPs ← 真 1.16M
```

### Code 路径（探索代理已确认）

`tools/quant/distill_from_teacher.py:262-276` 修复前：

```python
def _build_student(cfg_path: Path, init_path: Path, device):
    model = YOLO(str(cfg_path), task="detect").model    # build 1.16M tiny_fpga
    if init_path and init_path.exists():
        try:
            ckpt = torch.load(init_path, ...)            # 实为 23M teacher
            sd = ckpt.get("model", ckpt).state_dict()
            miss, unx = model.load_state_dict(sd, strict=False)  # size mismatch RAISE
            print(...)
        except Exception as e:                            # <-- 静默吞错
            print(f"[student] WARN: init load failed ({e!r}); using fresh weights")
    return model.to(device)
```

每次 distill 都打印一行 WARN，但训练继续从随机权重起跑。21 epoch 后 mAP 1.6%。

### 训练曲线（mAP 持续上涨，未饱和）

| epoch | mAP50 | mAP50-95 | P | R |
|---:|---:|---:|---:|---:|
| 10 | 1.84 % | 0.77 % | 6.9 % | 14.3 % |
| 15 | 2.56 % | 1.17 % | 85.6 % | 2.9 % |
| 20 | 3.05 % | 1.46 % | 80.7 % | 4.0 % |
| 21 | 3.32 % | 1.63 % | 85.2 % | 4.0 % |

mAP50-95 每 5 epoch 涨 0.3-0.4%，没饱和；但起点是 random，30 ep 也只能到 ~3%。

### 容量天花板

文献基准（Phase 1 探索）：
- YOLOv8n 3.2M @ 640 = 37.3% mAP50-95
- YOLOv8n @ 256 估计 ~28-32%
- NanoDet-Plus 1.8M @ 416 = 34.1%（params 最接近）
- **1.16M @ 256 @ COCO 80-class 估计上限 12-20%**

即使修了 bug + 跑 supervised pretrain，80-class 路线天花板也只能 ~15-20%，离 demo 视觉效果（30%+）有距离。**用户选择 5-class subset 路线**。

---

## 已修复

| 文件 | 改动 |
|---|---|
| `tools/quant/distill_from_teacher.py` | `_build_student` 重写：load_state_dict 前先 verify shape；不匹配则 raise（除非显式 `--allow-random-init`），同时打印 coverage 比例 + shape mismatch 数量 |
| 同上 | `_cb_save_epoch_ckpt` 加 `ema_state_dict` 字段保存 |
| 同上 (argparse) | 加 `--allow-random-init` flag |
| `tools/quant/_eval_ep_oneshot.py` | 加 `--use-ema` flag，eval 时优先加载 EMA weights |

---

## 后续

详见 plan: `C:\Users\jielu\.claude\plans\polished-watching-deer.md`

走 5-class subset 路线 (person / bottle / cup / cell phone / book)：
- Phase A: label filter + supervised pretrain (3-7 h GPU)
- Phase B (conditional): KD distill from real pretrained init
- Phase C: PTQ + 板上 W11 byte-exact

——记于 2026-05-15，A2-W11
