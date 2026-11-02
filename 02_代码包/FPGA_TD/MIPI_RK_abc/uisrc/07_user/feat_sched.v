

`timescale 1ns / 1ps

module feat_sched #(
    parameter integer NSEG_A = 12,
    parameter integer NSEG_B = 6,
    parameter integer NSEG_C = 3,
    parameter integer V_ACTIVE = 1080
)(
    input  wire         clk,
    input  wire         rst_n,
    input  wire         de,
    input  wire         sof,
    input  wire         eol,

    output reg  [7:0]   O_pay_addr,
    output reg  [1:0]   O_pay_sel,        
    input  wire [31:0]  I_a_data,
    input  wire [31:0]  I_b_data,
    input  wire [31:0]  I_c_data,

    input  wire         I_a_any_lit,
    input  wire         I_b_any_green,
    input  wire         I_c_any_green,

    output wire [511:0] O_blk_a,
    output wire [511:0] O_blk_b,
    output wire         O_sel,            
    output wire         O_tog,            

    output reg  [15:0]  O_frame_cnt,
    output reg  [1:0]   O_mode,
    output reg  [7:0]   O_seg,
    output wire         O_active_a,
    output wire         O_active_b,
    output wire         O_active_c
);

    assign O_active_a = (O_mode == 2'd0);
    assign O_active_b = (O_mode == 2'd1);
    assign O_active_c = (O_mode == 2'd2);

    localparam [31:0] MAGIC = 32'hA5C35A00;

    

    reg [1:0]  mode;
    reg [7:0]  seg;
    reg [15:0] frame_cnt;

    reg [1:0]  cur_mode;
    reg [7:0]  cur_seg;
    reg [15:0] cur_frame;

    reg        ready;

    function [7:0] last_seg;
        input [1:0] m;
        begin
            case (m)
                2'd0:    last_seg = NSEG_A[7:0] - 8'd1;
                2'd1:    last_seg = NSEG_B[7:0] - 8'd1;
                default: last_seg = NSEG_C[7:0] - 8'd1;
            endcase
        end
    endfunction

    wire [1:0] nxt_mode = (seg == last_seg(mode))
                        ? ((mode == 2'd2) ? 2'd0 : (mode + 2'd1)) : mode;
    wire [7:0] nxt_seg  = (seg == last_seg(mode)) ? 8'd0 : (seg + 8'd1);

    

    reg        pbusy;
    reg [3:0]  pcnt;
    reg [7:0]  pbase;
    reg [31:0] pay [0:11];
    reg [31:0] xacc;
    reg        pay_valid;

    wire [31:0] rd_mux = (O_pay_sel == 2'd0) ? I_a_data :
                         (O_pay_sel == 2'd1) ? I_b_data : I_c_data;
    wire [3:0]  pidx   = pcnt - 4'd2;   

    

    reg  [511:0] blk_a, blk_b;
    reg          sel, tog;

    wire [31:0] w0 = MAGIC;
    wire [31:0] w1 = {16'd0, cur_frame};
    wire        any_flag = (cur_mode == 2'd0) ? I_a_any_lit :
                           (cur_mode == 2'd1) ? I_b_any_green : I_c_any_green;
    wire [7:0]  flags = {5'd0,
                         (cur_seg == last_seg(cur_mode)),   
                         any_flag,                          
                         ready};                            

    wire [31:0] w2 = {4'd2, 2'b00, cur_mode, cur_seg, flags, cur_frame[7:0]};

    wire [31:0]  w15 = xacc ^ w1 ^ w2;

    wire [511:0] block = {w15, pay[11], pay[10], pay[9], pay[8], pay[7], pay[6],
                          pay[5], pay[4], pay[3], pay[2], pay[1], pay[0],
                          w2, w1, w0};

    assign O_blk_a = blk_a;
    assign O_blk_b = blk_b;
    assign O_sel   = sel;
    assign O_tog   = tog;

    

    localparam [9:0] LAST_LINE = V_ACTIVE - 1;
    reg [9:0] yline;
    wire eof = de & eol & (yline == LAST_LINE);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)          yline <= 10'd0;
        else if (de & sof)   yline <= 10'd0;
        else if (de & eol)   yline <= yline + 10'd1;
    end

    

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            mode        <= 2'd0;
            seg         <= 8'd0;
            frame_cnt   <= 16'd0;
            cur_mode    <= 2'd0;
            cur_seg     <= 8'd0;
            cur_frame   <= 16'd0;
            ready       <= 1'b0;
            pbusy       <= 1'b0;
            pcnt        <= 4'd0;
            pbase       <= 8'd0;
            O_pay_addr  <= 8'd0;
            O_pay_sel   <= 2'd0;
            xacc        <= MAGIC;
            pay_valid   <= 1'b0;
            blk_a       <= {512{1'b0}};
            blk_b       <= {512{1'b0}};
            sel         <= 1'b0;
            tog         <= 1'b0;
            O_frame_cnt <= 16'd0;
            O_mode      <= 2'd0;
            O_seg       <= 8'd0;
        end else begin

            if (de & sof) begin
                cur_mode    <= mode;
                cur_seg     <= seg;
                cur_frame   <= frame_cnt;
                O_mode      <= mode;
                O_seg       <= seg;
                O_frame_cnt <= frame_cnt;

                mode        <= nxt_mode;
                seg         <= nxt_seg;
                frame_cnt   <= frame_cnt + 16'd1;

                pbusy       <= 1'b1;
                pcnt        <= 4'd0;
                pbase       <= (seg << 3) + (seg << 2);   
                O_pay_sel   <= mode;
                xacc        <= MAGIC;
                pay_valid   <= 1'b0;
            end else if (pbusy) begin

                

                
                if (pcnt == 4'd0) begin
                    O_pay_addr <= pbase;
                    pcnt       <= 4'd1;
                end else begin
                    if (pcnt >= 4'd2) begin
                        pay[pidx] <= rd_mux;
                        xacc      <= xacc ^ rd_mux;
                    end
                    if (pcnt <= 4'd11)
                        O_pay_addr <= pbase + {4'd0, pcnt};
                    if (pcnt == 4'd13) begin
                        pbusy     <= 1'b0;
                        pay_valid <= 1'b1;
                    end else begin
                        pcnt <= pcnt + 4'd1;
                    end
                end
            end

            if (eof & pay_valid) begin
                if (sel) blk_b <= block;
                else     blk_a <= block;
                sel   <= ~sel;
                tog   <= ~tog;
                ready <= 1'b1;
            end
        end
    end

`ifdef FEAT_SIM_DEBUG

    always @(posedge clk) begin
        if (de & eol & (yline == LAST_LINE))
            $display("[sched] frame=%0d eof pay_valid=%b mode=%0d seg=%0d",
                     cur_frame, pay_valid, cur_mode, cur_seg);
        if (eof & pay_valid)
            $display("[sched] publish frame=%0d w0=%h tog=%b", cur_frame, w0, tog);
    end
`endif

endmodule
