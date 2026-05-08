# -*- coding: utf-8 -*-
"""
GPU + RGB 实时 SpikeYOLO 检测脚本

用法:
    # 摄像头 (device id = 0)
    python realtime_detect.py --weights spikeyolo_23M_T1.pt --source 0

    # 视频文件
    python realtime_detect.py --weights spikeyolo_23M_T1.pt --source video.mp4

    # RTSP 流
    python realtime_detect.py --weights spikeyolo_23M_T1.pt --source rtsp://...

    # 单张图片 / 图片目录
    python realtime_detect.py --weights spikeyolo_23M_T1.pt --source image.jpg
    python realtime_detect.py --weights spikeyolo_23M_T1.pt --source ./imgs/

依赖:
    - PyTorch + CUDA
    - ultralytics (项目内置)
    - opencv-python
    - 权重文件: 从 README.md 里的 Google Drive 链接下载
      推荐 23M T=1 权重 (速度/精度平衡)
"""

import argparse
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np
import torch

from ultralytics import YOLO


def parse_args():
    p = argparse.ArgumentParser(description="SpikeYOLO GPU+RGB real-time detection")
    p.add_argument("--weights", type=str, required=True,
                   help="SpikeYOLO .pt 权重路径 (如 23M T=1)")
    p.add_argument("--source", type=str, default="0",
                   help="视频源: 摄像头 id / 视频文件 / RTSP / 图片路径")
    p.add_argument("--imgsz", type=int, default=640, help="推理输入尺寸")
    p.add_argument("--conf", type=float, default=0.25, help="置信度阈值")
    p.add_argument("--iou", type=float, default=0.45, help="NMS IoU 阈值")
    p.add_argument("--device", type=str, default="0",
                   help='GPU id (如 "0") 或 "cpu"')
    p.add_argument("--half", action="store_true",
                   help="使用 FP16 (需 CUDA)，可进一步降延迟")
    p.add_argument("--warmup", type=int, default=5, help="预热帧数 (不计入 FPS)")
    p.add_argument("--save", type=str, default="",
                   help="保存输出视频的路径，留空不保存")
    p.add_argument("--no-show", action="store_true", help="不显示窗口")
    p.add_argument("--debug-snn", action="store_true",
                   help="打印模型层类型, 并 hook LIF 输出统计脉冲稀疏度 (确认是 SNN 在跑)")
    return p.parse_args()


def resolve_source(src: str):
    """把 --source 字符串解析成 cv2.VideoCapture 能接受的形式。"""
    if src.isdigit():
        return int(src)
    return src


def is_image_path(src: str) -> bool:
    exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
    return Path(src).suffix.lower() in exts


# ---------------- SNN debug 工具 ----------------

# 全局存放 LIF hook 的统计 (滑动窗口)
_lif_stats = {"sparsity": deque(maxlen=200), "fired": 0, "total": 0,
              "name": None, "shape": None}


def _lif_hook(_module, _inp, out):
    """统计 LIF 输出中非零 (脉冲) 元素的比例。"""
    if not isinstance(out, torch.Tensor):
        return
    with torch.no_grad():
        fired = (out != 0).sum().item()
        total = out.numel()
        _lif_stats["fired"] += fired
        _lif_stats["total"] += total
        _lif_stats["sparsity"].append(fired / max(total, 1))
        _lif_stats["shape"] = tuple(out.shape)


def install_snn_debug(model):
    """打印模型每层类型 + 在第一个 LIF 神经元上挂 hook 统计脉冲稀疏度。"""
    # 1. 打印层级结构
    layers = list(model.model.model)
    print("\n[debug-snn] 模型层类型分布:")
    type_count = {}
    for i, m in enumerate(layers):
        name = type(m).__name__
        type_count[name] = type_count.get(name, 0) + 1
    for name, n in sorted(type_count.items(), key=lambda kv: -kv[1]):
        marker = " <-- SNN 模块" if any(k in name for k in
                                       ("Spike", "MS_", "mem_update", "LIF")) else ""
        print(f"  {name:30s}  x{n}{marker}")

    spike_layers = [type(m).__name__ for m in layers
                    if any(k in type(m).__name__ for k in ("Spike", "MS_"))]
    if spike_layers:
        print(f"[debug-snn] ✓ 检测到 {len(spike_layers)} 个 SNN 风格层, "
              f"前几个: {spike_layers[:5]}")
    else:
        print("[debug-snn] ✗ 未检测到 SNN 风格层 — 这不像是 SpikeYOLO 权重")

    # 2. 找第一个 LIF 神经元 (类名为 mem_update) 挂 hook
    target = None
    target_name = None
    for full_name, sub in model.model.named_modules():
        if type(sub).__name__ == "mem_update":
            target, target_name = sub, full_name
            break

    if target is None:
        print("[debug-snn] 没找到 mem_update LIF 层, 跳过脉冲稀疏度统计")
        return

    target.register_forward_hook(_lif_hook)
    _lif_stats["name"] = target_name
    print(f"[debug-snn] ✓ 已 hook LIF 层: {target_name}")
    print("[debug-snn] HUD 会显示 SpikeRate (该 LIF 输出的脉冲发放率, 普通 ANN 不会有这个数)")

    # 多层热力图可视化
    viz = LIFVisualizer(model, num_layers=3, panel_w=220)
    print()
    return viz


