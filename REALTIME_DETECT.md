# SpikeYOLO 实时检测脚本 (`realtime_detect.py`) 使用说明

GPU + RGB 实时推理脚本，支持摄像头 / 视频文件 / RTSP / 单图 / 图片目录，可选 SNN 调试可视化（脉冲发放率 + 多层 LIF 热力图）。

## 1. 依赖

* PyTorch + CUDA（CPU 也能跑，但很慢）
* `ultralytics`（**用仓库内置版本**，不是 pip 装的官方版——本仓库里改造过 `BaseModel._predict_once`，会调用 `spikingjelly.clock_driven.functional.reset_net` 重置膜电位）
* `spikingjelly`
* `opencv-python`（**不是** `opencv-python-headless`，否则 `cv2.imshow` 没窗口）
* `numpy`

权重文件去 README.md 里的 Google Drive 链接下载。推荐：

* `SpikeYOLO_23.1M_T1D4.pt` — 23M 参数，T=1，速度/精度平衡
* T=2 / 69M 权重也可以，只是更慢

## 2. 快速开始

```bash
# 摄像头 (device id = 0)
python realtime_detect.py --weights models/SpikeYOLO_23.1M_T1D4.pt --source 0

# 视频文件
python realtime_detect.py --weights models/SpikeYOLO_23.1M_T1D4.pt --source video.mp4

# RTSP
python realtime_detect.py --weights models/SpikeYOLO_23.1M_T1D4.pt --source rtsp://...

# 单张图片 / 图片目录
python realtime_detect.py --weights models/SpikeYOLO_23.1M_T1D4.pt --source image.jpg
python realtime_detect.py --weights models/SpikeYOLO_23.1M_T1D4.pt --source ./imgs/
```

按 `q` 退出。

## 3. 命令行参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--weights` | 必填 | SpikeYOLO `.pt` 权重路径 |
| `--source` | `0` | 摄像头 id / 视频文件 / RTSP / 图片路径 |
| `--imgsz` | `640` | 推理输入尺寸 |
| `--conf` | `0.25` | 置信度阈值 |
| `--iou` | `0.45` | NMS IoU 阈值 |
| `--device` | `0` | GPU id (`"0"`) 或 `"cpu"` |
| `--half` | False | FP16 推理（需 CUDA），降延迟 |
| `--warmup` | `5` | 预热帧数（不计入 FPS 统计） |
| `--save` | `""` | 输出视频保存路径，留空不保存 |
| `--no-show` | False | 不弹窗显示 |
| `--debug-snn` | False | 打印模型层类型 + 脉冲发放率 + 多层 LIF 热力图 |

## 4. SNN 调试模式 (`--debug-snn`)

```bash
python realtime_detect.py --weights models/SpikeYOLO_23.1M_T1D4.pt --source 0 --debug-snn
```

加这个开关后会做三件事：

### 4.1 启动时打印模型层类型分布

```
[debug-snn] 模型层类型分布:
  SpikeConv                       x32  <-- SNN 模块
  MS_ConvBlock                    x8   <-- SNN 模块
  MS_GetT                         x1   <-- SNN 模块
  SpikeDetect                     x1   <-- SNN 模块
  ...
[debug-snn] ✓ 检测到 42 个 SNN 风格层
```

如果看不到 `Spike*` / `MS_*` 这种层名，说明加载到的不是 SpikeYOLO 权重。

### 4.2 HUD 多一行 SpikeRate

画面左上角原本只显示 FPS / Latency / Detections / Device，加 `--debug-snn` 后会多一行：

```
SpikeRate:  18.42%  (SNN)
```

这是第一个 LIF 神经元（`mem_update`）输出张量中**非零元素的比例**——即脉冲发放率。普通 ANN 不会有这个数（它的激活是稠密浮点）。SpikeYOLO 典型值在 10%~30% 之间。

退出时还会再打印一次累计统计 + 张量形状（`(T, B, C, H, W)` 五维 = SNN，四维 `(B, C, H, W)` = ANN）。

