# Step 5 — Post-synth utilization breakdown (R2 handler input)

Per Main's request 2026-05-13T10:42 to inform R2 handler selection.

## Top-level totals (system_wrapper, post-synth, pre-place)

| Resource | Used | Cap | % |
|---|---:|---:|---:|
| Total LUT  | **68577** | 53200 | **129%** |
| Logic LUT  | 64878 | 53200 | 122% |
| LUTRAM     |  1528 | 17400 |   9% |
| SRL        |  2171 |     ? |     |
| FF total   | 78492 | 106400 | 74% |
| DSP        |   161 |   220 |  73% |
| BRAM36     |     2 |   140 |   1% |
| BRAM18     |     9 |   280 |   3% |

Post-place numbers Main saw (54339 combined / 65250 total) are *post-opt*; synth-side here is closer to the un-optimized count.

## Top-level breakdown (LUT-sorted)

| Instance | LUT | FF | DSP | % of total LUT |
|---|---:|---:|---:|---:|
| **spike_accel_0** | **57939** | 64550 | 161 | **84.5%** |
| ic_data_hp0 | 5960 | 7522 | 0 |  8.7% |
| ic_data_hp1 | 2293 | 3277 | 0 |  3.3% |
| axi_dma_feat | 1749 | 2305 | 0 |  2.5% |
| ic_ctrl     |  574 |  758 | 0 |  0.8% |
| (rst_clk, irq_concat, etc.) | ~62 | ~80 | 0 |  ~0.1% |

**spike_accel_0 consumes 85% of total LUT**. The Smartconnect bundles (ic_data_hp0 mainly) take another 12%. Trying to shrink the Vivado-side infrastructure won't move the needle — must shrink spike_accel.

## spike_accel internals (post-synth)

| Component | LUT | FF | DSP | % of spike_accel |
|---|---:|---:|---:|---:|
| `grp_sa_conv2d_bn_..._fu_658` | **28195** | 31122 | 2 | **48.7%** |
| `grp_sa_ms_all_conv_block_185_1_fu_473` | 8739 | 9011 | 74 | 15.1% |
| `grp_sa_spike_sppf_1_fu_676` | 7691 | 7334 | 25 | 13.3% |
| `grp_sa_ms_downsampling_199_1_fu_620` | 3871 | 4021 | 35 | 6.7% |
| `grp_sa_conv2d_bn_..._535_1_fu_713` | 2578 | 2942 | 25 | 4.4% |
| `gmem4_m_axi_U` | 1632 | 1934 |  0 | 2.8% |
| `gmem3_m_axi_U` | 1366 | 1925 |  0 | 2.4% |
| `control_r_s_axi_U` | 1169 | 1195 |  0 | 2.0% |
| `gmem1_m_axi_U` |  898 | 1173 |  0 | 1.6% |
| `gmem0_m_axi_U` |  705 |  990 |  0 | 1.2% |
| `gmem2_m_axi_U` |  602 |  857 |  0 | 1.0% |
| `control_s_axi_U` |  108 |   84 |  0 | 0.2% |
| (other small) | ~3K |  | ~0 | ~5% |

## The headline finding: one conv2d_bn instance owns half the chip

**`grp_sa_conv2d_bn_40_71_118_240_333_426_1_fu_658` = 28195 LUTs / 31122 FFs / 2 DSPs / 0 BRAM** alone.

Note the bizarre profile: **28K LUTs with only 2 DSPs**. The second conv2d_bn instance (`535_1_fu_713`) has 2578 LUTs / 25 DSPs — much more economical and DSP-balanced. **Same source function**, two HLS instances, vastly different LUT cost.

Most likely root cause: the `fu_658` instance got an aggressive UNROLL or ARRAY_PARTITION on its inner loop that **promoted scalar multipliers to LUT-based shift-add** instead of DSP MAC. With 28K LUTs and only 2 DSPs, Vitis decided to inline multipliers as LUTs (probably because the operand was a small const-foldable INT8 that the DSP block doesn't economize for).

Confirmation needed by B1: compare `sa_conv2d_bn` callsite at line 40-71-118-240-333-426 vs 535. The first one likely has full-unroll + DSP-bypass; second has rate-limited unroll.

## R2 handler ranking (revised)

### Recommended: **Handler C' — selective shrink of fu_658**

If we can reduce `fu_658` from 28K LUT → ~3K LUT (matching the `_535_1_fu_713` cost), we save **~25K LUT** instantly. Total becomes ~43K LUT — fits Z-7020 with margin.

How: find the inner-loop pragma on the cpu-side `sa_conv2d_bn` definition (around the call site lines 40/71/118/...) and either:
- Reduce `SA_UNROLL_F(N)` factor by 4-8× on the offending inner loop, OR
- Add `BIND_OP op=mul impl=dsp48` to force DSP allocation, OR
- Force `BIND_STORAGE type=ram_2p impl=bram` on a buffer that got UNROLL-expanded into FFs (the 31K FFs at fu_658 is suspect too).

**Effort**: 5-15 minutes of B1 tcl/pragma work, single re-csynth (~5 min) to verify.

### Backup: Handler B — PE array 16×8 → 8×8

If C' can't find the culprit pragma easily, blanket-halve the PE array (per RISK_RULES.yaml R2 §1). Cost ~2 hr; halves throughput too.

### Not useful here: Handler A — m_axi bundle merge

5 m_axi adapters total only **5203 LUT** (gmem0..4 sum). Merging to 1 m_axi saves at most ~3K LUT. Doesn't move LUT 129% → < 100%.

## Post-synth timing (also dumped per Main's request)

```
Design Timing Summary (post-synth, system_wrapper):
  WNS(ns)     : -0.962
  TNS(ns)     : -67.816
  Failing eps : 86 of 196963
  WPWS(ns)    : +2.520 (pulse width slack OK)
```

R1 status: **86 timing endpoints failing at -0.962 ns WNS**. Much better than HLS-est -19.62 ns. Vivado retiming + impl typically resolves marginal sub-1ns WNS by 70-80%. If R2 closes (design fits) and impl runs, WNS likely closes too.

## Outputs

| Path | Size | Note |
|---|---:|---|
| `runs/remote_machine/post_synth_util_hier.rpt` | ~450 KB | Full hierarchical breakdown |
| `runs/remote_machine/post_synth_util_flat.rpt` | ~80 KB  | Flat summary |
| `runs/remote_machine/post_synth_timing.rpt`    | ~30 KB  | Timing summary |
| `runs/remote_machine/dump_util_breakdown.tcl`  | ~700 B  | The script that generated these |

— Remote Claude, 2026-05-13T12:05:00+08:00
