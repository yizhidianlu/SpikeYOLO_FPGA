# Risk R1 — HLS timing closure (marginal)

## Trigger
WNS = -0.04 ns @ 10 ns clock (sa_tiny_fpga_top, Vitis HLS 2024.1 csynth).

## Severity
**Marginal / margin-conservative**. The negativity comes entirely from uncertainty buffer:

```
Target:      10.000 ns
Estimated:    7.341 ns  ← actual datapath delay
Uncertainty:  2.700 ns  ← HLS-applied 27% headroom
WNS:         -0.041 ns  = 10.000 - 7.341 - 2.700
```

Without uncertainty (actual slack): **+2.659 ns**. Vivado post-impl re-times and frequently improves; this is expected to close at Step 5.

## Top 5 longest paths (from csynth slack column)

Cannot dump exact path detail from HLS csynth.rpt (path-level timing only available after Vivado impl). Module-level slack from `sa_tiny_fpga_top_csynth.rpt`:

| Module | Slack (ns) |
|---|---:|
| `sa_tiny_fpga_top` (top)                   | **-0.04** |
| `sa_ms_all_conv_block_172_1`               | +0.33     |
| `sa_conv2d_bn_24_58_105_218_303_389_1`     | +0.33     |
| `sa_conv2d_int_27_61_392_1`                | +0.36     |
| `sa_spike_sppf_1`                          | +0.33 (est) |
| `sa_ms_downsampling_186_1`                 | +0.33 (est) |

All non-top modules have positive slack ≥ +0.33 ns. Negative is purely top-level control / dispatcher logic.

## Per handoff §10 / RISK_RULES.yaml R1

- **Action taken**: this risk report written, NOT retrying (Remote cannot modify HLS pragma per protocol)
- **Assignees**: B1 / B2 / B3 (per RISK_RULES.yaml)
- **Recommended handlers**: PIPELINE II=2 on dispatcher; retime; or re-target after Step 5 Vivado impl confirms closure

## Recommendation

**Proceed to Step 5** (Vivado BD + impl). If Step 5 implementation also reports WNS < 0 at 100 MHz, escalate to B1/B2 owners with full post-impl path detail. Likely Vivado closes due to its retiming + physical opt passes.

— Remote Claude, 2026-05-12T17:32:00+08:00
