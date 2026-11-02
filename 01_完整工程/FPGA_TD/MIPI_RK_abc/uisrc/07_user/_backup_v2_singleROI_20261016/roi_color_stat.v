

`timescale 1ns / 1ps

module roi_color_stat #(
    parameter integer H_ACTIVE     = 1920,
    parameter integer V_ACTIVE     = 1080,
    parameter integer PIX_PER_BEAT = 4,
    parameter integer N_ROI        = 8,
    parameter integer SUM_W        = 32,
    parameter integer CNT_W        = 24,
    parameter integer XW           = 12,
    parameter integer YW           = 12
)(
    input  wire                    I_clk,        
    input  wire                    I_rst_n,      

    input  wire                    I_de,         
    input  wire                    I_sof,        
    input  wire                    I_eol,        
    input  wire [127:0]            I_px,         

    input  wire [N_ROI*(2*XW+2*YW)-1:0] I_roi_geo,

    input  wire [N_ROI-1:0]        I_roi_en,

    output wire [N_ROI*SUM_W-1:0]  O_rsum,
    output wire [N_ROI*SUM_W-1:0]  O_gsum,
    output wire [N_ROI*SUM_W-1:0]  O_bsum,
    output wire [N_ROI*CNT_W-1:0]  O_cnt,
    output wire [N_ROI*24-1:0]     O_maxrgb,     

    output wire                    O_frame_end,
    output reg  [15:0]             O_frame_cnt,

    output reg  [15:0]             O_line_beats,
    output reg  [31:0]             O_frame_beats,
    output reg  [15:0]             O_line_cnt
);

    localparam [XW-1:0]  BEATS_M1 = (H_ACTIVE / PIX_PER_BEAT) - 1;
    localparam [YW-1:0]  LINES_M1 = V_ACTIVE - 1;

    wire _unused_bm1 = |BEATS_M1;      

    

    reg [XW-1:0] x_r;
    reg [YW-1:0] y_r;

    

    reg        frame_had_data;        

    wire last_beat_of_last_line = I_de & I_eol & (y_r == LINES_M1);
    wire early_sof              = I_de & I_sof & frame_had_data;

    assign O_frame_end = last_beat_of_last_line | early_sof;

    

    reg [15:0] cur_line_beats;
    reg [31:0] cur_frame_beats;
    reg [15:0] cur_line_cnt;

    

    always @(posedge I_clk or negedge I_rst_n) begin
        if (!I_rst_n) begin
            x_r             <= {XW{1'b0}};
            y_r             <= {YW{1'b0}};
            frame_had_data  <= 1'b0;
            cur_line_beats  <= 16'd0;
            cur_frame_beats <= 32'd0;
            cur_line_cnt    <= 16'd0;
            O_frame_cnt     <= 16'd0;
            O_line_beats    <= 16'd0;
            O_frame_beats   <= 32'd0;
            O_line_cnt      <= 16'd0;
        end else begin

            if (I_de & I_sof) begin
                x_r             <= {{(XW-1){1'b0}}, 1'b1};   
                y_r             <= {YW{1'b0}};
                cur_line_beats  <= 16'd1;
                cur_frame_beats <= 32'd1;
                cur_line_cnt    <= 16'd0;
                frame_had_data  <= 1'b0;
            end

            else if (I_de & I_eol) begin
                x_r            <= {XW{1'b0}};
                y_r            <= (y_r == LINES_M1) ? {YW{1'b0}} : (y_r + 1'b1);
                O_line_beats   <= cur_line_beats + 16'd1;
                cur_line_beats <= 16'd0;
                cur_line_cnt   <= cur_line_cnt + 16'd1;
                cur_frame_beats<= cur_frame_beats + 32'd1;
                frame_had_data <= 1'b1;
            end

            else if (I_de) begin
                x_r            <= x_r + 1'b1;
                cur_line_beats <= cur_line_beats + 16'd1;
                cur_frame_beats<= cur_frame_beats + 32'd1;
            end

            if (O_frame_end) begin
                O_frame_cnt   <= O_frame_cnt + 16'd1;
                O_frame_beats <= (I_de & I_eol) ? (cur_frame_beats + 32'd1)
                                                :  cur_frame_beats;
                O_line_cnt    <= (I_de & I_eol) ? (cur_line_cnt + 16'd1)
                                                :  cur_line_cnt;
            end
        end
    end

    wire [XW-1:0] beat_x_base = x_r << 2;   

    

    genvar n;
    generate
        for (n = 0; n < N_ROI; n = n + 1) begin : g_roi
            wire [XW-1:0] x0 = I_roi_geo[n*(2*XW+2*YW) + 0         +: XW];
            wire [YW-1:0] y0 = I_roi_geo[n*(2*XW+2*YW) + XW        +: YW];
            wire [XW-1:0] x1 = I_roi_geo[n*(2*XW+2*YW) + XW+YW     +: XW];
            wire [YW-1:0] y1 = I_roi_geo[n*(2*XW+2*YW) + 2*XW+YW   +: YW];

            wire [SUM_W-1:0] rsum_w, gsum_w, bsum_w;
            wire [CNT_W-1:0] cnt_w;
            wire [7:0]       rmax_w, gmax_w, bmax_w;

            roi_win_acc #(
                .PIX_PER_BEAT (PIX_PER_BEAT),
                .SUM_W        (SUM_W),
                .CNT_W        (CNT_W),
                .XW           (XW),
                .YW           (YW)
            ) u_acc (
                .I_clk          (I_clk),
                .I_rst_n        (I_rst_n),
                .I_en           (I_roi_en[n]),
                .I_de           (I_de),
                .I_x_base       (beat_x_base),
                .I_y            (y_r),
                .I_end_of_frame (O_frame_end),
                .I_px           (I_px),
                .I_x0           (x0),
                .I_y0           (y0),
                .I_x1           (x1),
                .I_y1           (y1),
                .O_rsum         (rsum_w),
                .O_gsum         (gsum_w),
                .O_bsum         (bsum_w),
                .O_cnt          (cnt_w),
                .O_rmax         (rmax_w),
                .O_gmax         (gmax_w),
                .O_bmax         (bmax_w)
            );

            assign O_rsum  [n*SUM_W +: SUM_W] = rsum_w;
            assign O_gsum  [n*SUM_W +: SUM_W] = gsum_w;
            assign O_bsum  [n*SUM_W +: SUM_W] = bsum_w;
            assign O_cnt   [n*CNT_W +: CNT_W] = cnt_w;
            assign O_maxrgb[n*24    +: 24   ] = {rmax_w, gmax_w, bmax_w};
        end
    endgenerate

endmodule
