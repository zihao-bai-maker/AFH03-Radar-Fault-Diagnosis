

`timescale 1ns / 1ps

module cam_stat_top #(
    parameter integer H_ACTIVE       = 1920,
    parameter integer V_ACTIVE       = 1080,
    parameter integer N_ROI          = 16,
    parameter integer INJECT_WORDS   = 240,    
    parameter integer INJECT_ENABLE  = 1,      
    parameter integer SAT_THR        = 250     
)(

    input  wire         I_pix_clk,       
    input  wire         I_pix_rst_n,     
    input  wire         I_isp_de,        
    input  wire [127:0] I_isp_px,        
    input  wire         I_isp_sof,       
    input  wire         I_isp_eol,       

    input  wire         I_hs_clk,        
    input  wire         I_hs_rst_n,      

    input  wire         I_pack_tvalid,
    output wire         O_pack_tready,
    input  wire [31:0]  I_pack_tdata,
    input  wire         I_pack_tuser_sof,
    input  wire         I_pack_tlast,

    output wire         O_tx_tvalid,
    input  wire         O_tx_tready,
    output wire [31:0]  O_tx_tdata,
    output wire         O_tx_tuser_sof,
    output wire         O_tx_tlast,

    input  wire         I_cfg_we,
    input  wire [15:0]  I_cfg_addr,
    input  wire [31:0]  I_cfg_wdata,
    input  wire         I_cfg_re,
    output wire [31:0]  O_cfg_rdata,

    output wire [N_ROI-1:0]   O_lit,
    output wire [N_ROI*8-1:0] O_lit_level,
    output wire [15:0]        O_frame_cnt,

    output wire [15:0]        O_line_beats,
    output wire [31:0]        O_frame_beats,
    output wire [15:0]        O_line_cnt
);

    

    localparam integer XBLK_WORDS = 3 + 3*N_ROI + 3;
    localparam integer TOT_WORDS  = 15 + XBLK_WORDS;
    localparam integer BLK_W      = TOT_WORDS * 32;

    

    wire [N_ROI*32-1:0] rsum, gsum, bsum;
    wire [N_ROI*24-1:0] cnt;
    wire [N_ROI*24-1:0] maxrgb;
    wire [N_ROI*24-1:0] satcnt;      
    wire [N_ROI*24-1:0] mean24;      
    wire [N_ROI*8-1:0]  max8;        
    wire                mean_valid;  
    wire                frame_end;

    wire [N_ROI*48-1:0] roi_geo;

    roi_color_stat #(
        .H_ACTIVE     (H_ACTIVE),
        .V_ACTIVE     (V_ACTIVE),
        .PIX_PER_BEAT (4),
        .N_ROI        (N_ROI),
        .SAT_THR      (SAT_THR)
    ) u_roi_stat (
        .I_clk        (I_pix_clk),
        .I_rst_n      (I_pix_rst_n),
        .I_de         (I_isp_de),
        .I_sof        (I_isp_sof),
        .I_eol        (I_isp_eol),
        .I_px         (I_isp_px),
        .I_roi_geo    (roi_geo),
        .I_roi_en     ({N_ROI{1'b1}}),
        .O_rsum       (rsum),
        .O_gsum       (gsum),
        .O_bsum       (bsum),
        .O_cnt        (cnt),
        .O_maxrgb     (maxrgb),
        .O_satcnt     (satcnt),
        .O_mean24     (mean24),
        .O_max8       (max8),
        .O_mean_valid (mean_valid),
        .O_frame_end  (frame_end),
        .O_frame_cnt  (O_frame_cnt),
        .O_line_beats (O_line_beats),
        .O_frame_beats(O_frame_beats),
        .O_line_cnt   (O_line_cnt)
    );

    wire [BLK_W-1:0] stat_block;
    wire             stat_valid;

    cam_stat_regs #(
        .N_ROI   (N_ROI),
        .SAT_THR (SAT_THR)
    ) u_stat_regs (
        .I_clk         (I_pix_clk),
        .I_rst_n       (I_pix_rst_n),
        .I_rsum        (rsum),
        .I_gsum        (gsum),
        .I_bsum        (bsum),
        .I_cnt         (cnt),
        .I_maxrgb      (maxrgb),
        .I_satcnt      (satcnt),        
        .I_mean24      (mean24),        
        .I_max8        (max8),          
        .I_mean_valid  (mean_valid),    
        .I_frame_end   (frame_end),
        .I_frame_cnt   (O_frame_cnt),
        .I_line_beats  (O_line_beats),
        .I_frame_beats (O_frame_beats),
        .I_line_cnt    (O_line_cnt),
        .I_cfg_we      (I_cfg_we),
        .I_cfg_addr    (I_cfg_addr),
        .I_cfg_wdata   (I_cfg_wdata),
        .I_cfg_re      (I_cfg_re),
        .O_cfg_rdata   (O_cfg_rdata),
        .O_lit         (O_lit),
        .O_lit_level   (O_lit_level),
        .O_any_lit     (),
        .O_roi_geo     (roi_geo),
        .O_stat_block  (stat_block),
        .O_stat_valid  (stat_valid)
    );

    

    reg [BLK_W-1:0] blk_a, blk_b;
    reg         sel_p;      
    reg         tog_p;
    reg         valid_p_d;

    always @(posedge I_pix_clk or negedge I_pix_rst_n) begin
        if (!I_pix_rst_n) begin
            blk_a     <= {BLK_W{1'b0}};
            blk_b     <= {BLK_W{1'b0}};
            sel_p     <= 1'b0;
            tog_p     <= 1'b0;
            valid_p_d <= 1'b0;
        end else begin
            valid_p_d <= stat_valid;
            if (stat_valid & ~valid_p_d) begin   
                if (sel_p) blk_b <= stat_block;
                else       blk_a <= stat_block;
                sel_p <= ~sel_p;
                tog_p <= ~tog_p;
            end
        end
    end

    reg [2:0]    tog_sync;
    reg [BLK_W-1:0] blk_hs;
    always @(posedge I_hs_clk or negedge I_hs_rst_n) begin
        if (!I_hs_rst_n) begin
            tog_sync <= 3'd0;
            blk_hs   <= {BLK_W{1'b0}};
        end else begin
            tog_sync <= {tog_sync[1:0], tog_p};
            if (tog_sync[2] ^ tog_sync[1])       
                blk_hs <= sel_p ? blk_a : blk_b; 
        end
    end

    

    localparam INJ_EN = (INJECT_ENABLE != 0);

    axis_stat_inject #(
        .INJECT_WORDS (INJECT_WORDS),
        .INJECT_LINE  (0),
        .BLK_WORDS    (TOT_WORDS)
    ) u_inject (
        .clk          (I_hs_clk),
        .rst_n        (I_hs_rst_n),
        .enable       (INJ_EN),
        .s_tvalid     (I_pack_tvalid),
        .s_tready     (O_pack_tready),
        .s_tdata      (I_pack_tdata),
        .s_tuser_sof  (I_pack_tuser_sof),
        .s_tlast      (I_pack_tlast),
        .m_tvalid     (O_tx_tvalid),
        .m_tready     (O_tx_tready),
        .m_tdata      (O_tx_tdata),
        .m_tuser_sof  (O_tx_tuser_sof),
        .m_tlast      (O_tx_tlast),
        .I_stat_block (blk_hs)
    );

endmodule
