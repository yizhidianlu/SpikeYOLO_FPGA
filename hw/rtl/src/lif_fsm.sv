// =============================================================================
// SpikeYOLO I-LIF + MultiSpike4 state machine — M5 candidate RTL replacement
//
// Triggered by: B1 timing fail @ 150 MHz on LIF state machine path
// Replaces:     HLS-generated state machine in hw/hls/src/lif_expand.cpp
//               (mem_update + expand_cumulative in tools/fpga/numpy_reference.py)
// Input:        INT32 accumulated membrane potential, per channel
// Output:       N_SUB-bit binary spike packet (T=1, MAX_SPIKE=4 substeps)
// Constraint:   membrane potential clamp to [0, MAX_SPIKE]
//
// M5 design notes:
//   - Per-channel pipeline (no FSM-style state encoding — keeps Fmax high):
//       stage1: (acc_in + bias) >> out_shift          -- BN fuse
//       stage2: clamp to [0, MAX_SPIKE]               -- saturate
//       stage3: expand cumulative -> N_SUB binary     -- spike[i] = (clamped > i)
//   - Total latency: 3 cycles, II=1 throughput, fully pipelined
//   - Replaces the C++ loop in expand_cumulative() with a parallel compare bank
//
// Acceptance criteria (M5 W2):
//   - tb_lif_fsm.py cocotb: cycle-accurate match with numpy_reference.mem_update
//   - synth: 0 DSP (pure shifter + comparator), LUT <= 0.7x HLS baseline
// =============================================================================

`timescale 1ns/1ps

module lif_fsm #(
    parameter int N_SUB   = 4,          // MultiSpike4 substep count
    parameter int ACC_W   = 32,
    parameter int SHIFT_W = 8
)(
    input  logic                       clk,
    input  logic                       rst_n,
    input  logic        signed [ACC_W-1:0]   acc_in,
    input  logic        signed [ACC_W-1:0]   bias_in,
    input  logic                              valid_in,
    input  logic        [SHIFT_W-1:0]        out_shift,
    output logic        [N_SUB-1:0]          spike_out,
    output logic                              valid_out
);

    // TODO M5 W2: 3-stage pipeline
    //   - stage1: y_i32 <= (acc_in + bias_in) >>> out_shift  (arith shift)
    //   - stage2: clamped <= (y_i32 < 0) ? 0
    //                       : (y_i32 > N_SUB) ? N_SUB : y_i32[$clog2(N_SUB+1)-1:0]
    //   - stage3: spike_out[i] <= (clamped > i)  for i in [0, N_SUB-1]
    //
    // valid pipeline: 3-stage FF shift register matches the data pipeline.
    //
    // Reference: tools/fpga/numpy_reference.py:mem_update + expand_cumulative

endmodule
