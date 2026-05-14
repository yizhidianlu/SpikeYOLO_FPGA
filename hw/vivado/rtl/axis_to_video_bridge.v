//-----------------------------------------------------------------------------
// hw/vivado/rtl/axis_to_video_bridge.v
//
// In-tree replacement for `xilinx.com:ip:v_axis_to_video_out:4.0`. Accepts a
// 24-bit RGB AXI4-Stream from VDMA and re-times it onto the parallel-RGB +
// HSync/VSync/ActiveVideo pin set expected by Digilent's `rgb2dvi:1.4`.
//
// Why this file exists:
//   The Xilinx `v_axis_to_video_out` IP ships only with the "Video & Image
//   Processing IP Suite" component of Vivado, which the Remote install was
//   missing (URGENT_ASK_18, 2026-05-13). Rather than gate the project on a
//   per-machine installer step, we provide a small synthesisable bridge that
//   covers the M3 HDMI use-case (VDMA → rgb2dvi at 148.5 MHz pixel clock).
//
// Scope / limitations vs. Xilinx IP:
//   - Single-clock domain — slave AXI-Stream and parallel video share aclk
//     (we drive both from FCLK_CLK1 = 148.5 MHz, see build_bd.tcl).
//     Cross-clock variants would need a CDC FIFO; defer to M5.
//   - Trusts upstream pacing: VDMA is configured to emit one beat per pixel
//     of one frame at 1080p60. We assert tready whenever v_tc says we are in
//     the active video region; tdata is sampled on every active cycle.
//   - SOF/EOL (s_axis_tuser/_tlast) are accepted but not used — the v_tc
//     timing source is authoritative for frame/line boundaries.
//   - No debug counters; production rev should add lockstep observers.
//
// Vendor parity:
//   - tdata bit ordering matches v_axis_to_video_out v4.0 default
//     ([23:16]=R, [15:8]=G, [7:0]=B).
//   - vid_data is registered (1-cycle latency) so rgb2dvi sees clean RGB +
//     sync edges aligned to the same pixel clock.
//
// Owner: B2 (Block Design). M3 Verilog source freeze 2026-05-14.
//-----------------------------------------------------------------------------

`timescale 1ns / 1ps

module axis_to_video_bridge #(
    parameter integer C_AXIS_TDATA_WIDTH = 24
) (
    // Common pixel clock + active-low synchronous reset
    input  wire                              s_axis_aclk,
    input  wire                              s_axis_aresetn,

    // Slave AXI4-Stream (driven by VDMA M_AXIS_MM2S)
    input  wire [C_AXIS_TDATA_WIDTH-1:0]     s_axis_tdata,
    input  wire                              s_axis_tvalid,
    output wire                              s_axis_tready,
    input  wire                              s_axis_tuser,   // SOF (unused)
    input  wire                              s_axis_tlast,   // EOL (unused)

    // Video timing inputs (driven by v_tc vtiming_out bus, individual pins)
    input  wire                              vtiming_active_video,
    input  wire                              vtiming_hsync,
    input  wire                              vtiming_vsync,
    input  wire                              vtiming_hblank, // unused, kept for IP compat
    input  wire                              vtiming_vblank, // unused, kept for IP compat

    // Parallel video outputs (consumed by rgb2dvi RGB port)
    output reg  [C_AXIS_TDATA_WIDTH-1:0]     vid_data,
    output reg                               vid_active_video,
    output reg                               vid_hsync,
    output reg                               vid_vsync
);

    // tready opens whenever v_tc says we are inside the active video region;
    // VDMA self-paces to the pixel clock so this naturally throttles the
    // stream during hblank/vblank.
    assign s_axis_tready = vtiming_active_video;

    // Single-stage pipeline: register everything to the same pixel clock so
    // rgb2dvi sees clean transitions and HDMI tx PLL can lock cleanly.
    always @(posedge s_axis_aclk) begin
        if (!s_axis_aresetn) begin
            vid_data         <= {C_AXIS_TDATA_WIDTH{1'b0}};
            vid_active_video <= 1'b0;
            vid_hsync        <= 1'b0;
            vid_vsync        <= 1'b0;
        end else begin
            vid_active_video <= vtiming_active_video;
            vid_hsync        <= vtiming_hsync;
            vid_vsync        <= vtiming_vsync;
            // During active video, latch the AXIS payload. During blanking,
            // hold the previous value (rgb2dvi gates on active_video anyway).
            if (vtiming_active_video && s_axis_tvalid) begin
                vid_data <= s_axis_tdata;
            end
        end
    end

endmodule
