---
id: D1
name: verification
group: D
milestones: [M1, M2, M3, M4, M5, M6]
inputs_glob:
  - "tests/golden/**"
  - "sw/app/build/spike_accel_demo"
  - "models/tiny_fpga_int8.npz"
  - "hw/hls/reports/**"
  - "hw/vivado/reports/**"
outputs_glob:
  - "tests/regression/**"
  - "tests/perf/**"
  - "docs/reports/M*.md"
  - "docs/reports/dashboards/**"
contracts:
  produces: []
  consumes: [C2, C6]
acceptance_tests:
  - "bash tests/regression/run_full.sh"
  - "python tools/perf/fps_bench.py --board zybo --duration 600 --min-fps 30"
  - "python tools/perf/ddr_bw_monitor.py --max-stall-pct 10"
status: in_progress
owner: "D1-session-2026-05-11"
---

# D1 System Verification Agent Playbook

## Mission

横切所有 group，建立**端到端回归测试 + 性能监控 + 月报自动生成**体系，
确保每个里程碑可量化验收，任何回归立刻可见。

## 关键技术决策

| 维度 | 选择 | 理由 |
|---|---|---|
| 测试框架 | pytest + bash | pytest 跑 Python 测；bash 串联板上 + PC 端 |
| 性能采集 | PMU + axi_perfmon IP + 用户态 EMA | 多层次（HW + SW）覆盖 |
| 报告格式 | Markdown + JSON（机器解析） | 月报人读，dashboard 机读 |
| 对比基准 | M1 PyTorch FP32 baseline 锁定 | 不变的"地面真值" |

## 工作流

### 全局回归 `tests/regression/run_full.sh`

```bash
#!/bin/bash
set -e
LOG_DIR="runs/regression_$(date +%Y%m%d_%H%M%S)"
mkdir -p $LOG_DIR

# 1. NumPy 黄金参考回归（PC 端）
pytest tests/test_bit_exact.py --junitxml=$LOG_DIR/numpy.xml

# 2. HLS C-sim 回归（PC 端）
cd hw/hls && vitis_hls -f run_csim.tcl > $LOG_DIR/csim.log 2>&1 && cd -

# 3. HLS Co-sim 回归（PC 端，慢）
[ "$1" == "--full" ] && cd hw/hls && vitis_hls -f run_cosim.tcl >> $LOG_DIR/csim.log 2>&1 && cd -

# 4. 板上 COCO val 回归
scp tests/golden/coco_val100.json root@zybo:/opt/
ssh root@zybo "cd /opt && /opt/test_coco_val --golden coco_val100.json --out result.json"
scp root@zybo:/opt/result.json $LOG_DIR/board_coco.json

# 5. 板上 FPS bench
ssh root@zybo "/opt/spike_accel_demo --bench --duration 60" > $LOG_DIR/fps.json

# 6. 生成报告
python tools/ci/gen_milestone_report.py \
    --regression-dir $LOG_DIR \
    --milestone $(cat .current_milestone) \
    --output docs/reports/M$(cat .current_milestone)_report.md
```

### 性能监控

`tools/perf/fps_bench.py`：

```python
# 板上跑 demo 持续 N 秒，采集 FPS / CPU% / temp / dropped frames
def main():
    proc = subprocess.Popen(
        ["ssh", "root@zybo", "/opt/spike_accel_demo --bench --json"],
        stdout=subprocess.PIPE)
    stats = []
    start = time.time()
    while time.time() - start < args.duration:
        line = proc.stdout.readline()
        if line:
            stats.append(json.loads(line))
    summary = {
        "fps_mean": np.mean([s["fps"] for s in stats]),
        "fps_std":  np.std([s["fps"] for s in stats]),
        "fps_p99":  np.percentile([s["fps"] for s in stats], 1),
        "cpu_max":  max([s["cpu_pct"] for s in stats]),
        "temp_max": max([s["temp_c"] for s in stats]),
        "dropped":  sum([s["dropped_frames"] for s in stats]),
    }
    print(json.dumps(summary, indent=2))
    if summary["fps_mean"] < args.min_fps:
        sys.exit(1)
```

