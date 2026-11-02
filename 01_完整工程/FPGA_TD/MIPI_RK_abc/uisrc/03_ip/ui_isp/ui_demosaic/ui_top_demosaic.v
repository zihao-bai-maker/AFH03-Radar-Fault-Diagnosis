

module ui_top_demosaic #(
    parameter IMG_HEIGHT          = 1080,  
    parameter IMG_WIDTH           = 1920,  
    parameter data_complete_delay = 50  ,
    parameter BAYER_MODE          = "BGGR"
)
(
    input           I_clk   		,  
    input           I_rst_n 		,  

    input [39:0]    I_axi4s_tdata 	,  
    input [9:0]     I_axi4s_tdest 	,
    input           I_axi4s_tlast 	,  
    input           I_axi4s_tvalid	,  
    input           I_axi4s_tuser 	,  
    output          I_axi4s_tready	,  

    output          O_tlast  		,  
    output          O_tuser  		,  
    output [127:0]  O_tdata  		,  
    output          O_tvalid 		,  
    input           O_tready 		   
);

wire 		demosaic_tlast ; 
wire 		demosaic_tuser ; 
wire 		demosaic_tvalid; 
wire 		demosaic_tready; 

wire        bayer_ypos      ;
wire [95:0] matrix_last_line;
wire [95:0] matrix_cur_line ;
wire [95:0] matrix_next_line;

ui_raw_matrix_3x3_buffer #(
    .IMG_HEIGHT         (IMG_HEIGHT         )	,  
    .IMG_WIDTH          (IMG_WIDTH          )	,  
    .data_complete_delay(data_complete_delay)
)X_ui_raw_matrix_3x3_buffer 
(
   .I_clk    				(I_clk   )				,  
   .I_rst_n  				(I_rst_n )				,  

   .I_axi4s_video_tdata 	(I_axi4s_tdata )	,  
   .I_axi4s_video_tdest 	(I_axi4s_tdest )	,
   .I_axi4s_video_tlast 	(I_axi4s_tlast )	,  
   .I_axi4s_video_tvalid	(I_axi4s_tvalid)	,  
   .I_axi4s_video_tuser 	(I_axi4s_tuser )	,  
   .I_axi4s_video_tready	(I_axi4s_tready)	,  

   .O_tlast         		(demosaic_tlast )		,   
   .O_tuser         		(demosaic_tuser )		,   
   .O_tvalid        		(demosaic_tvalid)		,   
   .O_tready        		(demosaic_tready)		,   

   .bayer_ypos      		(bayer_ypos      )		,   
   .matrix_last_line		(matrix_last_line)		,   
   .matrix_cur_line 		(matrix_cur_line )		,   
   .matrix_next_line		(matrix_next_line)		    
);

ui_bilinear_interpolation #(
    .BAYER_MODE 		(BAYER_MODE)
	)
X_ui_bilinear_interpolation(
	.I_clk            	(I_clk   )			,
	.I_rst_n          	(I_rst_n )			,

	.I_tlast      		(demosaic_tlast )  	,
	.I_tuser      		(demosaic_tuser )  	,
	.I_tvalid     		(demosaic_tvalid)  	,
	.I_tready     		(demosaic_tready)  	,

	.bayer_ypos       	(bayer_ypos       )	,
	.matrix_last_line 	(matrix_last_line )	,
	.matrix_cur_line  	(matrix_cur_line  )	,
	.matrix_next_line 	(matrix_next_line )	,

	.O_tlast 			(O_tlast )			,
	.O_tuser 			(O_tuser )			,
	.O_tdata 			(O_tdata )			,
	.O_tvalid			(O_tvalid)			,
	.O_tready			(O_tready)			

);

endmodule