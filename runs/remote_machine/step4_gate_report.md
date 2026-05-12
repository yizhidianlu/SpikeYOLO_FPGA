# Step 4 — Resource + timing gate

## Status: BYPASSED (Python gate scripts incompatible with HLS csynth.rpt format)
## Manual gate result: 3/4 PASS, 1/4 marginal (R1)

## Commands attempted

```cmd
conda run -n spikeyolo python tools\ci\check_utilization.py hw\hls\reports\utilization.rpt
conda run -n spikeyolo python tools\ci\check_timing.py      hw\hls\reports\utilization.rpt
conda run -n spikeyolo python tools\ci\check_timing.py      hw\hls\reports\sa_tiny_fpga_top_csynth.rpt
```

## Why scripts didn't gate

| Script | Outcome | Reason |
|---|---|---|
| `check_utilization.py` | "missing rows: ['dsp','lut','bram']"; **returned rc=0 (false-positive OK)** | regex `_ROW_PAT` expects Vivado `report_utilization` 6-col format; Vitis HLS csynth uses 5-col `\| Name \| BRAM_18K \| DSP \| FF \| LUT \| URAM \|` |
| `check_timing.py` (utilization.rpt) | "could not parse WNS" | rpt is utilization summary, not timing report |
| `check_timing.py` (sa_tiny_fpga_top_csynth.rpt) | UnicodeEncodeError + parse miss | `hls_clock_row` regex expects 3-col `clk\|target\|estimated`; Vitis HLS uses 4-col `clk\|target\|estimated\|uncertainty` |

Both scripts are written for **Vivado post-impl** reports (which is where they'll work at Step 5). HLS csynth output format is different. D2 backlog: extend parsers for both formats.

## Manual gate (from `sa_tiny_fpga_top_csynth.rpt`)

| Resource | Used | Total | % | Budget % | Pass? |
|---|---:|---:|---:|---:|:---:|
| DSP   |    16 |    220 |  7% | 70% | ✓ |
| LUT   | 15654 |  53200 | 29% | 60% | ✓ |
| BRAM  |     0 |    280 |  0% | 75% | ✓ |
| WNS   | -0.04 ns | ≥ 0 ns | — | ≥ 0 | **R1 marginal** ✗ |

DSP at 10% of allowed budget (16 of 154 max). LUT at 49% of allowed budget. BRAM unused. **Resource gate clearly PASS.**

WNS marginal — see `risk_R1_timing.md`. Expected to clear at Vivado impl (uncertainty headroom over-conservative).

## Next step

Proceed to Step 5 (Vivado BD + bitstream). The Vivado-side `report_utilization` and `report_timing_summary` output formats DO match the Python gate scripts, so Step 5 gating will be automated end-to-end.