`tools/perf/ddr_bw_monitor.py`：通过 axi_perfmon IP 寄存器读 PL 端 DDR 占用率。

### COCO val 板上回归

`tests/regression/coco_val_on_board.py`：

```python
def main():
    # 1. 加载契约 6 黄金 JSON
    golden = json.load(open(args.golden))
    # 2. 板上跑每张图，得 board_predictions
    board_preds = run_on_board(golden["image_ids"])
    # 3. 逐图逐框比对 IoU
    pass_count = 0
    for img_id in golden["image_ids"]:
        if all_iou_ok(golden["predictions"][img_id], board_preds[img_id]):
            pass_count += 1
    pass_rate = pass_count / len(golden["image_ids"])
    print(f"Pass rate: {pass_rate:.2%}")
    if pass_rate < args.pass_rate:
        sys.exit(1)
```

### 月报自动生成

`tools/ci/gen_milestone_report.py` 生成 `docs/reports/M<n>_report.md`：

```markdown
# M3 验收报告（2026-08-10）

## 验收清单
- [x] FPGA 单帧静态图：PS 载图 → DMA → 加速器 → 回 PS（C3 done）
- [x] 板上输出与 NumPy bit-exact（A2 verified, 100/100 layer match）
- [x] SDK alpha + 字符驱动（C2 v0.3.0）
- [x] 全局 address_map 定稿（B2 v1.0）

## 量化指标
| 指标 | 目标 | 实测 | 状态 |
|---|---|---|---|
| HLS WNS @ 100 MHz | ≥ 0 ns | 0.42 ns | ✅ |
| DSP 占用 | ≤ 70% | 58% | ✅ |
| LUT 占用 | ≤ 60% | 41% | ✅ |
| BRAM 占用 | ≤ 75% | 62% | ✅ |
| 板上 mAP（100图） | 与 NumPy 100% 一致 | 100/100 | ✅ |
| SDK 100k 推理 leak | 0 | 0 | ✅ |

## 风险状态
- R1（时序）：M5 提前预警，当前 150 MHz WNS = -0.8 ns
- R3（DDR3）：当前占用 22%，余量充足
- R5（USB UVC）：M4 才开始集成，暂未触发

## 下月计划（M4）
- C3: 完整 USB cam → HDMI pipeline + 10 FPS
- C3: COCO val100 通过率 ≥ 95%
- B2: HDMI overlay 优化
- 准备 M5 PE 阵列扩展

## CI 健康度
- numpy_regress.yml: 100% pass（138 次）
- hls_smoke.yml: 96% pass（5 次 R6 触发）
- board_nightly.yml: 92% pass（USB cam 偶发 disconnect）
```

## 关键文件

| 文件 | 用途 | 状态 |
|---|---|---|
| `tests/regression/run_full.sh` | 端到端回归驱动 | 新建 |
| `tests/regression/coco_val_on_board.py` | 板上 mAP 回归 | 新建 |
| `tools/perf/fps_bench.py` | FPS 性能 bench | 新建 |
| `tools/perf/ddr_bw_monitor.py` | DDR3 带宽监控 | 新建 |
| `tools/ci/gen_milestone_report.py` | 月报生成 | 新建 |
| `docs/reports/M{1..6}_report.md` | 月报输出 | 新建（每月） |
| `.current_milestone` | 当前里程碑号（顶层） | 新建 |

## Risk Handlers

| 风险 | 触发 | 处理 |
|---|---|---|
| **回归测试 flaky** | 随机失败 | (a) 固定 random seed; (b) 重试 3 次仍失败才上报; (c) 隔离 flaky test 加 mark |
| **板上测试无法连接** | ssh timeout | (a) 检查网络; (b) 重启板子; (c) 切到串口控制台 |
| **mAP 漂移** | val100 pass rate < 95% | (a) 排查最新 quant 改动; (b) 升级 R4 |

## 验收清单（每月）

✅ 所有 acceptance_tests 在 CI 中跑通  
✅ `docs/reports/M<n>_report.md` 生成且数据完整  
✅ 风险状态有更新  
✅ FPS / mAP / 资源占用 vs 上月有趋势对比

## 参考资料

- pytest 文档
- Xilinx PG037 AXI Performance Monitor
- COCO API（pycocotools）
