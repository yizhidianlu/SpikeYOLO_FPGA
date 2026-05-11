# -*- coding: utf-8 -*-
"""
SpikeYOLO GPU 环境自检脚本
运行: python check_env.py
"""
import importlib
import sys


def check(name, importer):
    try:
        mod = importer()
        ver = getattr(mod, "__version__", "unknown")
        print(f"[ok]  {name:20s} {ver}")
        return mod
    except Exception as e:
        print(f"[MISS] {name:20s} {e}")
        return None


def main():
    print(f"Python: {sys.version.split()[0]}")
    print("-" * 60)

    torch = check("torch", lambda: importlib.import_module("torch"))
    check("torchvision", lambda: importlib.import_module("torchvision"))
    check("opencv-python", lambda: importlib.import_module("cv2"))
    check("numpy", lambda: importlib.import_module("numpy"))
    check("ultralytics", lambda: importlib.import_module("ultralytics"))
    check("spikingjelly", lambda: importlib.import_module("spikingjelly"))
    check("timm", lambda: importlib.import_module("timm"))

    print("-" * 60)
    if torch is None:
        return
    print(f"CUDA available       : {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"CUDA version (torch) : {torch.version.cuda}")
        print(f"cuDNN version        : {torch.backends.cudnn.version()}")
        print(f"GPU count            : {torch.cuda.device_count()}")
        for i in range(torch.cuda.device_count()):
            props = torch.cuda.get_device_properties(i)
            mem = props.total_memory / (1024 ** 3)
            print(f"  [{i}] {props.name}  ({mem:.1f} GB)")

    print("-" * 60)
    print("权重下载 (README.md):")
    print("  23M  T=1 D=4 : https://drive.google.com/drive/folders/1c5p09ZRCFeK1M5wH6zQduJltZalMzQkZ")
    print("  69M  T=1 D=4 : https://drive.google.com/file/d/1rmcUMJztbjFFbbVqW8xwgshKNZel1psZ")
    print("  binary 23M   : https://drive.google.com/file/d/1YQ29eDUfmaze2jl_UREX4Zeb1u8tpHfl")
    print("把 .pt 放到当前目录，然后运行:")
    print("  python realtime_detect.py --weights spikeyolo_23M_T1.pt --source 0")


if __name__ == "__main__":
    main()
