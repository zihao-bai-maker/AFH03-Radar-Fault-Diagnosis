

`timescale 1ns / 1ps

module csi2_frame_tx #(
    parameter [5:0]   DT         = 6'h1E,        
    parameter [1:0]   VC         = 2'd0,         
    parameter integer H_ACTIVE   = 1920,
    parameter integer V_ACTIVE   = 1080,
    parameter integer BPP_NUM    = 2,            
    parameter integer BPP_DEN    = 1,            

    parameter [31:0]  GAP_LINE   = 32'd200,      
    parameter [31:0]  GAP_FRAME  = 32'd4000      
) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        enable,

    input  wire        s_tvalid,
    output reg         s_tready,
    input  wire [31:0] s_tdata,
    input  wire        s_tuser_sof,   
    input  wire        s_tlast,       

    output reg         hs_en,
    output reg  [31:0] hs_data,
    output reg         hs_last,

    output reg  [31:0] frame_cnt,
    output reg  [31:0] packet_cnt
);

    localparam integer WC_INT         = (H_ACTIVE * BPP_NUM) / BPP_DEN;
    localparam [15:0]  WC             = WC_INT[15:0];
    localparam integer WORDS_PAYLOAD  = WC_INT / 4;
    localparam [5:0]   DT_FS          = 6'h00;
    localparam [5:0]   DT_FE          = 6'h01;

    

    function [7:0] ecc8;
        input [23:0] d;
        reg   [7:0]  e;
        begin
            e[7] = 1'b0;
            e[6] = 1'b0;
            e[5] = d[10]^d[11]^d[12]^d[13]^d[14]^d[15]^d[0]^d[1]^d[2]^d[3]^d[5]^d[6]^d[7];
            e[4] = d[20]^d[21]^d[22]^d[23]^d[8]^d[9]^d[0]^d[1]^d[2]^d[3]^d[4]^d[6]^d[7];
            e[3] = d[17]^d[18]^d[19]^d[23]^d[8]^d[9]^d[13]^d[14]^d[15]^d[3]^d[4]^d[5]^d[7];
            e[2] = d[16]^d[18]^d[19]^d[21]^d[22]^d[9]^d[11]^d[12]^d[15]^d[2]^d[4]^d[5]^d[6];
            e[1] = d[16]^d[17]^d[19]^d[20]^d[22]^d[8]^d[10]^d[12]^d[14]^d[1]^d[4]^d[5]^d[6]^d[7];
            e[0] = d[16]^d[17]^d[18]^d[20]^d[21]^d[23]^d[10]^d[11]^d[13]^d[0]^d[4]^d[5]^d[6]^d[7];
            ecc8 = e;
        end
    endfunction

    function [15:0] crc16_byte;
        input [15:0] cin;
        input [7:0]  b;
        reg   [15:0] c;
        integer i;
        begin
            c = cin ^ {8'h00, b};
            for (i = 0; i < 8; i = i + 1) begin
                if (c[0]) c = (c >> 1) ^ 16'h8408;
                else      c = c >> 1;
            end
            crc16_byte = c;
        end
    endfunction

    function [15:0] crc16_word;
        input [15:0] cin;
        input [31:0] w;
        begin
            crc16_word = crc16_byte(
                           crc16_byte(
                             crc16_byte(
                               crc16_byte(cin, w[7:0]),
                               w[15:8]),
                             w[23:16]),
                           w[31:24]);
        end
    endfunction

    function [31:0] build_short_hdr;
        input [5:0]  dt;
        input [15:0] data16;
        reg   [7:0]  di;
        reg   [23:0] d24;
        begin
            di              = {VC, dt};
            d24             = {di, data16[7:0], data16[15:8]};
            build_short_hdr = {ecc8(d24), data16[15:8], data16[7:0], di};
        end
    endfunction

    function [31:0] build_long_hdr;
        input [5:0]  dt;
        input [15:0] wc16;
        reg   [7:0]  di;
        reg   [23:0] d24;
        begin
            di             = {VC, dt};
            d24            = {di, wc16[7:0], wc16[15:8]};
            build_long_hdr = {ecc8(d24), wc16[15:8], wc16[7:0], di};
        end
    endfunction

    localparam [3:0] S_IDLE     = 4'd0;
    localparam [3:0] S_WAIT_SOF = 4'd1;
    localparam [3:0] S_FS       = 4'd2;
    localparam [3:0] S_LP_HDR_F = 4'd3;
    localparam [3:0] S_LP_PL_F  = 4'd4;
    localparam [3:0] S_LP_PL    = 4'd5;
    localparam [3:0] S_LP_HDR_N = 4'd6;
    localparam [3:0] S_LP_PL_N  = 4'd7;
    localparam [3:0] S_LP_CRC   = 4'd8;
    localparam [3:0] S_FE       = 4'd9;
    localparam [3:0] S_GAP      = 4'd10;

    reg [3:0]  state;
    reg [3:0]  state_after_gap;
    reg [31:0] gap_cnt;
    reg [31:0] gap_target;
    reg [15:0] pl_word_cnt;
    reg [15:0] line_cnt;
    reg [15:0] frame_num;
    reg [15:0] crc;
    reg [31:0] shadow_word;

    wire [31:0] fs_word = build_short_hdr(DT_FS, frame_num);
    wire [31:0] fe_word = build_short_hdr(DT_FE, frame_num);
    wire [31:0] lp_hdr  = build_long_hdr (DT,    WC);

    always @(*) begin
        case (state)
            S_WAIT_SOF: s_tready = 1'b1;
            S_LP_PL:    s_tready = 1'b1;
            S_LP_PL_N:  s_tready = 1'b1;
            default:    s_tready = 1'b0;
        endcase
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state           <= S_IDLE;
            state_after_gap <= S_IDLE;
            gap_cnt         <= 32'd0;
            gap_target      <= GAP_LINE;
            pl_word_cnt     <= 16'd0;
            line_cnt        <= 16'd0;
            frame_num       <= 16'd0;
            crc             <= 16'hFFFF;
            shadow_word     <= 32'd0;
            hs_en           <= 1'b0;
            hs_data         <= 32'd0;
            hs_last         <= 1'b0;
            frame_cnt       <= 32'd0;
            packet_cnt      <= 32'd0;
        end else if (!enable) begin
            state           <= S_IDLE;
            hs_en           <= 1'b0;
            hs_data         <= 32'd0;
            hs_last         <= 1'b0;
            pl_word_cnt     <= 16'd0;
            line_cnt        <= 16'd0;
            gap_cnt         <= 32'd0;
        end else begin
            case (state)

                S_IDLE: begin
                    hs_en    <= 1'b0;
                    hs_data  <= 32'd0;
                    hs_last  <= 1'b0;
                    line_cnt <= 16'd0;
                    state    <= S_WAIT_SOF;
                end

                
                S_WAIT_SOF: begin
                    hs_en   <= 1'b0;
                    hs_data <= 32'd0;
                    hs_last <= 1'b0;
                    if (s_tvalid && s_tuser_sof) begin
                        shadow_word <= s_tdata;
                        state       <= S_FS;
                    end

                end

                S_FS: begin
                    hs_en           <= 1'b1;
                    hs_data         <= fs_word;
                    hs_last         <= 1'b1;
                    packet_cnt      <= packet_cnt + 32'd1;
                    gap_cnt         <= 32'd0;
                    gap_target      <= GAP_LINE;
                    state_after_gap <= S_LP_HDR_F;
                    state           <= S_GAP;
                end

                S_LP_HDR_F: begin
                    hs_en       <= 1'b1;
                    hs_data     <= lp_hdr;
                    hs_last     <= 1'b0;
                    crc         <= 16'hFFFF;
                    pl_word_cnt <= 16'd0;
                    state       <= S_LP_PL_F;
                end

                S_LP_PL_F: begin
                    hs_en       <= 1'b1;
                    hs_data     <= shadow_word;
                    hs_last     <= 1'b0;
                    crc         <= crc16_word(16'hFFFF, shadow_word);
                    pl_word_cnt <= 16'd1;
                    if (WORDS_PAYLOAD <= 1)
                        state <= S_LP_CRC;
                    else
                        state <= S_LP_PL;
                end

                
                S_LP_PL: begin
                    if (s_tvalid) begin
                        hs_en       <= 1'b1;
                        hs_data     <= s_tdata;
                        hs_last     <= 1'b0;
                        crc         <= crc16_word(crc, s_tdata);
                        pl_word_cnt <= pl_word_cnt + 16'd1;
                        if (pl_word_cnt == (WORDS_PAYLOAD[15:0] - 16'd1))
                            state <= S_LP_CRC;
                    end else begin

                        hs_en <= 1'b0;
                    end
                end

                
                S_LP_HDR_N: begin
                    hs_en       <= 1'b1;
                    hs_data     <= lp_hdr;
                    hs_last     <= 1'b0;
                    crc         <= 16'hFFFF;
                    pl_word_cnt <= 16'd0;
                    state       <= S_LP_PL_N;
                end

                S_LP_PL_N: begin
                    if (s_tvalid) begin
                        hs_en       <= 1'b1;
                        hs_data     <= s_tdata;
                        hs_last     <= 1'b0;
                        crc         <= crc16_word(crc, s_tdata);
                        pl_word_cnt <= pl_word_cnt + 16'd1;
                        if (pl_word_cnt == (WORDS_PAYLOAD[15:0] - 16'd1))
                            state <= S_LP_CRC;
                    end else begin
                        hs_en <= 1'b0;
                    end
                end

                S_LP_CRC: begin
                    hs_en           <= 1'b1;
                    hs_data         <= {16'h0000, crc};
                    hs_last         <= 1'b1;
                    packet_cnt      <= packet_cnt + 32'd1;
                    line_cnt        <= line_cnt + 16'd1;
                    gap_cnt         <= 32'd0;
                    gap_target      <= GAP_LINE;
                    state           <= S_GAP;
                    if (line_cnt == (V_ACTIVE[15:0] - 16'd1))
                        state_after_gap <= S_FE;
                    else
                        state_after_gap <= S_LP_HDR_N;
                end

                S_FE: begin
                    hs_en           <= 1'b1;
                    hs_data         <= fe_word;
                    hs_last         <= 1'b1;
                    packet_cnt      <= packet_cnt + 32'd1;
                    frame_num       <= frame_num + 16'd1;
                    frame_cnt       <= frame_cnt + 32'd1;
                    line_cnt        <= 16'd0;
                    gap_cnt         <= 32'd0;
                    gap_target      <= GAP_FRAME;
                    state_after_gap <= S_WAIT_SOF;  
                    state           <= S_GAP;
                end

                S_GAP: begin
                    hs_en   <= 1'b0;
                    hs_data <= 32'd0;
                    hs_last <= 1'b0;
                    if (gap_cnt >= gap_target) begin

                        if (state_after_gap == S_LP_HDR_N ||
                            state_after_gap == S_LP_HDR_F) begin
                            if (s_tvalid)
                                state <= state_after_gap;
                        end else begin
                            state <= state_after_gap;
                        end
                    end else begin
                        gap_cnt <= gap_cnt + 32'd1;
                    end
                end

                default: state <= S_IDLE;
            endcase
        end
    end

endmodule
