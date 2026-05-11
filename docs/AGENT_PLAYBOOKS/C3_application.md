---
id: C3
name: application
group: C
milestones: [M4, M5, M6]
inputs_glob:
  - "sw/sdk/include/spike_accel.h"
  - "sw/sdk/build/libspike_accel.so"
  - "realtime_detect.py"
  - "models/tiny_fpga_int8.bin"
  - "tests/golden/coco_val100.json"
outputs_glob:
  - "sw/app/src/**/*.cpp"
  - "sw/app/src/**/*.h"
  - "sw/app/configs/runtime.yaml"
  - "sw/app/scripts/run_on_board.sh"
  - "sw/app/CMakeLists.txt"
contracts:
  produces: []
  consumes: [C5, C6]
acceptance_tests:
  - "cd sw/app/build && cmake --build . --target test"
  - "ssh root@zybo 'cd /opt/spike && ./run_on_board.sh --bench-fps --duration 600'"
  - "python tests/regression/coco_val_on_board.py --board zybo --pass-rate 0.95"
status: pending
owner: ""
---

# C3 Application Agent Playbook

## Mission

实现板上端到端 demo：**USB 摄像头 → letterbox 预处理 → spike_accel 推理 →
NMS 后处理 → HDMI 1080p overlay bbox 输出**，目标 30+ FPS 稳定运行 10 分钟。

## 关键技术决策

| 维度 | 选择 | 理由 |
|---|---|---|
| 摄像头 API | **V4L2 直接调用 + MMAP zero-copy** | 不走 OpenCV `VideoCapture`，避免冗余 copy |
| 视频格式 | **YUYV 640×480@30**，YUV→RGB on PS | UVC 普遍支持，FPGA 端不需 YUV 处理逻辑 |
| 预处理 | letterbox 256×256 + INT8 量化（C++ 移植自 `realtime_detect.py`） | 与训练侧对齐 |
| 后处理 | NMS C++ 实现（INT8 score + FP32 bbox） | 借鉴 ultralytics ops，但精简 |
| 显示 | **DRM dumb buffer + libdrm**（不走 fbdev） | 现代 Linux 推荐路径，零拷贝 |
| 多线程 | 3 线程：cap + infer + display，无锁 ringbuffer | 流水化 30 FPS |
| FPS meter | EMA 平滑 + HDMI 右上角 OSD | 调试用 |

## 工作流

### Phase 1: 串行 baseline（M4 Week 1-2）

单线程版本，先打通 pipeline 正确性：

```cpp
// sw/app/src/main.cpp (M4 版本)
int main() {
    sa_handle_t accel;
    sa_open(&accel);
    sa_load_weights(accel, "/lib/firmware/tiny_fpga_int8.bin");

    V4L2Capture cam("/dev/video0", 640, 480, V4L2_PIX_FMT_YUYV);
    DRMDisplay  disp("/dev/dri/card0", 1920, 1080);

    while (running) {
        auto raw = cam.grab();                        // YUYV
        auto rgb_letterboxed = preproc(raw, 256);     // INT8 RGB 256x256
        int8_t feat[FEAT_SIZE];
        sa_infer(accel, rgb_letterboxed.data(), feat, 100);
        auto boxes = postproc_nms(feat, 0.25f, 0.45f);
        auto canvas = upscale_letterbox_inverse(raw, boxes);
        disp.push(canvas);
    }
}
```

目标：单核串行 **≥ 10 FPS @ 1080p HDMI 输出**。

### Phase 2: 多线程双缓冲（M5 Week 2-3）

```
cap_thread:    V4L2 → ringbuf_in  (depth=4)
infer_thread:  ringbuf_in → sa_infer_async → ringbuf_out
display_thread: ringbuf_out + draw bbox → DRM page-flip
```

关键技术点：

- **DMA buffer pre-allocate**：sa_open 时一次性 mmap 8 块 CMA buffer，避免每帧 syscall
- **double-buffer DRM**：page-flip 而非 memcpy，VBLANK 同步
- **lock-free SPSC ringbuffer**：基于 `std::atomic<int>` head/tail

