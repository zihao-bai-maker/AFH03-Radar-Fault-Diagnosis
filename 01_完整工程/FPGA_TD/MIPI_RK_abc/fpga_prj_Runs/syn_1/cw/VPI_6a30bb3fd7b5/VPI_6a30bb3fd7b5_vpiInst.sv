              
module VPI_6a30bb3fd7b5 ( 
	output [7:0] outprobe0, 

	input	clk
);

	localparam VPI_OUTPUT_BUS_NUM = 1;
	localparam VPI_BUS_DOUT_NUM = 8;
	localparam integer VPI_BUS_DOUT_WIDTH[0:0] = {8};
	localparam integer VPI_BUS_DOUT_POS[0:0] = {0};
	localparam integer VPI_BUS_CTRL_POS[0:0] = {0};

	parameter VPI_BUS_CTRL_LEN = 33;
	parameter VPI_BUS_STAT_LEN = 1;
	parameter VPI_OUTPUT_INIT_VAL = 8'b01010000;

	wire vpi_behavior;
	wire vpi_rst;
	wire [32 : 0]  vpi_control;
	wire [0 : 0]  vpi_status;

    	top_vpi_hub #(
		.VPI_OUTPUT_BUS_NUM(VPI_OUTPUT_BUS_NUM),
		.VPI_BUS_DOUT_NUM(VPI_BUS_DOUT_NUM),
		.VPI_BUS_DOUT_WIDTH(VPI_BUS_DOUT_WIDTH),
		.VPI_BUS_DOUT_POS(VPI_BUS_DOUT_POS),
		.VPI_BUS_CTRL_POS(VPI_BUS_CTRL_POS)
	)
    	wrapper_vpi_top (
		.vpi_rst(vpi_rst),
		.vpi_control(vpi_control),
		.vpi_status(),
		.vpi_clk(clk),
		.vpi_behavior_clr(),
		.vpi_bus_din(),
		.vpi_bus_dout({outprobe0})
    	);

   	AL_LOGIC_DEBUGHUB #(
		.CTRL_LEN(VPI_BUS_CTRL_LEN),
		.STAT_LEN(VPI_BUS_STAT_LEN),
		.PWR_ON_CTRL(VPI_OUTPUT_INIT_VAL)
   	)
    	wrapper_debughub(
		.clk(clk),
		.control(vpi_control),
		.status(),
		.rst(vpi_rst),
		.behavior_clr()
    	);

endmodule

