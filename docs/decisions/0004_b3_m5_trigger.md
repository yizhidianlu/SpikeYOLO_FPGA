# Decision 0004 — B3 RTL Tuning M5 trigger conditions

Date:    2026-05-11
Owner:   B3-session-2026-05-11
Status:  prep_done (B3 stays dormant until any condition below trips)

## Context

B3 is the only conditional Agent in the team. It activates **only** when the
HLS-generated RTL from B1 cannot meet the M5 timing / resource / FPS targets.
This decision locks the exact trigger conditions and response path so the
M1-M4 sub-agents do not need to second-guess when B3 should be summoned.

## Trigger conditions (OR — any one is sufficient)

1. **Timing**: B1 `hw/hls/reports/timing.csv` reports `wns_ns < 0` for any
   kernel at the 150 MHz target (6.67 ns clock). B1 W4 already wired the
   per-kernel `wns_ns` column in this CSV.
2. **Resource overflow**: B1 `hw/hls/reports/utilization.rpt` shows any of
   the contract-3 caps exceeded:
     - DSP48E1 > 154  (70% of 220)
     - LUT     > 31920 (60% of 53200)
     - BRAM36  > 105   (75% of 140)
3. **FPS regression**: D1 monthly report shows board FPS < 25 for two
   consecutive months (M5 and M6 measurements).
4. **mAP regression force-expand**: A1 reports mAP50-95 drop > 1.5% and the
   accepted recovery path is to widen the PE array 16x8 -> 32x8 (extra DSP
   demands RTL hand-tuning to fit).

## Response path

When triggered, B3 follows these steps in order:

1. **Top-10 paths**: read `hw/hls/reports/timing.csv` and the underlying
   Vivado `report_timing -path 10` text dump (B1 emits this per kernel via
   `run_synth.tcl`).
2. **Classify** each long path into one of four buckets:
     - PE inner loop          -> `src/pe_array.sv`
     - LIF / MultiSpike4 FSM  -> `src/lif_fsm.sv`
     - Popcount tree          -> `src/popcount_tree.sv`
     - AXI handshake          -> stays in HLS (out of B3 scope)
3. **Pick 1-2 hottest modules** (Pareto: longest WNS deficit first).
   Write the actual RTL inside the skeletons that already exist in
   `hw/rtl/src/`.
4. **Verify** cycle-accurate vs the HLS baseline via cocotb
   (`hw/rtl/tb/tb_<module>.py`) using B1 host_csim dumps as golden.
5. **Hand back to B2**: B2 patches `hw/vivado/build_bd.tcl` to replace the
   chosen sub-module's HLS-generated `.v` file with the B3 hand-written
   `.sv` file. The rest of the IP stays HLS.

## Current progress (M1 W5)

Zero-day prep complete:

- Module skeletons exist (declarations + ports + TODO comments, no logic):
    - `hw/rtl/src/popcount_tree.sv`
    - `hw/rtl/src/pe_array.sv`
    - `hw/rtl/src/lif_fsm.sv`
- Testbench framework picked: cocotb + Verilator
  (see `hw/rtl/tb/README.md`)
- Build harness ready: `hw/rtl/Makefile`
  (`rtl_lint` runs today; `rtl_sim` / `rtl_synth_dry` land in M5 W2-W3)
- This decision document (the trigger contract)

When any condition above trips, B3 spins up from `prep_done` to `in_progress`
with zero ramp-up friction.

## Cross-references

- `docs/AGENT_PLAYBOOKS/B3_rtl_tuning.md` — full Playbook
- `docs/AGENT_PLAYBOOKS/B1_hls_kernel.md` §Phase 4 — B1's escalation hook
- `docs/CONTRACTS.md` §3 — contract 3 resource budget (DSP/LUT/BRAM caps)
- `docs/RISK_RULES.yaml` — R1 timing-close risk handler chain ending in B3