def lif_summary():
    """返回当前滑窗内的脉冲发放率 (0~1) 与 hook 形状, 没数据返回 None。"""
    if not _lif_stats["sparsity"]:
        return None
    rate = sum(_lif_stats["sparsity"]) / len(_lif_stats["sparsity"])
    return rate, _lif_stats["shape"], _lif_stats["name"]


class LIFVisualizer:
    """挂在多个 LIF 层上, 把脉冲张量渲染成热力图条 (右侧画板)。

    每层一格: 沿 T (时间步) 和 C (通道) 求和后得到 (H, W) 空间脉冲计数图,
    伪彩之后并排堆叠, 越亮表示该位置被发射的脉冲越多。
    """

    def __init__(self, model, num_layers=3, panel_w=220):
        self.panel_w = panel_w
        self.tensors = {}  # name -> 最近一次 LIF 输出
        self.rate_history = {}  # name -> deque, 用于角标 sparkline
        self.layer_names = []

        lif_modules = [(n, m) for n, m in model.model.named_modules()
                       if type(m).__name__ == "mem_update"]
        if not lif_modules:
            return

        # 在浅 / 中 / 深处各取一个 LIF, 平均分布
        n = min(num_layers, len(lif_modules))
        idxs = [int(round(i * (len(lif_modules) - 1) / max(n - 1, 1)))
                for i in range(n)]
        seen = set()
        for idx in idxs:
            if idx in seen:
                continue
            seen.add(idx)
            name, mod = lif_modules[idx]
            short = f"L{idx}/{len(lif_modules)-1}:{name.split('.')[-2] if '.' in name else name}"
            self.layer_names.append((name, short))
            self.rate_history[name] = deque(maxlen=120)
            mod.register_forward_hook(self._make_hook(name))

        print(f"[debug-snn] 可视化 hook 已挂在 {len(self.layer_names)} 个 LIF 层:")
        for name, short in self.layer_names:
            print(f"           - {short}  ({name})")

    def _make_hook(self, name):
        def hook(_m, _inp, out):
            if isinstance(out, torch.Tensor):
                self.tensors[name] = out.detach()
        return hook

    @staticmethod
    def _tensor_to_spatial(t: torch.Tensor) -> np.ndarray:
        """(T,B,C,H,W) 或 (B,C,H,W) → (H,W) 脉冲计数 numpy。"""
        with torch.no_grad():
            if t.ndim == 5:           # (T, B, C, H, W) → 时间步求和
                t = t.sum(dim=0)
            if t.ndim == 4:           # (B, C, H, W) → 通道求和
                t = t.sum(dim=1)
            t = t[0]                  # 取 batch 0
            return t.float().cpu().numpy()

    def render(self, target_h: int):
        """生成右侧贴图; 返回 (target_h, panel_w, 3) BGR 图。没数据返回 None。"""
        if not self.layer_names or not self.tensors:
            return None

        cell_h = target_h // len(self.layer_names)
        cells = []
        for name, short in self.layer_names:
            t = self.tensors.get(name)
            cell = np.zeros((cell_h, self.panel_w, 3), dtype=np.uint8)
            if t is not None:
                arr = self._tensor_to_spatial(t)
                rate = float((arr > 0).mean())
                self.rate_history[name].append(rate)

                mn, mx = float(arr.min()), float(arr.max())
                if mx - mn < 1e-9:
                    norm = np.zeros_like(arr, dtype=np.uint8)
                else:
                    norm = ((arr - mn) / (mx - mn) * 255).astype(np.uint8)

                heat = cv2.applyColorMap(norm, cv2.COLORMAP_JET)
                # 留 22 px 顶边给文字, 剩下放热图
                heat_h = max(cell_h - 22, 8)
                heat = cv2.resize(heat, (self.panel_w, heat_h),
                                  interpolation=cv2.INTER_NEAREST)
                cell[22:22 + heat_h] = heat

                # 顶部文字: 层名 + 当前发放率
                label = f"{short}  fire={rate * 100:.1f}%"
                cv2.putText(cell, label, (4, 16), cv2.FONT_HERSHEY_SIMPLEX,
                            0.45, (0, 0, 0), 3, cv2.LINE_AA)
                cv2.putText(cell, label, (4, 16), cv2.FONT_HERSHEY_SIMPLEX,
                            0.45, (255, 255, 255), 1, cv2.LINE_AA)

                # 底部 sparkline: 该层脉冲发放率随时间变化
                hist = list(self.rate_history[name])
                if len(hist) > 2:
                    spark_h = 18
                    sx0 = 0
                    sy0 = cell_h - spark_h
                    cv2.rectangle(cell, (sx0, sy0), (self.panel_w, cell_h),
                                  (30, 30, 30), -1)
                    pts = []
                    for i, v in enumerate(hist):
                        x = int(i * self.panel_w / max(len(hist) - 1, 1))
                        y = cell_h - 2 - int(v * (spark_h - 4))
                        pts.append((x, y))
                    for i in range(1, len(pts)):
                        cv2.line(cell, pts[i - 1], pts[i],
                                 (0, 255, 255), 1, cv2.LINE_AA)
            cells.append(cell)

        panel = np.vstack(cells)
        # 因为整除可能有 1~2 px 余量, 这里裁/补到 target_h
        if panel.shape[0] != target_h:
            panel = cv2.resize(panel, (self.panel_w, target_h),
                               interpolation=cv2.INTER_NEAREST)
        return panel


