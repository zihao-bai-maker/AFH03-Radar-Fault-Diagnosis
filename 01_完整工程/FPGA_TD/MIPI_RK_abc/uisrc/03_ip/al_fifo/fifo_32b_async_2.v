

`timescale 1ns/1ps

module fifo_32b_async_2 #(
    parameter DATA_WIDTH = 32,
    parameter ADDR_WIDTH = 12,                    
    parameter DEPTH      = (1 << ADDR_WIDTH),
    parameter RST_SYNC_STAGES = 3
) (
    input  wire                       rst,        
    input  wire                       wr_clk,
    input  wire                       rd_clk,
    input  wire [DATA_WIDTH-1:0]      din,
    input  wire                       wr_en,
    input  wire                       rd_en,
    output reg  [DATA_WIDTH-1:0]      dout,
    output wire                       full,
    output wire                       empty,
    output wire [ADDR_WIDTH-1:0]      rd_data_count,
    output wire [ADDR_WIDTH-1:0]      wr_data_count,
    output wire                       wr_rst_busy,
    output wire                       rd_rst_busy
);

    

    
    reg [RST_SYNC_STAGES-1:0] wr_rst_shift;
    reg [RST_SYNC_STAGES-1:0] rd_rst_shift;
    always @(posedge wr_clk or posedge rst) begin
        if (rst) wr_rst_shift <= {RST_SYNC_STAGES{1'b1}};
        else     wr_rst_shift <= {wr_rst_shift[RST_SYNC_STAGES-2:0], 1'b0};
    end
    always @(posedge rd_clk or posedge rst) begin
        if (rst) rd_rst_shift <= {RST_SYNC_STAGES{1'b1}};
        else     rd_rst_shift <= {rd_rst_shift[RST_SYNC_STAGES-2:0], 1'b0};
    end
    wire wr_rst = |wr_rst_shift;
    wire rd_rst = |rd_rst_shift;
    assign wr_rst_busy = wr_rst;
    assign rd_rst_busy = rd_rst;

    

    (* ram_style = "block" *) reg [DATA_WIDTH-1:0] mem [0:DEPTH-1];

    

    reg  [ADDR_WIDTH:0] wr_ptr_bin, wr_ptr_gray;
    reg  [ADDR_WIDTH:0] rd_ptr_bin, rd_ptr_gray;

    reg  [ADDR_WIDTH:0] wr_ptr_gray_rdsync0, wr_ptr_gray_rdsync;
    reg  [ADDR_WIDTH:0] rd_ptr_gray_wrsync0, rd_ptr_gray_wrsync;

    wire b2g_w = 1'b0; 
    wire _unused = b2g_w;

    function [ADDR_WIDTH:0] bin2gray;
        input [ADDR_WIDTH:0] bin;
        begin bin2gray = (bin >> 1) ^ bin; end
    endfunction

    wire do_write = wr_en && !full && !wr_rst;
    always @(posedge wr_clk or posedge wr_rst) begin
        if (wr_rst) begin
            wr_ptr_bin  <= {(ADDR_WIDTH+1){1'b0}};
            wr_ptr_gray <= {(ADDR_WIDTH+1){1'b0}};
        end else if (do_write) begin
            mem[wr_ptr_bin[ADDR_WIDTH-1:0]] <= din;
            wr_ptr_bin  <= wr_ptr_bin + 1'b1;
            wr_ptr_gray <= bin2gray(wr_ptr_bin + 1'b1);
        end
    end

    wire do_read = rd_en && !empty && !rd_rst;
    always @(posedge rd_clk or posedge rd_rst) begin
        if (rd_rst) begin
            rd_ptr_bin  <= {(ADDR_WIDTH+1){1'b0}};
            rd_ptr_gray <= {(ADDR_WIDTH+1){1'b0}};
            dout        <= {DATA_WIDTH{1'b0}};
        end else if (do_read) begin
            dout        <= mem[rd_ptr_bin[ADDR_WIDTH-1:0]];
            rd_ptr_bin  <= rd_ptr_bin + 1'b1;
            rd_ptr_gray <= bin2gray(rd_ptr_bin + 1'b1);
        end
    end

    always @(posedge rd_clk or posedge rd_rst) begin
        if (rd_rst) begin
            wr_ptr_gray_rdsync0 <= {(ADDR_WIDTH+1){1'b0}};
            wr_ptr_gray_rdsync  <= {(ADDR_WIDTH+1){1'b0}};
        end else begin
            wr_ptr_gray_rdsync0 <= wr_ptr_gray;
            wr_ptr_gray_rdsync  <= wr_ptr_gray_rdsync0;
        end
    end
    always @(posedge wr_clk or posedge wr_rst) begin
        if (wr_rst) begin
            rd_ptr_gray_wrsync0 <= {(ADDR_WIDTH+1){1'b0}};
            rd_ptr_gray_wrsync  <= {(ADDR_WIDTH+1){1'b0}};
        end else begin
            rd_ptr_gray_wrsync0 <= rd_ptr_gray;
            rd_ptr_gray_wrsync  <= rd_ptr_gray_wrsync0;
        end
    end

    
    assign empty = (rd_ptr_gray == wr_ptr_gray_rdsync) || rd_rst;

    
    wire [ADDR_WIDTH:0] wr_ptr_gray_next = bin2gray(wr_ptr_bin + 1'b1);
    wire [ADDR_WIDTH:0] rd_ptr_gray_wrsync_rev =
        { ~rd_ptr_gray_wrsync[ADDR_WIDTH -:2], rd_ptr_gray_wrsync[ADDR_WIDTH-2:0] };
    assign full = (wr_ptr_gray == rd_ptr_gray_wrsync_rev) || wr_rst;

    wire _unused_wn = |wr_ptr_gray_next;

    function [ADDR_WIDTH:0] gray2bin;
        input [ADDR_WIDTH:0] gr;
        reg   [ADDR_WIDTH:0] b;
        integer i;
        begin
            b[ADDR_WIDTH] = gr[ADDR_WIDTH];
            for (i = ADDR_WIDTH-1; i >= 0; i = i-1)
                b[i] = b[i+1] ^ gr[i];
            gray2bin = b;
        end
    endfunction

    wire [ADDR_WIDTH:0] wr_ptr_bin_rdsync = gray2bin(wr_ptr_gray_rdsync);
    wire [ADDR_WIDTH:0] rd_ptr_bin_wrsync = gray2bin(rd_ptr_gray_wrsync);

    assign wr_data_count = wr_ptr_bin[ADDR_WIDTH-1:0] - rd_ptr_bin_wrsync[ADDR_WIDTH-1:0];
    assign rd_data_count = wr_ptr_bin_rdsync[ADDR_WIDTH-1:0] - rd_ptr_bin[ADDR_WIDTH-1:0];

endmodule
