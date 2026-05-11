// =============================================================================
// SpikeYOLO PE array popcount tree — M5 candidate RTL replacement
//
// Triggered by: B1 timing fail @ 150 MHz on PE inner loop (6.67 ns target)
// Replaces:     HLS-generated reduction in conv2d_int.cpp PE accumulator
//               (sa_conv2d_int leaf kernel in hw/hls/src/conv2d_int.cpp)
// Input:        8x8 binary spike packet @ 256 MHz oversample (or 150 MHz native)
// Output:       7-bit popcount result (max 64 ones -> log2(64)+1 = 7)
// Latency:      3 cycle pipeline (Wallace tree depth)
//
// M5 design notes:
//   - Wallace tree CSA (carry-save adder) stage 1: 64 bits -> 22 partials
//   - CSA stage 2: 22 -> 8 partials
//   - CSA stage 3 + final CPA: 8 -> 7-bit count
//   - One pipeline reg between each stage to hit 150 MHz on Z-7020 -1 speed grade
//
// Reference: Xilinx UG902 §3.4 carry chain reduction
//            "Synthesis of Arithmetic Circuits" — Wallace popcount chapter
//
// Acceptance criteria (M5 W2):
//   - verilator --lint-only popcount_tree.sv :: 0 warning
//   - Vivado synth report_timing: setup slack >= 0.5 ns @ 6.67 ns
//   - LUT count <= 0.7x of HLS-baseline popcount LUT in utilization.rpt
// =============================================================================

`timescale 1ns/1ps

module popcount_tree #(
    parameter int IN_WIDTH  = 64,                  // 8x8 binary spike packet
    parameter int OUT_WIDTH = $clog2(IN_WIDTH + 1) // = 7 for IN_WIDTH=64
)(
    input  logic                       clk,
    input  logic                       rst_n,
    input  logic                       in_valid,
    input  logic [IN_WIDTH-1:0]        in_bits,
    output logic                       out_valid,
    output logic [OUT_WIDTH-1:0]       out_count
);

    // TODO M5 W2: Wallace tree 3-stage CSA pipeline
    //   stage1: 64 -> 22 partials via 21x (3:2) full-adder cells
    //   stage2: 22 ->  8 partials via 7x  (3:2) FAs
    //   stage3:  8 ->  1 final 7-bit sum via (3:2) FAs + ripple CPA
    //
    // Constraint: max 3 cycles end-to-end (1/3 of 150 MHz clock budget for
    // popcount alone — PE MAC accumulation reuses the same clock domain).
    //
    // valid pipeline: shift in_valid through 3 FF stages to match out_count.

endmodule
