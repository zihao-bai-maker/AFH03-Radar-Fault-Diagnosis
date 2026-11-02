

`timescale 1ns / 1ps

module ui_BLC #(
    parameter [9:0]  Black_level_offset_r0 = 15,
    parameter [9:0]  Black_level_offset_r1 = 15,
    parameter [9:0]  Black_level_offset_r2 = 15,
    parameter [9:0]  Black_level_offset_r3 = 15
)
(
    input                   I_clk  	  ,
    input                   I_rst_n	  ,

    input                   I_tlast   ,
    input                   I_tuser   ,
    input  [39:0]           I_tdata   ,
    input                   I_tvalid  , 
    input  [9:0]            I_tdest   ,
    output                  I_tready  ,

    output                  O_tlast   ,
    output                  O_tuser   ,
    output [39:0]           O_tdata   ,
    output                  O_tvalid  ,
    output [9:0]            O_tdest   ,
    input                   O_tready  

);

    reg                   I_tlast_r    ;
    reg                   I_tuser_r    ;
    reg                   I_tvalid_r   ;

    reg  [9:0]  		  data_out[3:0];

    wire [9:0]  I_blc_data[3:0];
    wire [9:0]  black_level_offset[3:0] ;

	
    assign black_level_offset[0] = Black_level_offset_r0;
    assign black_level_offset[1] = Black_level_offset_r1;
    assign black_level_offset[2] = Black_level_offset_r2;
    assign black_level_offset[3] = Black_level_offset_r3;

    assign I_blc_data[0] = I_tdata[9:0]  ;
    assign I_blc_data[1] = I_tdata[19:10];
    assign I_blc_data[2] = I_tdata[29:20];
    assign I_blc_data[3] = I_tdata[39:30];

    assign  O_tlast      = I_tlast_r;   
    assign  O_tuser      = I_tuser_r;   
    assign  O_tvalid     = I_tvalid_r;

    assign  O_tdata      = {data_out[3],data_out[2],data_out[1],data_out[0]};
    assign  I_tready     = O_tready;

    genvar i;
    generate for(i=0;i<4;i=i+1)
        begin:
        BLACK_LEVEL_OFFSET
        always @(posedge I_clk)begin 
            if (I_tvalid) begin

                if (I_blc_data[i] > black_level_offset[i]) begin
                    data_out[i] <= I_blc_data[i] - black_level_offset[i];
                end 
                else begin
                    data_out[i] <= 10'd0; 
                end
            end
        end
        end
    endgenerate

    always @(posedge I_clk or negedge I_rst_n) begin
        if(!I_rst_n)
            {I_tlast_r,I_tuser_r,I_tvalid_r} <= 0;
        else begin
            I_tlast_r <= I_tlast;
            I_tuser_r <= I_tuser;
            I_tvalid_r <= I_tvalid;
        end
    end

endmodule