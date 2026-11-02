`timescale 1ns/1ns

`define DRAM_BYTE_NUM 2   	   
`define DRAM_SIZE    "2G"     

`define MC_AXI  

module system_top#(
parameter DRAM_TYPE       = "DDR3"  ,            
parameter ECC             = "OFF",
parameter APP_ADDR_WIDTH  = (`DRAM_SIZE=="1G")?26:(`DRAM_SIZE=="2G")?27:(`DRAM_SIZE == "4G")?28:(`DRAM_SIZE == "8G")?29:28, 
parameter AXI_ID_WIDTH    =  4,                                                                                   
parameter APP_DATA_WIDTH  = (ECC == "ON")? (`DRAM_BYTE_NUM-1)*8*8 : `DRAM_BYTE_NUM*8*8,
parameter APP_MASK_WIDTH  = (ECC == "ON")? (`DRAM_BYTE_NUM-1)*8   : `DRAM_BYTE_NUM*8,
parameter AXI_ADDR_WIDTH  = APP_ADDR_WIDTH+3,
parameter AXI_DATA_WIDTH  = APP_DATA_WIDTH,
parameter DQ_WIDTH        = `DRAM_BYTE_NUM * 8,
parameter DQS_WIDTH       = `DRAM_BYTE_NUM,
parameter DM_WIDTH        = `DRAM_BYTE_NUM,
parameter ADDR_WIDTH      = (DRAM_TYPE=="DDR4")?17:(`DRAM_SIZE=="1G")?13:(`DRAM_SIZE=="2G")?14:(`DRAM_SIZE == "4G")?15:(`DRAM_SIZE == "8G")?16:15, 
parameter ROW_WIDTH       = (`DRAM_SIZE=="1G")?13:(`DRAM_SIZE=="2G")?14:(`DRAM_SIZE == "4G")?15:(`DRAM_SIZE == "8G")?16:15,                        
parameter COL_WIDTH       = 10,                  
parameter BA_WIDTH        = 3,                   
parameter BG_WIDTH        = 1,                   
parameter ODT_WIDTH       = 1,                   
parameter CKE_WIDTH       = 1,                   
parameter CS_WIDTH        = 1                    
)
(
    input                           I_sysclk_25m,	
    input                           I_ddr_clk   ,	

	
    output    [ADDR_WIDTH-1:0]      ddr_addr    , 
    output    [  BA_WIDTH-1:0]      ddr_ba      ,
    output    [ CKE_WIDTH-1:0]      ddr_cke     ,
    output    [ ODT_WIDTH-1:0]      ddr_odt     ,
    output    [  CS_WIDTH-1:0]      ddr_cs_n    ,
    output                          ddr_ras_n   ,
    output                          ddr_cas_n   ,
    output                          ddr_we_n    ,
    output                          ddr_ck_p    ,
    output                          ddr_ck_n    ,
    output                          ddr_reset_n ,
    inout     [  DM_WIDTH-1:0]      ddr_dm  	,
    inout     [  DQ_WIDTH-1:0]      ddr_dq      ,
    inout     [ DQS_WIDTH-1:0]      ddr_dqs_n   ,
    inout     [ DQS_WIDTH-1:0]      ddr_dqs_p   ,

	output wire 					O_clk_24m	,	
	output wire 					O_clk_rst	,	
    output wire 					O_cam_scl	,   
    inout  wire 					IO_cam_sda	,   

	

	input  wire		    			I_clk_hs_p  ,	
	input  wire	[3:0]				I_data_hs_p , 
	input  wire	[3:0]				I_data_lp_p ,
	input  wire	[3:0]				I_data_lp_n ,

	input  wire						I_dsi_en			,	
	output wire						O_mipi_dsi_hs_clk_p	,
	output wire	[3:0]				O_mipi_dsi_hs_data_p,
	output wire						O_mipi_dsi_lp_clk_p	,
	output wire						O_mipi_dsi_lp_clk_n	,
	output wire	[3:0]				O_mipi_dsi_lp_data_p,
	output wire	[3:0]				O_mipi_dsi_lp_data_n
);                                      

wire                       		S_dfi_clk             ;
wire                       		S_ddr_init_cal_done   ;

wire [AXI_ADDR_WIDTH-1:0]      	S_axi_awaddr  	;
wire                           	S_axi_awvalid 	;
wire                           	S_axi_awready 	;
wire   [AXI_ID_WIDTH-1:0]      	S_axi_awid    	;
wire                [7:0]      	S_axi_awlen   	; 
wire                [2:0]      	S_axi_awsize  	; 
wire                [1:0]      	S_axi_awburst 	; 
wire                [0:0]      	S_axi_awlock  	; 
wire                [3:0]      	S_axi_awcache 	; 
wire                [2:0]      	S_axi_awprot  	; 
wire                [3:0]      	S_axi_awqos   	;

wire [APP_DATA_WIDTH-1:0]      	S_axi_wdata   	;
wire [APP_MASK_WIDTH-1:0]      	S_axi_wstrb   	;
wire                           	S_axi_wvalid  	;
wire                           	S_axi_wlast   	;
wire                           	S_axi_wready  	;

wire   [AXI_ID_WIDTH-1:0]      	S_axi_bid     	;    
wire                [1:0]      	S_axi_bresp   	;    
wire                           	S_axi_bvalid  	;    
wire                           	S_axi_bready  	;    

wire [AXI_ADDR_WIDTH-1:0]      	S_axi_araddr  	;
wire                           	S_axi_arvalid 	;
wire                           	S_axi_arready 	;
wire [  AXI_ID_WIDTH-1:0]      	S_axi_arid    	;
wire                [7:0]      	S_axi_arlen   	;
wire                [2:0]      	S_axi_arsize  	;
wire                [1:0]      	S_axi_arburst 	;
wire                [0:0]      	S_axi_arlock  	;
wire                [3:0]      	S_axi_arcache 	;
wire                [2:0]      	S_axi_arprot  	;
wire                [3:0]      	S_axi_arqos   	;

wire [APP_DATA_WIDTH-1:0]      	S_axi_rdata   	;
wire                           	S_axi_rlast   	;
wire                           	S_axi_rvalid  	;
wire                           	S_axi_rready  	;
wire   [AXI_ID_WIDTH-1:0]      	S_axi_rid     	;
wire                [1:0]      	S_axi_rresp   	;

wire [AXI_ADDR_WIDTH-1:  0]    	S_fdma_waddr	;   
wire                           	S_fdma_wareq	;   
wire [15: 0]                   	S_fdma_wsize	;   
wire                           	S_fdma_wbusy	;   
wire [AXI_DATA_WIDTH-1 : 0]    	S_fdma_wdata	;   
wire                           	S_fdma_wvalid	;   
wire                           	S_fdma_wready	;   

wire [AXI_ADDR_WIDTH-1:  0]    	S_fdma_raddr	;   
wire                           	S_fdma_rareq	;   
wire [15: 0]                   	S_fdma_rsize	;   
wire                           	S_fdma_rbusy	;   
wire [AXI_DATA_WIDTH-1 : 0]    	S_fdma_rdata	;   
wire                           	S_fdma_rvalid	;   
wire                           	S_fdma_rready	;   
wire                           	S_test_error	;   

wire   							S_clk_24m		;
wire        					S_pclkx1		;
wire        					S_pclkx5		;
wire        					S_clk_70m		;
wire        					S_pll_lock		;

	wire							S_dsi_25m_unused;
	wire							S_dsi_byte_clk	;	
	wire							S_dsi_hs_x2		;	
	wire							S_dsi_hs_x4		;	
	wire							S_dsi_hs_x4_90d	;	
	wire							S_dsi_lp_clk	;	
	wire							S_dsi_pll_lock	;

	wire							S_dsi_R_tuser	;
	wire							S_dsi_R_tvalid	;
	wire							S_dsi_R_tlast	;
	wire	[31:0]					S_dsi_R_tdata32	;	
	wire							S_dsi_pack_tready;

	reg  [1:0]						S_dsi_en_sync	= 2'b00;
	wire							S_dsi_en_int	= S_dsi_en_sync[1];
	wire							S_dphy_rst_n	= S_pll_lock & S_dsi_pll_lock & S_dsi_en_int;

wire [7:0]						S_ae			;
wire 							S_cam_cfg_done	;
wire 							S_ae_cfg_done	;
wire 							S_ae_req		;

wire          					S_hs_rx_clk		;  
wire          					S_hs_rx_valid	;  
wire [31 : 0] 					S_hs_rx_data	; 
wire [3 : 0]					S_lane_error	;

wire        					S_csi_frame_start;       
wire        					S_csi_frame_end	;         
wire        					S_csi_valid		;             
wire[31:0]  					S_csi_data		;  

wire          					S_raw10_frame_start;
wire          					S_raw10_frame_end;
wire          					S_raw10_valid	;
wire [39 : 0] 					S_raw10_data	;

wire [39:0]						S_axis_tdata	;
wire 							S_axis_tvalid	;
wire 							S_axis_tlast	; 
wire 							S_axis_tuser	; 

wire							S_ISP_O_tready 	;
wire [127:0]					S_ISP_O_tdata  	;  
wire 							S_ISP_O_tlast  	;
wire 							S_ISP_O_tuser  	;
wire 							S_ISP_O_tvalid 	;

wire [7:0] 						S_wbuf_sync		;
wire [7:0] 						S_rbuf_sync		;

wire 							S_ud_wclk		;
wire 							S_ud_wtuser		; 
wire 							S_ud_wtvalid	; 
wire 							S_ud_wtlast		; 
wire 							S_ud_wtready	;  
wire [63:0] 					S_ud_wtdata		;  

wire        S_yuv_de;
wire        S_yuv_sof;
wire        S_yuv_last;
wire [63:0] S_yuv_data;

wire 							S_vtc_vs		;
wire 							S_vtc_hs		;
wire 							S_vtc_de_valid	;
wire 							S_vtc_user		;
wire 							S_vtc_last      ;

wire [31:0] 					S_ud_rtdata		;  

wire        					S_R_vrst		;

assign O_clk_rst				= 1'b1;

assign S_ud_wclk 				= S_hs_rx_clk	;
assign S_ud_wtuser 				= S_yuv_sof		;
assign S_ud_wtvalid 			= S_yuv_de		;
assign S_ud_wtlast 				= S_yuv_last	;
assign S_ud_wtdata 				= S_yuv_data	;

rgb_to_yuv422_quad u_rgb2yuv_quad (
	.clk        (S_hs_rx_clk    ),
	.rst_n      (S_pll_lock     ),
	.i_de       (S_ISP_O_tvalid ),
	.i_user_sof (S_ISP_O_tuser  ),
	.i_last     (S_ISP_O_tlast  ),
	.i_data     (S_ISP_O_tdata  ),
	.o_de       (S_yuv_de       ),
	.o_user_sof (S_yuv_sof      ),
	.o_last     (S_yuv_last     ),
	.o_data     (S_yuv_data     )
);

ui_pll X_ui_pll (
    .refclk  	(I_sysclk_25m	),
    .reset		(1'b0			),

    .lock		(S_pll_lock		),

    .clk0_out	(S_clk_24m		),
    .clk1_out	(S_pclkx1		),
    .clk2_out	(S_pclkx5		),
    .clk3_out	(S_clk_70m		)
  );

PH1_LOGIC_ODDR X_cam_clk (
    .q  		(O_clk_24m	), 
    .clk		(S_clk_24m	),
    .d0 		(1'b1		),
    .d1 		(1'b0		),
    .rst		(1'b0		)
  );

ui_ae_set X_ui_ae_set (
	.I_clk			(S_clk_24m		),
	.I_rst			(S_pll_lock		),
	.I_btn			(2'b11			),
	.I_cam_cfg_done	(S_cam_cfg_done	),
	.I_ae_cfg_done	(S_ae_cfg_done	),
	.O_ae_req		(S_ae_req		),
	.O_ae			(S_ae			)
  );

ui_cfg_imx415#(
	.CLK_DIV(24_000_000/100_000-1)
	)
X_ui_cfg_imx415(
	.I_clk			(S_clk_24m		),  
	.I_rst_n		(S_pll_lock		),  
	.I_ae_req		(S_ae_req		),
	.I_ae_data		(S_ae			),
	.O_cam_scl		(O_cam_scl		), 
	.IO_cam_sda		(IO_cam_sda		), 
	.O_cfg_done		(S_cam_cfg_done	),
	.O_ae_cfg_done	(S_ae_cfg_done	)
  );

mipi_dphy_rx_over_lvds_wrapper#(
    .DEVICE           ( "PH1"		 ),
    .LANE_NUM         ( 4    		 )
)X_mipi_dphy_rx_over_lvds_wrapper(
    .I_lp_clk         ( S_clk_70m    ),
    .I_rst            ( ~S_pll_lock  ),

    .I_mipi_clk_p     ( I_clk_hs_p   ),
    .I_mipi_data_hs_p ( I_data_hs_p  ),
    .I_mipi_data_lp_p ( I_data_lp_p  ),
    .I_mipi_data_lp_n ( I_data_lp_n  ),

    .I_lane_hs_invert ( 4'b0000      ),
    .I_lane_lp_invert ( 4'b0000      ),

    .O_hs_rx_clk      ( S_hs_rx_clk  ),
    .O_hs_rx_valid    ( S_hs_rx_valid),
    .O_hs_rx_data     ( S_hs_rx_data ),

    .O_lp_rx_lane0_p  (				 ),
    .O_lp_rx_lane0_n  (				 ),

    .O_lane_error     ( S_lane_error )
);

ui_csi_unpacket_4lane X_ui_csi_unpacket_4lane(
	.I_clk            ( S_hs_rx_clk       ),
	.I_rst_n          ( S_pll_lock        ),
	.I_hs_valid       ( S_hs_rx_valid     ),
	.I_hs_data        ( S_hs_rx_data      ),

	.O_csi_frame_start( S_csi_frame_start ),
	.O_csi_frame_end  ( S_csi_frame_end   ),
	.O_csi_valid      ( S_csi_valid       ),
	.O_csi_data       ( S_csi_data        )
);

ui_raw10_unpacket_4lane X_ui_raw10_unpacket_4lane (
	.I_clk  			(S_hs_rx_clk		),
	.I_rst_n			(S_pll_lock			),

	.I_csi_frame_start	(S_csi_frame_start	),
	.I_csi_frame_end  	(S_csi_frame_end	),
	.I_csi_valid      	(S_csi_valid		),
	.I_csi_data       	(S_csi_data			),

	.O_raw10_frame_start(S_raw10_frame_start),
	.O_raw10_frame_end  (S_raw10_frame_end  ),
	.O_raw10_valid      (S_raw10_valid      ),
	.O_raw10_data       (S_raw10_data       )
);

ui_image_correction #(
    .DATA_WIDTH  (40),
    .TDEST_WIDTH (10)
)X_ui_image_correction
(
    .I_clk            (S_hs_rx_clk		  ),
    .I_rst_n          (S_pll_lock		  ),

    .I_raw_data       (S_raw10_data       ),       
    .I_raw_valid      (S_raw10_valid      ),     
    .I_raw_frame_start(S_raw10_frame_start),
    .I_raw_frame_end  (S_raw10_frame_end  ),

    .O_raw_tdata 	  (S_axis_tdata 	  ),
    .O_raw_tlast 	  (S_axis_tlast 	  ),
    .O_raw_tvalid	  (S_axis_tvalid	  ),
    .O_raw_tuser 	  (S_axis_tuser 	  )

);

ui_isp_top X_ui_isp_top (
	.I_clk		     (S_hs_rx_clk		),
	.I_rst_n         (S_pll_lock		),
	.I_tlast         (S_axis_tlast 		),
	.I_tuser         (S_axis_tuser 		),
	.I_tdata         (S_axis_tdata 		),
	.I_tvalid        (S_axis_tvalid		),
	.I_tdest         (					),
	.O_tready        (S_ISP_O_tready	),
	.O_tdata         (S_ISP_O_tdata 	),
	.O_tlast         (S_ISP_O_tlast 	),
	.O_tuser         (S_ISP_O_tuser 	),
	.O_tvalid        (S_ISP_O_tvalid	),
	.I_tready        (					)
  );

ui_setvbuf#(
	.BUF_DELAY		(1			),
	.BUF_LENTH		(3			)
)
X_ui_setvbuf
(
	.I_bufn			(S_wbuf_sync),
	.O_bufn			(S_rbuf_sync)
);

ui_dbuf# (  
	.AXI_DATA_WIDTH	(AXI_DATA_WIDTH		),
	.AXI_ADDR_WIDTH	(AXI_ADDR_WIDTH		),
	.ENABLE_VSYNC	(1					),
	.W_BUFDEPTH		(2048				),
	.W_DATAWIDTH	(64					),
	.W_BASEADDR		(0					),
	.W_DSIZEBITS	(25					),
	.W_XSIZE		(480				),
	.W_XSTRIDE		(480				),
	.W_YSIZE		(1080				),
	.W_XDIV			(2					),
	.W_BUFSIZE		(3					),

	.R_BUFDEPTH		(2048				),
	.R_DATAWIDTH	(32					),
	.R_BASEADDR		(0					),
	.R_DSIZEBITS	(25					),
	.R_XSIZE		(960				),
	.R_XSTRIDE		(960				),
	.R_YSIZE		(1080				),
	.R_XDIV			(2					),
	.R_BUFSIZE		(3					) 
)
X_ui_dbuf
(
	.I_ui_clk		(S_dfi_clk			),
	.I_ui_rstn		(S_ddr_init_cal_done),

	.I_W_en      	(1					),
	.I_W_wclk    	(S_ud_wclk			),
	.I_W_tuser   	(S_ud_wtuser		),
	.I_W_tvalid  	(S_ud_wtvalid		),
	.I_W_tdata   	(S_ud_wtdata		),
	.I_W_tlast   	(S_ud_wtlast		),
	.O_W_tready  	(					),
	.O_W_sync_cnt	(S_wbuf_sync		),
	.I_W_buf     	(S_wbuf_sync		),

	.I_R_en      	(S_vtc_vs			),
	.I_R_rclk    	(S_pclkx1			),
	.I_R_tready  	(S_vtc_de_valid & S_dsi_pack_tready),
	.O_R_tuser   	(S_dsi_R_tuser		),
	.O_R_tvalid  	(S_dsi_R_tvalid		),
	.O_R_tdata   	(S_ud_rtdata		),
	.O_R_tlast   	(S_dsi_R_tlast		),
	.O_R_sync_cnt	(					),
	.I_R_buf     	(S_rbuf_sync		),
	.O_R_vrst    	(S_R_vrst			),

	.O_fdma_waddr 	(S_fdma_waddr		),
	.O_fdma_wareq 	(S_fdma_wareq		),
	.O_fdma_wsize 	(S_fdma_wsize		),
	.I_fdma_wbusy 	(S_fdma_wbusy		),
	.O_fdma_wdata 	(S_fdma_wdata		),
	.I_fdma_wvalid	(S_fdma_wvalid		),
	.O_fdma_wready	(S_fdma_wready		),
	.O_fdma_raddr 	(S_fdma_raddr		),
	.O_fdma_rareq 	(S_fdma_rareq		),
	.O_fdma_rsize 	(S_fdma_rsize		),
	.I_fdma_rbusy 	(S_fdma_rbusy		),
	.I_fdma_rdata 	(S_fdma_rdata		),
	.I_fdma_rvalid	(S_fdma_rvalid		),
	.O_fdma_rready	(S_fdma_rready		)

	

	
);

ui_FDMA#
(
	.M_AXI_B2B_SET		(1				),
	.M_AXI_ID_WIDTH		(AXI_ID_WIDTH	),
	.M_AXI_ADDR_WIDTH	(AXI_ADDR_WIDTH	),
	.M_AXI_DATA_WIDTH	(AXI_DATA_WIDTH	),
	.M_AXI_MAX_BURST_LEN(16				) 
)
X_ui_FDMA
(
	.I_fdma_waddr		(S_fdma_waddr	),
	.I_fdma_wareq		(S_fdma_wareq	),
	.I_fdma_wsize		(S_fdma_wsize	),
	.O_fdma_wbusy		(S_fdma_wbusy	),

	.I_fdma_wdata		(S_fdma_wdata	),
	.O_fdma_wvalid		(S_fdma_wvalid	),
	.I_fdma_wready		(1'b1			),

	.I_fdma_raddr		(S_fdma_raddr	),
	.I_fdma_rareq		(S_fdma_rareq	),
	.I_fdma_rsize		(S_fdma_rsize	),
	.O_fdma_rbusy		(S_fdma_rbusy	),

	.O_fdma_rdata		(S_fdma_rdata	),
	.O_fdma_rvalid		(S_fdma_rvalid	),
	.I_fdma_rready		(1'b1			),

	.M_AXI_ACLK         (S_dfi_clk		),
	.M_AXI_ARESETN      (S_ddr_init_cal_done),

	.M_AXI_AWID         (S_axi_awid		),
	.M_AXI_AWADDR       (S_axi_awaddr	),
	.M_AXI_AWLEN        (S_axi_awlen	),
	.M_AXI_AWSIZE       (S_axi_awsize	),
	.M_AXI_AWBURST      (S_axi_awburst	),
	.M_AXI_AWLOCK       (				),
	.M_AXI_AWCACHE      (S_axi_awcache	),
	.M_AXI_AWPROT       (S_axi_awprot	),
	.M_AXI_AWQOS        (				),
	.M_AXI_AWVALID      (S_axi_awvalid	),
	.M_AXI_AWREADY      (S_axi_awready	),

	.M_AXI_WDATA        (S_axi_wdata	),
	.M_AXI_WSTRB        (S_axi_wstrb	),
	.M_AXI_WLAST        (S_axi_wlast	),
	.M_AXI_WVALID       (S_axi_wvalid	),
	.M_AXI_WREADY       (S_axi_wready	),

	.M_AXI_BID          (S_axi_bid		),
	.M_AXI_BRESP        (S_axi_bresp	),
	.M_AXI_BVALID       (S_axi_bvalid	),
	.M_AXI_BREADY       (S_axi_bready	),

	.M_AXI_ARID         (S_axi_arid		),
	.M_AXI_ARADDR       (S_axi_araddr	),
	.M_AXI_ARLEN        (S_axi_arlen	),
	.M_AXI_ARSIZE       (S_axi_arsize	),
	.M_AXI_ARBURST      (S_axi_arburst	),
	.M_AXI_ARLOCK       (				),
	.M_AXI_ARCACHE      (S_axi_arcache	),
	.M_AXI_ARPROT       (				),
	.M_AXI_ARQOS        (				),
	.M_AXI_ARVALID      (S_axi_arvalid	),
	.M_AXI_ARREADY      (S_axi_arready	),

	.M_AXI_RID          (S_axi_rid		),
	.M_AXI_RDATA        (S_axi_rdata	),
	.M_AXI_RRESP        (S_axi_rresp	),
	.M_AXI_RLAST        (S_axi_rlast	),
	.M_AXI_RVALID       (S_axi_rvalid	),
	.M_AXI_RREADY       (S_axi_rready	)		
);

ui_ddr X_ui_ddr (

	.sys_rst_n  		(S_pll_lock		),
    .sys_clk    		(I_ddr_clk		),

`ifdef MC0_DRAM_DDR4
    .ddr_ck_t       	(				),
    .ddr_ck_c       	(				),
    .ddr_reset_n    	(				),
    .ddr_cke        	(				),
    .ddr_odt        	(				),
    .ddr_cs_n       	(				),
    .ddr_act_n      	(				),
    .ddr_bg         	(				),
    .ddr_ba         	(				),
    .ddr_addr       	(				),
    .ddr_dqs_t      	(				),
    .ddr_dqs_c      	(				),
    .ddr_dq         	(				),
    .ddr_dm_dbi     	(				),
`else
    .ddr_ck_p       	(ddr_ck_p		),    
    .ddr_ck_n       	(ddr_ck_n		),    
    .ddr_reset_n    	(ddr_reset_n	),   
    .ddr_cke        	(ddr_cke		),   
    .ddr_odt        	(ddr_odt		),    
    .ddr_cs_n       	(ddr_cs_n		),     
    .ddr_ras_n      	(ddr_ras_n		),    
    .ddr_cas_n      	(ddr_cas_n		), 		
    .ddr_we_n       	(ddr_we_n		),     
    .ddr_ba         	(ddr_ba			), 
    .ddr_addr       	(ddr_addr		),        
    .ddr_dqs_p      	(ddr_dqs_p		),   
    .ddr_dqs_n      	(ddr_dqs_n		),   
    .ddr_dq         	(ddr_dq			),
    .ddr_dm            	(ddr_dm			),
`endif

    .ctl_ram_rst_n     	(				),
    .ctl_ram_cke       	(				),

    .dfi_clk           	(S_dfi_clk		),
    .pll_locked        	(				),
    .ddrphy_rst_n      	(				),
    .ddr_init_cal_done 	(S_ddr_init_cal_done),
    .ddr_init_cal_err  	(				),
    .ddr_init_cal_step 	(				),

`ifdef MC0_MIS_AXI

    .axi_aclk          	(				),
    .axi_aresetn       	(				),

    .axi_awid          (S_axi_awid   	),
    .axi_awaddr        (S_axi_awaddr 	),
    .axi_awlen         (S_axi_awlen  	),
    .axi_awsize        (S_axi_awsize 	),
    .axi_awburst       (S_axi_awburst	),
    .axi_awlock        (S_axi_awlock 	),
    .axi_awcache       (S_axi_awcache	),
    .axi_awprot        (S_axi_awprot 	),
    .axi_awqos         (S_axi_awqos  	),
    .axi_awvalid       (S_axi_awvalid	),
    .axi_awready       (S_axi_awready	),

    .axi_wdata         (S_axi_wdata 	),
    .axi_wstrb         (S_axi_wstrb 	),
    .axi_wlast         (S_axi_wlast 	),
    .axi_wvalid        (S_axi_wvalid	),
    .axi_wready        (S_axi_wready	),

    .axi_bid           (S_axi_bid   	),
    .axi_bresp         (S_axi_bresp 	),
    .axi_bvalid        (S_axi_bvalid	),
    .axi_bready        (S_axi_bready	),

    .axi_arid          (S_axi_arid   	),
    .axi_araddr        (S_axi_araddr 	),
    .axi_arlen         (S_axi_arlen  	),
    .axi_arsize        (S_axi_arsize 	),
    .axi_arburst       (S_axi_arburst	),
    .axi_arlock        (S_axi_arlock 	),
    .axi_arcache       (S_axi_arcache	),
    .axi_arprot        (S_axi_arprot 	),
    .axi_arqos         (S_axi_arqos  	),
    .axi_arvalid       (S_axi_arvalid	),
    .axi_arready       (S_axi_arready	),

    .axi_rid           (S_axi_rid   	),
    .axi_rdata         (S_axi_rdata 	),
    .axi_rresp         (S_axi_rresp 	),
    .axi_rlast         (S_axi_rlast 	),
    .axi_rvalid        (S_axi_rvalid	),
    .axi_rready        (S_axi_rready	),
`else  

    .paxi_awaddr       (				), 
    .paxi_awvalid      (				), 
    .paxi_awready      (				), 

    .paxi_wdata        (				), 
    .paxi_wstrb        (				), 
    .paxi_wvalid       (				), 
    .paxi_wlast        (				), 
    .paxi_wready       (				), 

    .paxi_bresp        (				), 
    .paxi_bvalid       (				), 
    .paxi_bready       (				), 

    .paxi_araddr       (				), 
    .paxi_arvalid      (				), 
    .paxi_arready      (				), 			 

    .paxi_rdata        (				), 
    .paxi_rlast        (				), 
    .paxi_rvalid       (				), 
    .paxi_rready       (				), 
`endif

    .pzq_cal_done_i    (				),
    .pzq_cal_done_o    (				),

    .user_clk          (				), 
    .apb_clk           (				), 
    .mcu_busy          (				), 
    .user_update       (				), 
    .user_ram_addr     (				), 
    .user_ram_wr_en    (				), 
    .user_ram_rd_en    (				), 
    .user_ram_wr_data  (				), 
    .user_ram_rd_data  (				), 

    .uart_rxd          (				),
    .uart_txd          (				)
);

ui_vtc #(
	.H_ActiveSize      (1920			), 
	.H_SyncStart       (1920+88			), 
	.H_SyncEnd         (1920+88+44		), 
	.H_FrameSize       (1920+88+44+148	), 

	.V_ActiveSize      (1080			), 
	.V_SyncStart       (1080+4			), 
	.V_SyncEnd         (1080+4+5		), 
	.V_FrameSize       (1080+4+5+36		)  
) 
X_ui_vtc
(
    .I_vtc_rstn		   (~S_R_vrst		), 
    .I_vtc_clk		   (S_pclkx1		), 
    .O_vtc_vs		   (S_vtc_vs		), 
    .O_vtc_hs		   (S_vtc_hs		), 
    .O_vtc_de_valid	   (S_vtc_de_valid	), 
    .O_vtc_user		   (S_vtc_user		), 
    .O_vtc_last        (S_vtc_last      )  
);

pll_dsi u_ui_pll_dsi (
	.refclk		(I_sysclk_25m		),
	.reset		(1'b0				),
	.lock		(S_dsi_pll_lock		),
	.clk0_out	(S_dsi_25m_unused	),	
	.clk1_out	(S_dsi_byte_clk		),	
	.clk2_out	(S_dsi_hs_x2		),	
	.clk3_out	(S_dsi_hs_x4		),	
	.clk4_out	(S_dsi_hs_x4_90d	),	
	.clk5_out	(S_dsi_lp_clk		)	
);

always @(posedge I_sysclk_25m) begin
	S_dsi_en_sync <= {S_dsi_en_sync[0], I_dsi_en};
end

assign S_dsi_R_tdata32 = S_ud_rtdata;

wire        S_pack_tvalid;
wire        S_pack_tready;
wire [31:0] S_pack_tdata;
wire        S_pack_tsof;
wire        S_pack_tlast;

csi2_pack_yuv422_stream #(
	.H_ACTIVE	(1920),
	.V_ACTIVE	(1080)
) u_csi2_pack (

	.src_clk		(S_pclkx1			),
	.src_rst_n		(S_pll_lock			),
	.s_tvalid		(S_dsi_R_tvalid		),
	.s_tready		(S_dsi_pack_tready	),
	.s_tdata		(S_dsi_R_tdata32	),
	.s_tuser_sof	(S_dsi_R_tuser		),
	.s_tlast		(S_dsi_R_tlast		),

	.dst_clk		(S_dsi_byte_clk		),
	.dst_rst_n		(S_dphy_rst_n		),
	.enable			(S_dsi_en_int		),
	.m_tvalid		(S_pack_tvalid		),
	.m_tready		(S_pack_tready		),
	.m_tdata		(S_pack_tdata		),
	.m_tuser_sof	(S_pack_tsof		),
	.m_tlast		(S_pack_tlast		)
);

wire        S_stat_tx_tvalid;
wire [31:0] S_stat_tx_tdata;
wire        S_stat_tx_tsof;
wire        S_stat_tx_tlast;
wire        S_tx_s_tready;

wire [15:0] dg_feat_frame_cnt;
wire [1:0]  dg_feat_mode;
wire [7:0]  dg_feat_seg;
wire        dg_feat_any_lit;
wire [15:0] dg_feat_line_beats;
wire [15:0] dg_feat_frame_lines;
wire        dg_feat_blk_valid;

feat_top #(
	.H_ACTIVE      (1920),
	.V_ACTIVE      (1080),
	.INJECT_ENABLE (1)
) u_feat_top (
	.I_pix_clk        (S_hs_rx_clk        ),
	.I_pix_rst_n      (S_pll_lock         ),
	.I_isp_de         (S_ISP_O_tvalid     ),
	.I_isp_px         (S_ISP_O_tdata      ),
	.I_isp_sof        (S_ISP_O_tuser      ),
	.I_isp_eol        (S_ISP_O_tlast      ),
	.I_hs_clk         (S_dsi_byte_clk     ),
	.I_hs_rst_n       (S_dphy_rst_n       ),
	.I_pack_tvalid    (S_pack_tvalid      ),
	.O_pack_tready    (S_pack_tready      ),
	.I_pack_tdata     (S_pack_tdata       ),
	.I_pack_tuser_sof (S_pack_tsof        ),
	.I_pack_tlast     (S_pack_tlast       ),
	.O_tx_tvalid      (S_stat_tx_tvalid   ),
	.O_tx_tready      (S_tx_s_tready      ),
	.O_tx_tdata       (S_stat_tx_tdata    ),
	.O_tx_tuser_sof   (S_stat_tx_tsof     ),
	.O_tx_tlast       (S_stat_tx_tlast    ),
	.O_frame_cnt      (dg_feat_frame_cnt  ),
	.O_mode           (dg_feat_mode       ),
	.O_seg            (dg_feat_seg        ),
	.O_any_lit        (dg_feat_any_lit    ),
	.O_line_beats     (dg_feat_line_beats ),
	.O_frame_lines    (dg_feat_frame_lines),
	.O_blk_valid      (dg_feat_blk_valid  )
);

wire        S_hs_en;
wire [31:0] S_hs_data;
wire        S_hs_last;

csi2_frame_tx #(
	.DT			(6'h1E),	
	.VC			(2'd0 ),
	.H_ACTIVE	(1920 ),
	.V_ACTIVE	(1080 ),
	.BPP_NUM	(2    ),
	.BPP_DEN	(1    ),
	.GAP_LINE	(32'd200 ),
	.GAP_FRAME	(32'd4000)
) u_csi2_frame_tx (
	.clk			(S_dsi_byte_clk	),
	.rst_n			(S_dphy_rst_n	),
	.enable			(S_dsi_en_int	),
	.s_tvalid		(S_stat_tx_tvalid),
	.s_tready		(S_tx_s_tready	  ),
	.s_tdata		(S_stat_tx_tdata  ),
	.s_tuser_sof	(S_stat_tx_tsof	  ),
	.s_tlast		(S_stat_tx_tlast  ),
	.hs_en			(S_hs_en		),
	.hs_data		(S_hs_data		),
	.hs_last		(S_hs_last		),
	.frame_cnt		(				),
	.packet_cnt		(				)
);

mipi_dphy_tx_wrapper #(
	.LANE_NUM				(4      ),
	.HS_TX_FIFO_TYPE		("DRAM" ),
	.LP_TX_FIFO_TYPE		("DRAM" ),
	.LP_TX_MAX_DATA_LENGTH	(8      ),
	.CLK_LANE_MODE			("INTERRUPT"),
	.T_DATA_LPX				(10	),
	.T_DATA_HS_PREPARE		(7	),
	.T_DATA_HS_ZERO			(30	),
	.T_DATA_HS_TRAIL		(20	),
	.T_CLK_LPX				(10	),
	.T_CLK_PREPARE			(10	),
	.T_CLK_ZERO				(10	),
	.T_CLK_PRE				(10	),
	.T_CLK_POST				(10	),
	.T_CLK_TRAIL			(10	)
) u_dphy_tx (
	.I_hs_clk		(S_dsi_byte_clk			),
	.I_hs_clk_x2	(S_dsi_hs_x2			),
	.I_hs_clk_x4	(S_dsi_hs_x4			),
	.I_hs_clk_x4_90d(S_dsi_hs_x4_90d		),
	.I_lpdt_clk		(S_dsi_lp_clk			),
	.I_rst			(~S_dphy_rst_n			),

	.I_hs_tx_valid	(S_hs_en				),
	.I_hs_tx_data	(S_hs_data				),
	.I_hs_tx_last	(S_hs_last				),
	.O_hs_tx_ready	(						),

	.I_lp_tx_valid	(1'b0					),
	.I_lp_tx_data	(8'h00					),
	.I_lp_tx_last	(1'b0					),
	.O_lp_tx_ready	(						),

	.O_clk_hs_p		(O_mipi_dsi_hs_clk_p	),
	.O_data_hs_p	(O_mipi_dsi_hs_data_p	),
	.O_clk_lp_p		(O_mipi_dsi_lp_clk_p	),
	.O_clk_lp_n		(O_mipi_dsi_lp_clk_n	),
	.O_data_lp_p	(O_mipi_dsi_lp_data_p	),
	.O_data_lp_n	(O_mipi_dsi_lp_data_n	)
);

endmodule

