

`timescale 1ns / 1ps

module feat_div_seq #(
    parameter integer NUM_W = 29,      
    parameter integer DEN_W = 21       
)(
    input  wire                 clk,
    input  wire                 rst_n,
    input  wire                 start,
    input  wire [NUM_W-1:0]     num,
    input  wire [DEN_W-1:0]     den,

    output reg  [NUM_W-1:0]     quot,
    output reg  [DEN_W-1:0]     rem,
    output reg                  busy,
    output reg                  done
);

    localparam integer RW = DEN_W + 1;          

    reg [NUM_W-1:0] mn;                          
    reg [DEN_W-1:0] md;                          
    reg [RW-1:0]    rr;                          
    reg [7:0]       cnt;                         
    reg [NUM_W-1:0] qacc;

    wire [RW-1:0]   rr_sh = {rr[RW-2:0], mn[NUM_W-1]};
    wire            ge    = (rr_sh >= {1'b0, md});
    wire [RW-1:0]   rr_nx = ge ? (rr_sh - {1'b0, md}) : rr_sh;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            quot <= {NUM_W{1'b0}};
            rem  <= {DEN_W{1'b0}};
            busy <= 1'b0;
            done <= 1'b0;
            mn   <= {NUM_W{1'b0}};
            md   <= {DEN_W{1'b0}};
            rr   <= {RW{1'b0}};
            cnt  <= 8'd0;
            qacc <= {NUM_W{1'b0}};
        end else begin
            done <= 1'b0;
            if (start && !busy) begin
                mn   <= num;
                md   <= den;
                rr   <= {RW{1'b0}};
                qacc <= {NUM_W{1'b0}};
                cnt  <= NUM_W[7:0];
                busy <= 1'b1;
            end else if (busy) begin
                mn   <= {mn[NUM_W-2:0], 1'b0};
                rr   <= rr_nx;
                qacc <= {qacc[NUM_W-2:0], ge};
                if (cnt == 8'd1) begin
                    busy <= 1'b0;
                    done <= 1'b1;
                    quot <= {qacc[NUM_W-2:0], ge};
                    rem  <= rr_nx[DEN_W-1:0];
                end
                cnt <= cnt - 8'd1;
            end
        end
    end

endmodule
