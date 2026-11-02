

`timescale 1ns / 1ns 

module ui_i2c#
(
parameter WMEN_LEN = 8'd0,	
parameter RMEN_LEN = 8'd0,	
parameter CLK_DIV  = 16'd499
)
(
input  wire 					I_clk				,
input  wire 					I_rstn				,
output reg  					O_iic_scl = 1'b0	,
inout  wire 					IO_iic_sda			,
input  wire [WMEN_LEN*8-1'b1:0]	I_wr_data			,
input  wire [7:0]				I_wr_cnt			,
output reg  [RMEN_LEN*8-1'b1:0]	O_rd_data = 0		,
input  wire [7:0]				I_rd_cnt			,
input  wire 					I_iic_req			,
input  wire 					I_iic_mode			,
output reg  					O_iic_busy = 1'b0	,
output reg  					O_iic_bus_error		, 
output reg  					O_iic_sda_dg
);

localparam IDLE    = 4'd0;
localparam START   = 4'd1;
localparam W_WAIT  = 4'd2;
localparam W_ACK   = 4'd3;
localparam R_WAIT  = 4'd4;
localparam R_ACK   = 4'd5;
localparam STOP1   = 4'd6;
localparam STOP2   = 4'd7;

localparam SCL_DIV = CLK_DIV/2;

localparam OFFSET = SCL_DIV - SCL_DIV/4;	

reg [2:0] 	IIC_S 		= 4'd0; 	

reg [15:0] 	clkdiv 		= 16'd0;   	
reg 		scl_r 	    = 1'b1; 	
reg 		sda_o 	    = 1'b0; 	
reg 		scl_clk     = 1'b0; 	
reg [7:0] 	sda_r 		= 8'd0;  	
reg [7:0] 	sda_i_r 	= 8'd0;   	
reg [7:0] 	wcnt 		= 8'd0;    	
reg [7:0] 	rcnt 		= 8'd0;    	
reg [2:0] 	bcnt 		= 3'd0;    	
reg  		rd_req 		= 1'b0;  	

wire 		sda_i;                  
wire 		scl_offset;             

assign  sda_i   	= (IO_iic_sda == 1'b0) 	?  1'b0 : 1'b1;  	
assign  IO_iic_sda 	= (sda_o == 1'b0) 		?  1'b0 : 1'bz;    	
assign  scl_offset  = (clkdiv == OFFSET);						

always@(posedge I_clk)
    if(clkdiv < SCL_DIV)    
        clkdiv <= clkdiv + 1'b1;
    else begin
        clkdiv <= 16'd0; 
        scl_clk <= !scl_clk;
    end

always @(posedge I_clk) O_iic_scl <=  scl_offset ?  scl_r : O_iic_scl; 

always @(posedge I_clk) O_iic_sda_dg <= sda_i;  

always @(*) 
    if(IIC_S == IDLE || IIC_S == STOP1 || IIC_S == STOP2)
        scl_r <= 1'b1;
    else 
        scl_r <= scl_clk;

always @(*) 
    if(IIC_S == START || IIC_S == STOP1 || (IIC_S == R_ACK && (rcnt != I_rd_cnt)))
        sda_o <= 1'b0;
    else if(IIC_S == W_WAIT)
        sda_o <= sda_r[7]; 
    else  sda_o <= 1'b1; 

always @(posedge scl_clk) 
    if(IIC_S == W_ACK || IIC_S == START)begin
        sda_r <= I_wr_data[(wcnt*8) +: 8];
        if( rd_req ) sda_r <= {I_wr_data[7:1],1'b1};
    end
    else if(IIC_S == W_WAIT)
        sda_r <= {sda_r[6:0],1'b1};
    else 
        sda_r <= sda_r;

always @(negedge scl_clk)begin
    if(IIC_S == R_WAIT ) 
        sda_i_r <= {sda_i_r[6:0],sda_i};
    else if(IIC_S == R_ACK)
        O_rd_data[((rcnt-1'b1)*8) +: 8] <= sda_i_r[7:0];
    else if(IIC_S == IDLE)
        sda_i_r <= 8'd0;
end

always @(posedge scl_clk or negedge I_rstn )begin
	if(I_rstn == 1'b0)
    	O_iic_busy <= 1'b0; 
	else begin
    	if((I_iic_req == 1'b1 || rd_req == 1'b1 || O_iic_bus_error))
    	    O_iic_busy <= 1'b1; 
        else if(IIC_S == IDLE)
        	O_iic_busy <= 1'b0;
    end 		
end

always @(negedge scl_clk or negedge I_rstn )begin
	if(I_rstn == 1'b0)
    	O_iic_bus_error <= 1'b0;  	
	else begin
    	if(IIC_S  == W_ACK && sda_i == 1'b1)
    	    O_iic_bus_error <= 1'b1; 
        else if(I_iic_req == 0)
        	O_iic_bus_error <= 1'b0;
    end 		
end

always @(posedge scl_clk or negedge I_rstn )begin
		if(I_rstn == 1'b0)begin 
           wcnt 	<= 8'd0;
           rcnt 	<= 8'd0;
           bcnt     <= 0;
           rd_req 	<= 1'b0;  
           IIC_S    <= 0; 
        end
        else begin
        case(IIC_S) 
        IDLE:begin
           if(I_iic_req == 1'b1 || rd_req == 1'b1) 
              IIC_S  <= START; 
           else begin
              wcnt <= 8'd0; 
              rcnt <= 8'd0; 
           end
        end
        START:begin 
           bcnt <= 3'd7; 
           IIC_S  <= W_WAIT;
        end           
        W_WAIT:
        begin
           if(bcnt > 3'd0)
               bcnt  <= bcnt - 1'b1; 
           else begin 
               wcnt <= wcnt + 1'b1; 
               IIC_S  <= W_ACK;
           end
        end 
        W_ACK:
        begin 
           if(wcnt < I_wr_cnt)begin 
              bcnt <= 3'd7; 
              IIC_S <= W_WAIT;
           end
           else if(I_rd_cnt > 3'd0)begin
              if(rd_req == 1'b0 && I_iic_mode == 1'b1)begin 
                  rd_req <= 1'b1;
                  IIC_S <= IDLE; 
              end
              else 
                  IIC_S <= R_WAIT;
                  bcnt <= 3'd7;
           end
           else 
              IIC_S <= STOP1; 
        end  
        R_WAIT:
        begin
           rd_req <= 1'b0;
           bcnt  <= bcnt - 1'b1; 
           if(bcnt == 3'd0)begin 
              rcnt <= (rcnt < I_rd_cnt) ? (rcnt + 1'b1) : rcnt;
              IIC_S  <= R_ACK;
           end
        end
        R_ACK:
        begin
           bcnt <= 3'd7;
           IIC_S <= (rcnt < I_rd_cnt) ? R_WAIT : STOP1; 
        end  
        STOP1:begin
            rd_req 	<= 1'b0;              
            IIC_S <= STOP2;
        end
        STOP2:
            IIC_S <= IDLE;          
        default:
            IIC_S <= IDLE;
    	endcase
    end
end

endmodule
