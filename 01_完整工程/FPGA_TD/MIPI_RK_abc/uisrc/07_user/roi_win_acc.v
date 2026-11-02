

`timescale 1ns / 1ps

module roi_win_acc #(
    parameter integer PIX_PER_BEAT = 4,
    parameter integer SUM_W        = 32,
    parameter integer CNT_W        = 24,
    parameter integer XW           = 12,
    parameter integer YW           = 12,

    parameter integer SAT_THR      = 250
)(
    input  wire                I_clk,
    input  wire                I_rst_n,
    input  wire                I_en,            

    input  wire                I_de,            
    input  wire [XW-1:0]       I_x_base,        
    input  wire [YW-1:0]       I_y,             
    input  wire                I_end_of_frame,  
    input  wire [127:0]        I_px,            

    input  wire [XW-1:0]       I_x0,
    input  wire [YW-1:0]       I_y0,
    input  wire [XW-1:0]       I_x1,
    input  wire [YW-1:0]       I_y1,

    output reg  [SUM_W-1:0]    O_rsum,
    output reg  [SUM_W-1:0]    O_gsum,
    output reg  [SUM_W-1:0]    O_bsum,
    output reg  [CNT_W-1:0]    O_cnt,
    output reg  [7:0]          O_rmax,
    output reg  [7:0]          O_gmax,
    output reg  [7:0]          O_bmax,
    output reg  [CNT_W-1:0]    O_satcnt        
);

    wire de = I_de & I_en;
    wire eof = I_end_of_frame & I_en;

    

    
    wire [7:0] p_r  [PIX_PER_BEAT-1:0];
    wire [7:0] p_g  [PIX_PER_BEAT-1:0];
    wire [7:0] p_b  [PIX_PER_BEAT-1:0];
    wire       p_hit[PIX_PER_BEAT-1:0];
    wire       p_sat[PIX_PER_BEAT-1:0];   

    wire in_y = (I_y >= I_y0) && (I_y < I_y1);

    genvar k;
    generate
        for (k = 0; k < PIX_PER_BEAT; k = k + 1) begin : g_px
            wire [31:0]    slot = I_px[32*k +: 32];
            wire [XW+1:0]  x_k  = {2'b00, I_x_base} + k;   
            assign p_r[k] = slot[23:16];
            assign p_g[k] = slot[15: 8];
            assign p_b[k] = slot[ 7: 0];
            assign p_hit[k] = in_y &&
                              (x_k >= {2'b00, I_x0}) &&
                              (x_k <  {2'b00, I_x1});

            assign p_sat[k] = (p_r[k] > SAT_THR[7:0]) |
                              (p_g[k] > SAT_THR[7:0]) |
                              (p_b[k] > SAT_THR[7:0]);
        end
    endgenerate

    

    integer j;
    reg [SUM_W-1:0] beat_r, beat_g, beat_b;
    reg [3:0]       beat_n;
    reg [3:0]       beat_sat;      
    always @(*) begin
        beat_r   = {SUM_W{1'b0}};
        beat_g   = {SUM_W{1'b0}};
        beat_b   = {SUM_W{1'b0}};
        beat_n   = 4'd0;
        beat_sat = 4'd0;
        for (j = 0; j < PIX_PER_BEAT; j = j + 1) begin
            if (de && p_hit[j]) begin
                beat_r = beat_r + {{(SUM_W-8){1'b0}}, p_r[j]};
                beat_g = beat_g + {{(SUM_W-8){1'b0}}, p_g[j]};
                beat_b = beat_b + {{(SUM_W-8){1'b0}}, p_b[j]};
                beat_n = beat_n + 4'd1;
                if (p_sat[j]) beat_sat = beat_sat + 4'd1;
            end
        end
    end

    

    reg [SUM_W-1:0] acc_r, acc_g, acc_b;
    reg [CNT_W-1:0] acc_n;
    reg [CNT_W-1:0] acc_sat;       
    reg [7:0]       max_r, max_g, max_b;

    wire [SUM_W-1:0] acc_r_nx   = acc_r + beat_r;
    wire [SUM_W-1:0] acc_g_nx   = acc_g + beat_g;
    wire [SUM_W-1:0] acc_b_nx   = acc_b + beat_b;
    wire [CNT_W-1:0] acc_n_nx   = acc_n + {{(CNT_W-4){1'b0}}, beat_n};
    wire [CNT_W-1:0] acc_sat_nx = acc_sat + {{(CNT_W-4){1'b0}}, beat_sat};   

    always @(posedge I_clk or negedge I_rst_n) begin
        if (!I_rst_n) begin
            acc_r   <= {SUM_W{1'b0}};
            acc_g   <= {SUM_W{1'b0}};
            acc_b   <= {SUM_W{1'b0}};
            acc_n   <= {CNT_W{1'b0}};
            acc_sat <= {CNT_W{1'b0}};
            max_r   <= 8'd0;
            max_g   <= 8'd0;
            max_b   <= 8'd0;
            O_rsum  <= {SUM_W{1'b0}};
            O_gsum  <= {SUM_W{1'b0}};
            O_bsum  <= {SUM_W{1'b0}};
            O_cnt   <= {CNT_W{1'b0}};
            O_rmax  <= 8'd0;
            O_gmax  <= 8'd0;
            O_bmax  <= 8'd0;
            O_satcnt<= {CNT_W{1'b0}};
        end else if (eof) begin

            O_rsum   <= acc_r_nx;
            O_gsum   <= acc_g_nx;
            O_bsum   <= acc_b_nx;
            O_cnt    <= acc_n_nx;
            O_satcnt <= acc_sat_nx;      
            O_rmax   <= max_r;
            O_gmax   <= max_g;
            O_bmax   <= max_b;
            acc_r    <= {SUM_W{1'b0}};
            acc_g    <= {SUM_W{1'b0}};
            acc_b    <= {SUM_W{1'b0}};
            acc_n    <= {CNT_W{1'b0}};
            acc_sat  <= {CNT_W{1'b0}};
            max_r    <= 8'd0;
            max_g    <= 8'd0;
            max_b    <= 8'd0;
        end else if (de) begin
            acc_r   <= acc_r_nx;
            acc_g   <= acc_g_nx;
            acc_b   <= acc_b_nx;
            acc_n   <= acc_n_nx;
            acc_sat <= acc_sat_nx;
            for (j = 0; j < PIX_PER_BEAT; j = j + 1) begin
                if (p_hit[j]) begin
                    if (p_r[j] > max_r) max_r <= p_r[j];
                    if (p_g[j] > max_g) max_g <= p_g[j];
                    if (p_b[j] > max_b) max_b <= p_b[j];
                end
            end
        end
    end

endmodule
