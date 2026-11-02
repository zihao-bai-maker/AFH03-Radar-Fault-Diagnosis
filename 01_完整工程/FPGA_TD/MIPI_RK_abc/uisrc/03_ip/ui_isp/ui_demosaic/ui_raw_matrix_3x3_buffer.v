

module ui_raw_matrix_3x3_buffer #(
    parameter 			IMG_HEIGHT 			= 1080,  
    parameter 			IMG_WIDTH  			= 1920,   
    parameter 			data_complete_delay = 50
)
(
    input           	I_clk   			,  
    input           	I_rst_n 			,  

    input [39:0]  		I_axi4s_video_tdata ,  
    input [9:0]   		I_axi4s_video_tdest ,
    input         		I_axi4s_video_tlast ,  
    input         		I_axi4s_video_tvalid,  
    input         		I_axi4s_video_tuser ,  
    output        		I_axi4s_video_tready,  

    output        		O_tlast         	,   
    output        		O_tuser         	,   
    output        		O_tvalid        	,   
    input         		O_tready        	,   

    output        		bayer_ypos      	,   
    output  [95:0]		matrix_last_line	,   
    output  [95:0]		matrix_cur_line 	,   
    output  [95:0]		matrix_next_line        
);

function integer clog2b(
    input integer depth
);
    begin
        for(clog2b=0; depth>0; clog2b=clog2b+1)begin
            depth = depth >> 1;
        end
    end    
endfunction

localparam N = 3;  

localparam DATA_WIDTH   = 32;  

localparam IMG_WIDTH_4x = (IMG_WIDTH >> 2);  

wire                        zhenghe_tlast 	;    
wire                        zhenghe_tuser 	;    
wire  [31:0]                zhenghe_tdata 	;    
wire                        zhenghe_tvalid	;    

wire  [DATA_WIDTH-1:0]      raw_data        ;    
wire                        raw_data_valid  ;    

wire                		valid   [0:N-1] ;    
wire [DATA_WIDTH:0] 		data    [0:N-1] ;    

wire                		O_raw_tlast_d0	;    
wire                		O_raw_tuser_d0	;    
wire                		I_raw_tready	;    
wire [32:0]         		next_line_data	;    
wire [32:0]         		data_d2			;    
wire                		next_line_start	;    
wire                		bayer_ypos_d0	;    

reg [95:0]      matrix_cur_line_buffer       ; 
reg [95:0]      matrix_last_line_buffer      ; 
reg [95:0]      matrix_next_line_buffer      ; 
reg             tlast_d0,tlast_d1,tlast_d2;     
reg             tuser_d0,tuser_d1,tuser_d2;     
reg             ch_valid;                       
reg [13:0]      h_cnt;                          
reg [13:0]      v_cnt,v_cnt_d;                  
reg             next_line_data_valid;           
reg             valid_d0,valid_d1;              
reg             bayer_ypos_d;                   
reg  [32:0]     data_d0_d,data_d0;              
reg  [32:0]     data_d1;

assign data[0]  = {zhenghe_tuser, zhenghe_tdata};  
assign valid[0] = zhenghe_tvalid;                  

assign axi4s_video_tready = O_tready;

assign matrix_last_line = matrix_last_line_buffer;
assign matrix_cur_line  = matrix_cur_line_buffer ;
assign matrix_next_line = matrix_next_line_buffer;

assign bayer_ypos_d0 = !v_cnt_d[0] & ch_valid;

ui_mipi_to_raw_converter X_ui_mipi_to_raw_converter(
    .I_clk       (I_clk  ),              
    .I_rst_n     (I_rst_n),              
    .I_raw_tdata (I_axi4s_video_tdata ),   
    .I_raw_tdest (I_axi4s_video_tdest ),   
    .I_raw_tlast (I_axi4s_video_tlast ),   
    .I_raw_tvalid(I_axi4s_video_tvalid),   
    .I_raw_tuser (I_axi4s_video_tuser),    
    .I_raw_tready(I_raw_tready  ),       
    .O_raw_tdata (raw_data      ),       
    .O_raw_tlast (O_raw_tlast_d0),       
    .O_raw_tvalid(raw_data_valid),       
    .O_raw_tuser (O_raw_tuser_d0),       
    .O_raw_tready(1)                     
);

