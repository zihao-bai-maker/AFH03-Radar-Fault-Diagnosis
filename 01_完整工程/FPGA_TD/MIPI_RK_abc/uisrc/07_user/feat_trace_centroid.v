

`timescale 1ns / 1ps

module feat_trace_centroid #(
    parameter integer H_ACTIVE = 1920,
    parameter integer V_ACTIVE = 1080,
    parameter integer NBIN     = 128,
    parameter integer BINW     = 15,
    parameter integer G_THR    = 60,
    parameter integer G_DIFF   = 25
)(
    input  wire         clk,
    input  wire         rst_n,
    input  wire         active,        
    input  wire         de,
    input  wire         sof,
    input  wire         eol,
    input  wire [127:0] px,

    input  wire [5:0]   I_rd_addr,
    output reg  [31:0]  O_rd_data,

    output reg          any_green,
    output reg          frame_done
);

    

    wire [7:0] r0 = px[ 23:16], g0 = px[ 15: 8], b0 = px[  7:  0];
    wire [7:0] r1 = px[ 55:48], g1 = px[ 47:40], b1 = px[ 39: 32];
    wire [7:0] r2 = px[ 87:80], g2 = px[ 79:72], b2 = px[ 71: 64];
    wire [7:0] r3 = px[119:112], g3 = px[111:104], b3 = px[103: 96];

    function green1;
        input [7:0] fr, fg, fb;
        begin
            green1 = ({1'b0, fg} > 9'd60)
                   & ({1'b0, fg} > ({1'b0, fr} + 9'd25))
                   & ({1'b0, fg} > ({1'b0, fb} + 9'd25));
        end
    endfunction

    wire [3:0] grn = {green1(r3,g3,b3), green1(r2,g2,b2),
                      green1(r1,g1,b1), green1(r0,g0,b0)};
    wire [2:0] gcall = {2'b00, grn[0]} + {2'b00, grn[1]}
                     + {2'b00, grn[2]} + {2'b00, grn[3]};

    

    reg [10:0] xbase;
    reg [10:0] yline;
    reg [6:0]  cb;
    reg [24:0] cur_ys;
    reg [14:0] cur_cn;                    

    wire [11:0] cb1     = {5'd0, cb} + 12'd1;
    wire [11:0] bin_end = (cb1 << 4) - cb1;         
    wire [11:0] d       = bin_end - {1'b0, xbase};
    wire [2:0]  ncur    = (d >= 12'd4) ? 3'd4 : d[2:0];
    localparam [6:0] LAST_BIN = NBIN - 1;
    wire        wrap    = (xbase == 11'd0) && (cb == LAST_BIN);

    wire [2:0] g01  = {2'b00, grn[0]} + {2'b00, grn[1]};
    wire [2:0] g012 = g01 + {2'b00, grn[2]};
    reg  [2:0] gfirst;
    always @(*) begin
        case (ncur)
            3'd0:    gfirst = 3'd0;              
            3'd1:    gfirst = {2'b00, grn[0]};
            3'd2:    gfirst = g01;
            3'd3:    gfirst = g012;
            default: gfirst = gcall;
        endcase
    end
    wire [2:0] cn_first = wrap ? 3'd0  : gfirst;
    wire [2:0] cn_next  = wrap ? gcall : (gcall - gfirst);
    wire [12:0] ys_first = {2'd0, yline} * {10'd0, cn_first};   
    wire [12:0] ys_next  = {2'd0, yline} * {10'd0, cn_next};

    wire bnd = (ncur != 3'd4) | wrap;

    localparam [10:0] LAST_LINE = V_ACTIVE - 1;
    wire        frame_last = de & active & eol & (yline == LAST_LINE);

    

    

    reg [39:0] mem [0:NBIN-1];
    reg [39:0] m_rd;
    reg        m_we;
    reg [39:0] m_din;
    reg [6:0]  rmw_addr;
    reg [6:0]  ro_addr;
    reg        ro_busy;

    wire [6:0] m_addr = ro_busy ? ro_addr : rmw_addr;

    reg        clr_en;
    reg [6:0]  clr_idx;

    always @(posedge clk) begin
        m_rd <= mem[m_addr];
        if (clr_en)    mem[clr_idx] <= 40'd0;
        else if (m_we) mem[m_addr]  <= m_din;
    end

    reg [1:0]  rmw_st;
    reg [6:0]  rmw_a;
    reg [39:0] rmw_v;

    wire        col_req = de & active & bnd;
    wire [6:0]  col_bin = cb;

    wire [39:0] col_add = {(cur_cn + {12'd0, cn_first}),
                           (cur_ys + {12'd0, ys_first})};

    reg  fin_pend;
    wire fin_req = fin_pend & (rmw_st == 2'd0);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rmw_addr <= 7'd0;
            m_we     <= 1'b0;
            m_din    <= 40'd0;
            rmw_st   <= 2'd0;
            rmw_a    <= 7'd0;
            rmw_v    <= 40'd0;
            fin_pend <= 1'b0;
        end else begin
            m_we <= 1'b0;
            if (de & sof)        fin_pend <= 1'b0;
            else if (frame_last) fin_pend <= 1'b1;
            else if (fin_req)    fin_pend <= 1'b0;

            case (rmw_st)
                2'd0: if (fin_req) begin
                          rmw_a    <= col_bin;
                          rmw_v    <= {cur_cn, cur_ys};
                          rmw_addr <= col_bin;
                          rmw_st   <= 2'd1;
                      end else if (col_req) begin
                          rmw_a    <= col_bin;
                          rmw_v    <= col_add;
                          rmw_addr <= col_bin;
                          rmw_st   <= 2'd1;
                      end
                2'd1: rmw_st <= 2'd2;
                2'd2: begin
                          m_din    <= m_rd + rmw_v;
                          rmw_addr <= rmw_a;
                          m_we     <= 1'b1;
                          rmw_st   <= 2'd0;
                      end
                default: rmw_st <= 2'd0;
            endcase
        end
    end

    

    reg         div_start;
    reg  [28:0] div_num;
    reg  [20:0] div_den;
    wire [28:0] div_q;
    wire [20:0] div_r;
    wire        div_busy, div_done;

    feat_div_seq #(
        .NUM_W (29),
        .DEN_W (21)
    ) u_div (
        .clk   (clk),
        .rst_n (rst_n),
        .start (div_start),
        .num   (div_num),
        .den   (div_den),
        .quot  (div_q),
        .rem   (div_r),
        .busy  (div_busy),
        .done  (div_done)
    );

    

    reg [31:0] pay [0:35];      
    reg [3:0]  tst;
    reg [6:0]  ti;
    reg [24:0] ysum_q;
    reg [14:0] cnt_q;
    reg [7:0]  res;
    reg [31:0] word_q;
    reg [4:0]  wait_cnt;

    localparam [3:0] T_IDLE = 4'd0, T_WAIT = 4'd1, T_RD  = 4'd2, T_GOT = 4'd3,
                     T_GOT2 = 4'd9, T_EVAL = 4'd4, T_STRT = 4'd5, T_BUSY = 4'd6, T_PACK = 4'd7,
                     T_END  = 4'd8, T_CLR = 4'd10;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            tst        <= T_IDLE;
            ti         <= 7'd0;
            ysum_q     <= 25'd0;
            cnt_q      <= 15'd0;
            res        <= 8'd255;
            word_q     <= 32'd0;
            wait_cnt   <= 5'd0;
            div_start  <= 1'b0;
            div_num    <= 29'd0;
            div_den    <= 21'd0;
            frame_done <= 1'b0;
            clr_en     <= 1'b0;
            clr_idx    <= 7'd0;
        end else begin
            frame_done <= 1'b0;
            div_start  <= 1'b0;
            case (tst)
                T_IDLE: if (frame_last) begin
                            wait_cnt <= 5'd12;
                            tst      <= T_WAIT;
                        end
                T_WAIT: if (wait_cnt == 5'd0) begin
                            ti      <= 7'd0;
                            ro_busy <= 1'b1;
                            tst     <= T_RD;
                        end else begin
                            wait_cnt <= wait_cnt - 5'd1;
                        end
                T_RD: begin
                            ro_addr <= ti;
                            tst     <= T_GOT;
                        end
                T_GOT:  tst <= T_GOT2;             
                T_GOT2: tst <= T_EVAL;             
                T_EVAL: begin
                            ysum_q <= m_rd[24:0];
                            cnt_q  <= m_rd[39:25];
                            if (m_rd[39:25] == 15'd0) begin
                                res <= 8'd255;
                                tst <= T_PACK;
                            end else begin
                                div_num <= {4'd0, m_rd[24:0]} * 29'd17;
                                div_den <= {6'd0, m_rd[39:25]} * 21'd72;
                                tst     <= T_STRT;
                            end
                        end
                T_STRT: begin
                            div_start <= 1'b1;
                            tst       <= T_BUSY;
                        end
                T_BUSY: if (div_done) begin

                            if ({div_r, 1'b0} > {1'b0, div_den})       res <= div_q[7:0] + 8'd1;
                            else if ({div_r, 1'b0} < {1'b0, div_den})  res <= div_q[7:0];
                            else                                       res <= div_q[7:0] + {7'd0, div_q[0]};
                            tst <= T_PACK;
                        end
                T_PACK: begin
                            case (ti[1:0])
                                2'd0: word_q <= {24'd0, res};
                                2'd1: word_q <= {16'd0, res, word_q[7:0]};
                                2'd2: word_q <= {8'd0, res, word_q[15:0]};
                                default: word_q <= {res, word_q[23:0]};
                            endcase
                            if (ti[1:0] == 2'd3) pay[ti[6:2]] <= {res, word_q[23:0]};
                            if (ti == 7'd127) begin
                                ti      <= 7'd0;
                                clr_en  <= 1'b1;
                                clr_idx <= 7'd0;
                                tst     <= T_CLR;
                            end else begin
                                ti  <= ti + 7'd1;
                                tst <= T_RD;
                            end
                        end
                T_CLR: begin
                            if (clr_idx == 7'd127) begin
                                clr_en     <= 1'b0;
                                clr_idx    <= 7'd0;
                                ro_busy    <= 1'b0;
                                frame_done <= 1'b1;
                                tst        <= T_END;
                            end else begin
                                clr_idx <= clr_idx + 7'd1;
                            end
                        end
                T_END:  tst <= T_IDLE;
                default: tst <= T_IDLE;
            endcase
        end
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) O_rd_data <= 32'd0;
        else        O_rd_data <= pay[I_rd_addr];
    end

    

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            xbase     <= 11'd0;
            yline     <= 11'd0;
            cb        <= 7'd0;
            cur_ys    <= 25'd0;
            cur_cn    <= 15'd0;
            any_green <= 1'b0;
        end else if (de & sof) begin
            xbase     <= 11'd0;
            yline     <= 11'd0;
            cb        <= 7'd0;
            cur_ys    <= 25'd0;
            cur_cn    <= 15'd0;
            any_green <= 1'b0;
        end else if (de & active) begin
            xbase <= eol ? 11'd0 : (xbase + 11'd4);
            if (gcall != 3'd0) any_green <= 1'b1;

            if (bnd) begin
                cb     <= cb + 7'd1;
                cur_ys <= {12'd0, ys_next};
                cur_cn <= {12'd0, cn_next};
            end else begin
                cur_ys <= cur_ys + {12'd0, ys_first};
                cur_cn <= cur_cn + {12'd0, cn_first};
            end

            if (eol) yline <= yline + 11'd1;
        end
    end

endmodule
