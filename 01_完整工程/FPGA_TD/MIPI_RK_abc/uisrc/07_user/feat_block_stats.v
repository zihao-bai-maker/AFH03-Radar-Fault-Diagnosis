

`timescale 1ns / 1ps

module feat_block_stats #(
    parameter integer H_ACTIVE = 1920,
    parameter integer V_ACTIVE = 1080,
    parameter integer BLK      = 120,      
    parameter integer NX       = 16,
    parameter integer NY       = 9,
    parameter integer Y_THR    = 90,
    parameter [22:0]  DIV_MAGIC = 23'd4772186
)(
    input  wire         clk,
    input  wire         rst_n,
    input  wire         active,        
    input  wire         de,            
    input  wire         sof,           
    input  wire         eol,           
    input  wire [127:0] px,            

    input  wire [7:0]   I_rd_addr,
    output reg  [31:0]  O_rd_data,

    output reg          any_lit,       
    output reg          map_valid      
);

    localparam integer BEATS_GRP = BLK / 4;               
    localparam integer NBLK      = NX * NY;               
    localparam [7:0]   Y_THR8    = Y_THR;

    integer bi;

    

    wire [7:0] r0 = px[ 23:16], g0 = px[ 15: 8], b0 = px[  7:  0];
    wire [7:0] r1 = px[ 55:48], g1 = px[ 47:40], b1 = px[ 39: 32];
    wire [7:0] r2 = px[ 87:80], g2 = px[ 79:72], b2 = px[ 71: 64];
    wire [7:0] r3 = px[119:112], g3 = px[111:104], b3 = px[103: 96];

    

    wire [15:0] lum0 = {8'd0, r0} * 16'd47 + {8'd0, g0} * 16'd157 + {8'd0, b0} * 16'd16 + 16'd4096;
    wire [15:0] lum1 = {8'd0, r1} * 16'd47 + {8'd0, g1} * 16'd157 + {8'd0, b1} * 16'd16 + 16'd4096;
    wire [15:0] lum2 = {8'd0, r2} * 16'd47 + {8'd0, g2} * 16'd157 + {8'd0, b2} * 16'd16 + 16'd4096;
    wire [15:0] lum3 = {8'd0, r3} * 16'd47 + {8'd0, g3} * 16'd157 + {8'd0, b3} * 16'd16 + 16'd4096;

    wire lit0 = (lum0[15:8] > Y_THR8);
    wire lit1 = (lum1[15:8] > Y_THR8);
    wire lit2 = (lum2[15:8] > Y_THR8);
    wire lit3 = (lum3[15:8] > Y_THR8);

    wire [9:0] sum_r = {2'b00, r0} + {2'b00, r1} + {2'b00, r2} + {2'b00, r3};
    wire [9:0] sum_g = {2'b00, g0} + {2'b00, g1} + {2'b00, g2} + {2'b00, g3};
    wire [9:0] sum_b = {2'b00, b0} + {2'b00, b1} + {2'b00, b2} + {2'b00, b3};
    wire [2:0] sum_l = {2'b00, lit0} + {2'b00, lit1} + {2'b00, lit2} + {2'b00, lit3};

    

    reg [4:0]  gx;        
    reg [3:0]  grp;       
    reg [6:0]  gy;        
    reg [3:0]  band;      

    

    reg [21:0] acc_r, acc_g, acc_b;
    reg [13:0] acc_l;

    reg [21:0] bk_r [0:NX-1];
    reg [21:0] bk_g [0:NX-1];
    reg [21:0] bk_b [0:NX-1];
    reg [13:0] bk_l [0:NX-1];

    wire flush = de & active & ((gx == (BEATS_GRP-1)) | (eol & (gx != 5'd0)));
    wire [21:0] acc_r_nx = acc_r + {12'd0, sum_r};
    wire [21:0] acc_g_nx = acc_g + {12'd0, sum_g};
    wire [21:0] acc_b_nx = acc_b + {12'd0, sum_b};
    wire [13:0] acc_l_nx = acc_l + {11'd0, sum_l};

    

    reg        fbusy;
    reg [3:0]  fg;
    reg [3:0]  fband;
    reg        trig;

    wire [21:0] v_r = bk_r[fg];
    wire [21:0] v_g = bk_g[fg];
    wire [21:0] v_b = bk_b[fg];

    
    wire [21:0] v_l = bk_l[fg] * 14'd255;
    wire [44:0] p_r = v_r * DIV_MAGIC;
    wire [44:0] p_g = v_g * DIV_MAGIC;
    wire [44:0] p_b = v_b * DIV_MAGIC;
    wire [44:0] p_l = v_l * DIV_MAGIC;
    wire [7:0]  q_r = p_r[43:36];
    wire [7:0]  q_g = p_g[43:36];
    wire [7:0]  q_b = p_b[43:36];
    wire [7:0]  q_l = p_l[43:36];

    wire [31:0] blk_word = {q_r, q_g, q_b, q_l};

    

    reg [31:0] mem [0:NBLK-1];

    always @(posedge clk) begin
        if (fbusy) mem[{fband, fg}] <= blk_word;
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) O_rd_data <= 32'd0;
        else        O_rd_data <= mem[I_rd_addr];
    end

    

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            gx        <= 5'd0;
            grp       <= 4'd0;
            gy        <= 7'd0;
            band      <= 4'd0;
            acc_r     <= 22'd0;
            acc_g     <= 22'd0;
            acc_b     <= 22'd0;
            acc_l     <= 14'd0;
            any_lit   <= 1'b0;
            map_valid <= 1'b0;
            for (bi = 0; bi < NX; bi = bi + 1) begin
                bk_r[bi] <= 22'd0;
                bk_g[bi] <= 22'd0;
                bk_b[bi] <= 22'd0;
                bk_l[bi] <= 14'd0;
            end
            fbusy     <= 1'b0;
            fg        <= 4'd0;
            fband     <= 4'd0;
            trig      <= 1'b0;
        end else begin
            trig <= 1'b0;

            if (de & sof) begin
                gx        <= 5'd0;
                grp       <= 4'd0;
                gy        <= 7'd0;
                band      <= 4'd0;
                acc_r     <= 22'd0;
                acc_g     <= 22'd0;
                acc_b     <= 22'd0;
                acc_l     <= 14'd0;
                any_lit   <= 1'b0;
                map_valid <= 1'b0;
                for (bi = 0; bi < NX; bi = bi + 1) begin
                    bk_r[bi] <= 22'd0;
                    bk_g[bi] <= 22'd0;
                    bk_b[bi] <= 22'd0;
                    bk_l[bi] <= 14'd0;
                end
            end else if (de & active) begin

                

                
                if (flush) begin
                    bk_r[grp] <= bk_r[grp] + acc_r_nx;
                    bk_g[grp] <= bk_g[grp] + acc_g_nx;
                    bk_b[grp] <= bk_b[grp] + acc_b_nx;
                    bk_l[grp] <= bk_l[grp] + acc_l_nx;
                    acc_r     <= 22'd0;
                    acc_g     <= 22'd0;
                    acc_b     <= 22'd0;
                    acc_l     <= 14'd0;
                end else begin
                    acc_r <= acc_r_nx;
                    acc_g <= acc_g_nx;
                    acc_b <= acc_b_nx;
                    acc_l <= acc_l_nx;
                end

                if (eol) begin

                    gx   <= 5'd0;
                    grp  <= 4'd0;
                    if (gy == (BLK-1)) begin
                        gy    <= 7'd0;
                        band  <= (band == (NY-1)) ? 4'd0 : (band + 4'd1);
                        fband <= band;
                        trig  <= 1'b1;
                        if (band == (NY-1)) map_valid <= 1'b1;
                    end else begin
                        gy <= gy + 7'd1;
                    end
                end else begin
                    if (gx == (BEATS_GRP-1)) begin
                        gx  <= 5'd0;
                        grp <= grp + 4'd1;
                    end else begin
                        gx <= gx + 5'd1;
                    end
                end
            end

            if (trig) begin
                fbusy <= 1'b1;
                fg    <= 4'd0;
            end else if (fbusy) begin
                if (q_l != 8'd0) any_lit <= 1'b1;
                if (fg == (NX-1)) begin
                    fbusy <= 1'b0;
                    for (bi = 0; bi < NX; bi = bi + 1) begin
                        bk_r[bi] <= 22'd0;
                        bk_g[bi] <= 22'd0;
                        bk_b[bi] <= 22'd0;
                        bk_l[bi] <= 14'd0;
                    end
                end else begin
                    fg <= fg + 4'd1;
                end
            end
        end
    end

endmodule