ui_zhenghe#(
    .IMG_WIDTH ( IMG_WIDTH ),
    .IMG_HEIGHT( IMG_HEIGHT),
    .DATA_WIDTH( 32),
    .data_complete_delay (data_complete_delay)
) 
X_ui_zhenghe(
    .I_clk    (I_clk   ),               
    .I_rst_n  (I_rst_n ),               

    .I_tlast  (O_raw_tlast_d0 ),        
    .I_tuser  (O_raw_tuser_d0 ),        
    .I_tdata  (raw_data ),              
    .I_tvalid (raw_data_valid),         

    .O_tlast  (zhenghe_tlast ),         
    .O_tuser  (zhenghe_tuser ),         
    .O_tdata  (zhenghe_tdata ),         
    .O_tvalid (zhenghe_tvalid)          
);

genvar i;
generate
    for(i=1; i<3; i=i+1)
    begin: two_line_buffer  
        ui_line_buffer_demosaic #(
            .IMG_HEIGHT (IMG_HEIGHT),
            .IMG_WIDTH  (IMG_WIDTH )
        ) X_ui_line_buffer_demosaic (
            .I_clk     ( I_clk      ),    
            .I_rst_n   ( I_rst_n    ),    
            .I_tuser   ( data[i-1][32] & valid[i-1]), 
            .I_valid   ( valid[i-1] ),    
            .I_data    ( data[i-1]  ),    
            .O_valid   ( valid[i]   ),    
            .O_data    ( data[i]    )     
        );           
    end        
endgenerate

always @(posedge I_clk or negedge I_rst_n) begin
    if (!I_rst_n) begin
        data_d0_d <= 0;
        data_d0   <= 0;
        data_d1   <= 0;
        valid_d0  <= 0;
        valid_d1  <= 0;
    end
    else begin
        valid_d0  <= valid[0];
        valid_d1  <= valid_d0;
        data_d0_d <= data[0];
        data_d0   <= data_d0_d;
        data_d1   <= data[1];
    end
end

assign data_d2 = data[2];

