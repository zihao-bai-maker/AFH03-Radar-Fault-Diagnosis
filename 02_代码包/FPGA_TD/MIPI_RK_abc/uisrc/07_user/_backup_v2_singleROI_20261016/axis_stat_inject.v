

`timescale 1ns / 1ps

module axis_stat_inject #(
    parameter integer INJECT_WORDS = 16,   
    parameter integer INJECT_LINE  = 0     
)(
    input  wire        clk,            
    input  wire        rst_n,          
    input  wire        enable,         

    input  wire        s_tvalid,
    output wire        s_tready,
    input  wire [31:0] s_tdata,
    input  wire        s_tuser_sof,
    input  wire        s_tlast,

    output wire        m_tvalid,
    input  wire        m_tready,
    output wire [31:0] m_tdata,
    output wire        m_tuser_sof,
    output wire        m_tlast,

    input  wire [16*32-1:0] I_stat_block
);
    assign s_tready    = m_tready;
    assign m_tvalid    = s_tvalid;
    assign m_tuser_sof = s_tuser_sof;
    assign m_tlast     = s_tlast;

    localparam [15:0] INJ_WORDS = INJECT_WORDS;

    wire beat_acc = s_tvalid & m_tready;

    

    reg [15:0] icnt;    
    reg        iwin;    

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            icnt <= 16'd0;
            iwin <= 1'b0;
        end else if (beat_acc) begin
            if (s_tuser_sof) begin

                iwin <= (INJ_WORDS > 1);
                icnt <= 16'd1;
            end else if (iwin) begin
                if (icnt == INJ_WORDS - 16'd1) begin
                    iwin <= 1'b0;
                    icnt <= 16'd0;
                end else begin
                    icnt <= icnt + 16'd1;
                end
            end
        end
    end

    wire        inj = enable & beat_acc & (s_tuser_sof | iwin);
    wire [15:0] iw  = s_tuser_sof ? 16'd0 : icnt;

    assign m_tdata = inj ? I_stat_block[iw*32 +: 32] : s_tdata;

    wire _unused_line = |INJECT_LINE;

endmodule
