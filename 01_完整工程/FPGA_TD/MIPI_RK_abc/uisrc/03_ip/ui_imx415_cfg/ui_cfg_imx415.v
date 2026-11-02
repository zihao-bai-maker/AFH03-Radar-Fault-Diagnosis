

module ui_cfg_imx415#
(
parameter	 CLK_DIV  = 16'd999
)
(
input  wire             I_clk,  
input  wire             I_rst_n,  
input  wire             I_ae_req,
input  wire	 [7:0] 		I_ae_data,
output wire             O_cam_scl, 
inout  wire             IO_cam_sda, 
output reg              O_cfg_done, 
output reg              O_ae_cfg_done
);	

localparam CAM_ID = 8'h34;		

wire 		ic_busy			; 	
wire   		O_iic_bus_error	;

wire [23:0] REG_DATA_REG	; 	
wire [7 :0] REG_SIZE_REG	;	

wire [1 :0] REG_SIZE_ST = 2'd2; 
wire [2 :0] REG_SIZE_AE = 3'd4; 

reg  		O_cfg_done_r;	
reg  		iic_req		;	
reg  [7:0] 	rst_cnt		;	
reg  [21:0] cnt			;	

reg  [31:0] wr_data		;   

reg  [7 :0] reg_index	;   

reg [23:0] 	REG_DATA;    	
reg [7:0]  	REG_SIZE;    	

reg [23:0] 	REG_DATA_ST;  	
reg [23:0] 	REG_DATA_AE;  	

reg  [1 :0] TS_S = 2'd0; 	

always@(posedge I_clk or negedge I_rst_n)  
    if(I_rst_n == 1'b0) 
        rst_cnt<= 8'd0; 
    else if(rst_cnt[7] == 1'b0)
       rst_cnt <= rst_cnt + 1'b1; 
    else 
       rst_cnt <= rst_cnt; 

always@(posedge I_clk or negedge I_rst_n)  begin
    if(I_rst_n == 1'b0) 
         cnt <= 0;
    else if(cnt == 1000_000)
         cnt <= 0;
    else if(O_cfg_done == 1'b1)
         cnt <= cnt + 1;
    else if(O_cfg_done_r == 1'b1)
         cnt <= cnt;
end

always@(posedge I_clk or negedge I_rst_n)begin
    if(I_rst_n == 1'b0)begin
		REG_SIZE <= 8'b0;
		REG_DATA <= 24'b0;
	end
	else if(O_cfg_done == 1'b0)begin
		REG_SIZE <= REG_SIZE_REG;
		REG_DATA <= REG_DATA_REG;
	end
	else if(O_cfg_done == 1'b1 && O_cfg_done_r == 1'b0)begin
		REG_SIZE <= REG_SIZE_ST;
		REG_DATA <= REG_DATA_ST;
	end
	else if(O_cfg_done == 1'b1 && O_cfg_done_r == 1'b1)begin
		REG_SIZE <= REG_SIZE_AE;
		REG_DATA <= REG_DATA_AE;
	end
	else begin
		REG_SIZE <= 8'b0;
		REG_DATA <= 24'b0;
	end
end

always@(posedge I_clk ) begin 
    if(rst_cnt[7] == 1'b0)begin 
        reg_index  <= 9'd0;
        iic_req    <= 1'b0;
        wr_data    <= 32'd0;
        O_cfg_done <= 1'b0;
        O_cfg_done_r <= 1'b0;
        O_ae_cfg_done <= 1'b1;
        TS_S     <= 2'd0;    
    end
    else begin
        case(TS_S)
        0:if(reg_index == REG_SIZE && O_cfg_done == 1'b0) begin
            O_cfg_done <= 1'b1;       
        end 
        else if(reg_index == REG_SIZE && O_cfg_done == 1'b1 && O_cfg_done_r == 1'b0) begin
            O_cfg_done_r <= 1'b1;       
        end 
        else if(cnt== 1000_000)begin
            O_cfg_done_r <= 0;
            reg_index   <= 0;
        end
		else if(reg_index == REG_SIZE && O_cfg_done == 1'b1 && O_cfg_done_r == 1'b1) begin
            O_ae_cfg_done <= 1'b1;       
        end 
        else if(I_ae_req)begin
            O_ae_cfg_done <= 0;
            reg_index   <= 0;
        end
        else if((O_cfg_done&O_cfg_done_r&O_ae_cfg_done) == 1'b0)
            TS_S <= 2'd1;           
        1:if(!iic_busy)begin        
            iic_req  <= 1'b1;       
			wr_data[7  :0] <= CAM_ID;           
			wr_data[15 :8] <= REG_DATA[23:16];  
			wr_data[23:16] <= REG_DATA[15: 8];  
            wr_data[31:24] <= REG_DATA[7 : 0];  
            TS_S      <= 2'd2; 
        end    
        2:if(iic_busy)begin
             iic_req  <= 1'b0;  
             TS_S     <= 2'd3;  
        end
        3:if(!iic_busy)begin  
			reg_index<= reg_index + 1'b1;
			TS_S    <= 2'd0;
        end 
        endcase
   end
end

ui_i2c#
(
	.WMEN_LEN	(4		),     
	.RMEN_LEN	(1		),     
	.CLK_DIV	(CLK_DIV) 	   
)
X_ui_i2c
(
	.I_clk			(I_clk			),
	.I_rstn			(rst_cnt[7]		),
	.O_iic_scl		(O_cam_scl		),
	.IO_iic_sda		(IO_cam_sda		),
	.I_wr_data		(wr_data		),
	.I_wr_cnt		(8'd4			),
	.O_rd_data		(				),
	.I_rd_cnt		(8'd0			),
	.I_iic_mode		(1'b0			),
	.I_iic_req		(iic_req		),
	.O_iic_busy		(iic_busy		),
	.O_iic_bus_error(O_iic_bus_error)
);

ui_imx415reg X_ui_imx415reg
(
	.REG_SIZE	(REG_SIZE_REG	),  
	.REG_INDEX	(reg_index		),    
	.REG_DATA	(REG_DATA_REG	)   
);  

always@(*)
   case(reg_index)
		0:		REG_DATA_ST = {16'h3000, 8'h00}; 
		1:		REG_DATA_ST = {16'h3002, 8'h00}; 
		default:REG_DATA_ST = {16'h0000, 8'h00};
   endcase

always@(*)
   case(reg_index)
		0:		REG_DATA_AE = {16'h3090, I_ae_data}; 
		1:		REG_DATA_AE = {16'h3092, I_ae_data}; 
		2:		REG_DATA_AE = {16'h3094, I_ae_data}; 
		3:		REG_DATA_AE = {16'h3096, I_ae_data}; 
		default:REG_DATA_AE = {16'h0000, 8'h00};
   endcase

endmodule
