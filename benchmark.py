# -*- coding: utf-8 -*-
"""SpikeYOLO GPU 基准测试：加载权重 → 单图检测 → 延迟/FPS 统计。"""
import argparse
import time
from pathlib import Path

import cv2
import numpy as np
import torch

from ultralytics import YOLO


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--weights", default="models/SpikeYOLO_23.1M_T1D4.pt")
    p.add_argument("--image", default="logs_23M/val_batch0_labels.jpg",
                   help="测试图片路径（默认用项目自带验证图）")
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument("--device", default="0")
    p.add_argument("--half", action="store_true")
    p.add_argument("--warmup", type=int, default=10)
    p.add_argument("--iters", type=int, default=50)
    p.add_argument("--save", default="runs/benchmark_pred.jpg")
    return p.parse_args()


def main():
    args = parse_args()
    device = f"cuda:{args.device}" if torch.cuda.is_available() else "cpu"
    print(f"[info] device      : {device}")
    print(f"[info] weights     : {args.weights}")
    print(f"[info] image       : {args.image}")
    print(f"[info] imgsz/half  : {args.imgsz} / {args.half}")

    t0 = time.perf_counter()
    model = YOLO(args.weights)
    print(f"[info] load time   : {(time.perf_counter() - t0) * 1000:.1f} ms")

    # 一张图先试一次（完整 predict 流程，含后处理）
    t0 = time.perf_counter()
    results = model.predict(
        source=args.image,
        imgsz=args.imgsz,
        device=args.device,
        half=args.half,
        conf=0.25,
        iou=0.45,
        save=False,
        verbose=False,
    )
    print(f"[info] first infer : {(time.perf_counter() - t0) * 1000:.1f} ms (含首次编译)")

    r = results[0]
    det = 0 if r.boxes is None else len(r.boxes)
    print(f"[info] detections  : {det}")
    if det:
        for box, cls, conf in zip(r.boxes.xyxy.tolist(), r.boxes.cls.tolist(), r.boxes.conf.tolist()):
            name = r.names[int(cls)]
            print(f"  - {name:15s} conf={conf:.3f}  box={[round(v, 1) for v in box]}")

    # 保存可视化
    vis = r.plot()
    Path(args.save).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(args.save, vis)
    print(f"[info] saved vis to: {args.save}")

    # 基准：同一张图，逐次 predict
    print(f"\n[bench] warmup {args.warmup} iters ...")
    for _ in range(args.warmup):
        model.predict(source=args.image, imgsz=args.imgsz, device=args.device,
                      half=args.half, save=False, verbose=False)
    if torch.cuda.is_available():
        torch.cuda.synchronize()

    print(f"[bench] timing {args.iters} iters ...")
    dts = []
    for _ in range(args.iters):
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        t = time.perf_counter()
        model.predict(source=args.image, imgsz=args.imgsz, device=args.device,
                      half=args.half, save=False, verbose=False)
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        dts.append(time.perf_counter() - t)

    dts = np.array(dts) * 1000  # ms
    print("-" * 50)
    print(f"mean  latency : {dts.mean():7.2f} ms")
    print(f"p50   latency : {np.percentile(dts, 50):7.2f} ms")
    print(f"p95   latency : {np.percentile(dts, 95):7.2f} ms")
    print(f"min   latency : {dts.min():7.2f} ms")
    print(f"mean  FPS     : {1000 / dts.mean():7.2f}")
    print("-" * 50)

    if torch.cuda.is_available():
        mem_mb = torch.cuda.max_memory_allocated() / 1024 ** 2
        print(f"peak GPU mem  : {mem_mb:.1f} MB")


if __name__ == "__main__":
    main()