always @(posedge I_clk or negedge I_rst_n) begin 
    if(!I_rst_n) begin
        matrix_last_line_buffer <= 'b0 ;
        matrix_cur_line_buffer  <= 'b0 ;
        matrix_next_line_buffer <= 'b0 ;
    end else if(valid_d1) begin
        if(v_cnt == 0) begin  
            if(h_cnt == 0) begin  
                matrix_last_line_buffer <= {{24{1'b0}}, data_d0[31:24], data_d0[31:0], data_d0[31:0]} ;
                matrix_cur_line_buffer  <= {{24{1'b0}}, data_d0[31:24], data_d0[31:0], data_d0[31:0]} ;
                matrix_next_line_buffer <= {{24{1'b0}}, data_d0[31:24], data_d0[31:0], data_d0[31:0]} ;
            end else if(h_cnt == (IMG_WIDTH_4x - 1)) begin  
                matrix_last_line_buffer <= {matrix_next_line_buffer [63:0], matrix_next_line_buffer[7:0], {24{1'b0}}} ;
                matrix_cur_line_buffer  <= {matrix_next_line_buffer [63:0], matrix_next_line_buffer[7:0], {24{1'b0}}} ;
                matrix_next_line_buffer <= {matrix_next_line_buffer [63:0], matrix_next_line_buffer[7:0], {24{1'b0}}} ;
            end else begin  
                matrix_last_line_buffer <= {matrix_next_line_buffer[63:0], data_d0[31:0]} ;
                matrix_cur_line_buffer  <= {matrix_next_line_buffer[63:0], data_d0[31:0]} ;
                matrix_next_line_buffer <= {matrix_next_line_buffer[63:0], data_d0[31:0]} ;
            end
        end
        else if(v_cnt == 1) begin  
            if(h_cnt == 0) begin  
                matrix_last_line_buffer <= {{24{1'b0}}, data_d1[31:24], data_d1[31:0], data_d1[31:0]} ;
                matrix_cur_line_buffer  <= {{24{1'b0}}, data_d1[31:24], data_d1[31:0], data_d1[31:0]} ;
                matrix_next_line_buffer <= {{24{1'b0}}, data_d0[31:24], data_d0[31:0], data_d0[31:0]} ;
            end else if(h_cnt == (IMG_WIDTH_4x - 1)) begin  
                matrix_last_line_buffer <= {matrix_cur_line_buffer [63:0], matrix_cur_line_buffer[7:0], {24{1'b0}}} ;
                matrix_cur_line_buffer  <= {matrix_cur_line_buffer [63:0], matrix_cur_line_buffer[7:0], {24{1'b0}}} ;
                matrix_next_line_buffer <= {matrix_next_line_buffer [63:0], matrix_next_line_buffer[7:0], {24{1'b0}}} ;
            end else begin  
                matrix_last_line_buffer <= {matrix_cur_line_buffer[63:0],  data_d1[31:0]} ;
                matrix_cur_line_buffer  <= {matrix_cur_line_buffer[63:0],  data_d1[31:0]} ;
                matrix_next_line_buffer <= {matrix_next_line_buffer[63:0], data_d0[31:0]} ;
            end
        end
        else begin  
            if(h_cnt == 0) begin  
                matrix_last_line_buffer <= {{24{1'b0}}, data_d2[31:24], data_d2[31:0], data_d2[31:0]} ;
                matrix_cur_line_buffer  <= {{24{1'b0}}, data_d1[31:24], data_d1[31:0], data_d1[31:0]} ;
                matrix_next_line_buffer <= {{24{1'b0}}, data_d0[31:24], data_d0[31:0], data_d0[31:0]} ;
            end else if(h_cnt == (IMG_WIDTH_4x - 1)) begin  
                matrix_last_line_buffer <= {matrix_last_line_buffer[63:0], matrix_last_line_buffer[7:0], {24{1'b0}}} ;
                matrix_cur_line_buffer  <= {matrix_cur_line_buffer [63:0], matrix_cur_line_buffer [7:0], {24{1'b0}}} ;
                matrix_next_line_buffer <= {matrix_next_line_buffer[63:0], matrix_next_line_buffer[7:0], {24{1'b0}}} ;
            end else begin  
                matrix_last_line_buffer <= {matrix_last_line_buffer[63:0], data_d2[31:0]} ;
                matrix_cur_line_buffer  <= {matrix_cur_line_buffer [63:0], data_d1[31:0]} ;
                matrix_next_line_buffer <= {matrix_next_line_buffer[63:0], data_d0[31:0]} ;
            end  
        end
    end
    else begin
        matrix_last_line_buffer <= 'b0 ;
        matrix_cur_line_buffer  <= 'b0 ;
        matrix_next_line_buffer <= 'b0 ;
    end 
end

always @(posedge I_clk or negedge I_rst_n) begin
    if(!I_rst_n || zhenghe_tuser) begin
        h_cnt <= 0;
        v_cnt <= 0;
    end else begin
        h_cnt    <= valid_d1 ? ((h_cnt == IMG_WIDTH_4x - 1) ? 0 : h_cnt + 1) : h_cnt;
        v_cnt    <= valid_d1 && (h_cnt == IMG_WIDTH_4x - 1) ? ((v_cnt == IMG_HEIGHT - 1) ? 0 : v_cnt + 1) : v_cnt;
    end
end

always @(posedge I_clk or negedge I_rst_n) begin
    if(!I_rst_n) begin
        ch_valid <= 0;
        v_cnt_d <= 0;
    end else begin
        ch_valid <= valid_d1 ;
        v_cnt_d  <= v_cnt;
    end
end

assign bayer_ypos = bayer_ypos_d0 ;

always @(posedge I_clk or negedge I_rst_n) begin
    if (!I_rst_n) begin
        tlast_d0 <= 0;
        tlast_d1 <= 0;
        tlast_d2 <= 0;
        tuser_d0 <= 0;
        tuser_d1 <= 0;
        tuser_d2 <= 0;
    end
    else begin
        tlast_d0 <= zhenghe_tlast;
        tlast_d1 <= tlast_d0;
        tlast_d2 <= tlast_d1;
        tuser_d0 <= zhenghe_tuser;
        tuser_d1 <= tuser_d0;
        tuser_d2 <= tuser_d1;
    end
end

assign O_tuser  = tuser_d2;
assign O_tlast  = tlast_d2;
assign O_tvalid = ch_valid;

endmodule

