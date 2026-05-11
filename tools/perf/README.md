# tools/perf — Performance benchmarking (D1 Agent)

**Owner**: D1 System Verification Agent — see [`docs/AGENT_PLAYBOOKS/D1_verification.md`](../../docs/AGENT_PLAYBOOKS/D1_verification.md)

## Purpose

Board-side and PC-side performance instrumentation. Feeds D1 milestone reports and D2 nightly regression gates.

## Layout

```
fps_bench.py             Run demo on board, sample FPS / CPU / temp / dropped
ddr_bw_monitor.py        Sample DDR3 stall % via axi_perfmon registers
layer_latency.py         Per-layer cycle profile via spike_accel performance counters
power_meter.py           (Optional) measure board power via external INA219
```

## Usage

```bash
# 5-minute FPS bench with min-fps gate
python fps_bench.py \
    --board zybo \
    --duration 300 \
    --min-fps 30 \
    --output runs/fps.json

# DDR3 stall monitoring during 1-min stress test
python ddr_bw_monitor.py \
    --board zybo \
    --duration 60 \
    --max-stall-pct 10

# Per-layer latency breakdown
python layer_latency.py \
    --board zybo \
    --num-frames 100 \
    --output runs/layer_latency.csv
```

## Output JSON schema

```json
{
  "fps_mean": 31.2,
  "fps_std": 0.8,
  "fps_p99": 28.5,
  "cpu_max": 56.0,
  "temp_max": 62.0,
  "dropped": 0,
  "ddr_stall_pct": 6.4,
  "duration_s": 300,
  "frame_count": 9360,
  "timestamp": "2026-09-10T03:00:00Z"
}
```

## Used by

- D1 milestone report generator
- D2 board_nightly.yml gates

## References

- Xilinx PG037 AXI Performance Monitor
- linux perf events