def draw_hud(frame, fps, latency_ms, det_count, device_label, spike_rate=None):
    """在画面左上角画 FPS / 延迟 / 检测框数量。"""
    text_lines = [
        f"FPS: {fps:5.1f}",
        f"Latency: {latency_ms:5.1f} ms",
        f"Detections: {det_count}",
        f"Device: {device_label}",
    ]
    if spike_rate is not None:
        text_lines.append(f"SpikeRate: {spike_rate * 100:5.2f}%  (SNN)")
    x, y = 10, 25
    for line in text_lines:
        cv2.putText(frame, line, (x, y), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(frame, line, (x, y), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (0, 255, 0), 1, cv2.LINE_AA)
        y += 22
    return frame


def run_image(model, args, device_label):
    """单张图片 / 图片文件夹的分支。"""
    results = model.predict(
        source=args.source,
        imgsz=args.imgsz,
        conf=args.conf,
        iou=args.iou,
        device=args.device,
        half=args.half,
        save=True,
        verbose=False,
    )
    out_dir = results[0].save_dir if results else "runs/detect"
    print(f"[done] 结果已保存到: {out_dir}")


def open_capture(src):
    """打开视频源。Windows 摄像头优先用 DSHOW (MSMF 容易返回全黑帧)。"""
    resolved = resolve_source(src)
    is_camera = isinstance(resolved, int)

    if is_camera:
        # 摄像头: DSHOW → MSMF → 默认后端依次回退
        backends = [
            (cv2.CAP_DSHOW, "DSHOW"),
            (cv2.CAP_MSMF, "MSMF"),
            (cv2.CAP_ANY, "ANY"),
        ]
        for backend, name in backends:
            cap = cv2.VideoCapture(resolved, backend)
            if cap.isOpened():
                # 尝试读一帧确认不是全黑
                ok, frame = cap.read()
                if ok and frame is not None and frame.mean() > 1.0:
                    print(f"[info] 摄像头后端: {name}")
                    # 把读出来的第一帧塞回去 (避免丢帧), OpenCV 没有 unread, 直接重开一次更稳
                    cap.release()
                    cap = cv2.VideoCapture(resolved, backend)
                    return cap
                cap.release()
                print(f"[warn] {name} 后端打开成功但首帧全黑/读取失败, 尝试下一个...")
            else:
                print(f"[warn] {name} 后端无法打开摄像头, 尝试下一个...")
        raise RuntimeError(f"所有后端都无法从摄像头 {src} 读到有效画面")
    else:
        cap = cv2.VideoCapture(resolved)
        if not cap.isOpened():
            raise RuntimeError(f"无法打开视频源: {src}")
        return cap


def run_stream(model, args, device_label, viz=None):
    """摄像头 / 视频 / RTSP 的实时分支。"""
    cap = open_capture(args.source)

    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or args.imgsz
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or args.imgsz
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    # writer 在拿到首帧 vis 后再懒初始化, 因为加了 SNN 面板后宽度会变
    writer = None
    writer_fourcc = cv2.VideoWriter_fourcc(*"mp4v") if args.save else None

    # 用最近 30 帧滑窗估 FPS，避免瞬时抖动
    t_window = deque(maxlen=30)
    use_cuda = args.device != "cpu" and torch.cuda.is_available()

    frame_idx = 0
    black_warned = False
    print("[info] 开始推理，按 q 退出")
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("[info] 视频流结束")
                break

            # 采集端黑帧检测: 连续读到的帧亮度极低时给一次性提示
            if not black_warned and frame_idx < 30 and frame.mean() < 1.0:
                print(f"[warn] 第 {frame_idx} 帧均值={frame.mean():.2f}, 摄像头可能未输出有效画面 "
                      f"(被占用 / 隐私权限 / 虚拟摄像头无推流)")
                black_warned = True

            if use_cuda:
                torch.cuda.synchronize()
            t0 = time.perf_counter()

            results = model.predict(
                source=frame,
                imgsz=args.imgsz,
                conf=args.conf,
                iou=args.iou,
                device=args.device,
                half=args.half,
                verbose=False,
            )

            if use_cuda:
                torch.cuda.synchronize()
            dt = time.perf_counter() - t0

            # 预热阶段不计入 FPS
            if frame_idx >= args.warmup:
                t_window.append(dt)

            r = results[0]
            vis = r.plot()
            det_count = 0 if r.boxes is None else len(r.boxes)

            if len(t_window) > 0:
                avg_dt = sum(t_window) / len(t_window)
                fps = 1.0 / avg_dt if avg_dt > 0 else 0.0
                latency_ms = avg_dt * 1000.0
            else:
                fps, latency_ms = 0.0, dt * 1000.0

            spike_rate = None
            if args.debug_snn:
                summary = lif_summary()
                if summary is not None:
                    spike_rate = summary[0]
            vis = draw_hud(vis, fps, latency_ms, det_count, device_label, spike_rate)

            # 右侧拼脉冲热力图面板
            if viz is not None:
                panel = viz.render(vis.shape[0])
                if panel is not None:
                    vis = np.hstack([vis, panel])

            if args.save:
                if writer is None:
                    h, w = vis.shape[:2]
                    writer = cv2.VideoWriter(args.save, writer_fourcc, src_fps, (w, h))
                writer.write(vis)

            if not args.no_show:
                cv2.imshow("SpikeYOLO (RGB, GPU)", vis)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

            frame_idx += 1
    finally:
        cap.release()
        if writer is not None:
            writer.release()
        cv2.destroyAllWindows()

        if len(t_window) > 0:
            avg_dt = sum(t_window) / len(t_window)
            print(f"[stats] 平均延迟: {avg_dt * 1000:.2f} ms | "
                  f"平均 FPS: {1.0 / avg_dt:.2f} | "
                  f"有效帧数: {len(t_window)}")

        if _lif_stats["total"] > 0:
            overall = _lif_stats["fired"] / _lif_stats["total"]
            print(f"[debug-snn] LIF 层 {_lif_stats['name']} 累计脉冲发放率: "
                  f"{overall * 100:.2f}% "
                  f"({_lif_stats['fired']}/{_lif_stats['total']}, "
                  f"shape={_lif_stats['shape']})")


def main():
    args = parse_args()

    use_cuda = args.device != "cpu" and torch.cuda.is_available()
    if args.half and not use_cuda:
        print("[warn] --half 需要 CUDA，已降级为 FP32")
        args.half = False

    if use_cuda:
        gpu_name = torch.cuda.get_device_name(int(args.device))
        device_label = f"cuda:{args.device} ({gpu_name})"
    else:
        device_label = "cpu"
    print(f"[info] 使用设备: {device_label}")
    print(f"[info] 加载权重: {args.weights}")

    model = YOLO(args.weights)

    viz = None
    if args.debug_snn:
        viz = install_snn_debug(model)

    # 一次 dummy 前向做预热 (分配显存、编译 kernel)
    if use_cuda:
        dummy = torch.zeros(1, 3, args.imgsz, args.imgsz)
        _ = model.predict(source=dummy.numpy()[0].transpose(1, 2, 0),
                          imgsz=args.imgsz, device=args.device,
                          half=args.half, verbose=False)

    src = args.source
    if not src.isdigit() and is_image_path(src):
        run_image(model, args, device_label)
    else:
        run_stream(model, args, device_label, viz=viz)


if __name__ == "__main__":
    main()
