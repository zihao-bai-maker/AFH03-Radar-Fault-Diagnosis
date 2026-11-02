`timescale 1ns / 1ps

module yuv422_tpg_axis #(
    parameter integer H_ACTIVE     = 1280,
    parameter integer V_ACTIVE     = 720,
    parameter integer CHECKER_SIZE = 32
)(
    input  wire        clk,
    input  wire        rst_n,
    input  wire        enable,
    input  wire [1:0]  pattern,       

    output wire        m_tvalid,
    input  wire        m_tready,
    output wire [31:0] m_tdata,
    output wire        m_tuser_sof,
    output wire        m_tlast,

    output reg  [31:0] frame_count,
    output wire [15:0] dbg_word_x,
    output wire [15:0] dbg_line_y
);

    
    localparam integer WORDS_PER_LINE = H_ACTIVE / 2;

    function integer clog2_safe;
        input integer value;
        integer v;
        begin
            v = value - 1;
            for (clog2_safe = 0; v > 0; clog2_safe = clog2_safe + 1)
                v = v >> 1;
        end
    endfunction

    localparam integer X_W = (WORDS_PER_LINE <= 1) ? 1 : clog2_safe(WORDS_PER_LINE);
    localparam integer Y_W = (V_ACTIVE      <= 1) ? 1 : clog2_safe(V_ACTIVE);

    reg [X_W-1:0] word_x;
    reg [Y_W-1:0] line_y;

    wire fire          = m_tvalid & m_tready;
    wire last_word     = (word_x == (WORDS_PER_LINE - 1));
    wire last_line     = (line_y == (V_ACTIVE - 1));

    assign m_tvalid    = enable;
    assign m_tuser_sof = enable & (word_x == {X_W{1'b0}}) & (line_y == {Y_W{1'b0}});
    assign m_tlast     = enable & last_word;
    assign dbg_word_x  = {{(16-X_W){1'b0}}, word_x};
    assign dbg_line_y  = {{(16-Y_W){1'b0}}, line_y};

    wire [31:0] pixel_x0 = {16'd0, dbg_word_x} << 1;
    wire [31:0] pixel_x1 = pixel_x0 + 32'd1;
    wire [31:0] pixel_y  = {16'd0, dbg_line_y};

    function [2:0] bar_index;
        input [31:0] x;
        begin

            
            if      (x < ((H_ACTIVE * 1) / 8)) bar_index = 3'd0;
            else if (x < ((H_ACTIVE * 2) / 8)) bar_index = 3'd1;
            else if (x < ((H_ACTIVE * 3) / 8)) bar_index = 3'd2;
            else if (x < ((H_ACTIVE * 4) / 8)) bar_index = 3'd3;
            else if (x < ((H_ACTIVE * 5) / 8)) bar_index = 3'd4;
            else if (x < ((H_ACTIVE * 6) / 8)) bar_index = 3'd5;
            else if (x < ((H_ACTIVE * 7) / 8)) bar_index = 3'd6;
            else                               bar_index = 3'd7;
        end
    endfunction

    function [23:0] bar_yuv;
        input [2:0] idx;
        begin

            case (idx)
                3'd0: bar_yuv = {8'd235, 8'd128, 8'd128}; 
                3'd1: bar_yuv = {8'd210, 8'd16,  8'd146}; 
                3'd2: bar_yuv = {8'd170, 8'd166, 8'd16 }; 
                3'd3: bar_yuv = {8'd145, 8'd54,  8'd34 }; 
                3'd4: bar_yuv = {8'd107, 8'd202, 8'd222}; 
                3'd5: bar_yuv = {8'd82,  8'd90,  8'd240}; 
                3'd6: bar_yuv = {8'd41,  8'd240, 8'd110}; 
                default: bar_yuv = {8'd16,  8'd128, 8'd128}; 
            endcase
        end
    endfunction

    function [31:0] make_yuyv;
        input [7:0] y0;
        input [7:0] u0;
        input [7:0] y1;
        input [7:0] v0;
        begin
            make_yuyv = {v0, y1, u0, y0};
        end
    endfunction

    wire [23:0] bar0_yuv = bar_yuv(bar_index(pixel_x0));

    wire [7:0] color_y = bar0_yuv[23:16];
    wire [7:0] color_u = bar0_yuv[15:8];
    wire [7:0] color_v = bar0_yuv[7:0];

    wire [7:0] gray_y0 = pixel_x0[7:0];
    wire [7:0] gray_y1 = pixel_x1[7:0];

    wire checker_on = (((pixel_x0 / CHECKER_SIZE) ^ (pixel_y / CHECKER_SIZE)) & 32'd1) != 32'd0;
    wire [7:0] checker_y = checker_on ? 8'd235 : 8'd16;

    reg [31:0] data_mux;
    always @(*) begin
        case (pattern)
            2'd0: begin
                data_mux = make_yuyv(color_y, color_u, color_y, color_v);
            end
            2'd1: begin
                data_mux = make_yuyv(gray_y0, 8'd128, gray_y1, 8'd128);
            end
            2'd2: begin
                data_mux = make_yuyv(checker_y, 8'd128, checker_y, 8'd128);
            end
            default: begin

                
                data_mux = make_yuyv(dbg_word_x[7:0], 8'd128, dbg_line_y[7:0], 8'd128);
            end
        endcase
    end

    assign m_tdata = data_mux;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            word_x      <= {X_W{1'b0}};
            line_y      <= {Y_W{1'b0}};
            frame_count <= 32'd0;
        end else if (!enable) begin
            word_x <= {X_W{1'b0}};
            line_y <= {Y_W{1'b0}};
        end else if (fire) begin
            if (last_word) begin
                word_x <= {X_W{1'b0}};
                if (last_line) begin
                    line_y      <= {Y_W{1'b0}};
                    frame_count <= frame_count + 32'd1;
                end else begin
                    line_y <= line_y + 1'b1;
                end
            end else begin
                word_x <= word_x + 1'b1;
            end
        end
    end

endmodule
