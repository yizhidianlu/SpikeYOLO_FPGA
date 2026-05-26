# SpikeYOLO_FPGA — Edge Deployment of SpikeYOLO on Xilinx Zynq-7020

[![numpy_regress](https://github.com/yizhidianlu/SpikeYOLO_FPGA/actions/workflows/numpy_regress.yml/badge.svg)](https://github.com/yizhidianlu/SpikeYOLO_FPGA/actions/workflows/numpy_regress.yml)
[![hls_smoke](https://github.com/yizhidianlu/SpikeYOLO_FPGA/actions/workflows/hls_smoke.yml/badge.svg)](https://github.com/yizhidianlu/SpikeYOLO_FPGA/actions/workflows/hls_smoke.yml)
[![board_nightly](https://github.com/yizhidianlu/SpikeYOLO_FPGA/actions/workflows/board_nightly.yml/badge.svg)](https://github.com/yizhidianlu/SpikeYOLO_FPGA/actions/workflows/board_nightly.yml)

> End-to-end FPGA deployment of the ECCV 2024 Best-Paper-Candidate **SpikeYOLO** SNN detector onto a **Digilent ZYBO Z7-20** (Xilinx XC7Z020), targeting **1080p @ 30 FPS** USB-camera → spike accelerator → HDMI output, with **≤ 1 pp mAP** degradation versus the original FP32 checkpoint.

---

## 项目简介 / Project Overview

**English** — This repository takes the published `SpikeYOLO_23.1M_T1D4.pt` checkpoint (Luo et al., ECCV 2024, [BICLab/SpikeYOLO](https://github.com/BICLab/SpikeYOLO)) and turns it into a working low-power edge device. The pipeline distills the 23M-parameter teacher into a fully-int8, width-0.1875 student that synthesises onto a single XC7Z020 die, drives a real spike accelerator (5 × m_axi DDR3 masters, AXI-Lite control), and feeds bit-exact detections back to the PS for HDMI display. The full toolchain — quantization-aware distillation, Vitis HLS C++ kernels, Vivado block design, PetaLinux runtime, UIO driver — lives in this one repo with reproducible scripts for every stage.

**中文** — 本项目把 ECCV 2024 Best Paper Candidate 论文《Integer-Valued Training and Spike-Driven Inference Spiking Neural Network for High-performance and Energy-efficient Object Detection》(Luo et al., [BICLab/SpikeYOLO](https://github.com/BICLab/SpikeYOLO)) 发布的 23M 参数 `SpikeYOLO_23.1M_T1D4.pt` 模型，工程化部署到 **Digilent ZYBO Z7-20** 边缘开发板（Xilinx XC7Z020 SoC）。完整链路包括知识蒸馏到 tiny-fpga 学生模型、PTQ INT8 量化、Vitis HLS 加速核 (5 个 m_axi DDR3 master + AXI-Lite 控制)、Vivado 2024.1 block design、PetaLinux 运行时、UIO 驱动。目标是 1080p @ 30 FPS USB 摄像头 → spike accelerator → HDMI 实时演示，mAP 相对论文 baseline 退化 ≤ 1 pp。

## Why this project

SpikeYOLO 论文证明 SNN 在 COCO 上能达到 66.2% mAP@50，但发布的 23M / 69M checkpoint 仍是 GPU-friendly FP32 模型。把它真正放到嵌入式边缘设备上需要解决：

- **模型瘦身**：23M FP32 → ~1.5M INT8 + 抹掉 reparam conv，宽度 0.1875 width-multiplier
- **整数化推理**：BN 折叠 + per-channel out_shift 替代浮点 scale，全 INT8 forward
- **PE 阵列下沉到 HLS**：把 conv2d / sep_conv / ms_all_conv_block / spike_sppf / detect_head 全部用 Vitis HLS C++ 实现，编出可直接喂 Vivado 的 .xo
- **Z-7020 资源约束**：53.2K LUT + 220 DSP 在嵌入式 SoC 上是硬约束，需要 PIPELINE / ALLOCATION / BIND_OP 多管齐下
- **HDMI 1080p 输出链**：rgb2dvi + v_axis_to_video_out + v_tc 整合到 BD，AXI-VDMA 拉 frame buffer

这些工作在论文外，是从「论文公开权重」到「真硬件演示」的工程缺口。本仓库填补这部分缺口。

## Pipeline

```
                ┌──────────────────┐
 SpikeYOLO ECCV │ 23.1M FP32 .pt   │  (Luo et al. ECCV 2024)
   checkpoint   └────────┬─────────┘
                         │  distillation (det + KD_logits + feat_align + spike_rate)
                         ▼
                ┌──────────────────┐
                │ tiny_fpga FP32   │  width=0.1875, ~1.5M params
                │ .pt              │
                └────────┬─────────┘
                         │  PTQ (BN-fold + per-ch out_shift, INT8 sym)
                         ▼
                ┌──────────────────┐
                │ tiny_fpga INT8   │  models/tiny_fpga_int8_real.{bin,npz}
                │ .bin / .npz      │
                └────────┬─────────┘
                         │  HLS C++ port (numpy_reference.py → tiny_fpga_top.cpp)
                         ▼
                ┌──────────────────┐
                │ spike_accel .xo  │  5×m_axi gmem masters + AXI-Lite control
                │ (Vitis HLS 2024) │
                └────────┬─────────┘
                         │  Block Design (PS7 + ic_data_hp0/1 + ic_ctrl + irq)
                         ▼
                ┌──────────────────┐
                │ system.bit /     │  ZYBO Z7-20 bitstream (LUT 73%, 100 MHz)
                │ system.xsa       │
                └────────┬─────────┘
                         │  PetaLinux + UIO driver + DDR3 contiguous buffers
                         ▼
              ┌────────────────────┐
              │ USB-cam → spike    │  1080p @ 30 FPS end-to-end
              │ accel → HDMI 1080p │
              └────────────────────┘
```

## Status

| Milestone | Description | Status |
|---|---|---|
| **M1** Algorithm & csim | Reference numpy backend, 10 HLS kernels csim-bit-exact | ✅ Complete |
| **M1-A1** Distillation training | tiny_fpga FP32 / INT8 W8-W10 tracks | 🟡 W10 train2017 30-ep in progress |
| **M2-W1** Synth + Impl + Bitstream | Vivado place-and-route on XC7Z020 | ✅ Complete (LUT 73 %, see `runs/main_machine/M2_W1_synth_complete.md`) |
| **M2-W2** Timing closure + HW boot | WNS −0.764 ns → 0 ns; smoke test on real ZYBO | ⏳ In progress |
| **M3** HDMI output rebuild | rgb2dvi + v_axis_to_video_out + v_tc | ⏳ Queued |
| **M4** End-to-end USB-cam → HDMI demo | 1080p @ 30 FPS live | ⏳ Queued |
| **M5** Dataflow + PE upgrade | Replace serial scratch buffers with dataflow streams | ⏳ Future |
| **M6** Final ship + writeup | Reproducible release | ⏳ Future |

Latest bitstream KPIs (post-place-and-route, Vivado 2024.1):

| Resource | Used | Cap | % |
|---|---:|---:|---:|
| Slice LUT | 38 838 | 53 200 | **73.0 %** |
| Slice Register | 47 912 | 106 400 | 45.0 % |
| DSP48E1 | ~150 | 220 | 68 % |
| BRAM 36K / 18K | ~2 | 280 | <1 % |
| WNS @ 100 MHz | −0.764 ns | 0 | M2-W2 task |

## Repository Layout

```
.
├── ultralytics/             # PyTorch model defs (tiny_fpga.yaml + SNN blocks)
├── tools/
│   ├── quant/               # Distillation + PTQ INT8 scripts
│   ├── fpga/                # numpy_reference.py (HLS C++ golden reference)
│   ├── verify/              # extract_golden.py: bit-exact tensor dumps
│   └── ci/                  # A800/AutoDL bootstrap, COCO download, BITS, etc.
├── hw/
│   ├── hls/                 # Vitis HLS C++ kernels (10 of them + tiny_fpga_top)
│   │   ├── include/         # dtypes.h, axi_iface.h, op_macros.h
│   │   ├── src/             # conv2d_int.cpp, sep_conv.cpp, lif_expand.cpp, ...
│   │   └── tests/           # csim host tests against golden tensors
│   └── vivado/              # build_bd.tcl, build_bitstream.tcl, ip_repo/
├── sw/
│   ├── app/                 # Bare-metal + Linux userspace demo apps
│   ├── driver/              # UIO config + device tree fragments
│   ├── petalinux/           # PetaLinux project files
│   └── sdk/                 # Vitis SDK projects
├── models/                  # Teacher .pt + student .pt + INT8 .bin/.npz artifacts
├── docs/                    # Architecture, contracts, ADRs, collaboration protocol
├── runs/                    # Per-milestone reports + remote-machine comms
└── README.md                # this file
```

## Quickstart

### 1. Distillation training (NVIDIA GPU)

```bash
# Single-card RTX 3060/3070/4060 etc. — uses --batch-size 16 imgsz 256 by default
python tools/quant/distill_from_teacher.py \
    --teacher models/SpikeYOLO_23.1M_T1D4.pt \
    --student-cfg ultralytics/cfg/models/v8/snn_yolov8_tiny_fpga.yaml \
    --student-init models/tiny_fpga_fp32.pt \
    --config tools/quant/distill_config_train2017.yaml \
    --out models/tiny_fpga_fp32_distilled.pt \
    --epochs 30
```

Reboot-safe: every epoch atomically writes `runs/distill_train2017/resumable/latest.pt`; rerun the same command to resume.

### 2. PTQ INT8

```bash
python tools/quant/ptq_int8.py \
    --in  models/tiny_fpga_fp32_distilled.pt \
    --out models/tiny_fpga_int8.bin       # also writes .npz schema-mirror
```

### 3. HLS csim + csynth

```bash
cd hw/hls
source /opt/Xilinx/Vitis_HLS/2024.1/settings64.sh
vitis_hls -f run_csim.tcl                # 10/10 PASS expected
vitis_hls -f run_csynth.tcl              # produces .xo + component.xml
```

### 4. Vivado synth → impl → bitstream

```bash
vivado -mode batch -source hw/vivado/build_bd.tcl
vivado -mode batch -source hw/vivado/build_bitstream.tcl
# Output: hw/vivado/out/system.bit + system.xsa + address_map.yaml
```

### 5. Deploy to ZYBO Z7-20

```bash
# Build PetaLinux image (or use the provided .xsa with bare-metal app)
cd sw/petalinux && petalinux-build && petalinux-package --boot ...

# On the target, load via fpgautil or sysfs:
sudo fpgautil -b /lib/firmware/system.bit
sudo ./sw/app/build/spikeyolo_demo --weights /lib/firmware/tiny_fpga_int8.bin
```

## Background (upstream paper)

Implementation builds on the published **SpikeYOLO** weights (ECCV 2024 Best Paper Candidate):

> Luo X., Yao M., Chou Y., Xu B., Li G. **Integer-Valued Training and Spike-Driven Inference Spiking Neural Network for High-performance and Energy-efficient Object Detection.** ECCV 2024.
> Code: <https://github.com/BICLab/SpikeYOLO>

Pretrained checkpoints used as the distillation teacher:

- 23M T=1, D=4: <https://drive.google.com/drive/folders/1c5p09ZRCFeK1M5wH6zQduJltZalMzQkZ>
- 69M T=1, D=4: <https://drive.google.com/file/d/1rmcUMJztbjFFbbVqW8xwgshKNZel1psZ>
- Binary inference 23M T=1, D=4: <https://drive.google.com/file/d/1YQ29eDUfmaze2jl_UREX4Zeb1u8tpHfl>

We **do not** retrain SpikeYOLO from scratch; the above checkpoints are the frozen teacher for all distillation runs.

## Citation

If you use this repository, please cite both the original SpikeYOLO paper and this work:

```bibtex
@inproceedings{luo2024spikeyolo,
  title     = {Integer-Valued Training and Spike-Driven Inference Spiking Neural Network for High-performance and Energy-efficient Object Detection},
  author    = {Luo, Xinhao and Yao, Man and Chou, Yuhong and Xu, Bo and Li, Guoqi},
  booktitle = {European Conference on Computer Vision (ECCV)},
  year      = {2024}
}

@misc{spikeyolo_fpga,
  title  = {SpikeYOLO\_FPGA: ZYBO Z7-20 deployment of SpikeYOLO},
  author = {{(repository contributors)}},
  year   = {2026},
  url    = {https://github.com/yizhidianlu/SpikeYOLO_FPGA}
}
```

## Acknowledgements

- **SpikeYOLO** authors at BICLab (Institute of Automation, CAS): Xinhao Luo, Man Yao, Yuhong Chou, Bo Xu, Guoqi Li — for the original model and checkpoints.
- **Ultralytics YOLOv8** for the training framework.
- **SpikingJelly** for the SNN training primitives.
- **Digilent** for the ZYBO Z7-20 board and reference IP (`rgb2dvi:1.4`).
- **AMD/Xilinx** for Vitis HLS 2024.1 + Vivado 2024.1.

## License

The HLS / Vivado / PetaLinux / driver / app code in this repo is released under the same license as the upstream SpikeYOLO project. Please consult [BICLab/SpikeYOLO](https://github.com/BICLab/SpikeYOLO) for the model-weight license terms; the toolchain-side artifacts under `hw/`, `sw/`, `tools/` follow each vendor's respective license.

---

For collaboration / dev-protocol details, see `docs/COLLABORATION.md` and `docs/CONTRACTS.md`.
For per-milestone reports, see `runs/main_machine/` and `runs/remote_machine/`.
