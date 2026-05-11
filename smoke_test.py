# -*- coding: utf-8 -*-
"""冒烟测试：验证环境、GPU、关键库和 SpikeYOLO 内部模块能正常工作。"""
import sys
import traceback

OK = "[ok]  "
ER = "[ERR] "


def step(name, fn):
    print(f"--> {name}")
    try:
        result = fn()
        print(OK + (result or "done"))
        return True, result
    except Exception as e:
        print(ER + f"{type(e).__name__}: {e}")
        traceback.print_exc()
        return False, None


def test_torch():
    import torch
    msg = f"torch={torch.__version__}, CUDA={torch.cuda.is_available()}"
    if torch.cuda.is_available():
        msg += f", GPU={torch.cuda.get_device_name(0)}, cap={torch.cuda.get_device_capability(0)}"
    return msg


def test_cuda_compute():
    import torch
    if not torch.cuda.is_available():
        return "CUDA unavailable, skipped"
    x = torch.randn(256, 256, device="cuda")
    y = x @ x.T
    torch.cuda.synchronize()
    return f"GPU matmul ok, out.sum={y.sum().item():.2f}"


def test_timm_old_api():
    from timm.models.registry import register_model
    from timm.models.layers import to_2tuple, trunc_normal_, DropPath
    import timm
    return f"timm={timm.__version__}, old API accessible"


def test_spikingjelly_clock_driven():
    from spikingjelly.clock_driven.neuron import MultiStepLIFNode, MultiStepParametricLIFNode
    from spikingjelly.clock_driven import layer
    from importlib.metadata import version
    return f"spikingjelly={version('spikingjelly')}, clock_driven.* ok"


def test_spikeyolo_import():
    import torch
    from ultralytics.nn.modules.yolo_spikformer import mem_update, MultiSpike4
    neuron = mem_update()
    x = torch.randn(1, 1, 3, 16, 16)
    y = neuron(x)
    return f"mem_update forward ok, in={tuple(x.shape)}, out={tuple(y.shape)}"


def test_spikeyolo_model_yaml():
    from ultralytics import YOLO
    m = YOLO("ultralytics/cfg/models/v8/snn_yolov8.yaml", task="detect")
    n_params = sum(p.numel() for p in m.model.parameters())
    return f"YAML model built, params={n_params / 1e6:.2f}M"


def test_gpu_forward():
    import torch
    from ultralytics import YOLO
    if not torch.cuda.is_available():
        return "CUDA unavailable, skipped"
    m = YOLO("ultralytics/cfg/models/v8/snn_yolov8.yaml", task="detect")
    m.model.cuda().eval()
    x = torch.randn(1, 3, 640, 640, device="cuda")
    with torch.no_grad():
        out = m.model(x)
    torch.cuda.synchronize()
    shapes = [tuple(o.shape) if hasattr(o, "shape") else "list" for o in (out if isinstance(out, (list, tuple)) else [out])]
    return f"GPU forward ok, output shapes={shapes}"


def main():
    print("=" * 70)
    print(f"Python: {sys.version.split()[0]} | Platform: {sys.platform}")
    print("=" * 70)

    results = []
    results.append(step("torch + CUDA", test_torch))
    results.append(step("GPU compute (sm_120 kernel)", test_cuda_compute))
    results.append(step("timm 旧 API", test_timm_old_api))
    results.append(step("spikingjelly clock_driven", test_spikingjelly_clock_driven))
    results.append(step("SpikeYOLO mem_update neuron", test_spikeyolo_import))
    results.append(step("SpikeYOLO 模型 YAML 构建", test_spikeyolo_model_yaml))
    results.append(step("SpikeYOLO GPU 前向", test_gpu_forward))

    print("=" * 70)
    passed = sum(1 for ok, _ in results if ok)
    print(f"通过 {passed}/{len(results)} 项")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
