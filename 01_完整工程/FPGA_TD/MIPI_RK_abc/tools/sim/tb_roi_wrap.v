

`timescale 1ns / 1ps

module tb_roi_wrap #(
    parameter integer N_ROI   = 16,
    parameter integer SAT_THR = 250
)(
    input  wire         clk,
    input  wire         rst_n,

    input  wire         i_de,
    input  wire         i_sof,
    input  wire         i_eol,
    input  wire [127:0] i_px,
    input  wire [N_ROI*(24+24)-1:0] i_geo,   

    output wire [15:0]        o_frame_cnt,
    output wire               o_frame_end,

    output wire [N_ROI*32-1:0] o_rsum,
    output wire [N_ROI*32-1:0] o_gsum,
    output wire [N_ROI*32-1:0] o_bsum,
    output wire [N_ROI*24-1:0] o_cnt,
    output wire [N_ROI*24-1:0] o_maxrgb,
    output wire [N_ROI*24-1:0] o_satcnt,
    output wire [N_ROI*24-1:0] o_mean24,
    output wire [N_ROI*8-1:0]  o_max8,
    output wire                o_mean_valid,
    output wire [15:0]         o_line_beats,
    output wire [31:0]         o_frame_beats,
    output wire [15:0]         o_line_cnt,

    output wire [31:0]         a_rsum   [N_ROI-1:0],
    output wire [31:0]         a_gsum   [N_ROI-1:0],
    output wire [31:0]         a_bsum   [N_ROI-1:0],
    output wire [23:0]         a_cnt    [N_ROI-1:0],
    output wire [23:0]         a_maxrgb [N_ROI-1:0],
    output wire [23:0]         a_satcnt [N_ROI-1:0],
    output wire [23:0]         a_mean24 [N_ROI-1:0],
    output wire [7:0]          a_max8   [N_ROI-1:0]
);

    genvar gi;
    generate
        for (gi = 0; gi < N_ROI; gi = gi + 1) begin : g_unpack
            assign a_rsum  [gi] = o_rsum  [gi*32 +: 32];
            assign a_gsum  [gi] = o_gsum  [gi*32 +: 32];
            assign a_bsum  [gi] = o_bsum  [gi*32 +: 32];
            assign a_cnt   [gi] = o_cnt   [gi*24 +: 24];
            assign a_maxrgb[gi] = o_maxrgb[gi*24 +: 24];
            assign a_satcnt[gi] = o_satcnt[gi*24 +: 24];
            assign a_mean24[gi] = o_mean24[gi*24 +: 24];
            assign a_max8  [gi] = o_max8  [gi*8  +: 8];
        end
    endgenerate

    roi_color_stat #(
        .N_ROI    (N_ROI),
        .SAT_THR  (SAT_THR)
    ) u_roi (
        .I_clk        (clk),
        .I_rst_n      (rst_n),
        .I_de         (i_de),
        .I_sof        (i_sof),
        .I_eol        (i_eol),
        .I_px         (i_px),
        .I_roi_geo    (i_geo),
        .I_roi_en     ({N_ROI{1'b1}}),
        .O_rsum       (o_rsum),
        .O_gsum       (o_gsum),
        .O_bsum       (o_bsum),
        .O_cnt        (o_cnt),
        .O_maxrgb     (o_maxrgb),
        .O_satcnt     (o_satcnt),
        .O_mean24     (o_mean24),
        .O_max8       (o_max8),
        .O_mean_valid (o_mean_valid),
        .O_frame_end  (o_frame_end),
        .O_frame_cnt  (o_frame_cnt),
        .O_line_beats (o_line_beats),
        .O_frame_beats(o_frame_beats),
        .O_line_cnt   (o_line_cnt)
    );

endmodule
