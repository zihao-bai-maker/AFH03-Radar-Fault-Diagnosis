

`timescale 1ns / 1ps

module feat_green_proj #(
    parameter integer H_ACTIVE = 1920,
    parameter integer V_ACTIVE = 1080,
    parameter integer NCOL     = 64,
    parameter integer COLW     = 30,        
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

    input  wire [6:0]   I_rd_addr,
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
    reg [5:0]  cb;         
    reg [15:0] cur_col;    
    reg [11:0] row_line;   
    reg [15:0] cur_row;    
    reg [5:0]  rb;         
    reg [10:0] rb_edge;    

    wire [11:0] cb1     = {6'd0, cb} + 12'd1;
    wire [11:0] bin_end = (cb1 << 5) - (cb1 << 1);          
    wire [11:0] d       = bin_end - {1'b0, xbase};
    wire [2:0]  ncur    = (d >= 12'd4) ? 3'd4 : d[2:0];     
    localparam [5:0] LAST_CB = NCOL - 1;
    wire        wrap    = (xbase == 11'd0) && (cb == LAST_CB);

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
    wire [2:0] gc_first = wrap ? 3'd0  : gfirst;
    wire [2:0] gc_next  = wrap ? gcall : (gcall - gfirst);

    wire bnd = (ncur != 3'd4) | wrap;

    

    

    
    function [10:0] row_edge;
        input [6:0] i;
        reg [15:0] a;
        reg [15:0] b;
        begin
            a = ({9'd0, i} * 16'd135) >> 3;
            b = ({9'd0, i} * 16'd56) & 16'd63;
            if (b > 16'd32)      row_edge = a[10:0] + 11'd1;
            else if (b == 16'd32) row_edge = a[0] ? (a[10:0] + 11'd1) : a[10:0];
            else                 row_edge = a[10:0];
        end
    endfunction

    localparam [10:0] LAST_LINE = V_ACTIVE - 1;
    wire        frame_last = de & active & eol & (yline == LAST_LINE);

    

    

    

    
    reg [15:0] mem [0:127];      
    reg [15:0] m_rd;
    reg        m_we;
    reg [15:0] m_din;
    reg [6:0]  rmw_addr;
    reg [6:0]  ro_addr;
    reg        ro_busy;

    wire [6:0] m_addr = ro_busy ? ro_addr : rmw_addr;

    reg        clr_en;
    reg [6:0]  clr_idx;

    always @(posedge clk) begin
        m_rd <= mem[m_addr];
        if (clr_en)        mem[clr_idx] <= 16'd0;
        else if (m_we)     mem[m_addr]  <= m_din;
    end

    reg [1:0]  rmw_st;
    reg [6:0]  rmw_a;
    reg [15:0] rmw_v;

    
    wire        col_req = de & active & bnd;
    wire [6:0]  col_bin = {1'b0, cb};
    wire [15:0] col_add = cur_col + {13'd0, gc_first};
    wire        row_req = de & active & eol & (yline == (rb_edge - 11'd1));
    wire [6:0]  row_bin2 = {1'b1, rb};
    wire [15:0] row_add  = cur_row + {4'd0, row_line} + {13'd0, gcall};

    reg  fin_pend;
    wire fin_req = fin_pend & (rmw_st == 2'd0) & ~row_req;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rmw_addr <= 7'd0;
            m_we     <= 1'b0;
            m_din    <= 16'd0;
            rmw_st   <= 2'd0;
            rmw_a    <= 7'd0;
            rmw_v    <= 16'd0;
            fin_pend <= 1'b0;
        end else begin
            m_we <= 1'b0;
            if (frame_last)      fin_pend <= 1'b1;
            else if (fin_req)    fin_pend <= 1'b0;

            case (rmw_st)
                2'd0: if (row_req) begin
                          rmw_a    <= row_bin2;
                          rmw_v    <= row_add;
                          rmw_addr <= row_bin2;
                          rmw_st   <= 2'd1;
                      end else if (fin_req) begin
                          rmw_a    <= {1'b0, cb};
                          rmw_v    <= cur_col;
                          rmw_addr <= {1'b0, cb};
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

    

    
    reg [31:0] pay [0:71];      
    reg [2:0]  st;
    reg [6:0]  idx;
    reg [15:0] v_lo;
    reg [4:0]  wait_cnt;

    localparam [4:0] RD_WAIT = 5'd12;
    localparam [2:0] S_IDLE = 3'd0, S_WAIT = 3'd1, S_RD = 3'd2, S_GAP = 3'd3, S_CAP = 3'd4, S_CLR = 3'd5;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            st         <= S_IDLE;
            idx        <= 7'd0;
            v_lo       <= 16'd0;
            wait_cnt   <= 5'd0;
            ro_addr    <= 7'd0;
            ro_busy    <= 1'b0;
            frame_done <= 1'b0;
            clr_en     <= 1'b0;
            clr_idx    <= 7'd0;
        end else begin
            frame_done <= 1'b0;
            case (st)
                S_IDLE: begin
                            if (frame_last) begin
                                wait_cnt <= RD_WAIT;
                                st       <= S_WAIT;
                            end
                        end
                S_WAIT: begin
                            if (wait_cnt == 5'd0) begin
                                idx     <= 7'd0;
                                ro_busy <= 1'b1;
                                st      <= S_RD;
                            end else begin
                                wait_cnt <= wait_cnt - 5'd1;
                            end
                        end
                S_RD: begin
                            ro_addr <= idx[6:0];
                            st      <= S_GAP;      
                        end
                S_GAP:  st <= S_CAP;           
                S_CAP: begin
                            if (!idx[0]) begin
                                v_lo <= m_rd;
                                idx  <= idx + 7'd1;
                                st   <= S_RD;
                            end else begin
                                pay[idx[6:1]] <= {m_rd, v_lo};
                                idx <= idx + 7'd1;
                                if (idx == 7'd127) begin
                                    st      <= S_CLR;
                                    clr_en  <= 1'b1;
                                    clr_idx <= 7'd0;
                                end else begin
                                    st <= S_RD;
                                end
                            end
                        end
                S_CLR: begin
                            if (clr_idx == 7'd127) begin
                                clr_en     <= 1'b0;
                                clr_idx    <= 7'd0;
                                ro_busy    <= 1'b0;
                                frame_done <= 1'b1;
                                st         <= S_IDLE;
                            end else begin
                                clr_idx <= clr_idx + 7'd1;
                            end
                        end
                default: st <= S_IDLE;
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
            cb        <= 6'd0;
            cur_col   <= 16'd0;
            row_line  <= 12'd0;
            cur_row   <= 16'd0;
            rb        <= 6'd0;
            rb_edge   <= 11'd17;
            any_green <= 1'b0;
        end else if (de & sof) begin
            xbase     <= 11'd0;
            yline     <= 11'd0;
            cb        <= 6'd0;
            cur_col   <= 16'd0;
            row_line  <= 12'd0;
            cur_row   <= 16'd0;
            rb        <= 6'd0;
            rb_edge   <= row_edge(7'd1);
            any_green <= 1'b0;
        end else if (de & active) begin
            xbase <= eol ? 11'd0 : (xbase + 11'd4);
            if (gcall != 3'd0) any_green <= 1'b1;

            if (bnd) begin
                cb      <= cb + 6'd1;              
                cur_col <= {13'd0, gc_next};
            end else begin
                cur_col <= cur_col + {13'd0, gcall};
            end

            if (eol) begin
                row_line <= 12'd0;
                yline    <= yline + 11'd1;
                if (yline == (rb_edge - 11'd1)) begin
                    cur_row <= 16'd0;
                    rb      <= rb + 6'd1;
                    rb_edge <= row_edge({1'b0, rb} + 7'd2);   
                end else begin
                    cur_row <= cur_row + {4'd0, row_line} + {9'd0, gcall};
                end
            end else begin
                row_line <= row_line + {9'd0, gcall};
            end
        end
    end

endmodule
