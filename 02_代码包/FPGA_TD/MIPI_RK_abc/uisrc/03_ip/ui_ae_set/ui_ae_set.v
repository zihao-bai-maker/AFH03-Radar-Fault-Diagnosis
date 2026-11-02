

module ui_ae_set
(
input 	wire 		I_clk			,
input 	wire 		I_rst			,
input 	wire [1:0]	I_btn			,
input 	wire 		I_ae_cfg_done	,
input 	wire 		I_cam_cfg_done	,
output 	reg  		O_ae_req		,
output 	reg  [7:0]  O_ae
);

wire key0_down;
wire key1_down;

wire [7:0] outprobe0;

assign outprobe0 = 8'h50;

reg [1:0] btn_reg1;
reg [1:0] btn_reg2;
reg [7:0] ae_reg;

always@(posedge I_clk or negedge I_rst)begin
	if(!I_rst)begin
		btn_reg1 <= 2'b00;
		btn_reg2 <= 2'b00;
	end
	else begin
		btn_reg1 <= I_btn;
		btn_reg2 <= btn_reg1;
	end
end

always@(posedge I_clk or negedge I_rst)begin
	if(!I_rst)
		ae_reg <= 8'd60;
	else if(key0_down)
		ae_reg <= ae_reg + 1'b1;
	else if(key1_down)
		ae_reg <= ae_reg - 1'b1;
	else 
		ae_reg <= outprobe0;
end

always@(posedge I_clk or negedge I_rst)begin
	if(!I_rst)begin
		O_ae 	 <= 8'd60;
		O_ae_req <= 1'b0;
	end
	else if((O_ae != ae_reg) || (key0_down ||key1_down))begin
		O_ae     <= ae_reg;
		O_ae_req <= 1'b1;
    end
	else if(O_ae_req)
		O_ae_req <= 1'b0;

end

ui_key#(                                                                 
.REF_CLK(32'd24_000_000)
)
X_ui_key1
(
.I_sysclk(I_clk),
.I_rstn(I_rst),
.I_key(btn_reg2[0]),
.O_key_down(key0_down),
.O_key_up()
);

ui_key#(                                                                
.REF_CLK(32'd24_000_000)
)
X_ui_key2
(
.I_sysclk(I_clk),
.I_rstn(I_rst),
.I_key(btn_reg2[1]),
.O_key_down(key1_down),
.O_key_up()
);

endmodule

	