# tools/quant — Quantization Pipeline (A1 Agent)

**Owner**: A1 Quantization Agent — see [`docs/AGENT_PLAYBOOKS/A1_quantization.md`](../../docs/AGENT_PLAYBOOKS/A1_quantization.md)

## Purpose

Post-training (and optionally QAT) quantization of SpikeYOLO tiny_fpga to **INT8 weights + INT4 (MultiSpike4) activations**, with BN-fold and PE-tile weight packing.

Output target: COCO val mAP50-95 degradation ≤ 1.0% vs FP32 baseline.

## Layout

```
run_ptq.py                 Main PTQ flow
fold_bn.py                 Fold BN into Conv weights
qat_finetune.py            QAT fallback (only triggered on R4)
weight_packer.py           Python weight packing → .npz (Contract 1)
weight_packer_test.cpp     C++ packer (byte-identical check)
eval_quant_map.py          COCO val mAP evaluator with target threshold
calibrate.py               Activation histogram calibration (MSE-min)
```

## Pipeline

```bash
# 1. PTQ (calibrate + fold BN + quantize)
python run_ptq.py \
    --pt ../../models/tiny_fpga_fp32_retrained.pt \
    --calib-imgs ../../datasets/coco/calibration/ \
    --output ../../models/tiny_fpga_int8.npz

# 2. Pack weights to PE-tile order
python weight_packer.py \
    --input ../../models/tiny_fpga_int8.npz \
    --output ../../models/tiny_fpga_int8.bin

# 3. Evaluate mAP
python eval_quant_map.py \
    --weights ../../models/tiny_fpga_int8.npz \
    --val-set ../../datasets/coco/val2017 \
    --target-degradation 1.0

# 4. If mAP fails -> QAT
python qat_finetune.py --pt ... --epochs 5 --output models/tiny_fpga_qat.pt
```

## Contracts produced

- **C1**: `models/tiny_fpga_int8.npz` (PE-tile packed) + `models/tiny_fpga_int8.bin`

## Acceptance gates

- mAP degradation ≤ 1.0% (R4 budget)
- Python ↔ C++ weight packer byte-identical
- Per-channel cosine sim ≥ 0.999 after BN-fold

## References

- [`tools/fpga/numpy_reference.py`](../fpga/numpy_reference.py) — runtime dequant formula
- [`docs/CONTRACTS.md`](../../docs/CONTRACTS.md) — Contract 1 schema