### 4.3 右侧脉冲热力图面板

```
+--------------------------------+----------+
| YOLO 检测画面                  | L4: ...  |
| (含 bbox + HUD)                |  热力图  |
|                                | sparkline|
|                                +----------+
|                                | L18: ... |
|                                |  热力图  |
|                                | sparkline|
|                                +----------+
|                                | L31: ... |
|                                |  热力图  |
|                                | sparkline|
+--------------------------------+----------+
```

脚本会在浅 / 中 / 深三处的 `mem_update` LIF 上各挂一个 hook，每帧渲染一格，每格三件东西：

* **顶部文字**：层名（`L<idx>/<total>`）+ 当前帧脉冲发放率 `fire=xx.x%`
* **JET 配色热力图**：把该层 LIF 输出沿时间步 `T` 和通道 `C` 求和后得到的 `(H, W)` 空间脉冲密度图，亮处 = 该位置发放的脉冲多。会随画面里物体移动而流动——浅层贴近边缘 / 纹理，深层贴近被检测的目标位置。
* **底部黄色 sparkline**：该层脉冲发放率随时间变化（最近 120 帧），让你看到不同输入触发的脉冲活跃度起伏。

如果热力图全是均匀颜色（`min ≈ max`），说明那一层在该输入下完全不发或全发——是 SNN 的真实状态，不是 bug。

## 5. 摄像头黑屏问题排查

Win11 上跑 `--source 0` 经常画面全黑，原因和处理：

### 自动后端回退

脚本对**摄像头源**会按 `DSHOW → MSMF → ANY` 顺序尝试 OpenCV 后端，每个不仅看 `isOpened()`，还要求**首帧均值 > 1**（避开"打开成功但全黑"的坑）。启动日志里会打印实际用到的：

```
[info] 摄像头后端: DSHOW
```

这能解决 80% 的黑屏问题（MSMF 跟很多 USB 摄像头驱动不兼容，会持续返回全黑帧）。

### 黑帧告警

运行时若前 30 帧均值 < 1，会打印一次提示：

```
[warn] 第 0 帧均值=0.13, 摄像头可能未输出有效画面 (被占用 / 隐私权限 / 虚拟摄像头无推流)
```

按这个排查：

1. **被占用**：关掉 Teams、微信、OBS、浏览器 WebRTC 标签页等占用摄像头的软件。
2. **隐私权限**：Windows 设置 → 隐私和安全性 → 摄像头 → "允许桌面应用访问摄像头"开启。
3. **虚拟摄像头**：`--source 0` 可能选中了 OBS Virtual Camera，没推流时输出就是黑帧。试 `--source 1` / `--source 2`。
4. **硬件本身**：用 Win 自带"相机"应用先确认硬件正常。

### 三个后端全失败

会抛 `RuntimeError`，明确告诉你是采集端问题。

## 6. 输出文件

* `--save out.mp4`：把检测画面（含 HUD，加 `--debug-snn` 时也含右侧面板）录成 MP4。`VideoWriter` 在拿到首帧时懒初始化，自动按最终画面尺寸（含面板）开窗，不会出现帧尺寸不匹配。
* `--source` 是单图 / 图片目录时，结果落到 `runs/detect/`（YOLO 默认目录），脚本会打印实际路径。

## 7. 性能小贴士

* SNN 在 GPU 上**不会比 ANN 更快**——脉冲在 GPU 上仍按稠密浮点算。SpikeYOLO 的能效优势体现在神经形态硬件（Loihi、FPGA-SNN）。GPU 上看到的精度跟 YOLOv8 接近，正是论文要证明的事。
* `T1D4` 权重是 T=1 时间步，单次前向。换 T=2 / T=4 权重，FPS 会相应跌到 1/2 / 1/4。
* `--half` 在 CUDA 上能进一步降延迟。
* 第一次推理慢是 cuDNN 选 kernel + 显存分配，脚本已内置一次 dummy 前向预热。
