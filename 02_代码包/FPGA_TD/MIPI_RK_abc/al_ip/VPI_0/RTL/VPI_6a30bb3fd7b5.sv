    

module VPI_6a30bb3fd7b5 (  
    output [7:0] outprobe0, 
    input	clk
);
    localparam string IP_TYPE = "VPI";

    localparam VPI_OUTPUT_BUS_NUM = 1;
	localparam VPI_BUS_DOUT_NUM = 8;
	localparam integer VPI_BUS_DOUT_WIDTH[0:0] = {8};

    parameter VPI_OUTPUT_INIT_VAL = 8'b01010000;
endmodule

