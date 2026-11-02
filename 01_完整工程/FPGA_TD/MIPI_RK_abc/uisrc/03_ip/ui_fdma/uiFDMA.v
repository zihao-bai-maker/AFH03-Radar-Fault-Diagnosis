

`timescale 1ns / 1ns

module ui_FDMA#
(
parameter  integer         M_AXI_B2B_SET			= 3		    , 
parameter  integer         M_AXI_ID_WIDTH			= 6			, 
parameter  integer         M_AXI_ID			        = 0		    , 
parameter  integer         M_AXI_ADDR_WIDTH			= 32		, 
parameter  integer         M_AXI_DATA_WIDTH			= 64		, 
parameter  integer		   M_AXI_MAX_BURST_LEN      = 16          
)
(
input   wire [M_AXI_ADDR_WIDTH-1 : 0]      I_fdma_waddr          ,
input                                      I_fdma_wareq          ,
input   wire [15 : 0]                      I_fdma_wsize          ,
output                                     O_fdma_wbusy          ,

input   wire [M_AXI_DATA_WIDTH-1 :0]       I_fdma_wdata		     ,
output  wire                               O_fdma_wvalid         ,
input	wire                               I_fdma_wready		 ,

input   wire [M_AXI_ADDR_WIDTH-1 : 0]      I_fdma_raddr          ,
input                                      I_fdma_rareq          ,
input   wire [15 : 0]                      I_fdma_rsize          ,
output                                     O_fdma_rbusy          ,

output  wire [M_AXI_DATA_WIDTH-1 :0]       O_fdma_rdata		     ,
output  wire                               O_fdma_rvalid         ,
input	wire                               I_fdma_rready		 ,

input 	wire  								M_AXI_ACLK			,
input 	wire  								M_AXI_ARESETN		,
output 	wire [M_AXI_ID_WIDTH-1 : 0]		    M_AXI_AWID			,
output 	wire [M_AXI_ADDR_WIDTH-1 : 0] 	    M_AXI_AWADDR		,
output 	wire [7 : 0]						M_AXI_AWLEN			,
output 	wire [2 : 0] 						M_AXI_AWSIZE		,
output 	wire [1 : 0] 						M_AXI_AWBURST		,
output 	wire  								M_AXI_AWLOCK		,
output 	wire [3 : 0] 						M_AXI_AWCACHE		,
output 	wire [2 : 0] 						M_AXI_AWPROT		,  
output 	wire [3 : 0] 						M_AXI_AWQOS			,
output 	wire  								M_AXI_AWVALID		,
input	wire  								M_AXI_AWREADY		,
output  wire [M_AXI_ID_WIDTH-1 : 0] 		M_AXI_WID			,
output  wire [M_AXI_DATA_WIDTH-1 : 0] 	    M_AXI_WDATA			,
output  wire [M_AXI_DATA_WIDTH/8-1 : 0] 	M_AXI_WSTRB			,
output  wire  								M_AXI_WLAST			, 			
output  wire  								M_AXI_WVALID		,
input   wire  								M_AXI_WREADY		,
input   wire [M_AXI_ID_WIDTH-1 : 0] 		M_AXI_BID			,
input   wire [1 : 0] 						M_AXI_BRESP			,
input   wire  								M_AXI_BVALID		,
output  wire  								M_AXI_BREADY		, 
output  wire [M_AXI_ID_WIDTH-1 : 0] 		M_AXI_ARID			,	 

output  wire [M_AXI_ADDR_WIDTH-1 : 0] 	    M_AXI_ARADDR		,	 	
output  wire [7 : 0] 						M_AXI_ARLEN			,	 
output  wire [2 : 0] 						M_AXI_ARSIZE		,	 
output  wire [1 : 0] 						M_AXI_ARBURST		,	 
output  wire  								M_AXI_ARLOCK		,	 
output  wire [3 : 0] 						M_AXI_ARCACHE		,	 
output  wire [2 : 0] 						M_AXI_ARPROT		,	 
output  wire [3 : 0] 						M_AXI_ARQOS			,	 	   
output  wire  								M_AXI_ARVALID		,	 
input   wire  								M_AXI_ARREADY		,	 
input   wire [M_AXI_ID_WIDTH-1 : 0] 		M_AXI_RID			,	 
input   wire [M_AXI_DATA_WIDTH-1 : 0] 	    M_AXI_RDATA			,	 
input   wire [1 : 0] 						M_AXI_RRESP			,	 
input   wire  								M_AXI_RLAST			,	 
input   wire  								M_AXI_RVALID		,    
output  wire  								M_AXI_RREADY				
	);

function integer clogb2 (input integer bit_depth);              
begin                                                        
	    for(clogb2=0; bit_depth>0; clogb2=clogb2+1)                   
	        bit_depth = bit_depth >> 1;                               
end                                                           
endfunction 

localparam AXI_BYTES =  M_AXI_DATA_WIDTH/8;
localparam [3:0] MAX_BURST_LEN_SIZE = clogb2(M_AXI_MAX_BURST_LEN)  -1;         

reg     [M_AXI_ADDR_WIDTH-1 : 0]        axi_awaddr  =0;     
reg                                     axi_awvalid = 1'b0; 
wire    [M_AXI_DATA_WIDTH-1 : 0]        axi_wdata   ;       
wire                                    axi_wlast   ;       
reg                                     axi_wvalid  = 1'b0; 
wire                                    w_next= (M_AXI_WVALID & M_AXI_WREADY);
reg   [8 :0]                            wburst_len  = 1  ;  
reg   [8 :0]                            wburst_cnt  = 0  ;  
reg   [15:0]                            wfdma_cnt   = 0  ;  
reg                                     axi_wstart_locked  =0;  
wire  [15:0] axi_wburst_size   =        wburst_len * AXI_BYTES; 

assign M_AXI_AWID       = M_AXI_ID;         
assign M_AXI_AWADDR     = axi_awaddr;
assign M_AXI_AWLEN      = wburst_len - 1;   
assign M_AXI_AWSIZE     = clogb2(AXI_BYTES-1);
assign M_AXI_AWBURST    = 2'b01;            
assign M_AXI_AWLOCK     = 1'b0;
assign M_AXI_AWCACHE    = 4'b0010;          
assign M_AXI_AWPROT     = 3'h0;
assign M_AXI_AWQOS      = 4'h0;
assign M_AXI_AWVALID         = axi_awvalid;
assign M_AXI_WDATA      = axi_wdata;
assign M_AXI_WSTRB      = {(AXI_BYTES){1'b1}};
assign M_AXI_WLAST      = axi_wlast;
assign M_AXI_WVALID     = axi_wvalid & I_fdma_wready;
assign M_AXI_BREADY     = 1'b1;

assign  axi_wdata        = I_fdma_wdata;
assign  O_fdma_wvalid      = w_next;
reg     fdma_wstart_locked = 1'b0;
wire    fdma_wend;
wire    fdma_wstart;
assign   O_fdma_wbusy = fdma_wstart_locked ;

always @(posedge M_AXI_ACLK)
    if(M_AXI_ARESETN == 1'b0 || fdma_wend == 1'b1 )
        fdma_wstart_locked <= 1'b0;
    else if(fdma_wstart)
        fdma_wstart_locked <= 1'b1;                                

assign fdma_wstart = (fdma_wstart_locked == 1'b0 && I_fdma_wareq == 1'b1);    

always @(posedge M_AXI_ACLK)
    if(fdma_wstart)    
        axi_awaddr <= I_fdma_waddr;
    else if(axi_wlast == 1'b1)
        axi_awaddr <= axi_awaddr + axi_wburst_size ;                    

reg axi_wstart_locked_r1 = 1'b0, axi_wstart_locked_r2 = 1'b0;
always @(posedge M_AXI_ACLK)begin
    axi_wstart_locked_r1 <= axi_wstart_locked;
    axi_wstart_locked_r2 <= axi_wstart_locked_r1;
end

always @(posedge M_AXI_ACLK)
    if(M_AXI_ARESETN == 1'b0)
        axi_wstart_locked <= 1'b0;
    else if((fdma_wstart_locked == 1'b1) &&  axi_wstart_locked == 1'b0)
        axi_wstart_locked <= 1'b1; 
    else if(axi_wlast == 1'b1 || fdma_wstart == 1'b1)
        axi_wstart_locked <= 1'b0;

always @(posedge M_AXI_ACLK)
     if(M_AXI_ARESETN == 1'b0)
         axi_awvalid <= 1'b0; 
     else if((axi_wstart_locked_r1 == 1'b1) &&  axi_wstart_locked_r2 == 1'b0)
         axi_awvalid <= 1'b1;
     else if((axi_wstart_locked == 1'b1 && M_AXI_AWREADY == 1'b1)|| axi_wstart_locked == 1'b0)
         axi_awvalid <= 1'b0;       

always @(posedge M_AXI_ACLK)
    if(M_AXI_ARESETN == 1'b0)
         axi_wvalid <= 1'b0; 
    else if((axi_wstart_locked_r1 == 1'b1) &&  axi_wstart_locked_r2 == 1'b0)
        axi_wvalid <= 1'b1;
    else if(axi_wlast == 1'b1 || axi_wstart_locked == 1'b0)
        axi_wvalid <= 1'b0;

always @(posedge M_AXI_ACLK)
    if(axi_wstart_locked == 1'b0 || M_AXI_ARESETN == 1'b0)
        wburst_cnt <= 'd0;
    else if(w_next)
        wburst_cnt <= wburst_cnt + 1'b1;    

assign axi_wlast = (w_next == 1'b1) && (wburst_cnt == M_AXI_AWLEN);

reg wburst_len_req = 1'b0;
reg [15:0] fdma_wleft_cnt =16'd0;

always @(posedge M_AXI_ACLK)
        wburst_len_req <= fdma_wstart|axi_wlast;

always @(posedge M_AXI_ACLK)
    if( fdma_wstart || M_AXI_ARESETN == 1'b0 )begin
        wfdma_cnt <= 1'd0;
        fdma_wleft_cnt <= I_fdma_wsize;
    end
    else if(w_next)begin
        wfdma_cnt <= wfdma_cnt + 1'b1;  
        fdma_wleft_cnt <= (I_fdma_wsize - 1'b1) - wfdma_cnt;
    end

assign  fdma_wend = w_next && (fdma_wleft_cnt == 1 );

always @(posedge M_AXI_ACLK)begin
    if(M_AXI_ARESETN == 1'b0)begin
        wburst_len <= 1;
    end
    else if(wburst_len_req)begin
        if(fdma_wleft_cnt[15:MAX_BURST_LEN_SIZE] >0)  
            wburst_len <= M_AXI_MAX_BURST_LEN;
        else 
            wburst_len <= fdma_wleft_cnt[MAX_BURST_LEN_SIZE-1:0];
    end
    else wburst_len <= wburst_len;
end

reg     [M_AXI_ADDR_WIDTH-1 : 0]    axi_araddr =0   ;    
reg                               axi_arvalid  =1'b0;   
wire                              axi_rlast   ;   
wire                              axi_rready  = 1'b1;  
wire                              r_next      = (M_AXI_RVALID && M_AXI_RREADY);  
reg   [8 :0]                      rburst_len  = 1  ;  
reg   [8 :0]                      rburst_cnt  = 0  ;   
reg   [15:0]                      rfdma_cnt   = 0  ;     
wire  [15:0] axi_rburst_size   =  rburst_len * AXI_BYTES;   

assign M_AXI_ARID       = M_AXI_ID; 
assign M_AXI_ARADDR     = axi_araddr;
assign M_AXI_ARLEN      = rburst_len - 1; 
assign M_AXI_ARSIZE     = clogb2((AXI_BYTES)-1);
assign M_AXI_ARBURST    = 2'b01;
assign M_AXI_ARLOCK     = 1'b0; 
assign M_AXI_ARCACHE    = 4'b0010;
assign M_AXI_ARPROT     = 3'h0;
assign M_AXI_ARQOS      = 4'h0;
assign M_AXI_ARVALID    = axi_arvalid;
assign M_AXI_RREADY     = axi_rready&&I_fdma_rready; 
assign O_fdma_rdata     = M_AXI_RDATA;    
assign O_fdma_rvalid    = r_next;    

reg     fdma_rstart_locked = 1'b0;   
wire    fdma_rend;   
wire    fdma_rstart;   
assign   O_fdma_rbusy = fdma_rstart_locked ;  

always @(posedge M_AXI_ACLK)
    if(M_AXI_ARESETN == 1'b0 || fdma_rend == 1'b1)
        fdma_rstart_locked <= 1'b0;
    else if(fdma_rstart)
        fdma_rstart_locked <= 1'b1;                                

assign fdma_rstart = (fdma_rstart_locked == 1'b0 && I_fdma_rareq == 1'b1);    

always @(posedge M_AXI_ACLK)
    if(fdma_rstart == 1'b1 || M_AXI_ARESETN == 1'b0)    
        axi_araddr <= I_fdma_raddr;
    else if(axi_arvalid & M_AXI_ARREADY ) 
        axi_araddr <= axi_araddr + axi_rburst_size ;  

reg fdma_rstart_r = 1'b0;
always @(posedge M_AXI_ACLK)
        fdma_rstart_r <= fdma_rstart;

reg [3 :0] rb2b;  
reg [15:0] fdma_rleft_cnt;  
wire rb2b_last;  

reg [3:0]rb2b_last_cnt;  
always @(posedge M_AXI_ACLK)
    if(fdma_rstart || M_AXI_ARESETN == 1'b0)
        rb2b_last_cnt <= 0;
    else if((rb2b_last_cnt < M_AXI_B2B_SET) & axi_rlast)
         rb2b_last_cnt <= rb2b_last_cnt + 1'b1;
    else if(rb2b_last_cnt == M_AXI_B2B_SET )
        rb2b_last_cnt <= 0;

assign rb2b_last = (rb2b_last_cnt == M_AXI_B2B_SET -1'b1) & axi_rlast;

always @(posedge M_AXI_ACLK or negedge M_AXI_ARESETN)begin
    if(M_AXI_ARESETN == 0)begin
        axi_arvalid     <= 1'b0;
        rburst_len      <= 0;
        rb2b            <= 0;
        fdma_rleft_cnt  <= 0;
    end
    else begin
    	if(fdma_rstart)begin
        	axi_arvalid     <= 1'b0;
        	rburst_len      <= 0;
        	fdma_rleft_cnt  <= I_fdma_rsize;
        	rb2b            <= 0;
    	end
    	else if(M_AXI_B2B_SET == 1)begin 
        	if(M_AXI_ARREADY & axi_arvalid ) 
            	axi_arvalid <= 1'b0;
        	else if(fdma_rstart_r | (~fdma_rend&axi_rlast))begin 
            	if(fdma_rleft_cnt[15:MAX_BURST_LEN_SIZE] > 0)begin
                	axi_arvalid     <= 1'b1;
                	rburst_len      <= M_AXI_MAX_BURST_LEN; 
                	fdma_rleft_cnt  <= fdma_rleft_cnt - M_AXI_MAX_BURST_LEN;
            	end
            	else if(fdma_rleft_cnt[MAX_BURST_LEN_SIZE-1:0] >0 )begin
                	axi_arvalid     <= 1'b1;
                	rburst_len      <= fdma_rleft_cnt[MAX_BURST_LEN_SIZE-1:0]; 
                	fdma_rleft_cnt  <= 0; 
            	end
            	else if(fdma_rleft_cnt[MAX_BURST_LEN_SIZE-1:0] ==0 )begin
                	axi_arvalid     <= 1'b0;
            	end 
        	end
    	end
    	else begin
        	if(rb2b_last )begin
            	axi_arvalid   <= 1'b0;
            	rb2b          <= 0;
        	end
        	else if((rb2b != M_AXI_B2B_SET) & M_AXI_ARREADY)begin 
            	if(fdma_rleft_cnt[15:MAX_BURST_LEN_SIZE] > 0)begin
                	axi_arvalid     <= 1'b1;
                	rb2b            <= rb2b + 1'b1;
                	rburst_len      <= M_AXI_MAX_BURST_LEN; 
                	fdma_rleft_cnt  <= fdma_rleft_cnt - M_AXI_MAX_BURST_LEN;
            	end
            	else if(fdma_rleft_cnt[MAX_BURST_LEN_SIZE-1:0] >0 )begin
                	axi_arvalid     <= 1'b1;
                	rb2b            <= rb2b + 1'b1;
                	rburst_len      <= fdma_rleft_cnt[MAX_BURST_LEN_SIZE-1:0]; 
                	fdma_rleft_cnt  <= 0;
            	end
            	else if(fdma_rleft_cnt[MAX_BURST_LEN_SIZE-1:0] == 0 )begin
                	axi_arvalid     <= 1'b0;
                	rb2b            <= M_AXI_B2B_SET;
            	end    
        	end
        	else if(rb2b == M_AXI_B2B_SET) begin
            	axi_arvalid <= 1'b0;
        	end
    	end
    end
end

reg rburst_len_req = 1'b0;  
reg [8:0] rburst_len_d =0;  
reg [15:0] fdma_rleft_cnt_d;  

always @(posedge M_AXI_ACLK)
        rburst_len_req <= fdma_rstart|axi_rlast;

always @(posedge M_AXI_ACLK)begin
    if(M_AXI_ARESETN == 1'b0)begin
        rburst_len_d <= 1;
    end
    else if(rburst_len_req)begin
        if(fdma_rleft_cnt_d[15:MAX_BURST_LEN_SIZE] >0)  
            rburst_len_d <= M_AXI_MAX_BURST_LEN;
        else 
            rburst_len_d <= fdma_rleft_cnt_d[MAX_BURST_LEN_SIZE-1:0];
    end
    else rburst_len_d <= rburst_len_d;
end

always @(posedge M_AXI_ACLK)
    if(fdma_rstart || M_AXI_ARESETN == 1'b0)begin
    	fdma_rleft_cnt_d <= I_fdma_rsize;
        rfdma_cnt <= 1'd0;
    end
    else if(r_next)begin
    	fdma_rleft_cnt_d <= (I_fdma_rsize - 1'b1) - rfdma_cnt;
        rfdma_cnt <= rfdma_cnt + 1'b1;  
    end

always @(posedge M_AXI_ACLK)
    if(axi_rlast == 1'b1 |fdma_rstart || M_AXI_ARESETN == 1'b0)
        rburst_cnt <= 0;
    else if(r_next)
        rburst_cnt <= rburst_cnt + 1'b1;            
assign axi_rlast = (r_next == 1'b1) && (rburst_cnt == rburst_len_d-1);

assign  fdma_rend = r_next && (fdma_rleft_cnt_d == 1 );

endmodule