### Phase 3: 30 FPS 稳定化（M6 Week 1-3）

1. **CPU 亲和性**：cap_thread → CPU0，infer/display → CPU1
2. **预处理 SIMD**：YUV→RGB 用 NEON intrinsics（Cortex-A9 支持 NEON）
3. **NMS 优化**：检测框数通常 < 50，C++ greedy NMS < 0.5 ms
4. **OSD 字体**：用 8×8 bitmap 字体（不依赖 libfreetype，减启动时间）
5. **温度保护**：板温 > 70°C 时降为 25 FPS，记 log

### Phase 4: 老化测试与 demo 录制（M6 Week 4）

- 24 h 老化：`run_on_board.sh --duration 86400`，记 FPS 抖动、内存、温度
- 录制 demo 视频：HDMI 输出接 capture card

## 关键文件

| 文件 | 用途 | 状态 |
|---|---|---|
| `sw/app/src/main.cpp` | 应用入口 | 新建 |
| `sw/app/src/v4l2_capture.cpp` | V4L2 MMAP 封装 | 新建 |
| `sw/app/src/preproc.cpp` | letterbox + YUV→RGB + INT8 量化 | 新建（移植自 realtime_detect.py） |
| `sw/app/src/postproc_nms.cpp` | NMS + bbox 解码 | 新建（移植自 ultralytics ops） |
| `sw/app/src/drm_display.cpp` | libdrm + page-flip | 新建 |
| `sw/app/src/hdmi_overlay.cpp` | bbox 画线 + OSD 字体 | 新建 |
| `sw/app/src/fps_meter.cpp` | EMA FPS + 抖动统计 | 新建 |
| `sw/app/src/ringbuf.h` | lock-free SPSC | 新建 |
| `sw/app/configs/runtime.yaml` | 阈值、字体、显示参数 | 新建 |
| `sw/app/scripts/run_on_board.sh` | 板上启动脚本 | 新建 |
| `sw/app/CMakeLists.txt` | 构建脚本 | 新建 |
| `realtime_detect.py` | letterbox + NMS 算法参考 | 复用 |

## Risk Handlers

| 风险 | 触发 | 处理 |
|---|---|---|
| **R3 DDR3 带宽不够（VDMA 抢占）** | FPS 抖动 > 20% | (a) HDMI 1080p → 720p; (b) framebuffer 改 RGB565; (c) `tools/perf/ddr_bw_monitor.py` 定位 |
| **R5 USB cam 帧率不稳** | dropped > 5% | (a) YUYV → MJPEG; (b) 分辨率降 320×240 上采样; (c) Pcam MIPI 备选（需 B2 加 IP） |
| **PS CPU 占用过高** | top 看 cpu > 80% | (a) NEON 优化 YUV→RGB; (b) NMS 提前 conf 过滤; (c) HDMI 字体改预渲染贴图 |
| **DRM page-flip 失败** | `drmModePageFlip` 返回 EBUSY | (a) 检查 vblank 中断使能; (b) 用 fbdev 回退路径 |

## 验收清单

✅ M4: 静态摄像头画面，HDMI 1080p 显示 bbox，≥ 10 FPS  
✅ M4: `coco_val_on_board.py` 100 张图通过率 ≥ 95%（契约 6）  
✅ M5: 稳定 25-30 FPS，CPU < 60%  
✅ M6: **30+ FPS 连续 10 min**，FPS std/mean < 5%  
✅ M6: 24 h 老化无 hang / 无内存泄漏 / 温度 < 70°C  
✅ Demo 视频 + 一键 SD 卡烧录脚本

## 参考资料

- `realtime_detect.py`（letterbox、NMS、可视化算法**直接移植**）
- `ultralytics/utils/ops.py:non_max_suppression`（NMS 经典实现）
- Xilinx UG1144 PetaLinux Tools Documentation（DRM/KMS 章节）
- linux/Documentation/userspace-api/media/v4l/v4l2.rst
