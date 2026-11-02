

`timescale 1ns / 1ps

module cam_stat_regs #(
    parameter integer N_ROI   = 16,
    parameter integer SUM_W   = 32,
    parameter integer CNT_W   = 24,
    parameter integer LIT_MAX = 8'd64,
    parameter integer SAT_THR = 250,     

    parameter integer DEF_COLS  = 4,
    parameter integer DEF_X0    = 160,   
    parameter integer DEF_Y0    = 140,   
    parameter integer DEF_W     = 64,
    parameter integer DEF_H     = 64,
    parameter integer DEF_PITCH = 440,   
    parameter integer DEF_RPITCH= 440,   

    parameter integer DEF_THR_AVG = 150, 
    parameter integer DEF_MODE    = 32'h0000_0007  
)(
    input  wire                    I_clk,
    input  wire                    I_rst_n,

    input  wire [N_ROI*SUM_W-1:0]  I_rsum,
    input  wire [N_ROI*SUM_W-1:0]  I_gsum,
    input  wire [N_ROI*SUM_W-1:0]  I_bsum,
    input  wire [N_ROI*CNT_W-1:0]  I_cnt,
    input  wire [N_ROI*24-1:0]     I_maxrgb,

    input  wire [N_ROI*CNT_W-1:0]  I_satcnt,
    input  wire [N_ROI*24-1:0]     I_mean24,
    input  wire [N_ROI*8-1:0]      I_max8,
    input  wire                    I_mean_valid,   

    input  wire                    I_frame_end,   
    input  wire [15:0]             I_frame_cnt,
    input  wire [15:0]             I_line_beats,
    input  wire [31:0]             I_frame_beats,
    input  wire [15:0]             I_line_cnt,

    input  wire                    I_cfg_we,
    input  wire [15:0]             I_cfg_addr,
    input  wire [31:0]             I_cfg_wdata,
    input  wire                    I_cfg_re,
    output reg  [31:0]             O_cfg_rdata,

    output wire [N_ROI-1:0]        O_lit,
    output wire [N_ROI*8-1:0]      O_lit_level,
    output wire                    O_any_lit,

    output wire [N_ROI*48-1:0]     O_roi_geo,

    

    output reg  [TOT_WORDS*32-1:0] O_stat_block,
    output reg                     O_stat_valid
);

    

    

    

    localparam integer NROI_PAD   = (N_ROI < 8) ? 8 : N_ROI;   
    localparam integer XBLK_WORDS = 3 + 3*N_ROI + 3;
    localparam integer TOT_WORDS  = 15 + XBLK_WORDS;

    localparam integer CFG_N = 9 * N_ROI;    
    localparam integer RES_N = 9 * N_ROI;
    localparam integer GLO_N = 8;
    localparam [15:0]  GLO_BASE = 16'd0 + (CFG_N + RES_N);

    localparam integer DEF_THR = DEF_W * DEF_H * DEF_THR_AVG;

    

    reg fe_d;
    always @(posedge I_clk or negedge I_rst_n) begin
        if (!I_rst_n) fe_d <= 1'b0;
        else          fe_d <= I_frame_end;
    end

    

    wire [CFG_N*32-1:0] cfg_flat;
    wire [RES_N*32-1:0] res_flat;
    wire [N_ROI-1:0]    lit_w;
    wire [N_ROI*8-1:0]  lvl_flat;
    wire [N_ROI-1:0]    lit_lat;      
    wire [N_ROI*8-1:0]  lvl_nx_flat;  

    genvar n;
    generate
        for (n = 0; n < N_ROI; n = n + 1) begin : g_roi

            reg [31:0] c_x0y0, c_x1y1, c_rthr, c_gthr, c_bthr, c_mode;

            localparam [11:0] DX0 = DEF_X0 + (n % DEF_COLS) * DEF_PITCH;
            localparam [11:0] DY0 = DEF_Y0 + (n / DEF_COLS) * DEF_RPITCH;

            always @(posedge I_clk or negedge I_rst_n) begin
                if (!I_rst_n) begin
                    c_x0y0 <= {DY0, 4'd0, DX0};
                    c_x1y1 <= {DY0, 4'd0, (DX0 + DEF_W)};
                    c_rthr <= DEF_THR[31:0];
                    c_gthr <= DEF_THR[31:0];
                    c_bthr <= DEF_THR[31:0];
                    c_mode <= DEF_MODE;
                end else if (I_cfg_we) begin
                    if      (I_cfg_addr == (6*n + 0)) c_x0y0 <= I_cfg_wdata;
                    else if (I_cfg_addr == (6*n + 1)) c_x1y1 <= I_cfg_wdata;
                    else if (I_cfg_addr == (6*n + 2)) c_rthr <= I_cfg_wdata;
                    else if (I_cfg_addr == (6*n + 3)) c_gthr <= I_cfg_wdata;
                    else if (I_cfg_addr == (6*n + 4)) c_bthr <= I_cfg_wdata;
                    else if (I_cfg_addr == (6*n + 5)) c_mode <= I_cfg_wdata;
                end
            end

            assign cfg_flat[n*192 + 0*32 +: 32] = c_x0y0;
            assign cfg_flat[n*192 + 1*32 +: 32] = c_x1y1;
            assign cfg_flat[n*192 + 2*32 +: 32] = c_rthr;
            assign cfg_flat[n*192 + 3*32 +: 32] = c_gthr;
            assign cfg_flat[n*192 + 4*32 +: 32] = c_bthr;
            assign cfg_flat[n*192 + 5*32 +: 32] = c_mode;

            assign O_roi_geo[n*48 + 0  +: 12] = c_x0y0[11:0];    
            assign O_roi_geo[n*48 + 12 +: 12] = c_x0y0[27:16];   
            assign O_roi_geo[n*48 + 24 +: 12] = c_x1y1[11:0];    
            assign O_roi_geo[n*48 + 36 +: 12] = c_x1y1[27:16];   

            wire [SUM_W-1:0] rsum = I_rsum[n*SUM_W +: SUM_W];
            wire [SUM_W-1:0] gsum = I_gsum[n*SUM_W +: SUM_W];
            wire [SUM_W-1:0] bsum = I_bsum[n*SUM_W +: SUM_W];
            wire [CNT_W-1:0] cnt  = I_cnt [n*CNT_W +: CNT_W];
            wire [23:0]      mx   = I_maxrgb[n*24 +: 24];

            wire [CNT_W-1:0] sat  = I_satcnt[n*CNT_W +: CNT_W];
            wire [23:0]      mn   = I_mean24[n*24 +: 24];
            wire [7:0]       m8   = I_max8  [n*8 +: 8];

            wire lit_r = (c_rthr != 32'd0) && (rsum >= c_rthr);
            wire lit_g = (c_gthr != 32'd0) && (gsum >= c_gthr);
            wire lit_b = (c_bthr != 32'd0) && (bsum >= c_bthr);

            wire use_r  = c_mode[0];
            wire use_g  = c_mode[1];
            wire use_b  = c_mode[2];
            wire is_and = c_mode[3];
            wire inv    = c_mode[4];

            wire and_lit = (use_r ? lit_r : 1'b1) &
                           (use_g ? lit_g : 1'b1) &
                           (use_b ? lit_b : 1'b1);
            wire or_lit  = (use_r ? lit_r : 1'b0) |
                           (use_g ? lit_g : 1'b0) |
                           (use_b ? lit_b : 1'b0);
            wire raw_lit = is_and ? and_lit : or_lit;

            assign lit_w[n] = raw_lit ^ inv;

            reg [7:0] lvl;

            wire [7:0] lvl_nx = lit_lat[n]
                              ? ((lvl >= LIT_MAX) ? LIT_MAX : (lvl + 8'd1))
                              : ((lvl == 8'd0)    ? 8'd0    : (lvl - 8'd1));
            always @(posedge I_clk or negedge I_rst_n) begin
                if (!I_rst_n) lvl <= 8'd0;
                else if (fe_d) lvl <= lvl_nx;
            end
            assign lvl_flat[n*8 +: 8]    = lvl;
            assign lvl_nx_flat[n*8 +: 8] = lvl_nx;

            reg [31:0] d_rsum, d_gsum, d_bsum, d_cnt, d_max, d_lit;
            reg        d_lit_bit;

            reg [31:0] d_sat, d_mean, d_max8;

            always @(posedge I_clk or negedge I_rst_n) begin
                if (!I_rst_n) begin
                    d_rsum   <= 32'd0;
                    d_gsum   <= 32'd0;
                    d_bsum   <= 32'd0;
                    d_cnt    <= 32'd0;
                    d_max    <= 32'd0;
                    d_lit    <= 32'd0;
                    d_lit_bit<= 1'b0;
                    d_sat    <= 32'd0;
                    d_mean   <= 32'd0;
                    d_max8   <= 32'd0;
                end else if (I_frame_end) begin

                    d_rsum    <= rsum;
                    d_gsum    <= gsum;
                    d_bsum    <= bsum;
                    d_cnt     <= {{(32-CNT_W){1'b0}}, cnt};
                    d_max     <= {8'd0, mx};
                    d_lit_bit <= lit_w[n];

                    
                    d_sat     <= {{(32-CNT_W){1'b0}}, sat};
                    d_mean    <= {8'd0, mn};
                    d_max8    <= {24'd0, m8};
                end else if (fe_d) begin
                    d_lit <= {lvl_nx, 16'd0, d_lit_bit, 7'd0};
                end
            end

            assign lit_lat[n] = d_lit_bit;

            assign res_flat[n*288 + 0*32 +: 32] = d_rsum;
            assign res_flat[n*288 + 1*32 +: 32] = d_gsum;
            assign res_flat[n*288 + 2*32 +: 32] = d_bsum;
            assign res_flat[n*288 + 3*32 +: 32] = d_cnt;
            assign res_flat[n*288 + 4*32 +: 32] = d_max;
            assign res_flat[n*288 + 5*32 +: 32] = d_lit;
            assign res_flat[n*288 + 6*32 +: 32] = d_sat;      
            assign res_flat[n*288 + 7*32 +: 32] = d_mean;     
            assign res_flat[n*288 + 8*32 +: 32] = d_max8;     
        end
    endgenerate

    assign O_lit       = lit_w;
    assign O_lit_level = lvl_flat;
    assign O_any_lit   = |lit_w;

    

    reg [31:0] g_id, g_fcnt, g_status, g_ctrl;
    reg [7:0]  n_lit;

    
    integer m;
    always @(*) begin
        n_lit = 8'd0;
        for (m = 0; m < N_ROI; m = m + 1) n_lit = n_lit + {7'd0, lit_lat[m]};
    end

    always @(posedge I_clk or negedge I_rst_n) begin
        if (!I_rst_n) begin
            g_id     <= 32'hA5C30001;
            g_fcnt   <= 32'd0;
            g_status <= 32'd0;
            g_ctrl   <= 32'd0;
        end else begin
            g_fcnt <= {16'd0, I_frame_cnt};
            if (I_cfg_we && (I_cfg_addr == 16'h0063)) g_ctrl <= I_cfg_wdata;
            if (fe_d) g_status <= {14'd0, (|lit_lat), 1'b1, n_lit, I_frame_cnt[7:0]};
        end
    end

    

    

    wire [NROI_PAD*32-1:0] lit_blk;        
    generate
        for (n = 0; n < NROI_PAD; n = n + 1) begin : g_litblk
            if (n < N_ROI) begin : g_real
                assign lit_blk[n*32 +: 32] = {lvl_nx_flat[n*8 +: 8], 23'd0, lit_lat[n]};
            end else begin : g_pad
                assign lit_blk[n*32 +: 32] = 32'd0;   
            end
        end
    endgenerate

    wire [31:0] s0  = 32'hA5C35A00;                                  
    wire [31:0] s1  = {16'd0, I_frame_cnt};                          
    wire [31:0] s2  = {14'd0, (|lit_lat), 1'b1, n_lit, I_frame_cnt[7:0]}; 
    wire [31:0] s11 = {16'd0, I_line_beats};                         
    wire [31:0] s12 = I_frame_beats;                                 
    wire [31:0] s13 = 32'h5A5AA5A5;                                  
    wire [31:0] s14 = 32'hA5C30001;                                  

    

    wire [31:0] legacy_xor = s0 ^ s1 ^ s2
                    ^ lit_blk[0*32 +: 32] ^ lit_blk[1*32 +: 32]
                    ^ lit_blk[2*32 +: 32] ^ lit_blk[3*32 +: 32]
                    ^ lit_blk[4*32 +: 32] ^ lit_blk[5*32 +: 32]
                    ^ lit_blk[6*32 +: 32] ^ lit_blk[7*32 +: 32]
                    ^ s11 ^ s12 ^ s13 ^ s14;

    

    

    

    

    
    wire [31:0] x0  = 32'hA5C3E100;                                        
    wire [31:0] x1  = {14'd0, N_ROI[15:0], 8'd3, XBLK_WORDS[7:0]};
    wire [31:0] x2  = {14'd0, SAT_THR[15:0], 8'd8, 8'd0};
    wire [31:0] xend= 32'hA5C3E1FF;                                        
    wire [7:0]  div_gen = I_frame_cnt[7:0];
    wire [31:0] xver= {22'd0, div_gen, 8'h01};

    wire [N_ROI*64-1:0] roi_blk;      
    generate
        for (n = 0; n < N_ROI; n = n + 1) begin : g_roiblk
            assign roi_blk[n*64 + 0 +: 32] = {{(32-CNT_W){1'b0}}, I_satcnt[n*CNT_W +: CNT_W]};
            assign roi_blk[n*64 + 32 +: 32] = {8'd0, I_maxrgb[n*24 +: 24]};
        end
    endgenerate

    reg [31:0] xacc;
    integer p;
    always @(*) begin
        xacc = x0 ^ x1 ^ x2 ^ xend ^ xver;
        for (p = 0; p < N_ROI; p = p + 1)
            xacc = xacc ^ xmean32[p*32 +: 32]
                        ^ roi_blk[p*64 + 32 +: 32]
                        ^ roi_blk[p*64 +  0 +: 32];
    end
    wire [31:0] xxor = xacc;

    

    

    reg [TOT_WORDS*32-1:0] blk_nx;
    integer w;
    always @(*) begin
        blk_nx = TOT_WORDS*32'd0;

        blk_nx[0*32 +: 32] = s0;
        blk_nx[1*32 +: 32] = s1;
        blk_nx[2*32 +: 32] = s2;
        for (w = 0; w < 8; w = w + 1)
            blk_nx[(3+w)*32 +: 32] = lit_blk[w*32 +: 32];
        blk_nx[11*32 +: 32] = s11;
        blk_nx[12*32 +: 32] = s12;
        blk_nx[13*32 +: 32] = s13;
        blk_nx[14*32 +: 32] = s14;

        blk_nx[15*32 +: 32] = x0;
        blk_nx[16*32 +: 32] = x1;
        blk_nx[17*32 +: 32] = x2;
        for (w = 0; w < N_ROI; w = w + 1) begin
            blk_nx[(18 + 3*w + 0)*32 +: 32] = xmean32[w*32 +: 32];       
            blk_nx[(18 + 3*w + 1)*32 +: 32] = roi_blk[w*64 + 32 +: 32];  
            blk_nx[(18 + 3*w + 2)*32 +: 32] = roi_blk[w*64 +  0 +: 32];  
        end
        blk_nx[(18 + 3*N_ROI)*32 +: 32] = xend;
        blk_nx[(19 + 3*N_ROI)*32 +: 32] = xver;
        blk_nx[(20 + 3*N_ROI)*32 +: 32] = xxor;
    end

    always @(posedge I_clk or negedge I_rst_n) begin
        if (!I_rst_n) begin
            O_stat_block <= TOT_WORDS*32'd0;
            O_stat_valid <= 1'b0;
        end else begin
            O_stat_valid <= fe_d;          
            if (fe_d) O_stat_block <= blk_nx;
        end
    end

    

    
    reg [N_ROI*24-1:0] mean_snap;
    always @(posedge I_clk or negedge I_rst_n) begin
        if (!I_rst_n)        mean_snap <= {N_ROI*24{1'b0}};
        else if (I_mean_valid) mean_snap <= I_mean24;
    end

    wire [N_ROI*32-1:0] xmean32;
    generate
        for (n = 0; n < N_ROI; n = n + 1) begin : g_xmean32
            assign xmean32[n*32 +: 32] = {8'd0, mean_snap[n*24 +: 24]};
        end
    endgenerate

    

    
    always @(*) begin
        if (I_cfg_addr < CFG_N[15:0])
            O_cfg_rdata = cfg_flat[I_cfg_addr*32 +: 32];
        else if (I_cfg_addr < (CFG_N + RES_N))
            O_cfg_rdata = res_flat[(I_cfg_addr - CFG_N[15:0])*32 +: 32];
        else begin
            case (I_cfg_addr - GLO_BASE)
                16'd0:   O_cfg_rdata = g_id;
                16'd1:   O_cfg_rdata = g_fcnt;
                16'd2:   O_cfg_rdata = g_status;
                16'd3:   O_cfg_rdata = g_ctrl;
                16'd4:   O_cfg_rdata = legacy_xor;   
                16'd5:   O_cfg_rdata = x1;           
                16'd6:   O_cfg_rdata = xxor;         
                16'd7:   O_cfg_rdata = {24'd0, SAT_THR[7:0]};
                default: O_cfg_rdata = 32'hDEAD_BEEF;
            endcase
        end
    end

    wire _unused_re = I_cfg_re;   

endmodule
