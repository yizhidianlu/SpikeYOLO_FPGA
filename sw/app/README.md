# sw/app — End-to-end Demo (C3 Agent)

**Owner**: C3 Application Agent — see [`docs/AGENT_PLAYBOOKS/C3_application.md`](../../docs/AGENT_PLAYBOOKS/C3_application.md)

## Purpose

Full pipeline binary running on ZYBO Z7-20:

```
V4L2 USB camera → letterbox 256×256 → spike_accel inference
   → NMS post-processing → DRM HDMI 1080p overlay with bboxes
```

Targets **30+ FPS** continuous, **CPU < 60%**, COCO val100 IoU pass rate ≥ 95%.

## Layout

```
src/
  main.cpp                 Application entry
  v4l2_capture.cpp         MMAP zero-copy YUYV capture
  preproc.cpp              YUV→RGB + letterbox + INT8 quantization
  postproc_nms.cpp         NMS + bbox decode
  drm_display.cpp          libdrm page-flip
  hdmi_overlay.cpp         bbox draw + OSD font
  fps_meter.cpp            EMA FPS + jitter
  ringbuf.h                Lock-free SPSC for inter-thread
configs/runtime.yaml       Display thresholds, conf/iou settings, fonts
scripts/
  run_on_board.sh          Board-side launcher with options
  flash_demo.sh            Build + scp + restart demo
CMakeLists.txt             Cross-compile for armv7l
```

## Build (cross-compile from PC)

```bash
mkdir -p build && cd build
cmake .. -DCMAKE_TOOLCHAIN_FILE=../cmake/zynq_toolchain.cmake
cmake --build . -j
scp spike_accel_demo root@zybo:/opt/
```

## Run on board

```bash
ssh root@zybo "/opt/run_on_board.sh"           # 默认 30 FPS demo
ssh root@zybo "/opt/run_on_board.sh --bench"   # 性能基准模式
```

## Acceptance gates per milestone

| Milestone | FPS | CPU | val100 IoU pass | Other |
|---|---|---|---|---|
| M4 | ≥ 10 | < 80% | ≥ 95% | 1 h no-hang |
| M5 | 25–30 | < 70% | ≥ 95% | jitter < 8% |
| M6 | **≥ 30 (10 min)** | **< 60%** | **≥ 95%** | 24 h aging |

## References

- [`realtime_detect.py`](../../realtime_detect.py) — algorithmic reference for letterbox / NMS / SNN visualization
- libdrm documentation
- Linux V4L2 user-space API
