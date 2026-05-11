// =============================================================================
// SpikeYOLO PE array 16x8 systolic — M5 candidate RTL replacement
//
// Triggered by: B1 timing fail @ 150 MHz, OR utilization > 70%
// Replaces:     HLS-generated PE array in conv2d_int.cpp inner loop
//               (#pragma HLS UNROLL factor=8 + ARRAY_PARTITION dim=1 complete)
// Resource:     128 DSP48E1 (16 Co_tile x 8 Ci_tile, INT8 x INT8 -> INT32 acc)
// Throughput:   16x8 MAC/cycle = 128 ops/cycle @ 150 MHz = 19.2 GOP/s peak
//
// M5 design notes:
//   - Each PE = 1 DSP48E1 in OPMODE 0x05 (P = A*B + Cin) with INT8 SIMD
//     option (USE_SIMD="ONE48" for INT8 + INT32 acc; "TWO24" if we pack 2
//     INT8x8 pairs per DSP to halve DSP count when activation is binary).
//   - Skip-zero: when spike_in[ci]==0 the entire MAC column gates off via
//     a clock enable derived from |spike_in[ci]| (saves ~30% switching power).
//   - Acc is INT32 to avoid mid-sum saturation across 8 Ci_tile lanes; final
//     out_shift / bias / clamp is done downstream in lif_fsm.sv.
//
// Acceptance criteria (M5 W2):
//   - cycle-accurate match with HLS baseline RTL (tb_pe_array.py cocotb)
//   - synth: 128 DSP exact, LUT <= 0.85x HLS baseline
//   - Fmax >= 160 MHz post place-and-route
// =============================================================================

`timescale 1ns/1ps

module pe_array #(
    parameter int CO_TILE = 16,
    parameter int CI_TILE = 8,
    parameter int DATA_W  = 8,
    parameter int ACC_W   = 32
)(
    input  logic                                       clk,
    input  logic                                       rst_n,
    input  logic                                       in_valid,
    input  logic [CI_TILE*DATA_W-1:0]                  spike_in,   // 1 column INT8 spike
    input  logic [CO_TILE*CI_TILE*DATA_W-1:0]          weight_in,  // 16x8 INT8 weight tile
    output logic                                       out_valid,
    output logic [CO_TILE*ACC_W-1:0]                   acc_out     // 16 INT32 accumulators
);

    // TODO M5 W2: 16x8 systolic array with skip-zero gating.
    //   - Per-CO row: 8 DSP48E1 instances chained on PCIN/PCOUT for INT32 acc
    //   - Per-CI column: clock-enable = OR-reduce(spike_in[ci])
    //   - Pipeline depth: 1 (DSP input reg) + 1 (DSP P reg) + 1 (output reg)
    //     = 3 cycles latency, II=1 throughput
    //
    // valid pipeline: shift in_valid through 3 FF stages to match acc_out.
    //
    // Reference: Xilinx UG479 7-Series DSP48E1 Slice User Guide §2 DSP48E1
    //            primitive instantiation template.

endmodule
