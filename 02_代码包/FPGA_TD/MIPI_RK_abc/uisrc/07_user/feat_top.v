

`timescale 1ns / 1ps

module feat_top #(
    parameter integer H_ACTIVE      = 1920,
    parameter integer V_ACTIVE      = 1080,
    parameter integer INJECT_ENABLE = 1
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

    output wire [15:0]  O_frame_cnt,
    output wire [1:0]   O_mode,
    output wire [7:0]   O_seg,
    output wire         O_any_lit,
    output wire [15:0]  O_line_beats,
    output wire [15:0]  O_frame_lines,
    output wire         O_blk_valid
);

    

    wire [7:0]  pay_addr;
    wire [1:0]  pay_sel;
    wire [31:0] pay_a, pay_b, pay_c;

    wire        act_a, act_b, act_c;
    wire        a_any_lit, b_any_green, c_any_green;
    wire        a_map_valid, b_frame_done, c_frame_done;

    

    feat_block_stats #(
        .H_ACTIVE (H_ACTIVE),
        .V_ACTIVE (V_ACTIVE),
        .BLK      (120),
        .NX       (16),
        .NY       (9)
    ) u_a (
        .clk       (I_pix_clk),
        .rst_n     (I_pix_rst_n),
        .active    (act_a),
        .de        (I_isp_de),
        .sof       (I_isp_sof),
        .eol       (I_isp_eol),
        .px        (I_isp_px),
        .I_rd_addr (pay_addr),
        .O_rd_data (pay_a),
        .any_lit   (a_any_lit),
        .map_valid (a_map_valid)
    );

    

    feat_green_proj #(
        .H_ACTIVE (H_ACTIVE),
        .V_ACTIVE (V_ACTIVE)
    ) u_b (
        .clk        (I_pix_clk),
        .rst_n      (I_pix_rst_n),
        .active     (act_b),
        .de         (I_isp_de),
        .sof        (I_isp_sof),
        .eol        (I_isp_eol),
        .px         (I_isp_px),
        .I_rd_addr  (pay_addr[6:0]),
        .O_rd_data  (pay_b),
        .any_green  (b_any_green),
        .frame_done (b_frame_done)
    );

    

    feat_trace_centroid #(
        .H_ACTIVE (H_ACTIVE),
        .V_ACTIVE (V_ACTIVE)
    ) u_c (
        .clk        (I_pix_clk),
        .rst_n      (I_pix_rst_n),
        .active     (act_c),
        .de         (I_isp_de),
        .sof        (I_isp_sof),
        .eol        (I_isp_eol),
        .px         (I_isp_px),
        .I_rd_addr  (pay_addr[5:0]),
        .O_rd_data  (pay_c),
        .any_green  (c_any_green),
        .frame_done (c_frame_done)
    );

    

    wire [511:0] s_blk_a, s_blk_b;
    wire         s_sel, s_tog;

    feat_sched #(
        .V_ACTIVE (V_ACTIVE)
    ) u_sched (
        .clk            (I_pix_clk),
        .rst_n          (I_pix_rst_n),
        .de             (I_isp_de),
        .sof            (I_isp_sof),
        .eol            (I_isp_eol),
        .O_pay_addr     (pay_addr),
        .O_pay_sel      (pay_sel),
        .I_a_data       (pay_a),
        .I_b_data       (pay_b),
        .I_c_data       (pay_c),
        .I_a_any_lit    (a_any_lit),
        .I_b_any_green  (b_any_green),
        .I_c_any_green  (c_any_green),
        .O_blk_a        (s_blk_a),
        .O_blk_b        (s_blk_b),
        .O_sel          (s_sel),
        .O_tog          (s_tog),
        .O_frame_cnt    (O_frame_cnt),
        .O_mode         (O_mode),
        .O_seg          (O_seg),
        .O_active_a     (act_a),
        .O_active_b     (act_b),
        .O_active_c     (act_c)
    );

    assign O_any_lit  = (O_mode == 2'd0) ? a_any_lit :
                        (O_mode == 2'd1) ? b_any_green : c_any_green;
    assign O_blk_valid = a_map_valid | b_frame_done | c_frame_done;

    

    reg [2:0]   tog_sync;
    reg [1:0]   sel_sync;
    reg [511:0] blk_hs;

    always @(posedge I_hs_clk or negedge I_hs_rst_n) begin
        if (!I_hs_rst_n) begin
            tog_sync <= 3'd0;
            sel_sync <= 2'd0;
            blk_hs   <= {512{1'b0}};
        end else begin
            tog_sync <= {tog_sync[1:0], s_tog};
            sel_sync <= {sel_sync[0],  s_sel};
            if (tog_sync[2] ^ tog_sync[1])
                blk_hs <= sel_sync[1] ? s_blk_a : s_blk_b;
        end
    end

    

    localparam INJ_EN = (INJECT_ENABLE != 0);

    axis_stat_inject #(
        .INJECT_WORDS (16),
        .INJECT_LINE  (0),
        .BLK_WORDS    (16)
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

    

    reg [15:0] line_beats, line_cnt, frame_lines;
    always @(posedge I_pix_clk or negedge I_pix_rst_n) begin
        if (!I_pix_rst_n) begin
            line_beats  <= 16'd0;
            line_cnt    <= 16'd0;
            frame_lines <= 16'd0;
        end else if (I_isp_de & I_isp_sof) begin
            line_beats  <= 16'd0;
            line_cnt    <= 16'd0;
            frame_lines <= 16'd0;
        end else if (I_isp_de) begin
            line_beats <= I_isp_eol ? 16'd0 : (line_beats + 16'd1);
            if (I_isp_eol) begin
                line_cnt    <= line_cnt + 16'd1;
                frame_lines <= line_cnt + 16'd1;
            end
        end
    end

    assign O_line_beats  = line_beats;
    assign O_frame_lines = frame_lines;

endmodule
