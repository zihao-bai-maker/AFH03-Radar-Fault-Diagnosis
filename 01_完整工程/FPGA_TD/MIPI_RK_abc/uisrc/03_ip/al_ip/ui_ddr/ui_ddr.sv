

`define MC0_DRAM_DDR3
`define MC0_MIS_AXI
`define MC0_DDR3_2G
`define MC0_DDR3_X16
`define MC0_DDR3_1600G

`timescale 1ps/1ps

module ui_ddr #(
`ifdef MC0_DRAM_DDR4
    parameter DRAM_TYPE          = "DDR4",
`else
    parameter DRAM_TYPE          = "DDR3",
`endif

    parameter integer tCK        = 1876,
    parameter integer CWL        = 6,
    parameter integer CL         = 8,

    parameter integer CK_WIDTH   = 1,
    parameter integer ODT_WIDTH  = 1,
    parameter integer CKE_WIDTH  = 1,
    parameter integer CS_WIDTH   = 1,
    parameter integer BG_WIDTH   = 0,
    parameter integer BANK_WIDTH = 3,
    parameter integer COL_WIDTH  = 10,
    parameter integer ROW_WIDTH  = 14,
    parameter integer ADDR_WIDTH = (DRAM_TYPE == "DDR4") ? 17 : ROW_WIDTH,
    parameter integer DQS_WIDTH  = 2,
    parameter integer RK_NUM     = 1,

    parameter MC_ADDR_MAP        = "ROW_COL_BANK",
    parameter MC_REORDER         = "NORMAL",
    parameter MC_ECC             = "OFF",

    parameter MC_ADDR_WIDTH      = ROW_WIDTH + COL_WIDTH + BANK_WIDTH + BG_WIDTH,
    parameter MC_DATA_WIDTH      = (MC_ECC == "ON") ? (DQS_WIDTH-1)*8*8 : DQS_WIDTH*8*8,
    parameter MC_MASK_WIDTH      = (MC_ECC == "ON") ? (DQS_WIDTH-1)*8   : DQS_WIDTH*8,
    parameter AXI_ID_WIDTH       = 4,
    parameter AXI_ADDR_WIDTH     = MC_ADDR_WIDTH + $clog2(MC_DATA_WIDTH/8) - 3,
    parameter AXI_DATA_WIDTH     = MC_DATA_WIDTH,
    parameter AXI_MASK_WIDTH     = MC_MASK_WIDTH,

    parameter integer DX_NUM     = DQS_WIDTH,
    parameter integer BA_WIDTH   = BANK_WIDTH,
    parameter integer ADR_WIDTH  = ADDR_WIDTH

)(
    input                        sys_rst_n         ,
    input                        sys_clk           ,

`ifdef MC0_DRAM_DDR4
    output [CK_WIDTH      -1:0]  ddr_ck_t          ,
    output [CK_WIDTH      -1:0]  ddr_ck_c          ,
    output                       ddr_reset_n       ,
    output [CKE_WIDTH     -1:0]  ddr_cke           ,
    output [ODT_WIDTH     -1:0]  ddr_odt           ,
    output [CS_WIDTH      -1:0]  ddr_cs_n          ,
    output                       ddr_act_n         ,
    output [BG_WIDTH      -1:0]  ddr_bg            ,
    output [BA_WIDTH      -1:0]  ddr_ba            ,
    output [ADR_WIDTH     -1:0]  ddr_addr          ,
    inout  [DX_NUM        -1:0]  ddr_dqs_t         ,
    inout  [DX_NUM        -1:0]  ddr_dqs_c         ,
    inout  [DX_NUM*8      -1:0]  ddr_dq            ,
    inout  [DX_NUM        -1:0]  ddr_dm_dbi        ,
`else
    output [CK_WIDTH      -1:0]  ddr_ck_p          ,
    output [CK_WIDTH      -1:0]  ddr_ck_n          ,
    output                       ddr_reset_n       ,
    output [CKE_WIDTH     -1:0]  ddr_cke           ,
    output [ODT_WIDTH     -1:0]  ddr_odt           ,
    output [CS_WIDTH      -1:0]  ddr_cs_n          ,
    output                       ddr_ras_n         ,
    output                       ddr_cas_n         ,
    output                       ddr_we_n          ,
    output [BA_WIDTH      -1:0]  ddr_ba            ,
    output [ADR_WIDTH     -1:0]  ddr_addr          ,
    inout  [DX_NUM        -1:0]  ddr_dqs_p         ,
    inout  [DX_NUM        -1:0]  ddr_dqs_n         ,
    inout  [DX_NUM*8      -1:0]  ddr_dq            ,
    inout  [DX_NUM        -1:0]  ddr_dm            ,
`endif

    output                       ctl_ram_rst_n     ,
    output                       ctl_ram_cke       ,

    output                       dfi_clk           ,
    output                       pll_locked        ,
    output                       ddrphy_rst_n      ,
    output                       ddr_init_cal_done ,
    output                [7:0]  ddr_init_cal_err  ,
    output                [7:0]  ddr_init_cal_step ,

`ifdef MC0_MIS_AXI

    input                        axi_aclk          ,
    input                        axi_aresetn       ,

    input  [AXI_ID_WIDTH  -1:0]  axi_awid          ,
    input  [AXI_ADDR_WIDTH-1:0]  axi_awaddr        ,
    input  [7:0]                 axi_awlen         ,
    input  [2:0]                 axi_awsize        ,
    input  [1:0]                 axi_awburst       ,
    input  [0:0]                 axi_awlock        ,
    input  [3:0]                 axi_awcache       ,
    input  [2:0]                 axi_awprot        ,
    input  [3:0]                 axi_awqos         ,
    input                        axi_awvalid       ,
    output                       axi_awready       ,

    input  [AXI_DATA_WIDTH-1:0]  axi_wdata         ,
    input  [AXI_MASK_WIDTH-1:0]  axi_wstrb         ,
    input                        axi_wlast         ,
    input                        axi_wvalid        ,
    output                       axi_wready        ,

    output [AXI_ID_WIDTH  -1:0]  axi_bid           ,
    output [1:0]                 axi_bresp         ,
    output                       axi_bvalid        ,
    input                        axi_bready        ,

    input  [AXI_ID_WIDTH  -1:0]  axi_arid          ,
    input  [AXI_ADDR_WIDTH-1:0]  axi_araddr        ,
    input  [7:0]                 axi_arlen         ,
    input  [2:0]                 axi_arsize        ,
    input  [1:0]                 axi_arburst       ,
    input  [0:0]                 axi_arlock        ,
    input  [3:0]                 axi_arcache       ,
    input  [2:0]                 axi_arprot        ,
    input  [3:0]                 axi_arqos         ,
    input                        axi_arvalid       ,
    output                       axi_arready       ,

    output [AXI_ID_WIDTH  -1:0]  axi_rid           ,
    output [AXI_DATA_WIDTH-1:0]  axi_rdata         ,
    output [1:0]                 axi_rresp         ,
    output                       axi_rlast         ,
    output                       axi_rvalid        ,
    input                        axi_rready        ,
`else  

    input  [ MC_ADDR_WIDTH-1:0]  paxi_awaddr       , 
    input                        paxi_awvalid      , 
    output                       paxi_awready      , 

    input  [ MC_DATA_WIDTH-1:0]  paxi_wdata        , 
    input  [ MC_MASK_WIDTH-1:0]  paxi_wstrb        , 
    input                        paxi_wvalid       , 
    input                        paxi_wlast        , 
    output                       paxi_wready       , 

    output [               1:0]  paxi_bresp        , 
    output                       paxi_bvalid       , 
    input                        paxi_bready       , 

    input  [ MC_ADDR_WIDTH-1:0]  paxi_araddr       , 
    input                        paxi_arvalid      , 
    output                       paxi_arready      , 

    output [ MC_DATA_WIDTH-1:0]  paxi_rdata        , 
    output                       paxi_rlast        , 
    output                       paxi_rvalid       , 
    input                        paxi_rready       , 
`endif

    input                        pzq_cal_done_i    ,
    output                       pzq_cal_done_o    ,

    output               [ 3:0]  user_clk          , 
    output                       apb_clk           , 
    output                       mcu_busy          , 
    input                        user_update       , 
    input                [ 7:0]  user_ram_addr     , 
    input                        user_ram_wr_en    , 
    input                        user_ram_rd_en    , 
    input                [31:0]  user_ram_wr_data  , 
    output               [31:0]  user_ram_rd_data  , 

    input                        uart_rxd          ,
    output                       uart_txd

);

`ifdef MC0_MIS_AXI

wire [MC_ADDR_WIDTH-1:0]  paxi_awaddr ; 
wire                      paxi_awvalid; 
wire                      paxi_awready; 

wire [MC_DATA_WIDTH-1:0]  paxi_wdata  ; 
wire [MC_MASK_WIDTH-1:0]  paxi_wstrb  ; 
wire                      paxi_wvalid ; 
wire                      paxi_wlast  ; 
wire                      paxi_wready ; 

wire [              1:0]  paxi_bresp  ; 
wire                      paxi_bvalid ; 
wire                      paxi_bready ; 

wire [MC_ADDR_WIDTH-1:0]  paxi_araddr ; 
wire                      paxi_arvalid; 
wire                      paxi_arready; 

wire [MC_DATA_WIDTH-1:0]  paxi_rdata  ; 
wire                      paxi_rlast  ; 
wire                      paxi_rvalid ; 
wire                      paxi_rready ; 
`endif

wire                      ddrphy_cal_done = ddr_init_cal_done;

ph1_ddrmc_top #(

    .DRAM_TYPE          ( DRAM_TYPE         ),
    .DX_NUM             ( DX_NUM            ),
    .RK_NUM             ( RK_NUM            ),
    .tCK                ( tCK               ),
    .CL                 ( CL                ),
    .CWL                ( CWL               ),

    .MC_ECC             ( MC_ECC            ),
    .MC_ADDR_MAP        ( MC_ADDR_MAP       ),
    .MC_REORDER         ( MC_REORDER        ),

    .BITS_CK            ( CK_WIDTH          ),
    .BITS_CKE           ( CKE_WIDTH         ),
    .BITS_CS            ( CS_WIDTH          ),
    .BITS_ODT           ( ODT_WIDTH         ),
    .BITS_ADR           ( ADR_WIDTH         ),
    .BITS_ROW           ( ROW_WIDTH         ),
    .BITS_COL           ( COL_WIDTH         ),
    .BITS_BG            ( BG_WIDTH          ),
    .BITS_BA            ( BA_WIDTH          )
) u_ddrmc_top (
    .sys_rst_n          ( sys_rst_n         ),
    .sys_clk            ( sys_clk           ),

`ifdef MC0_DRAM_DDR4
    .ddr_ck_t           ( ddr_ck_t          ),
    .ddr_ck_c           ( ddr_ck_c          ),
    .ddr_reset_n        ( ddr_reset_n       ),
    .ddr_cke            ( ddr_cke           ),
    .ddr_odt            ( ddr_odt           ),
    .ddr_cs_n           ( ddr_cs_n          ),
    .ddr_act_n          ( ddr_act_n         ),
    .ddr_bg             ( ddr_bg            ),
    .ddr_ba             ( ddr_ba            ),
    .ddr_addr           ( ddr_addr          ),
    .ddr_dqs_t          ( ddr_dqs_t         ),
    .ddr_dqs_c          ( ddr_dqs_c         ),
    .ddr_dq             ( ddr_dq            ),
    .ddr_dm_n           ( ddr_dm_dbi        ),
`else
    .ddr_ck_p           ( ddr_ck_p          ),
    .ddr_ck_n           ( ddr_ck_n          ),
    .ddr_reset_n        ( ddr_reset_n       ),
    .ddr_cke            ( ddr_cke           ),
    .ddr_odt            ( ddr_odt           ),
    .ddr_cs_n           ( ddr_cs_n          ),
    .ddr_ras_n          ( ddr_ras_n         ),
    .ddr_cas_n          ( ddr_cas_n         ),
    .ddr_we_n           ( ddr_we_n          ),
    .ddr_ba             ( ddr_ba            ),
    .ddr_addr           ( ddr_addr          ),
    .ddr_dqs_p          ( ddr_dqs_p         ),
    .ddr_dqs_n          ( ddr_dqs_n         ),
    .ddr_dq             ( ddr_dq            ),
    .ddr_dm             ( ddr_dm            ),
`endif

    .ctl_ram_rst_n      ( ctl_ram_rst_n     ),
    .ctl_ram_cke        ( ctl_ram_cke       ),

    .dfi_clk            ( dfi_clk           ),
    .pll_locked         ( pll_locked        ),
    .ddrphy_rst_n       ( ddrphy_rst_n      ),
    .ddr_init_cal_done  ( ddr_init_cal_done ),
    .ddr_init_cal_err   ( ddr_init_cal_err  ),
    .ddr_init_cal_step  ( ddr_init_cal_step ),

    .paxi_awaddr        ( paxi_awaddr       ),
    .paxi_awvalid       ( paxi_awvalid      ),
    .paxi_awready       ( paxi_awready      ),

    .paxi_wdata         ( paxi_wdata        ),
    .paxi_wstrb         ( paxi_wstrb        ),
    .paxi_wvalid        ( paxi_wvalid       ),
    .paxi_wlast         ( paxi_wlast        ),
    .paxi_wready        ( paxi_wready       ),

    .paxi_bresp         ( paxi_bresp        ),
    .paxi_bvalid        ( paxi_bvalid       ),
    .paxi_bready        ( paxi_bready       ),

    .paxi_araddr        ( paxi_araddr       ),
    .paxi_arvalid       ( paxi_arvalid      ),
    .paxi_arready       ( paxi_arready      ),

    .paxi_rdata         ( paxi_rdata        ),
    .paxi_rlast         ( paxi_rlast        ),
    .paxi_rvalid        ( paxi_rvalid       ),
    .paxi_rready        ( paxi_rready       ),

    .user_clk           ( user_clk          ),
    .apb_clk            ( apb_clk           ),
    .mcu_busy           ( mcu_busy          ),
    .user_update        ( user_update       ),
    .user_ram_addr      ( user_ram_addr     ),
    .user_ram_wr_en     ( user_ram_wr_en    ),
    .user_ram_rd_en     ( user_ram_rd_en    ),
    .user_ram_wr_data   ( user_ram_wr_data  ),
    .user_ram_rd_data   ( user_ram_rd_data  ),

    .uart_txd           ( uart_txd          ),
    .uart_rxd           ( uart_rxd          ),

    .pzq_cal_done_i     ( pzq_cal_done_i    ),
    .pzq_cal_done_o     ( pzq_cal_done_o    )
);

`ifdef MC0_MIS_AXI
mc0_axi2mc_top #(
    .AXI_ID_WIDTH    ( 4              ),
    .AXI_ADDR_WIDTH  ( AXI_ADDR_WIDTH ),
    .AXI_DATA_WIDTH  ( AXI_DATA_WIDTH ),
    .AXI_MASK_WIDTH  ( AXI_MASK_WIDTH ),
    .MC_ADDR_WIDTH   ( MC_ADDR_WIDTH  ),
    .MC_DATA_WIDTH   ( MC_DATA_WIDTH  ),
    .MC_MASK_WIDTH   ( MC_MASK_WIDTH  )
) u_axi2mc (

    .axi_aclk        ( dfi_clk         ),
    .axi_aresetn     ( ddrphy_rst_n    ),

    .axi_awid        ( axi_awid        ),
    .axi_awaddr      ( axi_awaddr      ),
    .axi_awlen       ( axi_awlen       ),
    .axi_awsize      ( axi_awsize      ),
    .axi_awburst     ( axi_awburst     ),
    .axi_awlock      ( axi_awlock      ),
    .axi_awcache     ( axi_awcache     ),
    .axi_awprot      ( axi_awprot      ),
    .axi_awqos       ( 4'b0000         ),
    .axi_awvalid     ( axi_awvalid     ),
    .axi_awready     ( axi_awready     ),

    .axi_wdata       ( axi_wdata       ),
    .axi_wstrb       ( axi_wstrb       ),
    .axi_wlast       ( axi_wlast       ),
    .axi_wvalid      ( axi_wvalid      ),
    .axi_wready      ( axi_wready      ),

    .axi_bid         ( axi_bid         ),
    .axi_bresp       ( axi_bresp       ),
    .axi_bvalid      ( axi_bvalid      ),
    .axi_bready      ( axi_bready      ),

    .axi_arid        ( axi_arid        ),
    .axi_araddr      ( axi_araddr      ),
    .axi_arlen       ( axi_arlen       ),
    .axi_arsize      ( axi_arsize      ),
    .axi_arburst     ( axi_arburst     ),
    .axi_arlock      ( axi_arlock      ),
    .axi_arcache     ( axi_arcache     ),
    .axi_arprot      ( axi_arprot      ),
    .axi_arqos       ( axi_arqos       ),
    .axi_arvalid     ( axi_arvalid     ),
    .axi_arready     ( axi_arready     ),

    .axi_rid         ( axi_rid         ),
    .axi_rdata       ( axi_rdata       ),
    .axi_rresp       ( axi_rresp       ),
    .axi_rlast       ( axi_rlast       ),
    .axi_rvalid      ( axi_rvalid      ),
    .axi_rready      ( axi_rready      ),

    .ddrphy_rdy      ( ddrphy_cal_done ),

    .paxi_awaddr     ( paxi_awaddr     ),
    .paxi_awvalid    ( paxi_awvalid    ),
    .paxi_awready    ( paxi_awready    ),

    .paxi_wdata      ( paxi_wdata      ),
    .paxi_wstrb      ( paxi_wstrb      ),
    .paxi_wvalid     ( paxi_wvalid     ),
    .paxi_wlast      ( paxi_wlast      ),
    .paxi_wready     ( paxi_wready     ),

    .paxi_bresp      ( paxi_bresp      ),
    .paxi_bvalid     ( paxi_bvalid     ),
    .paxi_bready     ( paxi_bready     ),

    .paxi_araddr     ( paxi_araddr     ),
    .paxi_arvalid    ( paxi_arvalid    ),
    .paxi_arready    ( paxi_arready    ),

    .paxi_rdata      ( paxi_rdata      ),
    .paxi_rlast      ( paxi_rlast      ),
    .paxi_rvalid     ( paxi_rvalid     ),
    .paxi_rready     ( paxi_rready     )
);
`endif

endmodule

`timescale 1ps/1ps

module ph1_ddrmc_top #(

    parameter         DRAM_TYPE     = "DDR4", 
    parameter integer DX_NUM        = 4     , 
    parameter integer RK_NUM        = 1     , 
    parameter integer tCK           = 1250  ,
    parameter integer CWL           = 9     ,
    parameter integer CL            = 11    ,

    parameter integer BITS_CK       = 1     , 
    parameter integer BITS_CS       = 1     , 
    parameter integer BITS_CKE      = 1     , 
    parameter integer BITS_ODT      = 1     , 
    parameter integer BITS_BG       = 2     , 
    parameter integer BITS_BA       = 2     , 
    parameter integer BITS_ADR      = 18    , 
    parameter integer BITS_ROW      = 15    , 
    parameter integer BITS_COL      = 10    , 

    parameter         MC_ECC        = "OFF",
    parameter         MC_REORDER    = "STRICT",
    parameter         MC_ADDR_MAP   = "ROW_COL_BANK",

    parameter         MC_ADDR_WIDTH = (RK_NUM == 2) + BITS_BG + BITS_BA + BITS_ROW + BITS_COL, 
    parameter         MC_DATA_WIDTH = (MC_ECC == "OFF") ? DX_NUM*8*8 : (DX_NUM-1)*8*8, 
    parameter         MC_MASK_WIDTH = (MC_ECC == "OFF") ? DX_NUM*8   : (DX_NUM-1)*8
)(
    input                         sys_rst_n           , 
    input                         sys_clk             , 

`ifdef MC0_DRAM_DDR4
    output     [BITS_CK  -1:0]    ddr_ck_t            , 
    output     [BITS_CK  -1:0]    ddr_ck_c            , 
    output                        ddr_reset_n         , 
    output     [BITS_CKE -1:0]    ddr_cke             , 
    output     [BITS_ODT -1:0]    ddr_odt             , 
    output     [BITS_CS  -1:0]    ddr_cs_n            , 
    output                        ddr_act_n           , 
    output     [BITS_BG  -1:0]    ddr_bg              , 
    output     [BITS_BA  -1:0]    ddr_ba              , 
    output     [BITS_ADR -1:0]    ddr_addr            , 
    inout      [DX_NUM   -1:0]    ddr_dqs_t           , 
    inout      [DX_NUM   -1:0]    ddr_dqs_c           , 
    inout      [DX_NUM*8 -1:0]    ddr_dq              , 
    inout      [DX_NUM   -1:0]    ddr_dm_n            , 

`else 
    output     [BITS_CK  -1:0]    ddr_ck_p            , 
    output     [BITS_CK  -1:0]    ddr_ck_n            , 
    output                        ddr_reset_n         , 
    output     [BITS_CKE -1:0]    ddr_cke             , 
    output     [BITS_ODT -1:0]    ddr_odt             , 
    output     [BITS_CS  -1:0]    ddr_cs_n            , 
    output                        ddr_ras_n           , 
    output                        ddr_cas_n           , 
    output                        ddr_we_n            , 
    output     [BITS_BA  -1:0]    ddr_ba              , 
    output     [BITS_ADR -1:0]    ddr_addr            , 
    inout      [DX_NUM   -1:0]    ddr_dqs_p           , 
    inout      [DX_NUM   -1:0]    ddr_dqs_n           , 
    inout      [DX_NUM*8 -1:0]    ddr_dq              , 
    inout      [DX_NUM   -1:0]    ddr_dm              , 
`endif

    output                        ctl_ram_rst_n       ,
    output                        ctl_ram_cke         ,

    output                        dfi_clk             , 
    output                        pll_locked          , 
    output                        ddrphy_rst_n        ,
    output                        ddr_init_cal_done   , 
    output              [ 7:0]    ddr_init_cal_err    , 
    output              [ 7:0]    ddr_init_cal_step   , 

    input  [MC_ADDR_WIDTH-1:0]    paxi_awaddr         , 
    input                         paxi_awvalid        , 
    output                        paxi_awready        , 

    input  [MC_DATA_WIDTH-1:0]    paxi_wdata          , 
    input  [MC_MASK_WIDTH-1:0]    paxi_wstrb          , 
    input                         paxi_wvalid         , 
    input                         paxi_wlast          , 
    output                        paxi_wready         , 

    output [              1:0]    paxi_bresp          , 
    output                        paxi_bvalid         , 
    input                         paxi_bready         , 

    input  [MC_ADDR_WIDTH-1:0]    paxi_araddr         , 
    input                         paxi_arvalid        , 
    output                        paxi_arready        , 

    output [MC_DATA_WIDTH-1:0]    paxi_rdata          , 
    output                        paxi_rlast          , 
    output                        paxi_rvalid         , 
    input                         paxi_rready         , 

    output              [ 3:0]    user_clk            , 
    output                        apb_clk             , 
    output                        mcu_busy            , 
    input                         user_update         , 
    input               [ 7:0]    user_ram_addr       , 
    input                         user_ram_wr_en      , 
    input                         user_ram_rd_en      , 
    input               [31:0]    user_ram_wr_data    , 
    output              [31:0]    user_ram_rd_data    , 

    input                         uart_rxd            , 
    output                        uart_txd            , 

    input                         pzq_cal_done_i      ,
    output                        pzq_cal_done_o

);

localparam USR_DX_NUM = (MC_ECC == "OFF") ? DX_NUM : DX_NUM - 1;

wire                       ddrphy_rdy        ;

wire   [MC_DATA_WIDTH-1:0] paxi_rdata_b      ;
wire   [MC_DATA_WIDTH-1:0] paxi_wdata_b      ;
wire   [MC_MASK_WIDTH-1:0] paxi_wstrb_b      ;

wire   [         4-1:0]    dfi_reset_n       ;
wire   [BITS_CKE*4-1:0]    dfi_cke           ;
wire   [BITS_CS *4-1:0]    dfi_cs_n          ;
wire   [BITS_ODT*4-1:0]    dfi_odt           ;
wire   [         4-1:0]    dfi_act_n         ;
wire   [         4-1:0]    dfi_ras_n         ;
wire   [         4-1:0]    dfi_cas_n         ;
wire   [         4-1:0]    dfi_we_n          ;
wire   [BITS_BG *4-1:0]    dfi_bg            ;
wire   [BITS_BA *4-1:0]    dfi_bank          ;
wire   [BITS_ADR*4-1:0]    dfi_address       ;
wire   [DX_NUM  *4-1:0]    dfi_wrdata_en     ;
wire   [DX_NUM*8*8-1:0]    dfi_wrdata        ;
wire   [DX_NUM  *8-1:0]    dfi_wrdata_mask   ;
wire   [DX_NUM  *4-1:0]    dfi_rddata_en     ;
wire   [DX_NUM  *4-1:0]    dfi_rddata_valid  ;
wire   [DX_NUM*8*8-1:0]    dfi_rddata        ;

wire                       dhi_cmd_vld_p0    ;
wire                       dhi_cmd_vld_p1    ;
wire                       dhi_cmd_vld_p2    ;
wire                       dhi_cmd_vld_p3    ;
wire   [        32-1:0]    dhi_cmd_code_p0   ;
wire   [        32-1:0]    dhi_cmd_code_p1   ;
wire   [        32-1:0]    dhi_cmd_code_p2   ;
wire   [        32-1:0]    dhi_cmd_code_p3   ;
wire   [DX_NUM    -1:0]    dhi_rdata_vld     ;
wire   [DX_NUM*8*8-1:0]    dhi_rdata         ;
wire                       dhi_wdata_en      ;
wire   [DX_NUM*8*8-1:0]    dhi_wdata         ;
wire   [DX_NUM*8  -1:0]    dhi_wmask         ; 

ph1_ddrphy_wrapper u_ddr_phy (

    .sys_clk               ( sys_clk           ),
    .sys_rst_n             ( sys_rst_n         ),

    .pll_locked            ( pll_locked        ),
    .ddrphy_rst_n          ( ddrphy_rst_n      ),
    .ddr_init_cal_done     ( ddr_init_cal_done ),
    .ddr_init_cal_err      ( ddr_init_cal_err  ),
    .ddr_init_cal_step     ( ddr_init_cal_step ),

    .dfi_clk               ( dfi_clk           ),
    .dfi_reset_n           ( dfi_reset_n       ),
    .dfi_cke               ( dfi_cke           ),
    .dfi_cs_n              ( dfi_cs_n          ),
    .dfi_odt               ( dfi_odt           ),
`ifdef MC0_DRAM_DDR4
    .dfi_act_n             ( dfi_act_n         ),
`endif
    .dfi_ras_n             ( dfi_ras_n         ),
    .dfi_cas_n             ( dfi_cas_n         ),
    .dfi_we_n              ( dfi_we_n          ),
`ifdef MC0_DRAM_DDR4
    .dfi_bg                ( dfi_bg            ),
`endif
    .dfi_bank              ( dfi_bank          ),
    .dfi_address           ( dfi_address       ),
    .dfi_wrdata_en         ( dfi_wrdata_en     ),
    .dfi_wrdata            ( dfi_wrdata        ),
    .dfi_wrdata_mask       ( dfi_wrdata_mask   ),
    .dfi_rddata_en         ( dfi_rddata_en     ),
    .dfi_rddata_valid      ( dfi_rddata_valid  ),
    .dfi_rddata            ( dfi_rddata        ),

    .dfi_ctrlupd_req       ( 2'b00             ),
    .dfi_phyupd_ack        ( 2'b00             ),

`ifdef MC0_DRAM_DDR4
    .ddr_reset_n           ( ddr_reset_n       ),
    .ddr_ck_t              ( ddr_ck_t          ),
    .ddr_ck_c              ( ddr_ck_c          ),
    .ddr_cke               ( ddr_cke           ),
    .ddr_odt               ( ddr_odt           ),
    .ddr_cs_n              ( ddr_cs_n          ),
    .ddr_act_n             ( ddr_act_n         ),
    .ddr_ba                ( ddr_ba            ),
    .ddr_bg                ( ddr_bg            ),
    .ddr_addr              ( ddr_addr          ),
    .ddr_dqs_t             ( ddr_dqs_t         ),
    .ddr_dqs_c             ( ddr_dqs_c         ),
    .ddr_dq                ( ddr_dq            ),
    .ddr_dm_dbi            ( ddr_dm_n          ),
`else
    .ddr_reset_n           ( ddr_reset_n       ),
    .ddr_ck_p              ( ddr_ck_p          ),
    .ddr_ck_n              ( ddr_ck_n          ),
    .ddr_cke               ( ddr_cke           ),
    .ddr_odt               ( ddr_odt           ),
    .ddr_cs_n              ( ddr_cs_n          ),
    .ddr_ras_n             ( ddr_ras_n         ),
    .ddr_cas_n             ( ddr_cas_n         ),
    .ddr_we_n              ( ddr_we_n          ),
    .ddr_ba                ( ddr_ba            ),
    .ddr_addr              ( ddr_addr          ),
    .ddr_dqs_p             ( ddr_dqs_p         ),
    .ddr_dqs_n             ( ddr_dqs_n         ),
    .ddr_dq                ( ddr_dq            ),
    .ddr_dm                ( ddr_dm            ),
`endif

    .ctl_ram_rst_n         ( ctl_ram_rst_n     ),
    .ctl_ram_cke           ( ctl_ram_cke       ),

    .user_clk              ( user_clk          ),
    .apb_clk               ( apb_clk           ),
    .mcu_busy              ( mcu_busy          ),
    .user_update           ( user_update       ),
    .user_ram_addr         ( user_ram_addr     ),
    .user_ram_wr_en        ( user_ram_wr_en    ),
    .user_ram_rd_en        ( user_ram_rd_en    ),
    .user_ram_wr_data      ( user_ram_wr_data  ),
    .user_ram_rd_data      ( user_ram_rd_data  ),

    .pzq_cal_done_i        ( pzq_cal_done_i    ),
    .pzq_cal_done_o        ( pzq_cal_done_o    ),

    .uart_rxd              ( uart_rxd          ),
    .uart_txd              ( uart_txd          )
);

assign ddrphy_rdy = ddr_init_cal_done;

mc0_alc_mc_top #(

    .DRAM_TYPE     ( DRAM_TYPE     ),
    .DX_NUM        ( DX_NUM        ),
    .RK_NUM        ( RK_NUM        ),
    .tCK           ( tCK           ),
    .CL            ( CL            ),
    .CWL           ( CWL           ),

    .BG_WIDTH      ( BITS_BG       ),
    .BA_WIDTH      ( BITS_BA       ),
    .ROW_WIDTH     ( BITS_ROW      ),
    .COL_WIDTH     ( BITS_COL      ),

    .MC_ECC        ( MC_ECC        ),
    .MC_ADDR_MAP   ( MC_ADDR_MAP   ),
    .MC_REORDER    ( MC_REORDER    )
) u_ddr_mc (

    .clk                ( dfi_clk            ),
    .rst                (~ddrphy_rst_n       ),
    .ddrphy_rdy         ( ddrphy_rdy         ),

    .paxi_awaddr        ( paxi_awaddr        ),
    .paxi_awvalid       ( paxi_awvalid       ),
    .paxi_awready       ( paxi_awready       ),

    .paxi_wdata         ( paxi_wdata_b       ),
    .paxi_wstrb         ( paxi_wstrb_b       ),
    .paxi_wvalid        ( paxi_wvalid        ),
    .paxi_wlast         ( paxi_wlast         ),
    .paxi_wready        ( paxi_wready        ),

    .paxi_bresp         ( paxi_bresp         ),
    .paxi_bvalid        ( paxi_bvalid        ),
    .paxi_bready        ( paxi_bready        ),

    .paxi_araddr        ( paxi_araddr        ),
    .paxi_arvalid       ( paxi_arvalid       ),
    .paxi_arready       ( paxi_arready       ),

    .paxi_rdata         ( paxi_rdata_b       ),
    .paxi_rlast         ( paxi_rlast         ),
    .paxi_rvalid        ( paxi_rvalid        ),
    .paxi_rready        ( paxi_rready        ),

    .dhi_cmd_vld_p0     ( dhi_cmd_vld_p0     ),
    .dhi_cmd_vld_p1     ( dhi_cmd_vld_p1     ),
    .dhi_cmd_vld_p2     ( dhi_cmd_vld_p2     ),
    .dhi_cmd_vld_p3     ( dhi_cmd_vld_p3     ),
    .dhi_cmd_code_p0    ( dhi_cmd_code_p0    ),
    .dhi_cmd_code_p1    ( dhi_cmd_code_p1    ),
    .dhi_cmd_code_p2    ( dhi_cmd_code_p2    ),
    .dhi_cmd_code_p3    ( dhi_cmd_code_p3    ),
    .dhi_rdata_vld      (&dhi_rdata_vld      ),
    .dhi_rdata          ( dhi_rdata          ),
    .dhi_wdata_en       ( dhi_wdata_en       ),
    .dhi_wdata          ( dhi_wdata          ),
    .dhi_wmask          ( dhi_wmask          )
);

genvar n, p;
generate
for (n = 0; n <= USR_DX_NUM-1; n = n+1) begin: nIdx
    for (p = 0; p <= 7; p = p+1) begin: pIdx
        assign paxi_wdata_b[n*64+p*8 +: 8] = paxi_wdata[p*(USR_DX_NUM*8)+n*8 +: 8];
        assign paxi_wstrb_b[n* 8+p*1 +: 1] = paxi_wstrb[p*(USR_DX_NUM*1)+n*1 +: 1];

        assign paxi_rdata[p*(USR_DX_NUM*8)+n*8 +: 8] = paxi_rdata_b[n*64+p*8 +: 8];
    end
end
endgenerate

ph1_ddrphy_dfi_adapter #(
    .DRAM_TYPE  ( DRAM_TYPE ),
    .DX_NUM     ( DX_NUM    ),
    .RK_NUM     ( RK_NUM    ),
    .CL         ( CL        ),
    .CWL        ( CWL       ),
    .BITS_CS    ( BITS_CS   ),
    .BITS_CKE   ( BITS_CKE  ),
    .BITS_ODT   ( BITS_ODT  ),
    .BITS_BA    ( BITS_BA   ),
    .BITS_BG    ( BITS_BG   ),
    .BITS_ROW   ( BITS_ROW  ),
    .BITS_COL   ( BITS_COL  ),
    .BITS_ADR   ( BITS_ADR  ) 
) u_dfi_adapter (

    .clk                ( dfi_clk            ),
    .rst                (~ddrphy_rst_n       ),

    .dhi_cmd_vld_p0     ( dhi_cmd_vld_p0     ),
    .dhi_cmd_vld_p1     ( dhi_cmd_vld_p1     ),
    .dhi_cmd_vld_p2     ( dhi_cmd_vld_p2     ),
    .dhi_cmd_vld_p3     ( dhi_cmd_vld_p3     ),
    .dhi_cmd_code_p0    ( dhi_cmd_code_p0    ),
    .dhi_cmd_code_p1    ( dhi_cmd_code_p1    ),
    .dhi_cmd_code_p2    ( dhi_cmd_code_p2    ),
    .dhi_cmd_code_p3    ( dhi_cmd_code_p3    ),
    .dhi_rdata_vld      ( dhi_rdata_vld      ),
    .dhi_rdata          ( dhi_rdata          ),
    .dhi_wdata_en       ( dhi_wdata_en       ),
    .dhi_wdata          ( dhi_wdata          ),
    .dhi_wmask          ( dhi_wmask          ),

    .dfi_reset_n        ( dfi_reset_n        ),
    .dfi_cke            ( dfi_cke            ),
    .dfi_cs_n           ( dfi_cs_n           ),
    .dfi_odt            ( dfi_odt            ),
    .dfi_act_n          ( dfi_act_n          ),
    .dfi_ras_n          ( dfi_ras_n          ),
    .dfi_cas_n          ( dfi_cas_n          ),
    .dfi_we_n           ( dfi_we_n           ),
`ifdef MC0_DRAM_DDR4
    .dfi_bg             ( dfi_bg             ),
`endif
    .dfi_bank           ( dfi_bank           ),
    .dfi_address        ( dfi_address        ),
    .dfi_wrdata_en      ( dfi_wrdata_en      ),
    .dfi_wrdata         ( dfi_wrdata         ),
    .dfi_wrdata_mask    ( dfi_wrdata_mask    ),
    .dfi_rddata_en      ( dfi_rddata_en      ),
    .dfi_rddata_valid   ( dfi_rddata_valid   ),
    .dfi_rddata         ( dfi_rddata         ) 
);

endmodule

`timescale 1ps/1ps

module mc0_axi2mc_top #(
    parameter integer AXI_ID_WIDTH    = 4,
    parameter integer AXI_ADDR_WIDTH  = 30,
    parameter integer AXI_DATA_WIDTH  = 512,
    parameter integer AXI_MASK_WIDTH  = AXI_DATA_WIDTH/8,
    parameter integer MC_ADDR_WIDTH   = AXI_ADDR_WIDTH-3,
    parameter integer MC_DATA_WIDTH   = AXI_DATA_WIDTH,
    parameter integer MC_MASK_WIDTH   = AXI_MASK_WIDTH
)(

    input  wire                       axi_aclk        ,
    input  wire                       axi_aresetn     ,

    input  wire [AXI_ID_WIDTH  -1:0]  axi_awid        ,
    input  wire [AXI_ADDR_WIDTH-1:0]  axi_awaddr      ,
    input  wire [7:0]                 axi_awlen       ,
    input  wire [2:0]                 axi_awsize      ,
    input  wire [1:0]                 axi_awburst     ,
    input  wire [0:0]                 axi_awlock      ,
    input  wire [3:0]                 axi_awcache     ,
    input  wire [2:0]                 axi_awprot      ,
    input  wire [3:0]                 axi_awqos       ,
    input  wire                       axi_awvalid     ,
    output wire                       axi_awready     ,

    input  wire [AXI_DATA_WIDTH-1:0]  axi_wdata       ,
    input  wire [AXI_MASK_WIDTH-1:0]  axi_wstrb       ,
    input  wire                       axi_wlast       ,
    input  wire                       axi_wvalid      ,
    output wire                       axi_wready      ,

    output wire [AXI_ID_WIDTH  -1:0]  axi_bid         ,
    output wire [1:0]                 axi_bresp       ,
    output wire                       axi_bvalid      ,
    input  wire                       axi_bready      ,

    input  wire [AXI_ID_WIDTH  -1:0]  axi_arid        ,
    input  wire [AXI_ADDR_WIDTH-1:0]  axi_araddr      ,
    input  wire [7:0]                 axi_arlen       ,
    input  wire [2:0]                 axi_arsize      ,
    input  wire [1:0]                 axi_arburst     ,
    input  wire [0:0]                 axi_arlock      ,
    input  wire [3:0]                 axi_arcache     ,
    input  wire [2:0]                 axi_arprot      ,
    input  wire [3:0]                 axi_arqos       ,
    input  wire                       axi_arvalid     ,
    output wire                       axi_arready     ,

    output wire [AXI_ID_WIDTH  -1:0]  axi_rid         ,
    output wire [AXI_DATA_WIDTH-1:0]  axi_rdata       ,
    output wire [1:0]                 axi_rresp       ,
    output wire                       axi_rlast       ,
    output wire                       axi_rvalid      ,
    input  wire                       axi_rready      ,

    input  wire                       ddrphy_rdy      ,

    output  [MC_ADDR_WIDTH-1:0]  paxi_awaddr         , 
    output                       paxi_awvalid        , 
    input                        paxi_awready        , 

    output  [MC_DATA_WIDTH-1:0]  paxi_wdata          , 
    output  [MC_MASK_WIDTH-1:0]  paxi_wstrb          , 
    output                       paxi_wvalid         , 
    output                       paxi_wlast          , 
    input                        paxi_wready         , 

    input  [               1:0]  paxi_bresp          , 
    input                        paxi_bvalid         , 
    output                       paxi_bready         , 

    output  [MC_ADDR_WIDTH-1:0]  paxi_araddr         , 
    output                       paxi_arvalid        , 
    input                        paxi_arready        , 

    input   [MC_DATA_WIDTH-1:0]  paxi_rdata          , 
    input                        paxi_rlast          , 
    input                        paxi_rvalid         , 
    output                       paxi_rready
);

`pragma protect begin_protected
`pragma protect version = 1
`pragma protect encrypt_agent = "Anlogic"
`pragma protect encrypt_agent_info = "Anlogic Encryption Tool anlogic_2019"
`pragma protect key_keyowner = "Anlogic", key_keyname = "anlogic-rsa-009"
`pragma protect key_method = "rsa"
`pragma protect encoding = (enctype = "BASE64", line_length = 64, bytes = 128)
`pragma protect key_block
MbYt+dkADKPBI4UZ4xwBiw1cfSseg5IkS84Z9X/EXlpDfRApnM6qAexgq9qp2OjX
n4iGZJgW2mdFbvPG5AkRKzOivGzPl+6kItt1v8MM74zBQtgKOrm8OyKBDPuedwsP
q8wQk5W+3Rzvpru/yo2eIFBPDrxCbpzIMFP8qTz6+EQ=
`pragma protect key_keyowner = "Anlogic", key_keyname = "anlogic-rsa-009"
`pragma protect key_method = "rsa"
`pragma protect encoding = (enctype = "BASE64", line_length = 64, bytes = 128)
`pragma protect key_block
MbYt+dkADKPBI4UZ4xwBiw1cfSseg5IkS84Z9X/EXlpDfRApnM6qAexgq9qp2OjX
n4iGZJgW2mdFbvPG5AkRKzOivGzPl+6kItt1v8MM74zBQtgKOrm8OyKBDPuedwsP
q8wQk5W+3Rzvpru/yo2eIFBPDrxCbpzIMFP8qTz6+EQ=
`pragma protect key_keyowner = "Cadence Design Systems.", key_keyname = "CDS_RSA_KEY_VER_1"
`pragma protect key_method = "rsa"
`pragma protect encoding = (enctype = "BASE64", line_length = 64, bytes = 256)
`pragma protect key_block
HB2+wERhdl4moPYyyPsvqCgr3JjD2Pw0LcHnH6y0W3WWhQ1QEsOwud6MTeyPgH+/
MSA1s++MgRHlNT+3MidnzjT72gqkpPWD8wtZQ2r2+4lr7SfB4i/jrQh2EAqWnh+K
FXZJJyKu7/FRqqrhsQuQ80JmJnGa6MoYV+KEDrFkxGZlIKRqIJQXHW6vHWofH7Ti
g0QPysvsaIdvdO/3igNmIA+w8QZ09NxJWIMNI0NadJrJjYzuyLEb/fv4WVgb1+az
bW3uxOR0WDP+UVYHgnRTfMj/+SUCncZJ9Jv7PfmhFcTF0SQmgJ4ZXk31/7uq+Tdn
b2HNU4PQqLMmJAujsahnSQ==
`pragma protect key_keyowner = "Mentor Graphics Corporation", key_keyname = "MGC-VERIF-SIM-RSA-1"
`pragma protect key_method = "rsa"
`pragma protect encoding = (enctype = "BASE64", line_length = 64, bytes = 128)
`pragma protect key_block
H8E8eTp25atpBIF4zHFlkgb+of7C3gtMa5setgkK3yKKpiFxcs50WWeLenBTeuFR
NBnDK2vMFXS73/5/8KDY8KEkFpa1ox2rDMqxGkjx2OWqc9lJo/SILDRG1JPQkAmK
0NWts43Eko6yxC0fO86KRsrCNx5FjB6DFL+VOz64jzw=
`pragma protect key_keyowner = "Mentor Graphics Corporation", key_keyname = "MGC-VERIF-SIM-RSA-2"
`pragma protect key_method = "rsa"
`pragma protect encoding = (enctype = "BASE64", line_length = 64, bytes = 256)
`pragma protect key_block
Irvef75q4gRrvPOU4Iu3ZgDvwAuAZQqEHnR8WsyL6/I3ccZSXvIQa7qyIEsRZ5VV
sOmmvc/vIW97EbWQBoIsPmpI+GwndAnKqWDU91V
IRCyMT48Pdo8bPDEJCucfgSZaYujz8rS51r1DOpjPp6ljv3w5ZFC7i3FTU0HTLI3
vIPsUQQOUGoLqXmxJZhUWtlgbJWW0Jkd8vVdbtytzqcbUJqdhNRwg0kXrVh0gMoZ
QUK+q24TDZQiyFai8771UW30+Rr1K0zmuOQg22M4RHAnoXVumotpjKf+eDl+XC/n
/u3VdbHjKSXZ5QSsMxp5SQ==
`pragma protect key_keyowner = "Synopsys", key_keyname = "SNPS-VCS-RSA-1"
`pragma protect key_method = "rsa"
`pragma protect encoding = (enctype = "BASE64", line_length = 64, bytes = 128)
`pragma protect key_block
KzuoVWHjorafF3xV8vftccEcGgKpX0cmEjCjetskoZdF67QZRYdwDs3Gk+xFuZ7m
wjWFdsrkIz0yEEU4oDYRDJFTu3Ppx5Nymi/4QuMywGG+y5Vk1Bd+37zhelUC6vxc
XQHVCikAIo5MjlDehcR5XgIoQHrlCpqgXk+W9izNrh8=
`pragma protect key_keyowner = "Synopsys", key_keyname = "SNPS-VCS-RSA-2"
`pragma protect key_method = "rsa"
`pragma protect encoding = (enctype = "BASE64", line_length = 64, bytes = 128)
`pragma protect key_block
T8uS7TEitdacv7H+aj1ddF2fP5xBA4JJT86FXWAaLGwoQZK9GH3rsDo0RBUEHR6c
hXmddz2akRpewgtssRQb1XvtSR57MbXa06CXGLRWcqYSEuNSb586sCFixRE9DQ1j
zuXVd4EskEDIbQCJcoIvOORo05jacXfnvNinPFBwa9o=
`pragma protect data_method = "AES128-CBC"
`pragma protect encoding = (enctype = "BASE64", line_length = 64, bytes = 107872)
`pragma protect data_block
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
x4o3Qo7uOWOrfIgrSNG779Azn2oubH
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
UD05v1XN+J4I2l9f
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
w9iQrHtTI6oDWZrPDrbe0MGajw
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
SLzc0TB5XZa
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
cMP7I+QNfuIpZmPGEbYm
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
0ytoD/Zno38TUAfkDbHm
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
BlW1g/3YuXHfDWl7f5p0ARJB
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
jrfe6ErtPIyiD861CH2Yi
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
F
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
gG1rdRKafOTiiuqsBRn+GOy++b+OlM5+b+eviGu
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
HDidRGLF
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
P/HA7
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
PY
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
wT7m6tKUWzJaL
IcWKrqJFMbYmN8MIECtIThPdgyNtL0a4Ga2GyImKjq5Tl3yWGIpI9E2b4wuLWjTL
AgrebNksQUF7dJtMtm3n6JuohdZ7xLK3Fv7CUK6lWusV6NcPAUkzBwOC4GLTp8gm
lrIOHIoDSKezxnog3QdtHsFMu+EJchyVHudQgn/5epS+8nO3e/yfXWlF7cPA8yDi
laERpXQ4U0riWkrGrRhKvUnvcClrhBMxHD1f8cVGjbxLYpVsPj+EI7CvTkoSemNG
IQAOREDj0py4mrXC+5m2N5Weph+69q1Uh9WxHWujv7Sdi3GaiD6wyFfaUNyBwxfE
4bQi7E6rBIMKShMXnG4OYETXdq+X3h1RyTdwZOzthiPrfW2yv6s6ofKE1ZMrK+F3
Kmkj5yhXPe8ZNKfnt66tG4ra3nGfPZHNUwS3r4xKl3DtcpaoSzigncOM+7+YhY8Z
9ySJKKOr1+GIj0xGTBU+dblWSWjj/leW2DS8MXcea+6bq5irJr5lrAOO0JJSRpJa
yjIP+ejPUKe3p0RAnp1vQURAk97q87p360P5SqiJed8Lzmkz4P+KGmcOp4w8zPWq
txqIB+D1gEd63vDVdIILXQ8jkcWyoEAYW46aPc16fhSP38kG82EmlZ6yaxvJ9ily
XG1m5q3OqqFdfO+wKSdJmcm3bSbe6efPFmhBjM6PjNTYIdQorqBuXLlSGnijX5WV
SpXsZNWqn5M92Hia0GS8gXtxln+Q9uDUmf4jMNwPC429Ci7kT+naSNI3pK8qNBS9
A65bDiLlZ6Y5YKiZ+uc/GWeENZgxevk6ZYcZg2iGraed6J4PKNsBXS94NCmKZ33I
05l0Cs7VdEpG8VbGk9c2rZfJ2tiS6urR+5H/VMK4r1Atp/9FOkRffdlxiTJWo80a
Zmaa3QzlcAeb9QGcEUpBcmi/auv1lk36L8oRB/wjfJVbfwwxmoM+b0a3rGMsWrx9
VLR1WZBxXxgyantgP9sZrHpFeXnTLBPBA4Qp5P+DLTDrl0PMNZ6KxdcnQv5A3Aye
GyMtlisGYzSzaRLixoTf/e++Qm1ZwnFRXATBAqPs76ytEx4Wp+eD2wgVYljLuf0O
Q3bgLUmiBzZ1MO/nNrO2LwBXDLFS5GDm5EAazSemrK5d9GTeNacevZz0Jt7g5T4z
u1Gd1rrdTFeF9XhzRu11IpKT9fPJvxW+ZZTXZMET5Qsb0NgxZ6VHFkSRE3JsGPlZ
dP1lOUZR4Y2RtopzOJY4fe748W3KhrT3VPGoDmNomYeenNddwb4DhwDvr0HPsDCv
Gb9Iv4cgWwYBPv/yPdCF2CssN/LjQbK/bJ8+9r7YtshFzM4roarB1cAqD/mwwWiE
pRLLNZMzPu3+DET+uSZ9s2SKzkCTb3nsgfuc0YP7xh9Yikaa34AFcy2KdipMg/m8
+ShIE1bUkdyEy3k71INEHePkedjF8D5IowtAcJstc91ko1ywXHXpLgi2K9y+6KIy
xt0QH9XRVnPOHaBmVmeNwu2ssIkoaqpnLuxslRFzXxf3PSi+iVyhFgCBWb46JE1N
NvPqotaxkNDazmWOb7d1Y8iGwFj3c/Y410dWJou8diTIwGA30s9OhQVwJEoUKto8
6xObQgc9cNYQP43Wt/LU2WDYmCcMMnLWS7G8naYc7YXUhGt69XRk0uA0zfujCQYx
wZtIh+NKTDystjc4FYUepNggVOC5iHgvDtGxRSIMmzwQXcenLaOOZzhkipRFfG8W
7firOIrXmT6TUjqLn+GEWiJLP2cvSv49r
iL69WUMx6wGtZY5kDhIXZJgP2faWPmaOnVLefnmy/Q7tW44xxk7WSQjyrKmb6zAX
AXePdDIOJzoV8glIsEC12gcviKPjtSEBVOzPe/CvqwVyNpI+Q8jTSmZXdYISqbRZ
uJZej45DPDY3buts+B9lQpJXvxOn3fDu5OFk9WAnDh9oCBAmN4RldgYqPsHWOdMg
Z9evSq85juc4+DcThgTDLbEy+EXIce/mFG+qGlLn5LG9Rd0Dx7XgAY/FzzrAdcNA
tCMf/PardeawXjQP8B6sR2qGFUyKg0MHfnsWH0dcG1vMkHWu02163gSbBrzaDwwd
aK3loXzJHZQshdmLseBAlqOP+QpMLrGH7xAM6L1Eka+cJIwIsUkEPBzW3XqNMbJT
qCg/VMTg/gt4fhz3z4/N1e3a/32P+3Zl3szYmH2uX1ySxtVBMr1Zfw5oMzs7WuLk
eZw3rQpQduwRDvsyzTilol8S6wk3HFxWzUnoVL8bwM7vHTdxr/9edOE32mPQqYRa
CJjhLrFHkHZzs4gtgePNOs+vWlGIAY2un/mME3X2FjSIgvfx+Br8x3BDCXxbZThx
eWjZ5RthiEFwVsz4uwaKJxzeZ+djtgfm79OXsiRBCvrAWHnrg6cWXzvf7K6DqVM1
9CCwB6QYraoHTs6gMKnzqZPwXW5SDu/ERvRamwzTTrIbYH7ZIdtgTsqeItUvLkUT
qpQ2dPhRyx24T7l95EWXhY37A3th4BKXyHgLvudpaR1YwtUdoKTT4Vpl4iCULef7
DuZoxPGscGnVXU1Kme88kIBdolOy0kEPM/YX02gPJ7xziiXCpntpoZwTUFoHkT/o
fKXRA9CxZGHuuus3hDZxR8urDFEyd2db+5/WW2u8yAzwFKMCX71uOn5BNnt91OsA
oaapKpP64QvbAIHPL1eOfPSWODTuYORGSj1RSlqS3UdrIT/VGhMOOM4Ojz7HgPXV
BN+mm1ZIDO1wyCrYqHixSj0Mdm2BB4MSUDdk5omCGjcc8y+nZeDt6JjGLbfX2iuO
Zb+BvyKlr2Nuo3XZiodeDQk9SO0/s/UObk3mOcT66n9NKWJKD5XpPvhW1BdP8Pbk
ArVydtmAw6aDcqsnR3YC9fZ+mg02E5LlSHeRE87VL/q7Suz+hqRs4dIr9Vcga/XV
M7cI1Qo49sHoOWKcSbH/29CX42aln/p8Y66lKWM70VJ4/b9Eekg90LCSmb0FzwhY
TvJmL3aRg4bFLsooRr+/dqRI7JlGnAldm24u97IX9xo9uc/r4NToqm+SKtg/QwGy
rWnjSA1ZOFbDoWjKCf+qJAOETPvcJnb9j2gAqvyYdzqDGc4IBNTFKYMvCoYI4yZn
yILD2MtGMdfShDSdBtjK/xPf+LxKoDtKBFkpokLf9QHHpkXG5YNrvln3xc5XkT0u
FAs/qzO392uadIryXLpZWc1+YRxHAt/oyRzsC6FL9AIijn9X1lrsuaWvxTHPnODf
MHFK/eUFrTQJ6KBOEKDNZ2oaWaNv/1s2E+34nAk1UvWb1XXNR6Sw8Qu1hSXCe7hX
zm3gFmsY4H7RAnXWnWSLUVxZ8xTQaxlpZurEGwN18X9h5DpBGGihO/QIMBQoSMXW
UdSpfzyF9+GvK/CArLgxoB/4U9uXSreZe7BcC/2lCof270YReEI1eOrHuf8hCgJS
l5UOCi2jB7S/OzYexpiHq5ljaB4cQ9x4L2U0HVZfC4PMTbpz50vtEGbE3sqod2FE
X6VkuuKJ46H6Dr7kSevYKkw/CEtd5ZV5Tgdz9npJLMbKY1AXiK6xS+vj4Q5O0qZS
ItW305hbmsoO6Rg+FTY2gzyWpD/3TWZGImyT8FkvR68CHPS7XTZWpOJzNLF2LXTD
B/GbwsBbh/IcKL9BbPLNU+46NKkpakf7qurxEGSwBnF2WbH1KrZJbD6ibwuO62t+
8Z6UUWRCOiLyImQrZUD2n5DbtmRufyZMlXNuVeOu0IgS2V9cR0NKKn7bHqWU6m2R
zeY+22qsG5ODGapptu6fablOCfegfcHAKPmuZg133zYze4IVPNMi9FQQg6YySxf6
HYzjhPUcecxBIMfB2UYmGovJWkU
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
bOM/6uny4QU
+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
9xaO8WE6KT
Um5jH0/puklDyHZYWRKLGrMJceQP5zUK1DZCM4G7Gwh9wjtVMc/Nqoq5XbHGv7hg
l0tVuQsC9yuVbBp1g092yQHwbatr0jJlYmEL/tIGpNK5rWO1BdLAP6jwJ58qae3a
IS3yuWfcz3bMH/lx/us1A+KWcCmXPH9gEaQVqii9zk4rGsdS0RzcqlHu5iMDfDyk
DcpXHMRzVY+v1UCOqrd2NqAjlVOjCYIv18iZBORzLL+ZnFYZSLVfKUGA6uivkq3/
E9LEx8saXbMeFq7STTdSOE6p+BbyXLTUodhX6DtqrB1ip2NlbiYJP/kCSdpOT/vs
vYeEWOLDR8Yfha5OX1V36qe/Zjh3eJiAvGyslGtDdd0SIw8UOR6ahcRhVxXWPxZ6
0Fpmtrmr8+P/UqpnMXGY4tMohp4JRY8HU4Khbqjjr5oNmgbdgp/zl64iWcG2Q/XH
TIP4eS1LnEivTVU0n2/9zccIvCJuEtz5/C7894JJT+FmA45DkjZ6Bvdp7Ij1dzit
VI22opw3r4+VmsqGeYkGrRnNeoIw0kt++xhNIuzuY04sy0zga2bCZoBuqEFGmNf3
CYyBq4g5AWfuoIj+Q91NVvVefJI7g9hddx6ZgnxhR5mMtITZ5O6jMGozixr4k+RT
jC8RbHThoeUE6LskEA+j8kQ/v+dvaM3kBCGjVJ7Ch6M/crpF2lU6oEiZk+93ZAtZ
+FkZ47h7JjGEBBRY24NhYLOQDFH1Vw8Zz1OtV9axVap2VOPq4ik321Pqs2eXwga9
270uUzVGZpYk36HJHYZo8j7UnykfbvOP53bIskAxiB19KrQA47VPVs2xMQjrBIr4
ptlE04EHq3G/yvPeQGkZAR+n9LQNcu/gEsnAdkQs0MH7QRHDYuWVvyu0ow3v4I+1
AbwIWQxCydI2ntULdlQSYFPEuJ86YYdZq/PyF2JNUNuE+PYxz8hnYABkY56G7wMv
X
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
YbkgAcKnjyS5w2T2kfHn6
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
Ybq1oh081+lkGUU2IP2e4g==
`pragma protect end_protected

`timescale 1ps/1ps

module mc0_alc_mc_top #(
    parameter DRAM_TYPE            = "DDR3"  ,
    parameter DX_NUM               = 2       ,
    parameter RK_NUM               = 1       ,
    parameter BG_WIDTH             = 0       ,
    parameter BA_WIDTH             = 3       ,
    parameter ROW_WIDTH            = 13      ,
    parameter COL_WIDTH            = 10      ,

    parameter tCK                  = 1876    ,
    parameter CL                   = 11      ,
    parameter CWL                  = 9       ,

    parameter MC_ADDR_MAP          = "ROW_COL_BANK",
    parameter MC_REORDER           = "STRICT",
    parameter MC_ECC               = "ON"    ,

    parameter MC_ADDR_WIDTH        = (RK_NUM == 2) + BG_WIDTH + BA_WIDTH + ROW_WIDTH + COL_WIDTH,
    parameter MC_DATA_WIDTH        = (MC_ECC == "ON") ? (DX_NUM-1)*8*8 : DX_NUM*8*8,
    parameter MC_MASK_WIDTH        = (MC_ECC == "ON") ? (DX_NUM-1)*8   : DX_NUM*8  
)(

    input                                  clk                ,
    input                                  rst                ,
    input                                  ddrphy_rdy         ,

    input        [MC_ADDR_WIDTH-1 : 0]     paxi_awaddr        ,
    input                                  paxi_awvalid       ,
    output                                 paxi_awready       ,

    input        [MC_DATA_WIDTH-1 : 0]     paxi_wdata         ,
    input        [MC_MASK_WIDTH-1 : 0]     paxi_wstrb         ,
    input                                  paxi_wvalid        ,
    input                                  paxi_wlast         ,
    output                                 paxi_wready        ,

    output       [              1 : 0]     paxi_bresp         ,
    output                                 paxi_bvalid        ,
    input                                  paxi_bready        ,

    input        [MC_ADDR_WIDTH-1 : 0]     paxi_araddr        ,
    input                                  paxi_arvalid       ,
    output                                 paxi_arready       ,

    output       [MC_DATA_WIDTH-1 : 0]     paxi_rdata         ,
    output                                 paxi_rlast         ,
    output                                 paxi_rvalid        ,
    input                                  paxi_rready        ,

    output                                 dhi_cmd_vld_p0     ,
    output                                 dhi_cmd_vld_p1     ,
    output                                 dhi_cmd_vld_p2     ,
    output                                 dhi_cmd_vld_p3     ,
    output       [           32-1 : 0]     dhi_cmd_code_p0    ,
    output       [           32-1 : 0]     dhi_cmd_code_p1    ,
    output       [           32-1 : 0]     dhi_cmd_code_p2    ,
    output       [           32-1 : 0]     dhi_cmd_code_p3    ,

    input                                  dhi_rdata_vld      ,
    input        [   DX_NUM*8*8-1 : 0]     dhi_rdata          ,

    input                                  dhi_wdata_en       ,
    output       [   DX_NUM*8*8-1 : 0]     dhi_wdata          ,
    output       [   DX_NUM*8  -1 : 0]     dhi_wmask          
);

localparam  ECC_OREG    = 0;

localparam  PHY_DX_NUM  = DX_NUM;
localparam  USR_DX_NUM  = (MC_ECC == "ON") ? (DX_NUM-1) : DX_NUM;

localparam  CS_WIDTH    = 1;
localparam  CKE_WIDTH   = 1;
localparam  ODT_WIDTH   = 1;
localparam  ADDR_WIDTH  = (DRAM_TYPE == "DDR4") ? 17 : ROW_WIDTH;

localparam  DBAW_R      = 5;
localparam  DBAW_W      = 4;

localparam nRTP_min  = 4;
localparam nWTR_min  = 4;
localparam nRRD_min  = 4;
localparam nZQCS_min = 64;
localparam nXS_min   = 5;

localparam real tRTP_min  =  7_500;
localparam real tWTR_min  =  7_500;
localparam real tZQCS_min = 80_000;

`ifdef MC0_DDR3_8G
localparam real tRRD_min  =  7_500;
localparam real tFAW      = 40_000;
`else 
`ifdef MC0_DDR3_X16
localparam real tRRD_min  =  7_500;
localparam real tFAW      = 40_000;
`else 
localparam real tRRD_min  =  6_000;
localparam real tFAW      = 30_000;
`endif
`endif

localparam real tRAS = 35_000;

localparam real tREFI = 7_800_000;
localparam real tWR   = 15_000;

`ifdef MC0_DDR3_512M
localparam real tRFC = 90_000;
`elsif MC0_DDR3_1G
localparam real tRFC = 110_000;
`elsif MC0_DDR3_2G
localparam real tRFC = 160_000;
`elsif MC0_DDR3_4G
localparam real tRFC = 260_000;
`elsif MC0_DDR3_8G
localparam real tRFC = 350_000;
`endif

localparam integer nRCD  = CL;
localparam integer nRP   = CL;
localparam integer nRAS  = $ceil(tRAS /tCK);
localparam integer nRC   = nRP + nRAS; 

localparam integer nCCD  = 4;
localparam integer nRRD  = (nRRD_min  > $ceil(tRRD_min /tCK)) ? nRRD_min  : $ceil(tRRD_min /tCK);
localparam integer nWTR  = (nWTR_min  > $ceil(tWTR_min /tCK)) ? nWTR_min  : $ceil(tWTR_min /tCK);
localparam integer nRTP  = (nRTP_min  > $ceil(tRTP_min /tCK)) ? nRTP_min  : $ceil(tRTP_min /tCK);
localparam integer nWR   = (5         > $ceil(tWR      /tCK)) ? 5         : $ceil(tWR      /tCK);
localparam integer nFAW  = $ceil(tFAW /tCK);
localparam integer nREFI = $ceil(tREFI/tCK);
localparam integer nRFC  = $ceil(tRFC /tCK);

localparam integer nRTW   = CL + nCCD + 2 - CWL; 

`pragma protect begin_protected
`pragma protect version = 1
`pragma protect encrypt_agent = "Anlogic"
`pragma protect encrypt_agent_info = "Anlogic Encryption Tool anlogic_2019"
`pragma protect key_keyowner = "Anlogic", key_keyname = "anlogic-rsa-009"
`pragma protect key_method = "rsa"
`pragma protect encoding = (enctype = "BASE64", line_length = 64, bytes = 128)
`pragma protect key_block
aZ4fnqNdcJX97d209dBlzNVmXiFMNgiQ3Zg3dv+V6Q2ZAw0LgUv6DrVsOSFzDMf7
NxX7wxA6ReElO52H8bs6s/x5BTMqtoHIrOB88AU17ttLUzzZ6eHW2DX+JCSG8Rkq
9Lw1OySuZobo85rTLDdZdLEYSdQjN3LJnBuxfbmniiY=
`pragma protect key_keyowner = "Anlogic", key_keyname = "anlogic-rsa-009"
`pragma protect key_method = "rsa"
`pragma protect encoding = (enctype = "BASE64", line_length = 64, bytes = 128)
`pragma protect key_block
aZ4fnqNdcJX97d209dBlzNVmXiFMNgiQ3Zg3dv+V6Q2ZAw0LgUv6DrVsOSFzDMf7
NxX7wxA6ReElO52H8bs6s/x5BTMqtoHIrOB88AU17ttLUzzZ6eHW2DX+JCSG8Rkq
9Lw1OySuZobo85rTLDdZdLEYSdQjN3LJnBuxfbmniiY=
`pragma protect key_keyowner = "Cadence Design Systems.", key_keyname = "CDS_RSA_KEY_VER_1"
`pragma protect key_method = "rsa"
`pragma protect encoding = (enctype = "BASE64", line_length = 64, bytes = 256)
`pragma protect key_block
jAm/3vV7MWxkBpKUY66u+idinXxoMV/zRoVQLvbL+35BXSKcSqiMn3tmVQXoPvm7
6lQz1gw+aNWK2YPHOoASTHcOjgB64TvZcIbqBmOhLjJvmM2SOpq3N7uO1sPekdvP
SgC0mfD512NzW6lmaxGpKGQvFhXfOr8JgbXonpyzr0I5xpAnQoOzXfkZie5DD3Sk
BHBnt33AcwInQ0Vmcx7JPe+PGs/MIoh1eMjA9hCBzdpskolzHkVc/nuaRRtzJFuz
RwrevloWBRabGjp/x5lKFFOdb9QXXKeFgq+w62b8hQp/9dfc8xTXOQMrqPfEYSgJ
JYRXxgYtMlP6fPpXjQkA3Q==
`pragma protect key_keyowner = "Mentor Graphics Corporation", key_keyname = "MGC-VERIF-SIM-RSA-1"
`pragma protect key_method = "rsa"
`pragma protect encoding = (enctype = "BASE64", line_length = 64, bytes = 128)
`pragma protect key_block
G6uE+HyIiICiXs2dosuGcbxTGV/+0QuVQt77XGHSVewWM1SFtRfqeJeAExTxb0E5
UMe6xiYug4ZyeTMCzwIcNWtwqN1KK+IjzYFbkzr4+d21A94wSgkupvMJWksugtCC
AEsWKPrwlhItwLT1eJtLlcqzaNCjfSS03oE3e3QjVyE=
`pragma protect key_keyowner = "Mentor Graphics Corporation", key_keyname = "MGC-VERIF-SIM-RSA-2"
`pragma protect key_method = "rsa"
`pragma protect encoding = (enctype = "BASE64", line_length = 64, bytes = 256)
`pragma protect key_block
PULg/c3B+EGsqBOFQ0Li9pWNAe7i55gSRuRJlUweOIVYr27hUPblbjKCLYqV4YIw
X2DYeGCQ6aOLrkYR8J+Iuww6xOsofgc6JqWh8jwStjajduYAuqXVcwdBbNJGXTma
OzOJI691JRBQqSCHTtnme3j7Zuin67iubU16+f4C8VNFte6gJnI6yVMd4Jzk9YrF
eW3jaTdE2WgyFBsvPks/JgH23SM3FZyfF9eupHxT5dXdtX0CsqCWIbaTn0UeZaE3
69Yd6LA6xAImIe0ssBf1+PyTQpBDLBzt5Zl7b/9aj0VzRwgAhaOPzvXgBhgKRZSH
R107PAWxlQYOYLIwdWjVOA==
`pragma protect key_keyowner = "Synopsys", key_keyname = "SNPS-VCS-RSA-1"
`pragma protect key_method = "rsa"
`pragma protect encoding = (enctype = "BASE64", line_length = 64, bytes = 128)
`pragma protect key_block
tDX0qBZioj61+3FOrivpwAPdlgudLg22y79eEYVRVxrxeKxhcsGztfTZ6ufJqsV4
k2V4t8PmE+1m3ODE0OKmZVJGYNTvY1scGxJe8QMEUbbqYP6h3duN5Ivc7sxnd2VW
TkvBPttctq9+y0h2poshE3inQSwP96B9BifOPXKTTJQ=
`pragma protect key_keyowner = "Synopsys", key_keyname = "SNPS-VCS-RSA-2"
`pragma protect key_method = "rsa"
`pragma protect encoding = (enctype = "BASE64", line_length = 64, bytes = 128)
`pragma protect key_block
mivvANd9tcVaEVUlN3xilb80njSy5QIKKoWvl88U/tqUMPV1m95IRjXriqkxbDxA
32KHLa2NJ5RkVGzz6THhNptKoqnAxQ1XEGKE91wEX0R/TYwZZKuagXwZR161LfyW
ZnQGZxgcQs5NN+vfj1L81y5r2rNQIDHO1BmquXfEvG8=
`pragma protect data_method = "AES128-CBC"
`pragma protect encoding = (enctype = "BASE64", line_length = 64, bytes = 171344)
`pragma protect data_block
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
/ln3E
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
f+vVneo58xBIV5bzQE0aWKGoAb
wH26UrFyD23EAdynN6/UMd84edkEcA41qOKBXm9t+Fs3V7/2iv2HrCwZguVU0G+W
BLIat5hNoweqaOqHRygYfVQgoXS/yFcHT1QLPyth6J1bao2Vf+Y6xoQKmJ+j/klr
pU9lhLeaNJ9LPCRqGY1OcMY5IMEkLTyzdb2P5HH0H0r6fjmgSwX4f7fmgWVdnt74
unv8r4TwXyWpEVSyBjrg8o/6MJxQeOw5NDLdE4uvpFdFiIKFmhzwNeQEYPgHNH3k
DF9etgWHYzb3Ouw97H46sXnFCI4c11RVbT3ReEGaGqDp4hp496NehaiUdqrwW5J+
mLyP6BVFUCkffuZl7TSUeCUEBpBo7LpgazUOpllzBJSplAGJaKJ4uhRnNG4+CxlG
Bo478ilCHPklMejBG8bsnOQuR+k8gCoHaCoWsEggtZE62wBA6gA66h1V9+v/O8+s
chyVt/q0p1VqyiQp7InToHp3OFq9Y3q8KaOifEdt7P06ILTrH5+kZGIwbnb1jkD9
J3X+WW2ziL4hRDStszQMvXHIizQzQSQn/IZyrLU56DQX3uAsMCAc2X6gEwa9QPLx
X0O5ir2fKV1oY4KWqkabXE3yQhZaG4w3V30wd2nQ3/2nBYcYpNewjseuVBqlzaNB
3k5Pc+prpKkN9ZxQkvJsYKgAspbaAlNX2xkOzbGYuhS4crZXTEL8Ka6sfhoEFlTz
a/fgyeAuEWiEIprgWpQbXMCdpTJVtBXoSlprnEAh1OEKklr4EDMT5F/eAFrVVoXZ
i+xrIIYZw6NPmdussPyG0wkrPOwUAe9FDSBiiBZLhWLA+hAV07yBgYTBQGY6N2J7
mqAz2ef/nJZxgljBgMCJNQGe5+1TAbuk7DpM8INEZCSXpkmIne1DFfq8IAnelf4C
2dJcCNCQQRLSP4kXSL1pBDrQwL6S/FRBSY6S55ybbStAflV4+XP2jsNNd7DE8hNM
LAsKu/4RiIqhI/yi/xFZ/mCPnKlKVXvqqNNB7LX0LBVx2JxkwpttIYCSrPUkeDvX
dQMw0qtON3J7Ree15UaYYOY8Tsdsd+9CJNhArXyFUWm52xFHzVswC6MiuuF/rlP7
YaB4W8LMB9AQpn6pZTWcaUWG/mYdTGhLW9494tPvJ09PEiFgNEALgFC2iboN2n1m
4DZvRXcpgQCbkUP3gfco+AVtIQmVTPbnHmiyO/hu4AaA8YquoVaOmMEaFjJttNX5
JAvwHOnJrN7JCj+kVfCarDvIckd0XnE5DHzMRkjSC9LNWYtLwEOGTopeuxC6erTu
9t/FShN2Y9HNoykhSPXJo/q3aUOgnTZCElt6PxXnLJVnvEvktThQHdxzItkRyIMM
elQPsYlDYkgcQjLS2A8jIM/lfJbFGgnSjOE+a6UoT0LpqwcJ/5Wv0qEfLOni62ge
lsTEySrhBJBTlUSGBu5zBgoHtsLEZ84101Kasc/sPjhHnXI7Gdpsg+Fi5akHVgiw
dwrOviqH/og3dRmp8jbN2zYmDWUtNUXVtOjV3OCxFjItt3hMG2ncBuT3J4P4PaUX
WRB0JvPOxCvOPn9q9Rh1VrWFdS4CtPJXMoMdbuGhDgCLYciOVrnA42939KV3fUng
HBwtFAET44Zftw5aUstvuGHc/99GvO+La8hcwfazkOA8tR/wF84EP24hIs98XGrH
mxfo8auIycf+cDXAbj/X9Jv6Hk2hNqcoTP0AbaqQ8tjwKW00UISJ+ZrWwNTnN0Yj
gBNODnU8W1txQG4V14yXaiAi7zTVvmPjxX68+vx7CCl+pRr/CIKCNzTRDNXiitGy
IVfWwhUw+kUy6A0xU24DYdcZQeHBeld5yF3/rl5/T5lxJuZ2sc+OJNDR08hAkMnI
MkOoSsehQ2daG2NpSMJe5aP6WjU86ipgPMNvWgvmT+Ak7htYpqWXvETsbCSHEN3J
SCQ7P07VpSURr33suaEmQyYQQrEbJYSkx2SZZNEY14RYTiM3lQ6R92HM9dofOMlZ
mIds3IIRopz5th2M3TRypJUTzkXcOjQoQbFAS3JsJm2GB7fFNtLNRVrpMTgPnuLv
nHTtxcCM84mXZEfTfUuOIkRN18vawWKHJFs8IjfPLNaPZPp1wzxGW6kSdtVyedZq
uTPu/u2/ZLfVFmIATmIfgeErEKLpvTxfo6fJw0EzqKlOYjahj9+Yi4/Dp9pC+VlE
b4dVIYrNSJj/RVD1U13K/QWZKJkprreICqR4DcbHByktfC9Q/Q7mrTDhUGXSG46s
RH9ey7JgyJPyhnM+lz6PoA3oLh6Of8nElKO1Vqg7Wt2cwKvkIWRrmkZmNjNb+IUg
GDqwqfXcLvvphXni8Uaigb+7icLm4k++SwCJMUGpRewqS6RlEONHihjM0Fn5cMBE
w5BXBAFAsu4p1G6c4M9j3ZEZ10k/far8LqE9OWco2sh1zQq0Gv0JgId49+iv58ys
/6YlrmS+zvJZncsNalJEPqYIPM8jw1tMOqSncqcLZ2uZHnWX8LQ0gibI0mu6e2v8
rfBvyxps9Z9jJE5tsIo/VLUk/wtEVXeIJnsQVJhTGxvIc9hdOf26U+q4C5QbWKLD
QFatqGnOvvDmlPidQIQ3DRR5LyS236cmrP90YvX06eLpcB+kLnklCbZrGc1Y8vTy
aRrqYbfaklea046y/TRVYrgE/e69qDrGrGBU9TZYhzg/2wDh5267i1Mtvqk4+Xv9
ANS1Nf2oYkAsYg6z3XJspPnawo8uonGxg24EucpnA2iF/V41G0GG95W65H0XYe7l
SQ52fpHf6DZlvtiBBd/lC9I172CXjj/g9GruUkCrfAx/P24dAgJHwXFuRzU0tfdr
oNU398ZBSXxmMkSH5sxdB3Zi/KZK9bWiKsT4jlK5m705QOZDkYKhlp5OoYQ5I/QT
5vvNFj825mEVLgFXqH0M28SLQ2giuaR+LWK19RpqfAtzWayny308cya1UF2AbHjf
48Sedohk8ockB2KWWe4Vyu+2+3rEvvXogoIomiSg8/uISC2G0uP0WvFLDBqXJlHx
D1wcL0mvVtiLzJBRuQMLnVrFRRzVBM0iAadQ222XemlKsm9oNgBP2wH5lpBVOwg0
IbZu1j5a/9s6y+rH9x8Lzuq5r2/GDOlDOtPtRVG7eDbuqqlkGvdO5kQQc+3NNBK6
ZVW9ky/IDbU76MUCcZZUSOZr2H+ohSpgWbV3zWHn5J24xS3RGJTcHy5uwF6W8ssI
KXb+t8Hry7Bjc0f+yUYKQ0q6j2VcNkLTwE0NG0hesbYzHpPyxIp0eM6QEtWrTO4s
JdxjG7J+PPOEg19+WJM7KSRtIz1QO6BRI8WDaph5yTkRCPFOc+PQUdrRSaVA12Ur
UQeP9gsgbbYggbomA1WFEbrUvHYx6i3dw9+v2tfmyNp64t3u07TU/EulzfXiLsta
eZjGEbj5j15aco352fao8nQ292x9fWwFEzLJHhqp11MdA36NvCzaaNl/nlURCo2u
09AIz61dvMufJcXtd2xpzp29vFnHiTE3y8VKyW/SSmzka8q9Q/9hAv1GGLqj8NC0
yhNV++NvDbu2k67ZiDTQxjm0Z0WkTrXFxKjIwWIzgMtgOqSUsCuEH6NR/HPrS33f
gmnNRvH4kQ8Am5wkg2IpvNBbZ0yJbPiPjd3wIlUIFwOS7G+AVUtfny4UeYY8TSWg
4KJ/Nbuz8C3NPVBc5pLDwhfB4kM5aBCNFatSw5tL7Ohnj1JHRBA0V3LNEryHFgiH
04Al/01xAK1c44OISs/LYq/PD6fvcijW5ZuGdLPvtvRqnOeSTsj42p/oeQ3hqaD5
4TE5aEb2x1N8ApnWlJSG4dc+pAaVbnk6LAHhgCxWlI5dhvxPhBk+K2p/E1Gr8+Xi
i5ltrXEIw+MwSkO228LrmyrwDv5xf3TICKSaWpv8bY3AOMPwm8kUT3zF5iD6JLxt
zS6TLVlWF/So1ukedWISJEsgVD4r9xy7W4ICH1zIivnmPn7pa/48PB0EuZzySZ+P
rs9mQN0U1+jR4NqLCTCEGka2jwqerESLEQHNW6hkGCLhRwaAbjOEIpJgEKk1sOEP
ZQCv/CYhtnFkdxCT6dimjfNUZXLFVfOmWHl/Q3sp9geT3jFst/3BVvpl45YsiwQI
e+mFWHFEnwi7vQRFLkydwItSOiKWmQ+QF9xpLu4RURym15rSw4LgE4ReFNgZpyBa
tEj88phdGP/k9bWtmvEQX8qXqWC3UVqYJ5hFRJdHHdRWeWO6EDWQxuBuWmENcVra
fPM4xlnT46z1n2NthTD6Dh+ZXVGBjhpYppVdJLhxWQMdZinlnwYwEr8FC431Xp74
OKHEr4OahP8NF0TMgKoHoUUtqU+QoClAq2EXsTF/iWKQP/ssvP/ncgKnvhOiX3Yl
8dEi0yxQeFZA
/RpPwfCUlXxkBpJgFxkdtWyq0tJ3yxa8wVf3GeVpEuSwlY8t/alqKB3Mr/xkV7Qf
fkmvEHgMiFTIvFqZwgiYTypcV8A4vkBfcJeuF7avGN1sOh+VrnMxW9SNMJQsa/fK
pQX9Fp2YIL1t26rvygbkSGhpv9LJFPWD0GE20fvOyQTqLZ+9hkmIlriJiXPAgE5J
VdVOt5QrmFv0yjeBqZJ3mCnYdiTL0d7sLG0n/ICdRnm1ffGZ0N4+ghmEuW6PmESv
xi353bZpDRDDbRXjBG+9LDBwTs/SKKW8GRt5miSAzdvRPeyjqAhS589lalbHYWMD
+HLrhlY3FjTCOf4ijnTJBIMCR0VwpXTV6LVofNXWYniHg4VPcXfxtBsBOwpME7zE
ljFQUaQKvhk63XHyA3VL4bjG8ZekIQ8vxPL+vBO2Ew9U/NI2AJQVYss4Pg+E6fAF
BVgKnXLMuyZpQt8RniipYHZgIfdxAcVVi97jKMN8orIDbhTUmcR+6A2ZNA31rkmc
ZGPGeTBiVLjzI6jbSCi4Ok3iQgvBIyAiSk5oHmneKcCBMpHavwl067glqzbmpgF3
cyqgRppAl
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
A3HJjldssb686ipiyZZB95sOzenl
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
tlRnnc1JurlTi0jMarveOMxajMWCbFPiT+JuOF0
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
8KaP4GGGE7+Znc
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
8DC022cWBEKSsVeh2fvL6
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
e3UGfZSPDe
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
Tl989styNAUlzJu8D6aRvkYj7dpDeYBReoNKkTU
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
NdOX1mBM1BUc7LcFToZMLWj4MNddn
I8uaGUludEAgsKqHhOF7yyG/lb8B6kyJ3G9og96BOxgBIL/s0H5ur3Jvk6dymhJN
JzKLjS2MMWr/q0ZjyKJ1x4l17UOqSZR0c7W1KzzZ3YzYXHudKhgELgCGiPZ4dcl1
pWpqGaBnS/X043pFWgSgdPuderawoCR7fnz+OEUCOGZ69McBFVBlVwvS19YDTdBI
HLQvXeZ0l6F4fnp+/tb1GE8DlaFn2QpuFg1YyBuiaZjt+ROD+O+lNN4XSSv21D5x
mw13hL+6LhYHDy9a2yJ6fSssQ9F6eCOly5Ki8aXTZiPNG+PxSGR4S90vfeKwpnU7
5kOCCFT6bN7JmUOBTHpxPznDhszFpy84gBxI52FzWi18kyfuklVKQcgP7i448EQq
bnRF6e2Ixh0D/+d9XsO1W9Il6d4W60OoJPoZqqBF2434/dxmUhRViNsRdJccljNw
GA/ZUUAeUFfd/nqWfYrQ8SE7aGQjaYT/1IiJt+N9OURdGqrU6u6dsRA7WmGDN/Ov
NoSKW6jM9bRW+bHb9eUmhrTF10DsQKv9Q8kmlTeVHub5LVa/Cn1ExEGMSM/ObGOq
AIgKYjj283jh/v+iv9QRlvk3k1rwQvsXE9dH5yiUvfOjHZ2JQdiIBGk53opFdfhF
03pmrgrP1oqkYyrQ74TK41jzasK1VnOQ4cBH68Wuf86QDGcD4aaPqh4ONjYYOukV
xHN5/5S/xQBZQZJXJD44Icq0H0H/+/LSfAoHoJlPrSgtRnQV0pefdfNU+5e9eKYk
U74YW8I9PqersHGlLyjO9lyYYMw2NNXRaIeEZwS9ElBqH4du3BqfWocxcSDG0neW
FnsK5LRY7FruUEYEQuM8kXp3tjLLehSdED9wme05FXyyNKZDEx66XxSeJP9gBolQ
oal2Y0dhkvbkoBH7DaP2KT8mbbusvyX8XJc6Iwh+JgNB9cSJY/y3hL74stDVsvj3
qgu/G+lG6K9+rycDhQdCmpqMoCYQPtvQiMc1ZnsKKraqozqCLK4wiXqL/dzsKvpF
KFANGsKlXTzF6SEE0EHr14W2njQzQBixJEzFSiNSMHvvhg/zUyNuSTFl9Wg2UGMx
vGJ8ZMg1zqGDah1e/hicumvjzG8m/wfMUtNbtXSRzn1ZufNIFrhkAMxxbzjeTlwv
nLHLuP/6/fLG+yFOYKWzmjwdf+YUlj6JVNbcHts+J/LPyqtOijtRCrx+2FUT4ylz
DBYNzUlU3clQP7vBqr9n4HRhMRTR3H1WKyyuzlr5iKmoecyD5wAmQjHP2EZxrEAf
It3wjp9guVOoqcsFPq628Let7zYZwVpTGMUXI8MgtqgNYrxEnHLvzfY1oRo+fKUh
4jy6Kfm91LvZuAtB9qIUznPcGADat0MF6h6QsJSyK6mDf1TGWbe/cVAIMXo/Ja/h
QOht4LaVfSSQT6sUXReP39wMDOVHIVtKdIdAayStthWzY26RRmUUBi4n26cmxe71
OWveCzi1C9+bnG70pRTqwiimJjV6JCsQmQqhb8IsVLUOrNA/OsToQe8W92XzCdQj
eHfp
IDOcC+Bk/hMT21o0guz5/XMuF32IIbSxu36hof13gUGxjLQVeYoNZwxVs0SelUn2
zkNzl7pLliwS3bkB38GJYKRZYLv+GSIBylnpKTqLHNuKiqI3h4/0o4WPyYBsD5AK
+zrPcSDK6lmeNFLenLyQ5zJwkRxvCblBHK2HCIpAJuQGhc5hQi6I721AU0RRoUZG
l9Bn4BUQ+earZE5bZ+4pfV1igfp7ZRn/JXgH2UkaEZdOsEGUGb1yVakMNUK17X5P
fdbOfOj/noU0+XAcWhT1BNuDNoxu4tb8dSUQpzWcMNVTIWZUb/0dV9PosXTAF9W5
x9Y6LohkL75Hp3QCYlgLukarPCaibXqX0IFJizCcTe8Qc8djGMDVoAQMMsNFREix
rUx9+zEcMtkNhPBic6tWAl177aCvmZKJtj1W+SoyTwwN8NzH+WgWSpaTKCY/o6Ua
SGcq8XDpksjZu9ctlG+718Emp0gubWAVhMbdOPye6aQ/0d2KBeuZ+WScWdlIrfTf
VioEICun4vh6JUeLFQ6H993QnCaea3BgilKY7jMycaE3H1Qr5XT3q3F1GBBYifIh
vskp40idgZiOJJWP6oXCYjY1sD69rLE/2uzWljEHqLF4sHIm0PwQLo/GtOMGOUpd
MnMVpFx39lgt+OilKnMmC+DfZEW5vEFlU/r+DVX44+zLCtpWN80BaVShYUK3RvEC
vQDdUr66bRb37SffrTLoCyNx/KX7SW8wpIj20ktG9crK8nZaeB/BnOKmqmrAy9Gw
yJwsn2SSDNoNn6KzJ/WU05UoTT8fWAsqqoNDz2+XqnOfMzQQAw65ohKg7Cge8cNP
dX8LVSBZ
DloYXmbymf/W7eOocsRd+mjb0HBui5UAAiiZab70KL9tKySQFHbC1pcjDkho5xY+
iUZwHfQ0MVK93nc9qK+1GECu51Gak7Q90vsfMHEEaY2Spp7bQnF21u0z5XArM9sD
aM7dDzFL2ETehrTm2BCGXHKmn6T9bg08xz1FgpfhE+wWUn8Hq3h7kdC8O2BQoZwd
VLVMfgIquJ0puM6qEtmy+lfmeZ1XoPuuvk3rqmPrI6Jvk0wP/8TL9C48xYb9VW/X
4EWACfBzJKUsXHGf0Iz2n6hf/tKeXnIH5p+0VUEho+P4CCvmxp0EKZvzGURyUfBl
f1DDpHPUfrKNM61SnqjPAlx95lBfTFibAVV12iYvIMtPpVRuvvpEh4pvBfYHUzAc
snixeTayJbguPaOgO6B4XN8kVK49UEBOtCjOUcfIupNylkMWuHPwf/5LaD9tdoEf
pTqNYBP8p+cfTHMbY/KoM7hQ9h7YcD0LIAm5wXGwXGiiade+roZqR2s2PaFHbtRq
d00JeW1LEVwXOTCfRMBVY1V3vCxbvr8wwPlx0FIMbmYB2SRj5mdBSIMvcEJYtUk/
dy8Qc+38OCoxOME0znG1fnAbEAWjul9HDrNq2C9s3jVWPr6fORajs7NSvXm/+N+4
d/YygrCu8ZScvAdjYT/vcNkYBra/fgGb6omibTwdCdgLfXVnB3LZiYZjfAeMtsf4
sFglWQDrAnJ7qQta/p9qFj5npoNF3tDINin+awcDvG/dWY6O91focAzPB9U8yKdw
2M0VIiFf7n+Fud1HfmlbGeKZPQi3RQEQc22454b/G3VNt1NjN+66KXyX6GuxE3FU
f9DP6w/NWoFcgcB6THI8HFg58oLubLfmFULfZcO7oGaW9gwuyYBBTxkyKcZ2qlSc
5aQYpJxjYoj/odfsnPAFqUMCafbe/gP5OSbrHlaP14OL6ObkHg9oea/aSP5x7zfT
eL0oueyrRNpV5F0MD4lI5A8JApu9A4nvDFfKdtP4RWcT835GjXfzlnsYPqZSw4vA
SEi1DGV3SeWLSF1hmJF2KwLihGpBL2bt2BGVFGZhIC9raaMfUyYq57OsjVaaesKf
sHVahdCSlj3xsjmnoMorCW1Xv4p+7ej362WG5dBrQRuQvB8yOM+4P+FYsWeg0mAE
yS2lyJUhw2Y1/8nRAnbgmVOCEPDkLxtyh2ncxh/MkGo+JAIXq4UIUP4wGg1ebcQO
7k4aStAX45gSqtQ/ae44B9vpkSAuRyLv76ab0XG6T9GylOB+BryUjSIV5viGGNCD
lH6VRztig99LHNNpv68bpkG1MOGs0YHREyuEw14RY2JG84g7lIFbMeb5+2ns572+
/YR4aldEoOS/KTCQHaQFLP/Ug9K9pwfTEmR9db+rFUOCp+IQ9cucfFxii5GS8h9j
Nbg63oN+HiKhL5QO0FNRnMmCDNJWUMOJ3EaMFXF8UsZkWUl4us4YGgItCMo7ABZ/
GTj7M+D+q8i0EwwOHEcGCcon49E98BQgBQeZuEoVy8KU7yjBNYguU8gmQkj6v7vb
hzabDuBWP56Btq7jODrhgkhGgz0RjQZ118Dromz4oti+ywU/lnyTHCWMgVhCEYno
fIp8KQOgOsyhnzp62sXqque7PL1rWGg8LeNBf
kOyvKph5g8Gj5m09UU8EzdimBPawbOSiCOqAX9X2gTz5/YBPLu1GtvMtbtiNWFMQ
MjdVvoXZsBJBSnvkWBmON5RBKZAuVYbDrb/j5d+FrbFPd0WQWq5i/hHVEyK606gr
jangiBWZLmYzfSMnLM84AIn7P3lvsLEymED/58S00M7NNtGXYT2K07u846uQ4yB/
P/X/wQMtITw6qpdO9lgCvSIJINEIF77JrSEyn44OWou7EKohK1hmVXl61oxup23t
+X11DNab1ffC3A91c/9sJ5UDcgRQqkKICQRkXYpiopYM4vHTNdi5MHtNAsvG0hCv
ngasclIWo6tYw1UuwfWqL5qQ0dKtS6X3yHpkMJ+3aAEawTDVeOSWhutcvVTk7Awq
o4S14e9ZQENJgwQSsEuj88xQPrIsm3c1LWIAAb0eiB72Ob7zH/W0yMYIw7zzWPl+
d9ofYvjldUnhrosrzb8rdpVwQZqp4jfJBBU8zeKQPzrgxo9E6vvjvUi6ol1HbCHr
A4E0JAwoWgRIVfuwlt99dF6lp/ZDi3RPePhgaN1hpL/O7RZ7+8BAc/61G6aPKxdO
HYRnWjFnNL7Y6Z27sL0uZ/JUr2JqmM6oj0rKKzUQbGh0Ok7LV6XMueuw2CO6kchh
GZM6DflUc630tkaUD7/ZDgrPEeM1tgeMS1FcJZ2oHoqKixxuR3xjWcJtTQ6zM1qj
upp70H+nkWwUDndjaErrEGRIHfraTgHL1N8yqd+1aogFG5lptDwxNnQ2YQxg4wzf
cnUIKreQGujvd8cwodHsIU/6bn1nVi76Vp+W7esnCAWCze+1b0Rm76r7GOwkPaGb
35GMwyxc91gEEI8wN9nxWPWzfAF+mYBAJqAg5ix7XYzA9mdWt/PHjWv1epCTSdFt
9ateYBqitr3DoV6gHsIdPbvQLZYavuPiyeKBbzXIZ4+fPlArISYlmhLVwy24E1gU
M5ChttktPB0cRCC6V5+ChF61ixFJFziJtGWuhcFkRxOdum08pdxCWWuFTUt/U0rc
PCWNiInBYtCycfgjJgjKt6p
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
1AzQW58lRRbTvK7+3/cV9CsdRvxb0m
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
Lt1TDM+IpMysCVrVp9TF
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
pO1F
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
IRASuyO1+NqaHZOQJOC74Ix
eoG1VQanufjv/n+1+NWDU4RiHwrjTHHr3WMc6tUJaLPN/Afsvw28RUw06MBy0IiT
o8XrUc0f9yiYWshcN40cq+7Y6mMWBG329E7zcjGtohoT5GfsgNhasAggZVCTGilZ
W0+/ybu63304gkJMbWd3f2GpQW/Hbpdj1wNwq+s5ArhPaS+jhH5sj/k6rlOpK8pL
ZccfKvpwTQGx99uM/lZ5tLCluzQDRdrrhTrrBTv1K7ANnyrM2qdN8UUkxp39FsUz
Bn5qvXrhLEBPMZmDBkrZ9Md4htPy5ekSJF157aeUdPFvBYGTZO6BjzTwFBlK5GrJ
z5C+2/Rdh55x4UWv0DTqD+DoKORFBsDJymVo1+h7Ouun14/H1npYIDJCeuFtDTny
T1WNEHDgMZarKF5SAW089jdO2o8peGhdbjwy4cbHKjq6usPc5f/nOj7gsxNQ6Qcv
I+RUyVYGtl8s1g+NHL+g0tckY595ECL41HliDUE1Ud1XWa69a/u2CSO8XHguzq7O
3wbRunAqLjcpvq5IBFeKxk5lAmvk9Dvy2fzZY4xxasAedmMF4kkISVHB2tCiX22c
7T1qNwfeuLVR+S3OWtb2TyJkqTjRYvLdzr6nDf9ArWWQSizHoIYmJ/qZMjSN7vxm
uEyKxKazSnD7I725GDX4602Znn9Jj6k9K+sE2HBFQhx5EsUnoaHGZROSB96wL0b6
HaT/VvYR8qnwqpneG46WZsMZcbIU3Qk/Ivj2jf0lLVHxtiT7cRG7PonAi1ofsgNo
9wInNGRkPpXRk0VPN/SSGOwrkirOGz9rihEh5skYdtijQ6u3aHP2zhWRabswxJXK
mv/YswNLZFtH9vMsG5im2wcsG49nqbOzfZMsGvAyjJwlvwhgUMhPhMdScF3x4W9v
CSi3AzaUXQ3Ysnfpn606N6+XQsV02NjPLtxNtr0vXj3TTwBdkkkpsTi1u1EbWpoa
Ivz9mBMX1G52vi2K0PLKNHamXQdgpyoPEBvw6pHPx67goh8wk+xsgVyAdafhSWZy
RQdp733EG9ICruIMhr5LBLaeIokrqXirQlO80pAXX57HcoVWfQJsO/ekuBrQBsKT
D+2/Zv
oWPCkeyXLLc/GeK0NYGui9iwO449Jy40trMQzZGK4eRnEIupX4odJ65nJApn5b79
inZYPdnedE19pJQFNawSGmxEIEAIEQ+wrjuaA5pRdGOppylu9r/pf7Z9MHcrEF/K
fh/YvqEP9bpAAAI3dqjTos9X17pY/NqsTGRNWUyoOf4ALi/z3vrPyIgBfq/8drpU
Va6XtdiB0rVfEP79YdwaT8BzbzsMhMaWP/aTcnBHWtMAJZOKQdYD/a+otVZYywFK
sUT92XcaGxv4MVg1xdbQsWMQQTzou3zDUzLuzUzxjuM06hJMbhn8RKK2likmAW6p
1wT43l5sDjsFN52/04TfMw0fKN8QBjgtZ+cZfK8w+Ynot6pH/B8aN5p3PZOUaWdv
lx0SQ2KgAp5RG8TaYDKIj4YnzpCvUsGo2sjN7xisGY4CSCC9fnc6tl4q+2aW7MKO
j2QvPPa1q4xHlTGrq1Me7Vx3MxBs6iHLzgf9URH4WcRvdpdJFi5WNQMJoZak88JT
tsVfoo2Jy+dcncV6QEubPScMR+oa70chsIPB7qzbmKs3gDAHmEsxieLIwRBvUT6K
5NLKchMHUFFjPnwtVETqTaKtAfg6L7V9kR6RYWqHQNcnxE1+X4lKcN9hD5aTpLvF
z/ABlKc0UV0mxY+cZc1YCdealH5YJe7aqK9q/uOJd7NCVFctcf7R43IID/8k36AG
9PLNMzwCRxKK+8rF/OP94xD9OMvdFp0DNYJruuSnyhGTKNA3yFO6yUM+OZZMcd1c
G2WIk4H3Dgd5INUSSX3h23m6EqhU1lAvYAfCGCUBaxOvN0K7v1jHfZJOis3jjIbi
E1277kV3bixB8qSFRLpfJzrdXI0qpS7bZ47tgtObjK0ydLQ4wmgP2TG+h4J86kol
UtW3MUGx3dXyE5fEQadq74x7ZC4TpGhV7E6CBIS7Wh1pLj8v8O3bSywTvqmo/+OB
mMgobbMPBAnuKf32L1UGjPL/jMh6sYwDzCr2f5dL3ZkEjPfIrHaJmZJQN+4nNIyS
mWIWAhw5PqqXH3Pcg73D9CJtGneHgxpIelpYsP/5PxVDv4U0ezwTajQaiFKljMrQ
bELgaMjmwgV+1mHsB6zsgAw+WS5DBroZKZjDjUkcknF542rw+vCC75baGYXpmro2
/G0PRQ67myLeV/MFw9Bmtee8pI78WzStZmxdBYclcTAVpdA35lhFmeGAjrzInXFN
0pa54BWFukcDxum/iL52DOmiAhCikmUafOEbis8sbUP+8ac1eYPIlq9/FxqCGgEn
N5y6
ZScK9azezQN/n6u2aNSRjv9sKe9WXls3EGqi5RM2naHfODpEExxWKMBPjDR2+Ou/
nC1oZtOn/n2VeLn2CBWL4lx7fb6F6lvts0o1RlEYtdBz6SxaR3D/JUGZ9q1d3DJo
deZoxk/mKFNaInZOLGdXxZkaqsToOm6UM58L2LXBdHawcuZbzpFjUcHG6izEelgC
i3R5sqI5xpIVW9NlFSVd3GOPq9/y7WXLsv/dlQCqldTsS7ncFVo9ZMg3yvUmsiJT
O7/4y6qnW3nrt6tK9UdHVK6IlzZmQiJjYu8A+Fiuh2elVzLUhs/OGiF28uReIK+Q
X56WCewwBN/29+nES6Vkd91CHfcL2SVo69cGIp4j58BgU+gTrJhSSwkBpEdbabK0
butTo2Pmw554dCY229iemX4g3G5z30Dehs9wj5HEca+bOlGtYAzE1F4wkxbDigek
2MkytHCEW3xxQAlXFvbFZapLev654tTVhkO5KFoYyIsgjqKHW62f11J8VBbgGslq
lNXw3deGeytAD6Zehkjczjsafq5MIq0GifT7fQZCPpPlxmkSTCnmlqhn5iHU5lPM
WIN+xZMeDSxlF7NPAosBLGNifh3Edy+qpyCE3zH08tE1oe1I6DHOFLUW0f5Aeppy
6i2lNfUtBdgFmKsUQ1ly8fZiJg9HSfSAfseYLIwX/Z5NcJDo9c/Ro17I5Dl34WUC
UlOcNl7SapCtd4wRh4rRumSI1/+sqR4gauCBH4tPutYW+dQu1uqoQRf00DTohHX3
1B+HEhTKWEui7OaOR/CPg7xBsAdHm5aEJlfhnMkkN43Kg5BfOnPKKfoyHQvdGWhm
eukRVzJMl3cs9V/I093nXiUiSs+cDZKSIe0RZ+OM+eScoFoA42mKnEo1iY7kJ+qI
DlAkYJMaAv1vfZENdhipPAFyFEVLAg2fh45hOI3ykQqzSoSjNNMma7hwWxY/j5eM
5m2qcUJsNnaFZYDX2igeSBVsDl5BFDqfcp6JQHXJsP+i3RWAsHcQmXuj5YqK4y51
4JlHTJoqeGCNeyy02WLenjhrl7cO3S3ImmPg6VgMxFA+4xmYi3eyryVHJyFh5+Ig
OjA+TxYQ0STX5ariRuWURetUIowa5GT3uiOKSQ+7nDwne1lR2bjFbNufRvTJo3Hk
emITbujtDoQ83BfitqafHpB1wCdTFZisPbBQxFS9m3y0gN91u8ESRMmb5U4zo70U
9DoCMy8r0JuQzA9L95GUw2D81NVcMIJI+QcJuce44aQ7lJHp21ZoQl04sCQtB4KV
PSv/xHvl2KAc57HXWTzWrwd2HXlZVvKAA/f596GkbXWX1lz0uwzLG5X9J01ziy/P
LDAUEzMJo3CDFTyLGiwjhnOMyQmyQmuXY1YxZeSKte1n4Gx1NTq+Ga2hGcJpQmQ0
R9LwvJZ5lYxd62lzk8fU4aElCukezXVN3/imbThFPVBUmbyOMXyZghVb4v9GMFdS
x2fixjSBydzA6DssR0q6SfD8EHuhYaQDefNo/kwincNDj2DTSgmsTfT/MVG46pDJ
8M+/eaFBzzLS7ZBpEg1efv7O4gF8hZ3X1wsNLwRqPi7VJQ7mJ8bSbwLTIh0CUdZf
8aF9RJzxOGmOSoqr7SOaxkFiuDWzCS2C2zxuMpOEUBXdhsx5w8Hq9Ysja9yN3cEP
ON43KGqnkhsF0UJSMJMn7JnFPxGwxpGxlrW3oXkmNvvr8zZzKP0SGpyxkn+ewYdI
8pttBwMBMTeaMXwuuPYGgJqeAFHeFEnIk9vvbZUmHopqwREjJQCoZe3V0TI2j9ZY
MRoC8x+ZtsQEwS15wz4a7LpymbZWyBb2HK/ehpQ9n84ReDGf6RhDg6X0Ig87isPs
2FErA4sjeKowY7TclffZrWAQ0Nrr7KgYaxCqUwRRVJBlAOKjCW2gbG/kaZ6Myd0P
nJfDXP87fE0bTdZU18GyNDTsuMBpB2QSBuIps4AhIbjITZNYcOr9mmNHX7bNp78F
/JTF9K+9qMqAAJyIHk+amo4ripiMj+KB5TlmtFhPL8xnqWqyApTzJLG6uYkazSbC
3s09HiRcmZgzioMsi3Ag6Se8huAyBf5gxtdHMrJc21dAhwtUp3lEAhXnhr7w/SIS
FNF0tYbcxgXEmNxepDBvxEc25b0DmbGHF+WyTqHDqRpUqseeeP6lu700uwfxpeWV
/9Zo+28o/0lNFZ+GfphQisk9cU/Bim+tV5ExQw1Wzr9D1jgkhZvtX9imTl1YK1Ge
z4Z827H8pP4CLSH1ArLYici4gkOJ098yE8r9tKUqBEGxnOB/VX8A7puBgKndglYv
XBPFXm9vPZMpoV3noJRvK7ogCS6K5KvpMVfW/nCPg0ngvAhajZ9M0k9+KCXdS4zb
tmYPRcK7hxLVZERI82P6Nj0TIea3DYfN1Nn47OMIb3vUVYbqqy9NZpUBcJzcBOwh
NTLm/mTBVvm/crYiOvlS25j41Ede0epabtpiheOaBf39G7UH5mhDgDiBwyIptiOj
eq4tkqAB7mN2mQAjVV7G/9hoBwIEseJ/mn66sVc/ow+mkdY2fzMjmRjzi1yhC7NF
pytW/5U37nwW1Q7AIia2LrHHJ0fCn9DK7ldq8EGnlM9dO6AkLCkPzmRBNbnCcluw
Vu5qNqjL0kMgXS+AW0ntm1PfYPRzk1eZmt6Q33Ew/aCHnqLJVT6dE19+jQnhOSZw
zmrCdnaWX2RraE1uTOkJT4upRhaMr4642evfSOb89LJxTPiDsvCgBp3c25Zj1pic
/Vkd/aVgEd3u6v/da6cpEWWNrISku6JPYE00y8zLxQbjRsbR+a1uYD/Tu4STa1s+
CLBfK+5ESTBoc/vaoyfsdAf7xGxBbztIUL34baib49+XF8R+P9QyWuH6E56LcjcL
JwAsfXNUIugzBZU0wwI4SLt2dd1grHJ6v3cToi9yn2S7zrcePXtibjHR/VVyN4hB
9s2sNRX1W/uzPHZtuiPt0Z72TIn/MS9mtQGVVkXdLp1g1Cve04ZJQaEl2uINsW07
SBb8kv15CfWcao04loFWSHiFqZAu44+FZcAYCc+oe2f62JLKgBqlnvH+Qalx7J39
+43Q0N9gIMvgQ1YeF40nWrkcri50+Upnf6JN7rKcz3SX13FjSaYNaDMchMaFlEkY
xq1LuUoHvzJJ+o8qIGs8dDt48TeHoYst6Z0qIccrecKSc3evg/eiUYxWXOe21qu5
kxDeyF22hGctAp4eFGZ+s9I+cOY1PwlWg8mVjIjmCtI0fZ8zl3IpdLaWX3SwExWx
gKKllxqY4g/sxlr4m44/K+/3WRyCCEkbhkYwtMo1EANgrZQEz2jrc/CTqcVtI4Tk
JThOrIE+3fHSdviu0wZgnyfqJrb6buWrCf2MF2gHFdS8t6C6QMMUelhiVGw073z1
x1lYXg3hLcfVI9V2zrsRK62NyI5gvPM6clp/C80PzW/ctCMEXf5TV+CM9+ZSlpPj
K3CC2+lutSFfocICeC2kLRsz9RsFHo/f26Ig3ISrmNAZrmlyOHvfZet/3YoSoRvH
XWjavB6bxKaXerX/ZGzB0LjYrLFMa/Y3pix6CE57MWGhgN4mQoDdSnJYb5W0mdgY
Jr2yHp07U1WieWIV5ALSL
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
ShpcKinq
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
+XCtHASrVJJkEcmVVbN2DL7KqCPHu
csYyr+nx0pz0Z0uzPJ4pxsXeuYoaWJtZJXdaB5ISKI7s6EyKFd78x6s1kILly/Ep
jEtaWa9uyWlOrS+xRtwZhsI4W4h35wQTOkCoqrUuxb6nl4hHITegzR4Pfzc8MXOs
z/Ewd8duuX6gFA3YDz3y+hbc1Dkco4rbMfZmh5MnGtvg/KeCf4BFIRvxv+L2ERJ7
QPc9qPwNa+S0aPngYD6RFAWaisdk6rgnLVB92XtNocQkIDB3u5bwrA6b1NbpsDLK
9Bl9x5y0TQN+b2C3RttP7+0cUMEXirDTZJvlQNG0txzfsgyKjFaJN3rGDAHsrNMF
hUIcBM0X/zI0+dCJS2kABAO5E1Kh04sZ60BdusxXEM3EbVkRyPOxRj7s7vdL/pqy
BeT7RcHN5ZO6LLR2wQ8TG0MQIr69GgQFuqweMar2u1pmZUuog1s1/c/179SHJlaW
nlnse4jKnWT+3WCFH24Dtlr8LXeOELNz2m73VI+izyIOvvyY34tuurLV/bM2OZCS
H240f+6qS2Eoe8VJyIPdTpMyYE07RQgPvoZ63ArOiI09wlKeIjNCywx/YEkTXg6H
WCHLnAntmWnxoo8TaTBKrxOlpatEyi4cNuC3snH5HXiFHSJWofXDoRRDSuWpCPEc
a/GeYE7fvfgTRFHeLiyZl
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
oH0AZu8NX
+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
+sD3CjZRtgC9sv38yK2YTdP8FQy
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
V+4sG5tSyjkRBaqMG9rXDq+R4nWana
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
GGF
j9ogcnlQ+PetUr5yrbMNFMiMeFMILc6iEQbNUEhTlX5aU/dJvh6w2gJf+CPHOdy0
8NZTK3nNV4CYKz5RTmxmP5YMPlRt6/evBQ7wvlaLSJYIvq0RTNntCbFUZuztzhd3
i5o6Oo2W4omuil+liE2lRJB/MvAH1DaiBLOYLxzpTULj2eoMc69Nt5GLpqgx21+E
v821U/CkSZ+8MZwDLSDWmuYCOLesDstxxmh/Y6d+BRBB7e9LTRvDd1R/BnOo9Jui
5KXxwgTCWWnzG+WH22SdNQeoZIcIjrXBvRWMitVeLKqGpM2Ykjp5mB18GBiZAxii
nHUKVC1Sz/Ad9qIUA0KKWjEtfnJMMw+U53Ti1NFMoerukls1995Vy7/wgq2XHtLE
oEMzI1Oa8TuGro7os/JYUYYK2kWsh3+ZWvcaP4z1JFQ6fmsVgvJBUb71YV2rCa84
vHtOIsAF4SI00sWFzTq0OFevg3YgcKclpRsjmjnZ2PkMa4hi+e3FZPGv5XuvvsUG
bi0ziN8uGdDPs3zlU7RBNeRR2wmCzufszy1GWhmHwnD7R7nhBifgV+rY0nF2ty1o
EEPs8Silx6hF3wA0QMKIom3q2VTWGY6ZAIKmNj5mdW891eejyn3ul/MswDk9pTi8
M4D3i5onpnquQtLEPuSkwNNc2b0vX5XSsnSSITo+QVSjEOAwY/nEf/Un99/r4uzl
v4C1wPfLINhhueMkMASYJTYDCqHG3CIoO9
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
4WRZpD/JmgelDIM5tjc4h7ZJ3PSsY
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
XAPQzWQyGclFYSL6LFepDREH600QTI
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
tI5Uh+BLzH2Em18
lhCBtzIVPBZmsRXF+d/qIM6jPql+Hg6qmxExOW+GyfYR3Uj3Z/O6JyEIVxweObJo
EN1t8MM5OW/nJ2Bn5gXNTvnUvaAaU8PQQekJMJmnsvAUUR9lWRA5H/Rqebn8iE14
Q09MUBYBDYfcZGoP8KUMwplzn+WT63z65xUC7zma+EoJkzz3wIO/aeEkqb4mMjhW
S1oabi8nqE9+pj4+P1WQEmB564hknfeORtb780oqJBd+6g/ZRpM0sHW5Qp2PqCzj
wJCfN/AS6i/AqoDi1lN6rddBdir/xZLNqigqBu/mK1q15epZKvz7leh1y2eidMPF
R0+qUV0d7iSSvHB+VcyTrFhajgh/xH4fSLCs8Tj9ohya5E+F310N+q5pP73B+hXL
GPp8Ppk/rNyyYpDbgIW0IXcC+qzsv6WDSJX/78Q/DCCiiFkyNDCu43K38KPRh/1y
tVKvH2DYMMVewYWYFW285pqQsyo0jS+4rbTJprvqyAUXQ94UNC+DPG+9+L0ISsXA
wOIyAW/3aqADeDA+wJ5rXQeAX5cxTGi5C3VqNUb/vxdqvbpRkver5IjB5d0YwhWY
HRK2CXmwnmoLXCuIgSwL+xd+WktlYafO72LkLwU/Z9rF4XEU5WQv8o+1C+y8NZw+
T1Onn7Fpv9KtioGtH0k/KwGqcjhXsM0YjMlHw6Hjfk+TFXlHetNcbLKSKXsJgaQi
SxrLpPNchulzrgJu204rhYceHJp1ldML2qKBCCc66Fzic/U8XYY1jwfVLp6V+A70
vB8ujSatuBznS2IdPhJ6ZTApFFkAu5XWRCBsEUcDVaW1Ju0GT+t09Ut2bXnTKImU
ILdSQjTGr97xFYZAq7G1yIwOU36WqAxo4utcVRo71KlWC0EySIrFBRiQMq20bscI
oadQjhmQnWZGKzc7e9Sxh+MLkWQcEk+zT1j15/WAPqj9RFZK90h2xVkq+xtijcUz
vdZaxU6vtjYqsABhKrUaudXk2GcUJBPIkvOm3f86QcA/QmQQIr1khLz1y5RWGWd7
5VE5zl2iYeTix4f/qbt0sSMFgvNzqkEImy7H2PF8ThXzr2NjiIW+7xC6EM9eHd8I
ab2baG8dFVXxqpGnFa7647C6P1j6k6htV/IEb07kcqMC4hBSOpFeJ1wKBRvADA4M
/GUJgo00f/4UI+T6eg+H0bc7zEfbj29CqvyKaTIGVvWtfNjYC0L0lP9MvjBjD715
D71znLnzqLhK4kUptaihOibpmhIZu4I06F9RCHpgf71wPcboh1/F2tppnaZdUaUY
M8ZLY5rCXQWU5/99RbJtMNPYFm98vT4LXDdw3F8caTfRyHX6KfkL9s6KX2uW6EOT
x1n40B1FKZPK306CytY273Xpvx3rgqxcFY
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
rsZkQPh
WsbVu4TuN4CYU376Y8CJEoZTc3iPATpGl+nMcHo0LPCpACcxvifdaog3XxI1q6Rb
kTGxpXW+4gcKArJlBXMSHT1jfysG0u3VjamSqexZzQVQe05KUHokwBcygq7yjW7b
2EePYVeY0czo0XChv57mn7V/XOPfZZ6u60axO9u7aI2yq/1TkDSGGXpKnRlY6Kjx
BG5siROpSCIB1SJ+KBs+/QIaboZMUcoky724OPsbnaD0oMK+dA0GSYNR2iJ0ENgM
dKCFM+Suit9rCqc1HuoCmFtzBcdKDSwG3Zum5rR/LPuWHSm/VLPT8dIPm14972/Q
MoKJ7P/7Z1AZmRUvBKLCcD+YJNJa+VidWbaIYBJrGOGyHGSF5ewSgmqzCN3xdxAK
LmtNmEJhgOCy8LLt2P3UrBkKKz30kp5l1VqqtlsPYSrQIUtfn++RSXntPd4Gt5ID
Jdns7s1h4nqFb7mpUHto+osAaBit8LmdLc5TIpy8NrcVmrd3K/Xlt4oOAWVrtg0S
iZXSAlQIMPkRRifx9aqpNDrTnMF0P75ETV5fq0caK4Ic6nQ9ofESIe94uJNiwagc
ZzhTw8pGRn+9EFWC+bUbbzQoml0L7MYf+NM+XItyiDMibm5tNua8e3f29F24Oxrz
HVcFoDX6m7NPNoGIRVM1K
aNNYHetvlT/wwgYOd9iUX4OtsTrELr6OridjCaHkbTdOyyKOtlgRcnbNljcW5vZd
AFLSpy/jyInJTyN+G19Rt72+kCRCmr0cJYsXB4yhIyeogqvM1G5gRR8JB4p+7Dst
4aaeNx75vtccBSBptzvXWWbjFgpRsYozI8gZSdErSZQWj8aVXSgc0htbFjzV7PAq
JE59FChtSCA6qSZk/qy5bVMifZUkSCB1UIT9ucOEAkRKpDyZKxV5PgkHjbdKZnuh
oUs/WCX+bbggZ78CE8BiMNj3Z4RMLcsSN/P9z0mG9gkKjpi8RZdQtHvNeOMQUDC9
jihgfar/jY3hP/kc6GBGQUJJlAcVVd5ARiqbOudBHaNipvUli/ScsxQVvAl7m7o8
k1YkkTjlWtj5l0Y+m4jVC5tzA/21h4FNhiYneRPaLin+uycjVGbdm1GAscEdQdGN
r9F0zzQJ1ixOq36EvENDEAdySe02ILtVO05tN/MMeeOPrlUrrkTltWfrLA2R72Xf
rTKF2C/2WrGsaRCbRnRQ8q4qQjMmK3vIvLQguJxHcrwH/0JCnzYaUKLsAdtn1WWB
WvP/yv7eCTjqbnh7TryyjspHG5IKOIJfq8AuuXWzPFi1QRw0llJju+0QLFrvQhq7
CZSsGlYmebcGd+5fdWQWJ39HQ3TKfQrv8Tc5YOOWY66/uA8W6K56aNMEvhpaPzry
5ex6EVhrqQCl8CpNMLqp6jL6tCvvztgfEG/eMUDtwjqaGf+qPhvtjon80wD4QC/c
VMC7t43CJIsQ2eW4wuLfqePXetdLgZsozFA9yXBTujEy4hhZev6NXAfm+EQquk5d
roOVwr/63NEuj6jpbDGb9JlR5euOTcNokf579uz84STFjp0r6eSow9ASU8QU2igR
a4nXiH+Sn1/Bgvkd8BNboki1iSr76JlspLJBzpQ2TS0jDRgN6163TFnizGAm2v73
mwNvItAWKtipnO9RJtDDExnphwrt9kSSKEAqbEPkeWeZwt73gJtu0jkWPo53fSPj
BzcIgN0gr8/nVejCMfkpIjI0t3/9bkx7DVsixb1jQfqbPCyG5Y8t8N7y8XXUi+gS
xz8onEhJou5AznCoceYlkwyXkGdsxr4cL7FCInWwU8tpRdUnxU2g/6VxZmgfKoKT
12H9oOPtZ3okAGiy9qzbRJmGMTzrpKMYMqPZxGNRnUFRV9hmpfT0rli4dbFittul
d0uG25G5fmb9MjEFV9UkdFr6NL5EsJGsLm+OumBwvic3ncOL3M1czB89VlBNigpJ
cR9Xnsb1/tjc8nwUu71HaJYit56MKipNZinklZVnufSbNK6iJ3GKh90zbCnH/HSs
uxXHfDHm6c5MXItpnJWAQkwA82/ffuP65tF97gvhBPK9pscI0BG+ta/MQlcoZ1Xd
pFrmjeREHHZapLYGzyJS5mUc6eMsxbcqNSm+pvSUh5sQIw+c8DeRs6wxeEEfOxHf
K44H/IsEIw0w1LzObmM9keikTAyCxB7ni9zdPoLLco4xq0OI/5bOUOoPgH5THosh
7DiybrVJfeXVR5SiLiV81SLMhMDroi+UreLTSQyaNvT+hjymPq1RlnBShf8Pn7Qj
wCnt7+S/I7Q9i2lQ1tG6vTxljMhLUQvl+s3jRDULEkx5AUp/CQwqwdr0f612ZSZf
XyrN6gXa9GzF/5nqqQXoSW8+YD2Sw8PgRBMcjNsZ/8uwbt7ks3WX1mjQbqdFrqbf
IXK5JNF0uUlFrjGPCClONdhAZwjXEHS2z0y6aOrL1N7xVmCJaavatNTuCrv67Bo7
EOMDro37UhySkoMgEkXrlTragv/XBRlNrakz75N7v2tfRZ3p1w+ET4yZKArgxgka
zhGbCeS+0ShvLLX3ldKpPWR+xuxBTBM3bj0T9TzFcui23P/XseUIwYNhn5mDGwM9
wUm1Sg8ciGjx05a1bb1PAHVb28uMa5Vcoh7NggYlUa1BgvHKxBJdqqZ6g3axqJvR
gwRWh3/6SW0XDQUyi2hHCfSY0saypsS2IwJHQLhuK85PvG2TGxiOB/tOwyqvvdkM
Vke/8vUfTKkB3PiRBPHdlVSlm3aiuki/LVO0omAuQpHC/HZHxCfu0jU0NQ4PdMTd
xidcWtxgIXAY1RaGT5rANsjHGqXjDgbSX6CqZAey1lH5HoDT0pA4+Ybbv+aURMM0
5V2bl0dIgzZLYx5gtEsqhfBvgG3oB03BwMS61ufkRikcdALqKlPPq5kC47WfvuA7
g4PGcAvNYi/Iohj9V4YOU67IhQKvAByCR0HWvHwGzd+W8os8D29tFw9JDlCBT3+6
PWAigev+R+OB0IOZN34rEnfOgCxTyKSk1JdJ3gVRuM3hhWJdeoabRqm/LnXNa0qW
J6UYa58mhoU94WFXd1cYlNc/M34c4Q6oQTMWszv0/OqZFmtQnNFt+i8lNjB6Asxj
J/AFQnfuAg/Iel0qV6rC2NIlc/qHaOujtw+yn86+TS91L3D0ChPpW4ST/z1NI0Zz
EyfBA8lsR26rKirKcxLXcWOZfQIg52V8p6wZZptMF1KdIP1TCJ++2loVmiTypw4p
u48WDC66pMKafaIJm6QCXNy8o1OUQGSJuBmSJQw9+qGHaALgMVzWyM13zfpBt5Wp
VHMadl0k501VcDDb59EffITIUUxuWb+nVSptahg3MJp+Ysp93o1+7/oQj750P5cF
mYtVsLc1hXCQZbcmCBg2Del/QzFE0OlmhgR5VdZj91Z+JzflieGKnwngKNwlU348
GSuURlp66pXJlfRhVRjpmILI1LoJObnGpkVkwqL6mVwWA+EF1+qu54hRL7cxY60M
vYuIzWXqapHItaxxaWCQXl8xRMdXhzunUXR4EvsRJ0Bp25B1oW1RRT1KtuZ7vIah
yoRlMAoCokiFTwwVixqvZyoCmmYXXxiRqsldZNwwPXlNvvmE+rfgj3l0gxb3q0aD
6/h1WydTgI2m4a8PxOC8XoInlCPgGIt65ZK/INvY2vfsn3oRdn7JbcHyyme7b4mo
jxLvwqMHrU7mfsFZQvxu8u/kyud068vVWmPK47Bb6/0X+9MRYr8R9Fg0Rc8/0ife
4CaZJba8vuNbmz9D7B9GkM7YXYBmF/HhjxpUtlW5Pe0HhPZordMXmwM64bNR0X5U
F0dabFApD6io7hIJjaxSbRZGAX2m7CjPqxrcBP0GvixKA2jdV2MNcK0z3DJbMxkz
CcWvom/yHFmNmom6N9UPV0hFCFkuaVENayO/XBULXAbwjWh7Vajh00ESLxnKE4bd
m4t3LK20rhnJr+Zj/zSruLofO2IY/ryBMq9FP91kiW9Y8k7+Xvbw0JlgnfCNrzEZ
0N9IfAFDMz+FYsD7n4/bZpD/TeeaHPUlnPKoUnrZNdcQ7S/1MSJ55/NbQyJ9WkVR
FbphkJ54F/Hh7VEm8SmLRMUC8mO4tIojyWdorUS22cr079UlGo4zafAUTO+GUu6D
JST1tgIQf7lojjJ00ATtuT6eMbAeZNd1+wi+zQa2nXGvgurTzaw3x+2EcFnjtrhC
S2nfsxuMWMeyFVH2mM+Ci1b4Sq++JcrHNcWEf9aJ380fjbArSBYq4uS7HGZ+GP9r
O31ao8YXXhdtB42C+egARFgJq7I3Vs9ftyHT5iRP+xzrZkGzhuiRneG41nYMrkHp
EJ7wlpS3SLLxSGI5ijSmPueRTbsuvJeWt/OHhVa86TwN2FC370dk1eZPzfOpQkQ7
850O1YowBKawILB0DqbAEuvGWvKWu5z249uOZfNZLikBPg/8j9wxWWR6m7cBEzlZ
YUAF6brZ2dri1ILw/M5Anen+IfQjljhf38ZVs8c0JGZWciuxFDgstf7qaHijmaPK
fKQJfzS9cEJJcyh88aMa3+SunxnzGH9jIWTzwv9d3uPMwvl+EOd0CNDxPegoOYui
D8BL8k0bGksuVvb+Zx/ewpgZ/tMzJb2YE6on51dDjbldbFAG/yUXhCbrhUCMYQmk
dPoYQpzc/tma79X4+GmBUpblElrYeQyN20sQli93cRYe1h80jh3HI/XubYKVpBfb
W4da3NfcDM6wupGNU1eL4+K1eTd2YFt0iD2CxZRbQwftp16skkKZnee9NNpMB2gK
hAaB48gS2YyJttn9Ki6/QqeXe/zj7NM3vQ0rRnf9heNTd1NLko2OXcAry57ygRzJ
wm/J2znsUDlzyYrKsXbE418ZGRor9lghfLdD+PnW5VtFJVFd+lXBlKjSZQz5NpUl
tJAe9daWusC3tuf9JrxuPpeumo8LCaTrWJ5Cl4SRaD+qASUyhbHpZFxLu51T0Hy3
EukZSrK09JP4cnGOlUkhhHkQFQQtawT3H/KG16ANjWr1lNu24UBdsdoJuf/nNTSx
lXvOcsWly0Y5RjwaCykyD9Ws4E/fYo7dwPxh/WUD9ltLpXwm+8PNNfAzkg+kGezi
RT0XoA/KmUhYVU4qUsOWW+YBgObzrGtVTcez+K9qWF7FfOmoKbvCEcKsYd39YoiT
2Mc0X0DKyc+TMzy1GY3u3SxaL2Rp7s1iO/H6qXsXkufyhm8MYE5GX/N93YsOVPXN
+K6sp1wkd8s2bS4i92H6AX+LPbTOV+F0so/iaSTfH1oEGbmI4nBY3P14ip/e80+7
N7NfDM8TcB4CdUfjN7DzS2vZQHiJjqWKxulS1nDQjp
ppYF/aBswg+K8g1DmchYANo+2ZPAG0lnhABZZLsEFx6UY2Ws3FznCzZoRqU7JhKv
Z5FecdkH48vRuhURjNF3ygE4ppe9pz2kjGKfU+wuaiXdnJdonOFmwJLANwQoIao+
Bqdzj0Kh3ALzkqQ4hPSIkpU21GHa1Li3khKv17vqbZQTUlziY3gdNLyNWX1wqOZf
C8KzNh40MQvI8hoDRAZbChrWPf5K9jEF7He63u5LkXv4ERpySpPP5PR+4DoC8EPU
iEyzlI6/UNUgpfoe/su/mLGVUFWiHzpRLR7kT5P2VWvJkmBFDQjFeP/S2tX5WG8N
n1HmnIV5CYcgPVLxTrk3r8lhWn9FKjkowXlBCsrjkQMr48HMXCSCnhCAgb5TbBUW
Y+LQ1P0wTdKHf9YUPlwGCgRRFvxtHzhPAwmUGM/emrEtNE2ooFHPdr5DWvPQWq1c
FZn+X9wgtrMhM8DxCflE3tVMzt563SuzxelUohjdhUZNaO8HUq66HreOS2BALKEZ
rN4nwkLyK2osFkDhqfnXzKAx87kKcQ98EVXqdZmxvadfZpYQLueZLNMtoDyqjV7m
LZ1w/KfUStcUvotbr8NwxrK51D5xij/HDNMR8puM3bg52iqGb60lW2giV7zJfeb1
0gC49NoaajqBJyaFJO+wcOwMRxalRELp0TsLOh79U+VxbYpJhqxUVVLiy+IxBWzv
jKNjOQChFraS/kZdYQwLPQCOo1v0DCEEMSvPzzNF0iJ7mPQW1VZS4I5ydEGKh/Xe
KgoOl5WUE8y9k/wAU4+0PNYqK8YIaR3rM7ZseuIlfVsWJJ2B35oKq5S900JBe2GL
aDyiYZiUSYpAPoZg8bVUPfq9bkZhFbos+KROTAVRZl4vM8p+krY+BmXw5syCSjM8
O0MfDjocTx+TS2ABc4egeFsx2eKYfpUug706cW1kB26UCTbVj+3k+GQfYgYzA7LF
dR81AZtb9LOo5V1jdymLPBpwOjLmdp4bW+xYGNYiU/7GrZ5+X4xsnjfG7oIMEFh2
k3rcfT14B560fF2Fp7Wz6UuYjroAYSBlqXIBC374G3OohL7lTaZ4a0QGjP1BgQxk
keGF5gDhbFWD7Lax8A73+YQ/vr7ostQSzaGo6E8ZG6VA6OnjYHDM+dWqpjWQdjBe
9CwUmSWTqGScuvbt7lTL+lA14U1ckLtL8OfEoIPQwnnEuun3uXTaZPMoVZ3cdGxH
RoFtdYVs1/19Ry6SeuxRvqUefbTB43FyQenmqYpQUqEQSA5AbC8fEogfu753A/oC
2z6Ay5CHNxEnVjuAm42MFYE9vEAlFSX0QQQ6Lh/OXd6xH+bMNrPNRqO94evkpF0Q
h0C/UrZqWcZRuFmeqrImRpJu472c4LbA9Lh7ahTOC3LfwviTF/CzComPQYhmfzq8
Pdi/UVGzLK1NhqtNdhwG0tLswK/GluKk3wkYJlLIAtD1Yx7oRHM8nv751uVuT1Ol
NFG3ZvA+w6HKhKG3F6Pkxbd55lbJe4EdlQ4mvB2tmvNVVKkxTJiX4N4MR+0UZUtH
hGzf7O982cTqwJXnhf26CfnAhzBkoYfnDbkB3yIsoQJECEpVzHPFcpXgk7azEvQX
U3ImOKSF33EZpVSI8ExWD6452iTRbjCEHWlks0K+mb91nFgQ9XP8tbi7qnaAsOyp
F/hNOD0veakg8E9M5wwqRXRMvVVZYWuJjGa6JExm4Ew/AMHJ/qNTpo6exjHfdo3Q
LCabp9UNA3Oa6Nw3Kryk4JOCV5keB3T0x/ZEs0BF8+tNn/vVUm9E/jc0O7uGrKPV
ej0silJRDyySwdrCvN0TxPwkzoSk0n3s/RTr8XPXLweof2ULzH6xaTdNgvsVeUwF
HrPnRliwBEz18Rok0FRLhZFDO3NcVP0DKceT1NaCwbrG6mY+fFOLDeNdJjYNE93r
bsb7EfHb7oPmB7ncr3rZUlwoeY/Z3843QjvQRhFfjwEqJQWYa+NM2/rxLNooiqMu
Pf1d5bGRIOnjrxuQQPvWIcR7j1zDeZVOo7xFY3OTEwV9lzKqtarJjQ64F1XBw3pm
FC/geqKMuloakFzC3p6henau1A7cAZMBKOw3KrgCHGWQo8K7jZnoWIMMD0Upiz40
fK6Q7To2YMr3UUKBdsnuCOgRLhzOhyNl4EmmfXmrAN4n3gHcnEyi2fVNml71b8xA
DYI2QulrbJVnhe+1OjDb2Z69NnD3WFVRkOUu+DEkW2PLMqHgjaI6qiYSXp2NQ/OV
by+nJvRZWOA6p8RIcDFezdU+rItJqCGcGE2WYl3yfVlVUmLlrn4aVU4zkI9iOsM6
0J1q/QNnQ5+qWLmI/ArTzrVJJc3BD0toE5MkCdyvOfOjCGP93feNdWxNnje3Xr50
XD2WFzuVpyAgz8Ck1PriWr1rcBwA4s+ZPEeby/whsNBHny80w74EYL30WXSyOWJ/
QKAmL4cu6KNjLCEMcLj0klcXmmqKYGtskx/3ci3F13GVj8cuJjjlVbJi1u5E76s0
ZbPLAlSm/V27wIFGGWX3e7tI2okoay8BisOukCmhDkC/NGdDqfP0BV5ZORaBD/K0
ZwZTZLo6n8H3Ztz/E1p3gR9Spj29zRmONEug4h229q02Q9Ye7p1apIdmj8EpEFGf
quAmqzSSwIY4o0h3pwKejsVBA9N9Gb65KIWGtTBvhMhie+ury+/3oJxgRA6rYTlm
hVfVFtfwGuoojOBpB5O7lUDS31TUYiLwl2OuZrmjcWodVcSIXFx9nkt0kxxxVGyW
QURvHuaqLSQ/8P3qF/4nQggnNXP
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
`pragma protect end_protected

`timescale 1ps/1ps
module ph1_ddrphy_dfi_adapter #(
    parameter DRAM_TYPE           = "DDR4",
    parameter DX_NUM              = 4  ,
    parameter RK_NUM              = 1  ,
    parameter BITS_ADR            = 18 ,
    parameter BITS_ROW            = 18 ,
    parameter BITS_COL            = 10 ,
    parameter BITS_BA             = 2  ,
    parameter BITS_BG             = 1  ,

    parameter BITS_RK             = 0  ,
    parameter BITS_CS             = 1  ,
    parameter BITS_CKE            = 1  ,
    parameter BITS_ODT            = 1  ,

    parameter CWL                 = 12 ,
    parameter CL                  = 18 ,
    parameter TCQ                 = 0

)(
    input                                  clk                   ,
    input                                  rst                   ,

    input                                  cal_done              ,

    input                                  dhi_cmd_vld_p0        ,
    input                                  dhi_cmd_vld_p1        ,
    input                                  dhi_cmd_vld_p2        ,
    input                                  dhi_cmd_vld_p3        ,
    input            [        32-1 : 0]    dhi_cmd_code_p0       ,
    input            [        32-1 : 0]    dhi_cmd_code_p1       ,
    input            [        32-1 : 0]    dhi_cmd_code_p2       ,
    input            [        32-1 : 0]    dhi_cmd_code_p3       ,
    output                                 dhi_wdata_en          ,
    input            [DX_NUM *64-1 : 0]    dhi_wdata             ,
    input            [DX_NUM * 8-1 : 0]    dhi_wmask             ,
    output    reg    [DX_NUM    -1 : 0]    dhi_rdata_vld         ,
    output    reg    [DX_NUM *64-1 : 0]    dhi_rdata             ,

    output           [         4-1 : 0]    dfi_reset_n           ,
    output    reg    [BITS_CKE*4-1 : 0]    dfi_cke               ,
    output    reg    [BITS_CS *4-1 : 0]    dfi_cs_n              ,
    output    reg    [BITS_ODT*4-1 : 0]    dfi_odt               ,
    output    reg    [           3 : 0]    dfi_act_n             ,
    output    reg    [           3 : 0]    dfi_ras_n             ,
    output    reg    [           3 : 0]    dfi_cas_n             ,
    output    reg    [           3 : 0]    dfi_we_n              ,
`ifdef MC0_DRAM_DDR4
    output    reg    [BITS_BG *4-1 : 0]    dfi_bg                ,
`endif
    output    reg    [BITS_BA *4-1 : 0]    dfi_bank              ,
    output    reg    [BITS_ADR*4-1 : 0]    dfi_address           ,
    output    reg    [DX_NUM  *4-1 : 0]    dfi_wrdata_en         ,
    output    reg    [DX_NUM *64-1 : 0]    dfi_wrdata            ,
    output    reg    [DX_NUM  *8-1 : 0]    dfi_wrdata_mask       ,
    output    reg    [DX_NUM  *4-1 : 0]    dfi_rddata_en         ,
    input            [DX_NUM  *4-1 : 0]    dfi_rddata_valid      ,
    input            [DX_NUM *64-1 : 0]    dfi_rddata  

);

localparam BITS_BANK  = BITS_BG + BITS_BA;

localparam [3 : 0] CMD_MRS = 4'b1000;
localparam [3 : 0] CMD_REF = 4'b1001;
localparam [3 : 0] CMD_PRE = 4'b1010;
localparam [3 : 0] CMD_ACT = 4'b0011;
localparam [3 : 0] CMD_WR  = 4'b1100;
localparam [3 : 0] CMD_RD  = 4'b1101;

reg   [BITS_CKE *4-1 : 0]    dfi_cke_r             ;
reg   [BITS_CS  *4-1 : 0]    dfi_cs_n_r            ;
reg   [BITS_ODT *4-1 : 0]    dfi_odt_r             ;
reg   [            3 : 0]    dfi_act_n_r           ;
reg   [            3 : 0]    dfi_ras_n_r           ;
reg   [            3 : 0]    dfi_cas_n_r           ;
reg   [            3 : 0]    dfi_we_n_r            ;
`ifdef MC0_DRAM_DDR4
reg   [BITS_BG  *4-1 : 0]    dfi_bg_r              ;
`endif
reg   [BITS_BA  *4-1 : 0]    dfi_bank_r            ;
reg   [BITS_ADR *4-1 : 0]    dfi_addr_r            ;
reg   [ DX_NUM  *4-1 : 0]    dfi_wrdata_en_r       ;
reg   [ DX_NUM*8*8-1 : 0]    dfi_wrdata_r          ;
reg   [ DX_NUM  *8-1 : 0]    dfi_wrdata_mask_r     ;
reg   [ DX_NUM  *8-1 : 0]    dfi_rddata_en_r       ;

reg   [ 15:0]     wr_en_buffer ;
reg   [ 15:0]     rd_en_buffer ;

wire  [ 3:0] cmd_p0    = (dhi_cmd_vld_p0 == 1'b1) ? dhi_cmd_code_p0[31:28] : 4'b1111;
wire  [ 3:0] cmd_p1    = (dhi_cmd_vld_p1 == 1'b1) ? dhi_cmd_code_p1[31:28] : 4'b1111;
wire  [ 3:0] cmd_p2    = (dhi_cmd_vld_p2 == 1'b1) ? dhi_cmd_code_p2[31:28] : 4'b1111;
wire  [ 3:0] cmd_p3    = (dhi_cmd_vld_p3 == 1'b1) ? dhi_cmd_code_p3[31:28] : 4'b1111;

wire  [27:0] opcode_p0 = (dhi_cmd_vld_p0 == 1'b1) ? dhi_cmd_code_p0[27: 0] : 28'h0;
wire  [27:0] opcode_p1 = (dhi_cmd_vld_p1 == 1'b1) ? dhi_cmd_code_p1[27: 0] : 28'h0;
wire  [27:0] opcode_p2 = (dhi_cmd_vld_p2 == 1'b1) ? dhi_cmd_code_p2[27: 0] : 28'h0;
wire  [27:0] opcode_p3 = (dhi_cmd_vld_p3 == 1'b1) ? dhi_cmd_code_p3[27: 0] : 28'h0;

reg   [ 3:0] cmd_p0_r ;
reg   [ 3:0] cmd_p1_r ;
reg   [ 3:0] cmd_p2_r ;
reg   [ 3:0] cmd_p3_r ;

reg   [ 3:0] cmd_p0_rk;
reg   [ 3:0] cmd_p1_rk;
reg   [ 3:0] cmd_p2_rk;
reg   [ 3:0] cmd_p3_rk;

wire  [ 3:0] cmd_rk[3:0];

reg   [19:0] addr_p0;
reg   [19:0] addr_p1;
reg   [19:0] addr_p2;
reg   [19:0] addr_p3;

reg   [ 3:0] bank_p0;
reg   [ 3:0] bank_p1;
reg   [ 3:0] bank_p2;
reg   [ 3:0] bank_p3;

wire  [3:0] wr_en    ; 
wire  [3:0] rd_en    ; 
wire  [3:0] act_en   ;
reg   [3:0] act_en_r ;

reg   [3:0] wr_en_r0 ;
reg   [3:0] wr_en_r1 ;
reg   [3:0] wr_en_r2 ;
reg   [3:0] wr_en_r3 ;
wire  [3:0] wr_en_int;
reg   [3:0] wr_en_r  ;

reg   [3:0] rd_en_r0 ;
reg   [3:0] rd_en_r1 ;
reg   [3:0] rd_en_r2 ;
reg   [3:0] rd_en_r3 ;
wire  [3:0] rd_en_int;

assign wr_en[0] = (cmd_p0 == CMD_WR);
assign wr_en[1] = (cmd_p1 == CMD_WR);
assign wr_en[2] = (cmd_p2 == CMD_WR);
assign wr_en[3] = (cmd_p3 == CMD_WR);

assign rd_en[0] = (cmd_p0 == CMD_RD);
assign rd_en[1] = (cmd_p1 == CMD_RD);
assign rd_en[2] = (cmd_p2 == CMD_RD);
assign rd_en[3] = (cmd_p3 == CMD_RD);

assign act_en[0] = (cmd_p0 == CMD_ACT);
assign act_en[1] = (cmd_p1 == CMD_ACT);
assign act_en[2] = (cmd_p2 == CMD_ACT);
assign act_en[3] = (cmd_p3 == CMD_ACT);

always @ (posedge clk)
begin
    cmd_p0_r  <= cmd_p0;
    cmd_p1_r  <= cmd_p1;
    cmd_p2_r  <= cmd_p2;
    cmd_p3_r  <= cmd_p3;
    cmd_p0_rk <= (RK_NUM == 1) ? 4'b0001 : opcode_p0[27:24];
    cmd_p1_rk <= (RK_NUM == 1) ? 4'b0001 : opcode_p1[27:24];
    cmd_p2_rk <= (RK_NUM == 1) ? 4'b0001 : opcode_p2[27:24];
    cmd_p3_rk <= (RK_NUM == 1) ? 4'b0001 : opcode_p3[27:24];
    act_en_r  <= act_en;
end

assign cmd_rk[0] = {cmd_p3_rk[0], cmd_p2_rk[0], cmd_p1_rk[0], cmd_p0_rk[0]};
assign cmd_rk[1] = {cmd_p3_rk[1], cmd_p2_rk[1], cmd_p1_rk[1], cmd_p0_rk[1]};
assign cmd_rk[2] = {cmd_p3_rk[2], cmd_p2_rk[2], cmd_p1_rk[2], cmd_p0_rk[2]};
assign cmd_rk[3] = {cmd_p3_rk[3], cmd_p2_rk[3], cmd_p1_rk[3], cmd_p0_rk[3]};

always @ (posedge clk or posedge rst)
begin
    if (rst == 1'b1) begin
        addr_p0 <= 20'h0; 
        addr_p1 <= 20'h0;
        addr_p2 <= 20'h0;
        addr_p3 <= 20'h0;
        bank_p0 <= 4'h0; 
        bank_p1 <= 4'h0; 
        bank_p2 <= 4'h0;
        bank_p3 <= 4'h0;
    end else begin
        addr_p0 <= (cmd_p0 == CMD_ACT) ? {{(20-BITS_ROW){1'b0}}, opcode_p0[0 +: BITS_ROW]} :
                   (cmd_p0 == CMD_REF) ? {3'b0, 3'b001, 3'b0,    opcode_p0[10], 10'h0    } :
                   (cmd_p0 == CMD_PRE) ? {3'b0, 3'b010, 3'b0,    opcode_p0[10], 10'h0    } :
                   (cmd_p0 == CMD_WR ) ? {3'b0, 3'b100, 4'b0,    opcode_p0[0 +: BITS_COL]} :
                   (cmd_p0 == CMD_RD ) ? {3'b0, 3'b101, 4'b0,    opcode_p0[0 +: BITS_COL]} : 20'h0; 

        addr_p1 <= (cmd_p1 == CMD_ACT) ? {{(20-BITS_ROW){1'b0}}, opcode_p1[0 +: BITS_ROW]} :
                   (cmd_p1 == CMD_REF) ? {3'b0, 3'b001, 3'b0,    opcode_p1[10], 10'h0    } :
                   (cmd_p1 == CMD_PRE) ? {3'b0, 3'b010, 3'b0,    opcode_p1[10], 10'h0    } :
                   (cmd_p1 == CMD_WR ) ? {3'b0, 3'b100, 4'b0,    opcode_p1[0 +: BITS_COL]} :
                   (cmd_p1 == CMD_RD ) ? {3'b0, 3'b101, 4'b0,    opcode_p1[0 +: BITS_COL]} : 20'h0; 

        addr_p2 <= (cmd_p2 == CMD_ACT) ? {{(20-BITS_ROW){1'b0}}, opcode_p2[0 +: BITS_ROW]} :
                   (cmd_p2 == CMD_REF) ? {3'b0, 3'b001, 3'b0,    opcode_p2[10], 10'h0    } :
                   (cmd_p2 == CMD_PRE) ? {3'b0, 3'b010, 3'b0,    opcode_p2[10], 10'h0    } :
                   (cmd_p2 == CMD_WR ) ? {3'b0, 3'b100, 4'b0,    opcode_p2[0 +: BITS_COL]} :
                   (cmd_p2 == CMD_RD ) ? {3'b0, 3'b101, 4'b0,    opcode_p2[0 +: BITS_COL]} : 20'h0; 

        addr_p3 <= (cmd_p3 == CMD_ACT) ? {{(20-BITS_ROW){1'b0}}, opcode_p3[0 +: BITS_ROW]} :
                   (cmd_p3 == CMD_REF) ? {3'b0, 3'b001, 3'b0,    opcode_p3[10], 10'h0    } :
                   (cmd_p3 == CMD_PRE) ? {3'b0, 3'b010, 3'b0,    opcode_p3[10], 10'h0    } :
                   (cmd_p3 == CMD_WR ) ? {3'b0, 3'b100, 4'b0,    opcode_p3[0 +: BITS_COL]} :
                   (cmd_p3 == CMD_RD ) ? {3'b0, 3'b101, 4'b0,    opcode_p3[0 +: BITS_COL]} : 20'h0; 

        bank_p0 <= opcode_p0[23 : 20]; 
        bank_p1 <= opcode_p1[23 : 20]; 
        bank_p2 <= opcode_p2[23 : 20]; 
        bank_p3 <= opcode_p3[23 : 20]; 
    end
end

localparam [3:0] wrLatency = (CWL - 2);

wire  [ 1:0]  wtsel  = wrLatency[3:2];
wire  [ 1:0]  wpsel  = wrLatency[1:0];

wire  [ 7:0]  wdqs_pat = (8'h0f << wpsel);

always @ (posedge clk or posedge rst)
begin
    if (rst == 1'b1) begin
        wr_en_r0 <= 4'b0000;
        wr_en_r1 <= 4'b0000;
        wr_en_r2 <= 4'b0000;
        wr_en_r3 <= 4'b0000;
    end else begin
        wr_en_r0 <= wr_en;
        wr_en_r1 <= wr_en_r0;
        wr_en_r2 <= wr_en_r1;
        wr_en_r3 <= wr_en_r2;
    end
end

assign wr_en_int = (wtsel == 2'h0) ? wr_en_r0 :
                   (wtsel == 2'h1) ? wr_en_r1 :
                   (wtsel == 2'h2) ? wr_en_r2 :
                   (wtsel == 2'h3) ? wr_en_r3 : wr_en_r1;

always @ (posedge clk or posedge rst)
begin
    if (rst == 1'b1) begin
        wr_en_buffer <= 16'h0 ;
    end else if (wr_en_int[0] == 1'b1) begin
        wr_en_buffer <= (wr_en_buffer >> 4) | (wdqs_pat << 0);
    end else if (wr_en_int[1] == 1'b1) begin
        wr_en_buffer <= (wr_en_buffer >> 4) | (wdqs_pat << 1);
    end else if (wr_en_int[2] == 1'b1) begin
        wr_en_buffer <= (wr_en_buffer >> 4) | (wdqs_pat << 2);
    end else if (wr_en_int[3] == 1'b1) begin
        wr_en_buffer <= (wr_en_buffer >> 4) | (wdqs_pat << 3);
    end else begin
        wr_en_buffer <= (wr_en_buffer >> 4);
    end
end

wire  [DX_NUM*64-1 : 0]  wdata_n;
wire  [DX_NUM*8 -1 : 0]  wmask_n;
wire  [DX_NUM*64-1 : 0]  wdata_buffer;
wire  [DX_NUM*8 -1 : 0]  wmask_buffer;
wire  [DX_NUM*64-1 : 0]  wdata_reorder;
wire  [DX_NUM*8 -1 : 0]  wmask_reorder;

assign dhi_wdata_en = (wr_en_int[3:0] != 4'b0000);

always @ (posedge clk or posedge rst)
begin
    if (rst == 1'b1)
        wr_en_r <= 4'b0000;
    else
        wr_en_r <= wr_en_int;
end

genvar n, p;

assign wdata_n = dhi_wdata;
assign wmask_n = dhi_wmask;

generate
for (n = 0; n <= DX_NUM-1; n = n+1) begin : wdata_shift_nIdx
    ph1_ddrphy_dfi_wdata_shift u_dfi_wdata_shift (
        .clk     ( clk                      ),
        .rst     ( rst                      ),
        .psel    ( wpsel                    ),
        .wr_en   ( wr_en_int                ),
        .wdata_i ( wdata_n     [n*64 +: 64] ),
        .wdata_o ( wdata_buffer[n*64 +: 64] )
    );

    ph1_ddrphy_dfi_wmask_shift u_dfi_wmask_shift (
        .clk     ( clk                    ),
        .rst     ( rst                    ),
        .psel    ( wpsel                  ),
        .wr_en   ( wr_en_int              ),
        .wdata_i ( wmask_n     [n*8 +: 8] ),
        .wdata_o ( wmask_buffer[n*8 +: 8] )
    );
end
endgenerate

for (n = 0; n <= DX_NUM-1; n = n+1) begin : wdata_n2p_nIdx
    for (p = 0; p <= 7; p = p+1) begin : wdata_n2p_pIdx
        assign wdata_reorder[p*DX_NUM*8+n*8 +: 8] = wdata_buffer[n*64+p*8 +: 8];
        assign wmask_reorder[p*DX_NUM  +n       ] = wmask_buffer[n*8 +p       ];
    end
end

localparam [7:0] rdLatency = (CL - 4);

wire  [ 3:0]  rtsel  = rdLatency[5:2];
wire  [ 1:0]  rpsel  = rdLatency[1:0];

wire  [15:0]  rden_pat = (16'h00_0f << rpsel);

always @ (posedge clk or posedge rst)
begin
    if (rst == 1'b1) begin
        rd_en_r0 <= 4'b0000;
        rd_en_r1 <= 4'b0000;
        rd_en_r2 <= 4'b0000;
        rd_en_r3 <= 4'b0000;
    end else begin
        rd_en_r0 <= rd_en;
        rd_en_r1 <= rd_en_r0;
        rd_en_r2 <= rd_en_r1;
        rd_en_r3 <= rd_en_r2;
    end
end

assign rd_en_int = (rtsel == 3'h0) ? rd_en_r0 :
                   (rtsel == 3'h1) ? rd_en_r1 :
                   (rtsel == 3'h2) ? rd_en_r2 :
                   (rtsel == 3'h3) ? rd_en_r3 : rd_en_r1;

always @ ( posedge clk or posedge rst)
begin
    if (rst == 1'b1)
        rd_en_buffer <= 16'h0 ;
    else if (rd_en_int[0] == 1'b1)
        rd_en_buffer <= (rd_en_buffer >> 4) | (rden_pat << 0);
    else if (rd_en_int[1] == 1'b1)
        rd_en_buffer <= (rd_en_buffer >> 4) | (rden_pat << 1);
    else if (rd_en_int[2] == 1'b1)  
        rd_en_buffer <= (rd_en_buffer >> 4) | (rden_pat << 2);
    else if (rd_en_int[3] == 1'b1)  
        rd_en_buffer <= (rd_en_buffer >> 4) | (rden_pat << 3);
    else
        rd_en_buffer <= (rd_en_buffer >> 4);
end

for (n = 0; n <= DX_NUM-1; n = n+1) begin : rdata_nIdx
    for (p = 0; p <= 7; p = p+1) begin : rdata_pIdx
        always @ (posedge clk) begin
            dhi_rdata[n*64+p*8 +: 8] <= dfi_rddata[p*(DX_NUM*8)+n*8 +: 8];
        end
    end
end

for (n = 0; n <= DX_NUM-1; n = n+1) begin : rvld_nIdx
    always @ (posedge clk or posedge rst)
    begin
        if (rst == 1'b1)
            dhi_rdata_vld[n] <= 1'b0;
        else
            dhi_rdata_vld[n] <= dfi_rddata_valid[n];
    end
end

assign  dfi_reset_n  = 4'b1111;

integer rk; 

always @ (posedge clk or posedge rst)
begin
    if (rst) begin
        dfi_act_n_r   <= 4'b0;
        dfi_ras_n_r   <= 4'b0;
        dfi_cas_n_r   <= 4'b0;
        dfi_we_n_r    <= 4'b0;
        dfi_cke_r     <= {(BITS_CKE*4){1'b1}};
        dfi_odt_r     <= {(BITS_ODT*4){1'b0}};
        dfi_cs_n_r    <= {(BITS_CS *4){1'b1}};
`ifdef MC0_DRAM_DDR4
        dfi_bg_r      <= {(BITS_BG *4){1'b0}};
`endif
        dfi_bank_r    <= {(BITS_BA *4){1'b0}};
        dfi_addr_r    <= {(BITS_ADR*4){1'b0}};
    end else begin

        for (rk = 0; rk < BITS_ODT; rk = rk+1) begin : cmd_map_odt
            dfi_odt_r  [0*BITS_ODT+rk] <= (DRAM_TYPE == "DDR4") ? 1'b0 : (|wr_en == 1'b1) && (cmd_rk[rk] != 4'h0) ? 1'b1 : (|rd_en == 1'b1) && (cmd_rk[rk] != 4'h0) ? 1'b0 : dfi_odt_r[0*BITS_ODT+rk];
            dfi_odt_r  [1*BITS_ODT+rk] <= (DRAM_TYPE == "DDR4") ? 1'b0 : (|wr_en == 1'b1) && (cmd_rk[rk] != 4'h0) ? 1'b1 : (|rd_en == 1'b1) && (cmd_rk[rk] != 4'h0) ? 1'b0 : dfi_odt_r[1*BITS_ODT+rk];
            dfi_odt_r  [2*BITS_ODT+rk] <= (DRAM_TYPE == "DDR4") ? 1'b0 : (|wr_en == 1'b1) && (cmd_rk[rk] != 4'h0) ? 1'b1 : (|rd_en == 1'b1) && (cmd_rk[rk] != 4'h0) ? 1'b0 : dfi_odt_r[2*BITS_ODT+rk];
            dfi_odt_r  [3*BITS_ODT+rk] <= (DRAM_TYPE == "DDR4") ? 1'b0 : (|wr_en == 1'b1) && (cmd_rk[rk] != 4'h0) ? 1'b1 : (|rd_en == 1'b1) && (cmd_rk[rk] != 4'h0) ? 1'b0 : dfi_odt_r[3*BITS_ODT+rk];
        end

        for (rk = 0; rk < BITS_CS; rk = rk+1) begin : cmd_map_cs
            dfi_cs_n_r [0*BITS_CS +rk] <= (cmd_p0_r[3:0] == 4'b1111) ? 1'b1 : (cmd_p0_rk[rk] == 1'b1) ? 1'b0 : 1'b1;
            dfi_cs_n_r [1*BITS_CS +rk] <= (cmd_p1_r[3:0] == 4'b1111) ? 1'b1 : (cmd_p1_rk[rk] == 1'b1) ? 1'b0 : 1'b1;
            dfi_cs_n_r [2*BITS_CS +rk] <= (cmd_p2_r[3:0] == 4'b1111) ? 1'b1 : (cmd_p2_rk[rk] == 1'b1) ? 1'b0 : 1'b1;
            dfi_cs_n_r [3*BITS_CS +rk] <= (cmd_p3_r[3:0] == 4'b1111) ? 1'b1 : (cmd_p3_rk[rk] == 1'b1) ? 1'b0 : 1'b1;
        end

        dfi_act_n_r[0]  <=  cmd_p0_r[3];
        dfi_act_n_r[1]  <=  cmd_p1_r[3];
        dfi_act_n_r[2]  <=  cmd_p2_r[3];
        dfi_act_n_r[3]  <=  cmd_p3_r[3];

        dfi_ras_n_r[0]  <=  (DRAM_TYPE == "DDR3") ? cmd_p0_r[2] : act_en_r[0] ? addr_p0[16] : cmd_p0_r[2]; 
        dfi_ras_n_r[1]  <=  (DRAM_TYPE == "DDR3") ? cmd_p1_r[2] : act_en_r[1] ? addr_p1[16] : cmd_p1_r[2]; 
        dfi_ras_n_r[2]  <=  (DRAM_TYPE == "DDR3") ? cmd_p2_r[2] : act_en_r[2] ? addr_p2[16] : cmd_p2_r[2]; 
        dfi_ras_n_r[3]  <=  (DRAM_TYPE == "DDR3") ? cmd_p3_r[2] : act_en_r[3] ? addr_p3[16] : cmd_p3_r[2]; 

        dfi_cas_n_r[0]  <=  (DRAM_TYPE == "DDR3") ? cmd_p0_r[1] : act_en_r[0] ? addr_p0[15] : cmd_p0_r[1]; 
        dfi_cas_n_r[1]  <=  (DRAM_TYPE == "DDR3") ? cmd_p1_r[1] : act_en_r[1] ? addr_p1[15] : cmd_p1_r[1]; 
        dfi_cas_n_r[2]  <=  (DRAM_TYPE == "DDR3") ? cmd_p2_r[1] : act_en_r[2] ? addr_p2[15] : cmd_p2_r[1]; 
        dfi_cas_n_r[3]  <=  (DRAM_TYPE == "DDR3") ? cmd_p3_r[1] : act_en_r[3] ? addr_p3[15] : cmd_p3_r[1]; 

        dfi_we_n_r [0]  <=  (DRAM_TYPE == "DDR3") ? cmd_p0_r[0] : act_en_r[0] ? addr_p0[14] : cmd_p0_r[0]; 
        dfi_we_n_r [1]  <=  (DRAM_TYPE == "DDR3") ? cmd_p1_r[0] : act_en_r[1] ? addr_p1[14] : cmd_p1_r[0]; 
        dfi_we_n_r [2]  <=  (DRAM_TYPE == "DDR3") ? cmd_p2_r[0] : act_en_r[2] ? addr_p2[14] : cmd_p2_r[0]; 
        dfi_we_n_r [3]  <=  (DRAM_TYPE == "DDR3") ? cmd_p3_r[0] : act_en_r[3] ? addr_p3[14] : cmd_p3_r[0]; 

`ifdef MC0_DRAM_DDR4
        dfi_bg_r  [BITS_BG*0  +: BITS_BG ] <= bank_p0[BITS_BA +: BITS_BG];
        dfi_bg_r  [BITS_BG*1  +: BITS_BG ] <= bank_p1[BITS_BA +: BITS_BG];
        dfi_bg_r  [BITS_BG*2  +: BITS_BG ] <= bank_p2[BITS_BA +: BITS_BG];
        dfi_bg_r  [BITS_BG*3  +: BITS_BG ] <= bank_p3[BITS_BA +: BITS_BG];
`endif

        dfi_bank_r[BITS_BA*0  +: BITS_BA ] <= bank_p0[0 +: BITS_BA];
        dfi_bank_r[BITS_BA*1  +: BITS_BA ] <= bank_p1[0 +: BITS_BA];
        dfi_bank_r[BITS_BA*2  +: BITS_BA ] <= bank_p2[0 +: BITS_BA];
        dfi_bank_r[BITS_BA*3  +: BITS_BA ] <= bank_p3[0 +: BITS_BA];

        dfi_addr_r[BITS_ADR*0 +: BITS_ADR] <= addr_p0[0 +: BITS_ADR];
        dfi_addr_r[BITS_ADR*1 +: BITS_ADR] <= addr_p1[0 +: BITS_ADR];
        dfi_addr_r[BITS_ADR*2 +: BITS_ADR] <= addr_p2[0 +: BITS_ADR];
        dfi_addr_r[BITS_ADR*3 +: BITS_ADR] <= addr_p3[0 +: BITS_ADR];
    end
end

always @ (*) begin
    dfi_cke     <= dfi_cke_r     ;
    dfi_odt     <= dfi_odt_r     ;
    dfi_cs_n    <= dfi_cs_n_r    ;

    dfi_act_n   <= dfi_act_n_r   ;
    dfi_ras_n   <= dfi_ras_n_r   ;
    dfi_cas_n   <= dfi_cas_n_r   ;
    dfi_we_n    <= dfi_we_n_r    ;
`ifdef MC0_DRAM_DDR4
    dfi_bg      <= dfi_bg_r      ;
`endif
    dfi_bank    <= dfi_bank_r    ;
    dfi_address <= dfi_addr_r    ;
end

for (p = 0; p <= 3; p = p+1) begin : pIdx
    always @ (*) begin
        dfi_wrdata_en[DX_NUM*p +: DX_NUM] <= {DX_NUM{wr_en_buffer[p]}};
        dfi_rddata_en[DX_NUM*p +: DX_NUM] <= {DX_NUM{rd_en_buffer[p]}};
    end
end

always @ (*) begin
    dfi_wrdata      = wdata_reorder;
    dfi_wrdata_mask = (DRAM_TYPE == "DDR4") ? ~wmask_reorder : wmask_reorder; 
end

endmodule

`timescale 1ps/1ps

module ph1_ddrphy_dfi_wdata_shift (
    input          clk    ,
    input          rst    ,
    input   [ 1:0] psel   ,
    input   [ 3:0] wr_en  ,
    input   [63:0] wdata_i,
    output  [63:0] wdata_o
);

wire [     7:0]  sel;
wire [3*64-1:0]  wdata;
reg  [3*64-1:0]  buffer;

assign sel   = {(psel+2), 1'b0};
assign wdata = wdata_i << {sel, 3'b000}; 

always @ (posedge clk or posedge rst)
begin
    if (rst == 1'b1)
        buffer <= {(3*64){1'b0}};
    else if (wr_en[0] == 1'b1)
        buffer <= (buffer >> 64) | (wdata << 0*8);
    else if (wr_en[1] == 1'b1)
        buffer <= (buffer >> 64) | (wdata << 2*8);
    else if (wr_en[2] == 1'b1)
        buffer <= (buffer >> 64) | (wdata << 4*8);
    else if (wr_en[3] == 1'b1)
        buffer <= (buffer >> 64) | (wdata << 6*8);
    else
        buffer <= (buffer >> 64);
end

assign wdata_o = buffer[63:0];

endmodule

`timescale 1ps/1ps

module ph1_ddrphy_dfi_wmask_shift (
    input          clk    ,
    input          rst    ,
    input   [ 1:0] psel   ,
    input   [ 3:0] wr_en  ,
    input   [ 7:0] wdata_i,
    output  [ 7:0] wdata_o
);

wire [    3:0]  sel;
wire [3*8-1:0]  wdata;
reg  [3*8-1:0]  buffer;

assign sel   = (psel+2) << 1;
assign wdata = wdata_i << sel;

always @ (posedge clk or posedge rst)
begin
    if (rst == 1'b1)
        buffer <= {(3*8){1'b0}};
    else if (wr_en[0] == 1'b1)
        buffer <= (buffer >> 8) | (wdata << 0);
    else if (wr_en[1] == 1'b1)
        buffer <= (buffer >> 8) | (wdata << 2);
    else if (wr_en[2] == 1'b1)
        buffer <= (buffer >> 8) | (wdata << 4);
    else if (wr_en[3] == 1'b1)
        buffer <= (buffer >> 8) | (wdata << 6);
    else
        buffer <= (buffer >> 8);
end

assign wdata_o = buffer[7:0];

endmodule

`timescale 1ps/1ps

module ph1_ddrphy_wrapper (

    sys_clk              ,
    sys_rst_n            ,

`ifdef MC0_DRAM_DDR4
    ddr_ck_t             ,
    ddr_ck_c             ,
    ddr_reset_n          ,
    ddr_cke              ,
    ddr_odt              ,
    ddr_cs_n             ,
    ddr_act_n            ,
    ddr_bg               ,
    ddr_ba               ,
    ddr_addr             ,
    ddr_dqs_t            ,
    ddr_dqs_c            ,
    ddr_dq               ,
    ddr_dm_dbi           ,
    ddr_parity           ,
    ddr_alert_n          ,
`elsif MC0_DRAM_DDR3
    ddr_ck_p             ,
    ddr_ck_n             ,
    ddr_reset_n          ,
    ddr_cke              ,
    ddr_odt              ,
    ddr_cs_n             ,
    ddr_ras_n            ,
    ddr_cas_n            ,
    ddr_we_n             ,
    ddr_ba               ,
    ddr_addr             ,
    ddr_dqs_p            ,
    ddr_dqs_n            ,
    ddr_dq               ,
    ddr_dm               ,
`endif

    ctl_ram_rst_n        ,
    ctl_ram_cke          ,

    dfi_clk              ,
    dfi_reset_n          ,
    dfi_cke              ,
    dfi_odt              ,
    dfi_cs_n             ,
    dfi_ras_n            ,
    dfi_cas_n            ,
    dfi_we_n             ,
`ifdef MC0_DRAM_DDR4
    dfi_act_n            ,
    dfi_bg               ,
`endif
    dfi_bank             ,
    dfi_address          ,

`ifdef MC0_DRAM_DDR4
    dfi_parity_in        ,
    dfi_alert_n          ,
`endif

    dfi_wrdata_en        ,
    dfi_wrdata           ,
    dfi_wrdata_mask      ,
    dfi_rddata_en        ,
    dfi_rddata_valid     ,
    dfi_rddata           ,

    dfi_ctrlupd_req      ,
    dfi_ctrlupd_ack      ,
    dfi_phyupd_req       ,
    dfi_phyupd_ack       ,
    dfi_phyupd_type      ,

    uart_rxd             ,
    uart_txd             ,

    apb_clk              ,
    mcu_busy             ,
    user_update          ,
    user_ram_addr        ,
    user_ram_wr_en       ,
    user_ram_rd_en       ,
    user_ram_wr_data     ,
    user_ram_rd_data     ,

    user_clk             ,
    ddrphy_rst_n         ,
    pll_locked           ,

    pzq_cal_done_o       ,
    pzq_cal_done_i       ,

    ddr_init_cal_done    ,
    ddr_init_cal_step    ,
    ddr_init_cal_err
);

parameter DEVICE              = "PH1A90";
parameter TCK                 = 1876;
parameter CTRL_INDEX          = 0;
parameter DRAM_TYPE           = "DDR3";
parameter DM_DBI              = "DM_NODBI";

parameter BYTE_LANE_0         = 4'b0000;
parameter BYTE_LANE_1         = 4'b1111;
parameter BYTE_LANE_2         = 4'b0000;

parameter DATA_CTRL_0         = 4'b0000;
parameter DATA_CTRL_1         = 4'b1100;
parameter DATA_CTRL_2         = 4'b0000;

parameter CK_MAP              = 48'h107_106;
parameter RESET_MAP           = 12'h13B;
parameter CKE_MAP             = 24'hfff_10C;
parameter ODT_MAP             = 24'hfff_111;
parameter CS_MAP              = 24'hfff_101;

parameter ACT_MAP             = 12'hfff;
parameter RAS_MAP             = 12'h12B;
parameter CAS_MAP             = 12'h119;
parameter WE_MAP              = 12'h117;

parameter BANK_GROUP_MAP      = 24'hfff_fff;
parameter BANK_MAP            = 36'h116_11B_118;
parameter ADDR_MAP            = 216'h000_000_000_000_10A_11A_105_110_108_102_10B_103_100_112_115_109_113_114;

parameter PARITY_MAP          = 12'hfff;
parameter ALERT_MAP           = 12'hfff;

parameter DQS_BYTE_MAP        = 216'h000_000_000_000_000_000_000_000_000_000_000_000_000_000_127_126_137_136;
parameter DM_MAP              = 108'h000_000_000_000_000_000_000_121_13a;
parameter DATA0_MAP           = 96'h138_135_139_134_131_132_133_130;
parameter DATA1_MAP           = 96'h122_123_124_125_128_12A_129_120;
parameter DATA2_MAP           = 96'h000_000_000_000_000_000_000_000;
parameter DATA3_MAP           = 96'h000_000_000_000_000_000_000_000;
parameter DATA4_MAP           = 96'h000_000_000_000_000_000_000_000;
parameter DATA5_MAP           = 96'h000_000_000_000_000_000_000_000;
parameter DATA6_MAP           = 96'h000_000_000_000_000_000_000_000;
parameter DATA7_MAP           = 96'h000_000_000_000_000_000_000_000;
parameter DATA8_MAP           = 96'h000_000_000_000_000_000_000_000;
parameter LOC_DX_BYTELANE_MAP = 72'h00_00_00_00_00_00_00_12_13;
parameter LOC_AC_BYTELANE_MAP = 32'h11_10;

parameter AC_WIDTH            = 2;
parameter CK_WIDTH            = 1;
parameter ODT_WIDTH           = 1;
parameter CKE_WIDTH           = 1;
parameter CS_WIDTH            = 1;

parameter ROW_WIDTH           = 14;
parameter ADDR_WIDTH          = 14;
parameter BG_WIDTH            = 0;
parameter BANK_WIDTH          = 3;

parameter DQS_WIDTH           = 2;
parameter DQ_WIDTH            = 16;
parameter DM_WIDTH            = 2;

parameter USER_CLK_EN         = 4'b0000;
parameter CLOCK_RATE          = 50_000_000;

input                      sys_clk           ;
input                      sys_rst_n         ;

`ifdef MC0_DRAM_DDR4
output [  CK_WIDTH  -1:0]  ddr_ck_t          ;
output [  CK_WIDTH  -1:0]  ddr_ck_c          ;
output                     ddr_reset_n       ;
output [ CKE_WIDTH  -1:0]  ddr_cke           ;
output [ ODT_WIDTH  -1:0]  ddr_odt           ;
output [  CS_WIDTH  -1:0]  ddr_cs_n          ;
output                     ddr_act_n         ;
output [BANK_WIDTH  -1:0]  ddr_ba            ;
output [  BG_WIDTH  -1:0]  ddr_bg            ;
output [ADDR_WIDTH  -1:0]  ddr_addr          ;
output                     ddr_parity        ;
input                      ddr_alert_n       ;
inout  [ DQS_WIDTH  -1:0]  ddr_dqs_t         ;
inout  [ DQS_WIDTH  -1:0]  ddr_dqs_c         ;
inout  [  DQ_WIDTH  -1:0]  ddr_dq            ;
inout  [  DM_WIDTH  -1:0]  ddr_dm_dbi        ;
`elsif MC0_DRAM_DDR3
output [  CK_WIDTH  -1:0]  ddr_ck_p          ;
output [  CK_WIDTH  -1:0]  ddr_ck_n          ;
output                     ddr_reset_n       ;
output [ CKE_WIDTH  -1:0]  ddr_cke           ;
output [ ODT_WIDTH  -1:0]  ddr_odt           ;
output [  CS_WIDTH  -1:0]  ddr_cs_n          ;
output                     ddr_ras_n         ;
output                     ddr_cas_n         ;
output                     ddr_we_n          ;
output [BANK_WIDTH  -1:0]  ddr_ba            ;
output [ADDR_WIDTH  -1:0]  ddr_addr          ;
inout  [ DQS_WIDTH  -1:0]  ddr_dqs_p         ;
inout  [ DQS_WIDTH  -1:0]  ddr_dqs_n         ;
inout  [  DQ_WIDTH  -1:0]  ddr_dq            ;
inout  [  DM_WIDTH  -1:0]  ddr_dm            ;
`endif

output                     ctl_ram_rst_n     ;
output                     ctl_ram_cke       ;

output                     dfi_clk           ;
input  [             3:0]  dfi_reset_n       ;
input  [ CKE_WIDTH*4-1:0]  dfi_cke           ;
input  [ ODT_WIDTH*4-1:0]  dfi_odt           ;
input  [ CS_WIDTH *4-1:0]  dfi_cs_n          ;
input  [             3:0]  dfi_ras_n         ;
input  [             3:0]  dfi_cas_n         ;
input  [             3:0]  dfi_we_n          ;
`ifdef MC0_DRAM_DDR4
input  [             3:0]  dfi_act_n         ;
input  [  BG_WIDTH*4-1:0]  dfi_bg            ;
`endif
input  [BANK_WIDTH*4-1:0]  dfi_bank          ;
input  [ADDR_WIDTH*4-1:0]  dfi_address       ;

`ifdef MC0_DRAM_DDR4
input  [             3:0]  dfi_parity_in     ;
output [             3:0]  dfi_alert_n       ;
`endif

input  [ DQS_WIDTH*4-1:0]  dfi_wrdata_en     ;
input  [  DQ_WIDTH*8-1:0]  dfi_wrdata        ;
input  [  DM_WIDTH*8-1:0]  dfi_wrdata_mask   ;
input  [ DQS_WIDTH*4-1:0]  dfi_rddata_en     ;
output [ DQS_WIDTH*4-1:0]  dfi_rddata_valid  ;
output [  DQ_WIDTH*8-1:0]  dfi_rddata        ;

input  [             1:0]  dfi_ctrlupd_req   ;
output [             1:0]  dfi_ctrlupd_ack   ;
output [             1:0]  dfi_phyupd_req    ;
input  [             1:0]  dfi_phyupd_ack    ;
output [             3:0]  dfi_phyupd_type   ;

input                      uart_rxd          ;
output                     uart_txd          ;

output                     apb_clk           ;
output                     mcu_busy          ;
input                      user_update       ;
input  [  7:0]             user_ram_addr     ;
input                      user_ram_wr_en    ;
input                      user_ram_rd_en    ;
input  [ 31:0]             user_ram_wr_data  ;
output [ 31:0]             user_ram_rd_data  ;

output [  3:0]             user_clk          ;
output                     ddrphy_rst_n      ;
output                     pll_locked        ;
output                     pzq_cal_done_o    ;
input                      pzq_cal_done_i    ;
output                     ddr_init_cal_done ;
output [  7:0]             ddr_init_cal_err  ;
output [  7:0]             ddr_init_cal_step ;

localparam WDM  = (DM_DBI == "DM_NODBI"    ) ? "ENABLE" :
                  (DM_DBI == "DM_DBIRD"    ) ? "ENABLE" : "DISABLE";
localparam WDBI = (DM_DBI == "NODM_DBIWR"  ) ? "ENABLE" :
                  (DM_DBI == "NODM_DBIWRRD") ? "ENABLE" : "DISABLE";
localparam RDBI = (DM_DBI == "DM_DBIRD"    ) ? "ENABLE" :
                  (DM_DBI == "NODM_DBIRD"  ) ? "ENABLE" :
                  (DM_DBI == "NODM_DBIWRRD") ? "ENABLE" : "DISABLE";

wire  [ 31:0]    ddrphy_sr; 
wire  [ 31:0]    ddrphy_cr; 

wire  [  2:0]    ctl_clk;
wire  [  2:0]    ddr_clk;
reg   [  3:0]    ddrphy_rst_r; 
reg   [  3:0]    apb_rst_r;    

wire             ppc_dfi_clk;
wire  [  3:0]    ppc_dfi_reset_n;
wire  [  7:0]    ppc_dfi_cke;
wire  [  7:0]    ppc_dfi_odt;
wire  [  7:0]    ppc_dfi_cs_n;
wire  [  3:0]    ppc_dfi_act_n;
wire  [  3:0]    ppc_dfi_ras_n;
wire  [  3:0]    ppc_dfi_cas_n;
wire  [  3:0]    ppc_dfi_we_n;
wire  [  7:0]    ppc_dfi_bg;
wire  [ 11:0]    ppc_dfi_bank;
wire  [ 71:0]    ppc_dfi_address;
wire  [ 35:0]    ppc_dfi_wrdata_en;
wire  [575:0]    ppc_dfi_wrdata;
wire  [ 71:0]    ppc_dfi_wrdata_mask;
wire  [ 35:0]    ppc_dfi_rddata_en;
wire  [ 35:0]    ppc_dfi_rddata_valid;
wire  [575:0]    ppc_dfi_rddata;

wire  [  3:0]    ppc_dfi_parity ;
wire  [  3:0]    ppc_dfi_alert_n;

wire             apb_pclk;
wire             apb_prst_n;
wire             apb_psel;
wire             apb_penable;
wire             apb_pwrite;
wire  [ 31:0]    apb_paddr;
wire  [ 31:0]    apb_pwdata;
wire  [ 31:0]    apb_prdata;
wire             apb_pready;

wire             dfx_apb_psel;
wire             dfx_apb_penable;
wire             dfx_apb_pwrite;
wire  [ 15:0]    dfx_apb_paddr;
wire  [ 31:0]    dfx_apb_pwdata;
wire  [ 31:0]    dfx_apb_prdata;
wire             dfx_apb_pready;

wire             uram_clr;
wire             uram_en;
wire  [  7:0]    uram_addr;
wire  [ 31:0]    uram_rdata;

wire  [  3:0]    cfg_bit_deskew = 4'h0;

wire  [  3:0]    cfg_wdm        = (WDM  == "ENABLE") ? 4'h1 : 4'h0;
wire  [  3:0]    cfg_wdbi       = (WDBI == "ENABLE") ? 4'h1 : 4'h0;
wire  [  3:0]    cfg_rdbi       = (RDBI == "ENABLE") ? 4'h1 : 4'h0;

wire  [  3:0]    cfg_gate_fix   = (DEVICE == "PH1A400") ? 4'h1 : 4'h0;

ph1_ddrphy_clk_gen u_ddrphy_clk_gen (
    .ref_clk          ( sys_clk          ),
    .sys_rst          (~sys_rst_n        ),

    .cfg_clk          ( apb_pclk         ),
    .dfi_clk          ( dfi_clk          ),
    .ctl_clk          ( ctl_clk          ),
    .ddr_clk          ( ddr_clk          ),
    .usr_clk          ( user_clk         ),
    .pll_lock         ( pll_locked       )
);

always @ (posedge dfi_clk or negedge pll_locked)
begin
    if (pll_locked == 1'b0)
        ddrphy_rst_r <= 4'h0;
    else
        ddrphy_rst_r <= {ddrphy_rst_r[2:0], 1'b1};
end

assign ddrphy_rst_n = ddrphy_rst_r[3];

always @ (posedge apb_pclk or negedge pll_locked)
begin
    if (pll_locked == 1'b0)
        apb_rst_r <= 4'h0;
    else
        apb_rst_r <= {apb_rst_r[2:0], 1'b1};
end

assign apb_prst_n = apb_rst_r[3];

assign apb_clk    = apb_pclk;

ph1_ddrphy_mcu_wrapper u_ddrphy_mcu (
    .i_clk             ( apb_pclk         ),
    .i_rst             (~apb_prst_n       ),

    .o_apb_psel        ( apb_psel         ),
    .o_apb_penable     ( apb_penable      ),
    .o_apb_pwrite      ( apb_pwrite       ),
    .o_apb_paddr       ( apb_paddr        ),
    .o_apb_pwdata      ( apb_pwdata       ),
    .i_apb_prdata      ( apb_prdata       ),
    .i_apb_pready      ( apb_pready       ),

    .ddrphy_cr         ( ddrphy_cr        ),
    .ddrphy_sr         ( ddrphy_sr        ),

    .uram_en           ( uram_en          ),
    .uram_clr          ( uram_clr         ),
    .uram_addr         ( uram_addr        ),
    .uram_rdata        ( uram_rdata       ),

    .dfx_apb_psel      ( dfx_apb_psel     ),
    .dfx_apb_penable   ( dfx_apb_penable  ),
    .dfx_apb_pwrite    ( dfx_apb_pwrite   ),
    .dfx_apb_paddr     ( dfx_apb_paddr    ),
    .dfx_apb_pwdata    ( dfx_apb_pwdata   ),
    .dfx_apb_prdata    ( dfx_apb_prdata   ),
    .dfx_apb_pready    ( dfx_apb_pready   ),

    .o_uart_txd        ( uart_txd         ),
    .i_uart_rxd        ( uart_rxd         )
);

assign ddr_init_cal_step = ddrphy_sr[ 7:0];
assign ddr_init_cal_err  = ddrphy_sr[15:8];
assign ddr_init_cal_done = ddrphy_sr[31];
assign mcu_busy          = ddrphy_sr[30];
assign pzq_cal_done_o    = ddrphy_sr[24];

`ifdef PH1_DDRPHY_SIM
assign ddrphy_cr = {4'h1, 4'h0,                 cfg_rdbi, cfg_wdbi, cfg_wdm, cfg_bit_deskew, cfg_gate_fix, 4'h0};
`else
assign ddrphy_cr = {4'h0, 3'b0, pzq_cal_done_i, cfg_rdbi, cfg_wdbi, cfg_wdm, cfg_bit_deskew, cfg_gate_fix, 4'h0};
`endif

ph1_ddrphy_uram2apb u_uram2apb (

    .clk          ( apb_pclk         ),
    .rst          (~apb_prst_n       ),

    .uram_update  ( user_update      ),
    .uram_addr    ({8'h0, user_ram_addr}),
    .uram_wen     ( user_ram_wr_en   ),
    .uram_wdata   ( user_ram_wr_data ),
    .uram_ren     ( user_ram_rd_en   ),
    .uram_rdata   ( user_ram_rd_data ),

    .apb_psel     ( dfx_apb_psel     ),
    .apb_penable  ( dfx_apb_penable  ),
    .apb_pwrite   ( dfx_apb_pwrite   ),
    .apb_paddr    ( dfx_apb_paddr    ),
    .apb_pwdata   ( dfx_apb_pwdata   ),
    .apb_prdata   ( dfx_apb_prdata   ),
    .apb_pready   ( dfx_apb_pready   ),

    .i_uram_clr   ( uram_clr         ),
    .o_uram_en    ( uram_en          ),
    .o_uram_addr  ( uram_addr        ),
    .i_uram_rdata ( uram_rdata       )
);

ph1_ddrphy_dfi_glue #(
    .DX_NUM    (  DQS_WIDTH ),
    .BITS_CK   (   CK_WIDTH ),
    .BITS_CKE  (  CKE_WIDTH ),
    .BITS_ODT  (  ODT_WIDTH ),
    .BITS_CS   (   CS_WIDTH ),
    .BITS_BG   (   BG_WIDTH ),
    .BITS_BA   ( BANK_WIDTH ),
    .BITS_ROW  (  ROW_WIDTH ),
    .BITS_ADR  ( ADDR_WIDTH )
) u_ddrphy_dfi_glue (
    .clk                  ( dfi_clk              ),
    .rst_n                ( ddrphy_rst_n         ),

    .dfi_reset_n          ( dfi_reset_n          ),
    .dfi_cke              ( dfi_cke              ),
    .dfi_odt              ( dfi_odt              ),
    .dfi_cs_n             ( dfi_cs_n             ),
    .dfi_ras_n            ( dfi_ras_n            ),
    .dfi_cas_n            ( dfi_cas_n            ),
    .dfi_we_n             ( dfi_we_n             ),
`ifdef MC0_DRAM_DDR4
    .dfi_act_n            ( dfi_act_n            ),
    .dfi_bg               ( dfi_bg               ),
`endif
    .dfi_bank             ( dfi_bank             ),
    .dfi_address          ( dfi_address          ),
`ifdef MC0_DRAM_DDR4
    .dfi_parity           ( dfi_parity_in        ),
    .dfi_alert_n          ( dfi_alert_n          ),
`endif

    .dfi_wrdata_en        ( dfi_wrdata_en        ),
    .dfi_wrdata           ( dfi_wrdata           ),
    .dfi_wrdata_mask      ( dfi_wrdata_mask      ),
    .dfi_rddata_en        ( dfi_rddata_en        ),
    .dfi_rddata_valid     ( dfi_rddata_valid     ),
    .dfi_rddata           ( dfi_rddata           ),

    .ppc_dfi_reset_n      ( ppc_dfi_reset_n      ),
    .ppc_dfi_cke          ( ppc_dfi_cke          ),
    .ppc_dfi_odt          ( ppc_dfi_odt          ),
    .ppc_dfi_cs_n         ( ppc_dfi_cs_n         ),
    .ppc_dfi_ras_n        ( ppc_dfi_ras_n        ),
    .ppc_dfi_cas_n        ( ppc_dfi_cas_n        ),
    .ppc_dfi_we_n         ( ppc_dfi_we_n         ),
    .ppc_dfi_act_n        ( ppc_dfi_act_n        ),
    .ppc_dfi_bg           ( ppc_dfi_bg           ),
    .ppc_dfi_bank         ( ppc_dfi_bank         ),
    .ppc_dfi_address      ( ppc_dfi_address      ),
    .ppc_dfi_parity       ( ppc_dfi_parity       ),
    .ppc_dfi_alert_n      ( ppc_dfi_alert_n      ),
    .ppc_dfi_wrdata_en    ( ppc_dfi_wrdata_en    ),
    .ppc_dfi_wrdata       ( ppc_dfi_wrdata       ),
    .ppc_dfi_wrdata_mask  ( ppc_dfi_wrdata_mask  ),
    .ppc_dfi_rddata_en    ( ppc_dfi_rddata_en    ),
    .ppc_dfi_rddata_valid ( ppc_dfi_rddata_valid ),
    .ppc_dfi_rddata       ( ppc_dfi_rddata       )
);

ph1_ddrphy_top #(
    .DEVICE              ( DEVICE        ),
    .MC_TCK              ( TCK           ),
    .MC_IDX              ( CTRL_INDEX    ),

    .WDM                 ( WDM           ),
    .WDBI                ( WDBI          ),
    .RDBI                ( RDBI          ),

    .AC_NUM              ( AC_WIDTH      ),
    .DX_NUM              ( DQS_WIDTH     ),
    .CK_WIDTH            ( CK_WIDTH      ),
    .CS_WIDTH            ( CS_WIDTH      ),
    .CKE_WIDTH           ( CKE_WIDTH     ),
    .ODT_WIDTH           ( ODT_WIDTH     ),
    .BG_WIDTH            ( BG_WIDTH      ),
    .BA_WIDTH            ( BANK_WIDTH    ),
    .ADR_WIDTH           ( ADDR_WIDTH    ),
    .DQS_WIDTH           ( DQS_WIDTH     ),
    .DQ_WIDTH            ( DQ_WIDTH      ),
    .DM_WIDTH            ( DM_WIDTH      ),

    .BK0_BYTE            ( BYTE_LANE_0   ),
    .BK1_BYTE            ( BYTE_LANE_1   ),
    .BK2_BYTE            ( BYTE_LANE_2   ),
    .BK0_DX_EN           ( DATA_CTRL_0   ),
    .BK1_DX_EN           ( DATA_CTRL_1   ),
    .BK2_DX_EN           ( DATA_CTRL_2   ),

    .CK_MAP              ( CK_MAP        ),
    .RST_MAP             ( RESET_MAP     ),
    .CKE_MAP             ( CKE_MAP       ),
    .ODT_MAP             ( ODT_MAP       ),
    .CS_MAP              ( CS_MAP        ),
    .ACT_MAP             ( ACT_MAP       ),
    .RAS_MAP             ( RAS_MAP       ),
    .CAS_MAP             ( CAS_MAP       ),
    .WE_MAP              ( WE_MAP        ),

    .BG_MAP              ( BANK_GROUP_MAP),
    .BA_MAP              ( BANK_MAP      ),
    .ADR_MAP             ( ADDR_MAP      ),

    .PAR_MAP             ( PARITY_MAP    ),
    .ALT_MAP             ( ALERT_MAP     ),

    .DQS_MAP             ( DQS_BYTE_MAP  ),
    .DM_MAP              ( DM_MAP        ),
    .DATA0_MAP           ( DATA0_MAP     ),
    .DATA1_MAP           ( DATA1_MAP     ),
    .DATA2_MAP           ( DATA2_MAP     ),
    .DATA3_MAP           ( DATA3_MAP     ),
    .DATA4_MAP           ( DATA4_MAP     ),
    .DATA5_MAP           ( DATA5_MAP     ),
    .DATA6_MAP           ( DATA6_MAP     ),
    .DATA7_MAP           ( DATA7_MAP     ),
    .DATA8_MAP           ( DATA8_MAP     ),

    .AC_BYTE_MAP         ( LOC_AC_BYTELANE_MAP ),
    .DX_BYTE_MAP         ( LOC_DX_BYTELANE_MAP )

) u_ddrphy_top (

    .usr_rst_n           ( ddrphy_rst_n         ),
    .usr_clk             ( dfi_clk              ), 
    .ctl_clk             ( ctl_clk              ), 
    .ddr_clk             ( ddr_clk              ), 

    .cal_done            ( ddr_init_cal_done    ),

`ifdef MC0_DRAM_DDR4
    .ddr_ck_t            ( ddr_ck_t             ),
    .ddr_ck_c            ( ddr_ck_c             ),
    .ddr_reset_n         ( ddr_reset_n          ),
    .ddr_cke             ( ddr_cke              ),
    .ddr_odt             ( ddr_odt              ),
    .ddr_cs_n            ( ddr_cs_n             ),
    .ddr_act_n           ( ddr_act_n            ),
    .ddr_bg              ( ddr_bg               ),
    .ddr_ba              ( ddr_ba               ),
    .ddr_addr            ( ddr_addr             ),
    .ddr_dqs_t           ( ddr_dqs_t            ),
    .ddr_dqs_c           ( ddr_dqs_c            ),
    .ddr_dq              ( ddr_dq               ),
    .ddr_dm_n            ( ddr_dm_dbi           ),

    .ddr_parity          ( ddr_parity           ),
    .ddr_alert_n         ( ddr_alert_n          ),
`else
    .ddr_ck_p            ( ddr_ck_p             ),
    .ddr_ck_n            ( ddr_ck_n             ),
    .ddr_reset_n         ( ddr_reset_n          ),
    .ddr_cke             ( ddr_cke              ),
    .ddr_odt             ( ddr_odt              ),
    .ddr_cs_n            ( ddr_cs_n             ),
    .ddr_ras_n           ( ddr_ras_n            ),
    .ddr_cas_n           ( ddr_cas_n            ),
    .ddr_we_n            ( ddr_we_n             ),
    .ddr_ba              ( ddr_ba               ),
    .ddr_addr            ( ddr_addr             ),
    .ddr_dqs_p           ( ddr_dqs_p            ),
    .ddr_dqs_n           ( ddr_dqs_n            ),
    .ddr_dq              ( ddr_dq               ),
    .ddr_dm              ( ddr_dm               ),
`endif

    .ctl_ram_rst_n       ( ctl_ram_rst_n        ),
    .ctl_ram_cke         ( ctl_ram_cke          ),

    .dfi_reset_n         ( ppc_dfi_reset_n      ),
    .dfi_cke             ( ppc_dfi_cke          ),
    .dfi_odt             ( ppc_dfi_odt          ),
    .dfi_cs_n            ( ppc_dfi_cs_n         ),
    .dfi_act_n           ( ppc_dfi_act_n        ),
    .dfi_ras_n           ( ppc_dfi_ras_n        ),
    .dfi_cas_n           ( ppc_dfi_cas_n        ),
    .dfi_we_n            ( ppc_dfi_we_n         ),
    .dfi_bg              ( ppc_dfi_bg           ),
    .dfi_bank            ( ppc_dfi_bank         ),
    .dfi_address         ( ppc_dfi_address      ),

    .dfi_parity          ( ppc_dfi_parity       ),
    .dfi_alert_n         ( ppc_dfi_alert_n      ),

    .dfi_wrdata_en       ( ppc_dfi_wrdata_en    ),
    .dfi_wrdata          ( ppc_dfi_wrdata       ),
    .dfi_wrdata_mask     ( ppc_dfi_wrdata_mask  ),
    .dfi_rddata_en       ( ppc_dfi_rddata_en    ),
    .dfi_rddata_valid    ( ppc_dfi_rddata_valid ),
    .dfi_rddata          ( ppc_dfi_rddata       ),

    .dfi_ctrlupd_req     ( dfi_ctrlupd_req      ),
    .dfi_ctrlupd_ack     ( dfi_ctrlupd_ack      ),
    .dfi_phyupd_req      ( dfi_phyupd_req       ),
    .dfi_phyupd_ack      ( dfi_phyupd_ack       ),
    .dfi_phyupd_type     ( dfi_phyupd_type      ),

    .apb_pclk            ( apb_pclk             ),
    .apb_prst_n          ( apb_prst_n           ),
    .apb_psel            ( apb_psel             ),
    .apb_paddr           ( apb_paddr[17:2]      ),
    .apb_penable         ( apb_penable          ),
    .apb_pwrite          ( apb_pwrite           ),
    .apb_pwdata          ( apb_pwdata           ),
    .apb_prdata          ( apb_prdata           ),
    .apb_pready          ( apb_pready           )
);

`ifdef PH1_DDRPHY_SIM

assign (weak1, weak0) user_update      = 1'b0;
assign (weak1, weak0) user_ram_addr    = 8'h0;
assign (weak1, weak0) user_ram_wr_en   = 1'b0;
assign (weak1, weak0) user_ram_rd_en   = 1'b0;
assign (weak1, weak0) user_ram_wr_data = 32'h0;

assign (weak1, weak0) dfi_ctrlupd_req  = 2'b00;
assign (weak1, weak0) dfi_phyupd_ack   = 2'b00;

wire        apb_wr_en, apb_rd_en;
reg  [31:0] ddrphy_sr_r;

assign apb_wr_en = (apb_pwrite == 1'b1) ? (apb_psel & apb_penable & apb_pready) : 1'b0;
assign apb_rd_en = (apb_pwrite == 1'b0) ? (apb_psel & apb_penable & apb_pready) : 1'b0;

initial begin
    wait (ddr_init_cal_done);
    $display ("[DDRPHY_INFO] Initialization and Calibration Finished!");
end

always @ (posedge apb_pclk)
begin
    ddrphy_sr_r <= ddrphy_sr;
end

always @ (posedge apb_pclk)
begin
    if (apb_wr_en)
        $display("[DDRPHY_INFO] Write : 0x%04x = 0x%08x", apb_paddr[17:2], apb_pwdata);
    else if (apb_rd_en)
        $display("[DDRPHY_INFO] Read  : 0x%04x = 0x%08x", apb_paddr[17:2], apb_prdata);

    if (ddrphy_sr != ddrphy_sr_r)
        $display("[DDRPHY_INFO] Step  : 0x%08x", ddrphy_sr);
end
`endif 

endmodule

`timescale 1ps/1ps

module ph1_ddrphy_top #(
    parameter DEVICE      = "PH1A400",
    parameter DRAM_TYPE   = "DDR3",
    parameter MC_TCK      = 1250,
    parameter MC_IDX      = 0,

    parameter WDM         = "ENABLE",
    parameter WDBI        = "DISABLE",
    parameter RDBI        = "DISABLE",

    parameter AC_NUM      = 3,
    parameter DX_NUM      = 9,
    parameter CK_WIDTH    = 1,
    parameter ODT_WIDTH   = 1,
    parameter CKE_WIDTH   = 1,
    parameter CS_WIDTH    = 1,
    parameter BG_WIDTH    = 2,
    parameter BA_WIDTH    = 2,
    parameter ADR_WIDTH   = 17,

    parameter DQS_WIDTH   = 9,
    parameter DQ_WIDTH    = 72,
    parameter DM_WIDTH    = 9,

    parameter BK0_BYTE    = 4'b1111,
    parameter BK1_BYTE    = 4'b1111,
    parameter BK2_BYTE    = 4'b1111,
    parameter BK0_DX_EN   = 4'b1000,
    parameter BK1_DX_EN   = 4'b1111,
    parameter BK2_DX_EN   = 4'b1111,

    parameter CK_MAP      = 48'h004_005,
    parameter RST_MAP     = 12'h027,
    parameter CKE_MAP     = 24'h020,
    parameter ODT_MAP     = 24'h000_023,
    parameter CS_MAP      = 24'h000_022,
    parameter RAS_MAP     = 12'h000,
    parameter CAS_MAP     = 12'h000,
    parameter WE_MAP      = 12'h000,
    parameter ACT_MAP     = 12'h026,

    parameter BG_MAP      = 24'h020_019,
    parameter BA_MAP      = 36'h000_025_024,
    parameter ADR_MAP     = 216'h000_018_016_017_014_015_012_013_010_011_008_009_006_007_002_003_000_001,

    parameter PAR_MAP     = 12'h028,
    parameter ALT_MAP     = 12'h029,

    parameter DQS_MAP     = 216'h235_234_225_224_215_214_205_204_135_134_125_124_115_114_105_104_035_034,
    parameter DM_MAP      = 108'h23a_22a_21a_20a_13a_12a_11a_10a_03a,
    parameter DATA0_MAP   = 96'h039_038_037_036_033_032_031_030,
    parameter DATA1_MAP   = 96'h109_108_107_106_103_102_101_100,
    parameter DATA2_MAP   = 96'h119_118_117_116_113_112_111_110,
    parameter DATA3_MAP   = 96'h129_128_127_126_123_122_121_120,
    parameter DATA4_MAP   = 96'h139_138_137_136_133_132_131_130,
    parameter DATA5_MAP   = 96'h209_208_207_206_203_202_201_200,
    parameter DATA6_MAP   = 96'h219_218_217_216_213_212_211_210,
    parameter DATA7_MAP   = 96'h229_228_227_226_223_222_221_220,
    parameter DATA8_MAP   = 96'h239_238_237_236_233_232_231_230,

    parameter AC_BYTE_MAP = 32'h00_02_01_00,
    parameter DX_BYTE_MAP = 72'h23_22_21_20_13_12_11_10_03

)(
    input                          usr_rst_n,
    input                          usr_clk,
    input                 [2:0]    ctl_clk,
    input                 [2:0]    ddr_clk,

    input                          cal_done,

`ifdef MC0_DRAM_DDR4
    output [      CK_WIDTH-1:0]    ddr_ck_t,
    output [      CK_WIDTH-1:0]    ddr_ck_c,
    output                         ddr_reset_n,
    output [     CKE_WIDTH-1:0]    ddr_cke,
    output [     ODT_WIDTH-1:0]    ddr_odt,
    output [      CS_WIDTH-1:0]    ddr_cs_n,
    output                         ddr_act_n,
    output [      BG_WIDTH-1:0]    ddr_bg,
    output [      BA_WIDTH-1:0]    ddr_ba,
    output [     ADR_WIDTH-1:0]    ddr_addr,
    output                         ddr_parity,
    input                          ddr_alert_n,
    inout  [     DQS_WIDTH-1:0]    ddr_dqs_t,
    inout  [     DQS_WIDTH-1:0]    ddr_dqs_c,
    inout  [      DQ_WIDTH-1:0]    ddr_dq,
    inout  [      DM_WIDTH-1:0]    ddr_dm_n,
`elsif MC0_DRAM_DDR3
    output [      CK_WIDTH-1:0]    ddr_ck_p,
    output [      CK_WIDTH-1:0]    ddr_ck_n,
    output                         ddr_reset_n,
    output [     CKE_WIDTH-1:0]    ddr_cke,
    output [     ODT_WIDTH-1:0]    ddr_odt,
    output [      CS_WIDTH-1:0]    ddr_cs_n,
    output                         ddr_ras_n,
    output                         ddr_cas_n,
    output                         ddr_we_n,
    output [      BA_WIDTH-1:0]    ddr_ba,
    output [     ADR_WIDTH-1:0]    ddr_addr,
    inout  [     DQS_WIDTH-1:0]    ddr_dqs_p,
    inout  [     DQS_WIDTH-1:0]    ddr_dqs_n,
    inout  [      DQ_WIDTH-1:0]    ddr_dq,
    inout  [      DM_WIDTH-1:0]    ddr_dm,
`endif

    output                         ctl_ram_rst_n,
    output                         ctl_ram_cke,

    input  [  3:0]       dfi_reset_n,
    input  [  7:0]       dfi_cke,
    input  [  7:0]       dfi_odt,
    input  [  7:0]       dfi_cs_n,
    input  [  3:0]       dfi_act_n,
    input  [  3:0]       dfi_ras_n,
    input  [  3:0]       dfi_cas_n,
    input  [  3:0]       dfi_we_n,
    input  [  7:0]       dfi_bg,
    input  [ 11:0]       dfi_bank,
    input  [ 71:0]       dfi_address,
    input  [  3:0]       dfi_parity,
    output [  3:0]       dfi_alert_n,

    input  [ 35:0]       dfi_wrdata_en,
    input  [575:0]       dfi_wrdata,
    input  [ 71:0]       dfi_wrdata_mask,
    input  [ 35:0]       dfi_rddata_en,
    output [ 35:0]       dfi_rddata_valid,
    output [575:0]       dfi_rddata,

    input  [  1:0]       dfi_ctrlupd_req,
    output [  1:0]       dfi_ctrlupd_ack,
    output [  1:0]       dfi_phyupd_req,
    input  [  1:0]       dfi_phyupd_ack,
    output [  3:0]       dfi_phyupd_type,

    input                apb_pclk,
    input                apb_prst_n,
    input                apb_psel,
    input                apb_penable,
    input                apb_pwrite,
    input  [ 15:0]       apb_paddr,
    input  [ 31:0]       apb_pwdata,
    output [ 31:0]       apb_prdata,
    output               apb_pready
);

localparam [9*8*12-1:0] DQ_MAP = {DATA8_MAP, DATA7_MAP, DATA6_MAP, DATA5_MAP, DATA4_MAP, DATA3_MAP, DATA2_MAP, DATA1_MAP, DATA0_MAP};

wire                ppc_apb_pclk    ;
wire                ppc_apb_prst_n  ;
wire                ppc_apb_psel    ;
wire                ppc_apb_penable ;
wire                ppc_apb_pwrite  ;
wire [ 15:0]        ppc_apb_paddr   ;
wire [ 31:0]        ppc_apb_pwdata  ;
wire [ 31:0]        ppc_apb_prdata  ;
wire                ppc_apb_pready  ;

wire                phy_apb_pclk    ;
wire                phy_apb_prst_n  ;
wire                phy_apb_psel    ;
wire                phy_apb_penable ;
wire                phy_apb_pwrite  ;
wire [ 15:0]        phy_apb_paddr   ;
wire [ 31:0]        phy_apb_pwdata  ;
wire [ 31:0]        phy_apb_prdata  ;
wire                phy_apb_pready  ;

wire                ctl_ac_rst_n;
wire [  8:0]        ctl_dx_rst_n;
wire                ctl_ac_fifo_rst_n;
wire [  8:0]        ctl_dx_fifo_rst_n;

wire [ 15:0]        ctl_ck       ;
wire [ 15:0]        ctl_cke      ;
wire [ 15:0]        ctl_odt      ;
wire [ 15:0]        ctl_cs_n     ;
wire [  7:0]        ctl_act_n    ;
wire [ 15:0]        ctl_bg       ;
wire [ 15:0]        ctl_ba       ;
wire [143:0]        ctl_addr     ;

wire [  7:0]        ctl_parity   ;
wire [  7:0]        ctl_alert_n  ;

wire [ 71:0]        ctl_wdqs     ;
wire [575:0]        ctl_wdq      ;
wire [ 71:0]        ctl_wdm      ;
wire [575:0]        ctl_rdq      ;
wire [ 71:0]        ctl_rdbi     ;
wire [ 17:0]        ctl_rdq_vld  ;
wire [ 71:0]        ctl_gate     ;
wire [ 71:0]        ctl_gate_pre ;

wire [ 71:0]        ctl_oe       ;
wire [ 71:0]        ctl_te       ;
wire [ 71:0]        ctl_pdr      ;

wire                zqcal_clear      ;
wire                zqcal_start      ;
wire                zqcal_update     ;
wire [  2:0]        zqcal_done       ;

wire                dcc_clear        ;
wire                dcc_start        ;
wire                dcc_update       ;
wire [ 11:0]        dcc_done         ;

wire [ 12:0]        dcp_sel          ;
wire [ 59:0]        dcp_addr         ;
wire [ 89:0]        dcp_data         ;
wire [  9:0]        dcp_gate         ;
wire [  8:0]        dcp_rksel        ;

wire [  8:0]        mdl_cal_mode     ;
wire [ 62:0]        mdl_cal_clk_en   ;
wire [ 62:0]        mdl_cal_en       ;
wire [ 62:0]        mdl_cal_en_out   ;
wire [ 62:0]        mdl_cal_out      ;

wire [  7:0]        lpbk_en          ;
wire [  8:0]        wrlvl_mode       ;
wire [ 71:0]        wrlvl_din        ;
wire [ 17:0]        dqs_gate_cnt     ;
wire [ 17:0]        dqs_gate_status  ;
wire                dqs_pupd_en      ;

wire [ 11:0]        bm_ac_rst_n      ;
wire [ 11:0]        bm_dx_rst_n      ;
wire [ 11:0]        bm_ac_fifo_rst_n ;
wire [ 11:0]        bm_dx_fifo_rst_n ;

wire                bm_zqcal_clear   ;
wire                bm_zqcal_start   ;
wire                bm_zqcal_update  ;
wire [  2:0]        bm_zqcal_done    ;

wire                bm_dcc_clear     ;
wire                bm_dcc_start     ;
wire                bm_dcc_update    ;
wire [ 11:0]        bm_dcc_done      ;

wire [ 11:0]        bm_dcp_sel       ;
wire [  5:0]        bm_dcp_addr[0:11];
wire [  8:0]        bm_dcp_data[0:11];
wire [ 11:0]        bm_dcp_gate      ;
wire [ 11:0]        bm_dcp_rksel     ;

wire [ 11:0]        bm_mdl_cal_mode          ;
wire [  6:0]        bm_mdl_cal_clk_en  [0:11];
wire [  6:0]        bm_mdl_cal_en      [0:11];
wire [  6:0]        bm_mdl_cal_en_out  [0:11];
wire [  6:0]        bm_mdl_cal_out     [0:11];

wire [  7:0]        bm_lpbk_en         [0:11];
wire [155:0]        bm_indd                  ;
wire [ 11:0]        bm_wrlvl_mode            ;
wire [  1:0]        bm_dqs_gate_cnt    [0:11];
wire [  1:0]        bm_dqs_gate_status [0:11];
wire [ 11:0]        bm_dqs_pupd_en           ;

wire [  7:0]        bm_ctl_wdata [0:3*4*13-1];
wire [  7:0]        bm_ctl_rdata [0:3*4*13-1];
wire [ 11:0]        bm_ctl_rdata_vld         ;
wire [  7:0]        bm_ctl_gate  [0:3*4-1]   ;
wire [  7:0]        bm_ctl_pdr   [0:3*4-1]   ;
wire [  7:0]        bm_ctl_ts    [0:3*4-1]   ;
wire [  7:0]        bm_ctl_te    [0:3*4-1]   ;

assign ppc_apb_pclk     = apb_pclk    ;
assign ppc_apb_prst_n   = apb_prst_n  ;
assign ppc_apb_penable  = apb_penable ;
assign ppc_apb_pwrite   = apb_pwrite  ;
assign ppc_apb_paddr    = apb_paddr   ;
assign ppc_apb_pwdata   = apb_pwdata  ;

assign phy_apb_pclk     = apb_pclk    ;
assign phy_apb_prst_n   = apb_prst_n  ;
assign phy_apb_penable  = apb_penable ;
assign phy_apb_pwrite   = apb_pwrite  ;
assign phy_apb_paddr    = apb_paddr   ;
assign phy_apb_pwdata   = apb_pwdata  ;

assign ppc_apb_psel     = (apb_paddr[12] == 1'b0) ? apb_psel : 1'b0;
assign phy_apb_psel     = (apb_paddr[12] == 1'b1) ? apb_psel : 1'b0;

assign apb_pready       = (apb_paddr[12] == 1'b0) ? ppc_apb_pready :
                          (apb_paddr[12] == 1'b1) ? phy_apb_pready : 1'b1;

assign apb_prdata       = (apb_paddr[12] == 1'b0) ? ppc_apb_prdata :
                          (apb_paddr[12] == 1'b1) ? phy_apb_prdata : 32'hdeadbeef;

ph1_ddrphy_ppc #(
    .DEVICE ( DEVICE ),
    .DX_NUM ( DX_NUM )
) u_ddrphy_ppc (

    .usr_clk              ( usr_clk              ),
    .usr_rst_n            ( usr_rst_n            ),

    .dfi_reset_n          ( dfi_reset_n          ),
    .dfi_cke              ( dfi_cke              ),
    .dfi_odt              ( dfi_odt              ),
    .dfi_cs_n             ( dfi_cs_n             ),
    .dfi_act_n            ( dfi_act_n            ),
    .dfi_ras_n            ( dfi_ras_n            ),
    .dfi_cas_n            ( dfi_cas_n            ),
    .dfi_we_n             ( dfi_we_n             ),
    .dfi_bg               ( dfi_bg               ),
    .dfi_bank             ( dfi_bank             ),
    .dfi_addr             ( dfi_address          ),

    .dfi_parity           ( dfi_parity           ),
    .dfi_alert_n          ( dfi_alert_n          ),

    .dfi_wrdata_en        ( dfi_wrdata_en        ),
    .dfi_wrdata           ( dfi_wrdata           ),
    .dfi_wrdata_mask      ( dfi_wrdata_mask      ),
    .dfi_rddata_en        ( dfi_rddata_en        ),
    .dfi_rddata_valid     ( dfi_rddata_valid     ),
    .dfi_rddata           ( dfi_rddata           ),

    .dfi_ctrlupd_req      ( dfi_ctrlupd_req      ),
    .dfi_ctrlupd_ack      ( dfi_ctrlupd_ack      ),
    .dfi_phyupd_req       ( dfi_phyupd_req       ),
    .dfi_phyupd_type      ( dfi_phyupd_type      ),
    .dfi_phyupd_ack       ( dfi_phyupd_ack       ),

    .ctl_ac_rst_n         ( ctl_ac_rst_n         ),
    .ctl_dx_rst_n         ( ctl_dx_rst_n         ),
    .ctl_ac_fifo_rst_n    ( ctl_ac_fifo_rst_n    ),
    .ctl_dx_fifo_rst_n    ( ctl_dx_fifo_rst_n    ),

    .ctl_ram_rst_n        ( ctl_ram_rst_n        ),
    .ctl_ram_cke          ( ctl_ram_cke          ),
    .ctl_ck               ( ctl_ck               ),
    .ctl_cke              ( ctl_cke              ),
    .ctl_odt              ( ctl_odt              ),
    .ctl_cs_n             ( ctl_cs_n             ),
    .ctl_act_n            ( ctl_act_n            ),
    .ctl_bg               ( ctl_bg               ),
    .ctl_ba               ( ctl_ba               ),
    .ctl_addr             ( ctl_addr             ),

    .ctl_parity           ( ctl_parity           ),
    .ctl_alert_n          ( ctl_alert_n          ),

    .ctl_wdqs             ( ctl_wdqs             ),
    .ctl_wdq              ( ctl_wdq              ),
    .ctl_wdm              ( ctl_wdm              ),
    .ctl_gate             ( ctl_gate_pre         ),
    .ctl_rdq_vld          ( ctl_rdq_vld          ),
    .ctl_rdq              ( ctl_rdq              ),
    .ctl_rdbi             ( ctl_rdbi             ),
    .ctl_oe               ( ctl_oe               ),
    .ctl_te               ( ctl_te               ),
    .ctl_pdr              ( ctl_pdr              ),

    .dcc_done             ( dcc_done             ),
    .dcc_clear            ( dcc_clear            ),
    .dcc_start            ( dcc_start            ),
    .dcc_update           ( dcc_update           ),

    .zqcal_done           ( zqcal_done           ),
    .zqcal_clear          ( zqcal_clear          ),
    .zqcal_start          ( zqcal_start          ),
    .zqcal_update         ( zqcal_update         ),

    .mdl_cal_mode          ( mdl_cal_mode        ),
    .mdl_cal_clk_en        ( mdl_cal_clk_en      ),
    .mdl_cal_en            ( mdl_cal_en          ),
    .mdl_cal_en_out        ( mdl_cal_en_out      ),
    .mdl_cal_out           ( mdl_cal_out         ),

    .dcp_sel              ( dcp_sel              ),
    .dcp_addr             ( dcp_addr             ),
    .dcp_data             ( dcp_data             ),
    .dcp_gate             ( dcp_gate             ),
    .dcp_rksel            ( dcp_rksel            ),

    .lpbk_en              ( lpbk_en              ),

    .wrlvl_din            ( wrlvl_din            ),
    .wrlvl_mode           ( wrlvl_mode           ),
    .dqs_pupd_en          ( dqs_pupd_en          ),
    .dqs_gate_status      ( dqs_gate_status      ),
    .dqs_gate_cnt         ( dqs_gate_cnt         ),

    .apb_pclk             ( ppc_apb_pclk         ),
    .apb_prst_n           ( ppc_apb_prst_n       ),
    .apb_psel             ( ppc_apb_psel         ),
    .apb_penable          ( ppc_apb_penable      ),
    .apb_pwrite           ( ppc_apb_pwrite       ),
    .apb_paddr            ( ppc_apb_paddr[15:0]  ),
    .apb_pwdata           ( ppc_apb_pwdata       ),
    .apb_prdata           ( ppc_apb_prdata       ),
    .apb_pready           ( ppc_apb_pready       )
);

ph1_ddrphy_bus_matrix #(

    .WDM                        ( WDM               ),
    .WDBI                       ( WDBI              ),
    .RDBI                       ( RDBI              ),

    .AC_NUM                     ( AC_NUM            ),
    .DX_NUM                     ( DX_NUM            ),
    .CK_WIDTH                   ( CK_WIDTH          ),
    .CKE_WIDTH                  ( CKE_WIDTH         ),
    .ODT_WIDTH                  ( ODT_WIDTH         ),
    .CS_WIDTH                   ( CS_WIDTH          ),
    .ADR_WIDTH                  ( ADR_WIDTH         ),
    .BG_WIDTH                   ( BG_WIDTH          ),
    .BA_WIDTH                   ( BA_WIDTH          ),
    .DQS_WIDTH                  ( DQS_WIDTH         ),
    .DQ_WIDTH                   ( DQ_WIDTH          ),
    .DM_WIDTH                   ( DM_WIDTH          ),

    .BK0_BYTE                   ( BK0_BYTE          ),
    .BK1_BYTE                   ( BK1_BYTE          ),
    .BK2_BYTE                   ( BK2_BYTE          ),
    .BK0_DX_EN                  ( BK0_DX_EN         ),
    .BK1_DX_EN                  ( BK1_DX_EN         ),
    .BK2_DX_EN                  ( BK2_DX_EN         ),

    .RST_MAP                    ( RST_MAP           ),
    .CK_MAP                     ( CK_MAP            ),
    .CKE_MAP                    ( CKE_MAP           ),
    .ODT_MAP                    ( ODT_MAP           ),
    .CS_MAP                     ( CS_MAP            ),
    .ACT_MAP                    ( ACT_MAP           ),
    .RAS_MAP                    ( RAS_MAP           ),
    .CAS_MAP                    ( CAS_MAP           ),
    .WE_MAP                     ( WE_MAP            ),
    .BG_MAP                     ( BG_MAP            ),
    .BA_MAP                     ( BA_MAP            ),
    .ADR_MAP                    ( ADR_MAP           ),
    .PAR_MAP                    ( PAR_MAP           ),
    .ALT_MAP                    ( ALT_MAP           ),

    .DQS_MAP                    ( DQS_MAP           ),
    .DM_MAP                     ( DM_MAP            ),
    .DQ_MAP                     ( DQ_MAP            ),

    .DX_BYTE_MAP                ( DX_BYTE_MAP       ),
    .AC_BYTE_MAP                ( AC_BYTE_MAP       )

) u_ddrphy_bm (

    .clk                         ( usr_clk             ),
    .rst_n                       ( usr_rst_n           ),

    .cal_done                    ( cal_done            ),

    .ctl_dx_rst_n                ( ctl_dx_rst_n        ),
    .ctl_ac_rst_n                ( ctl_ac_rst_n        ),
    .ctl_ac_fifo_rst_n           ( ctl_ac_fifo_rst_n   ),
    .ctl_dx_fifo_rst_n           ( ctl_dx_fifo_rst_n   ),

    .ctl_rst_n                   ( ctl_ram_rst_n     ),
    .ctl_ck                      ( ctl_ck            ),
    .ctl_cke                     ( ctl_cke           ),
    .ctl_odt                     ( ctl_odt           ),
    .ctl_cs_n                    ( ctl_cs_n          ),
    .ctl_act_n                   ( ctl_act_n         ),
    .ctl_bg                      ( ctl_bg            ),
    .ctl_ba                      ( ctl_ba            ),
    .ctl_addr                    ( ctl_addr          ),

    .ctl_parity                  ( ctl_parity        ),
    .ctl_alert_n                 ( ctl_alert_n       ),

    .ctl_wdqs                    ( ctl_wdqs          ),
    .ctl_wdq                     ( ctl_wdq           ),
    .ctl_wdm                     ( ctl_wdm           ),
    .ctl_gate                    ( ctl_gate_pre      ),
    .ctl_rdq_vld                 ( ctl_rdq_vld       ),
    .ctl_rdq                     ( ctl_rdq           ),
    .ctl_rdbi                    ( ctl_rdbi          ),

    .ctl_oe                      ( ctl_oe            ),
    .ctl_te                      ( ctl_te            ),
    .ctl_pdr                     ( ctl_pdr           ),

    .dcp_sel                     ( dcp_sel           ),
    .dcp_addr                    ( dcp_addr          ),
    .dcp_data                    ( dcp_data          ),
    .dcp_gate                    ( dcp_gate          ),
    .dcp_rksel                   ( dcp_rksel         ),

    .zqcal_clear                 ( zqcal_clear       ),
    .zqcal_start                 ( zqcal_start       ),
    .zqcal_update                ( zqcal_update      ),
    .zqcal_done                  ( zqcal_done        ),

    .dcc_clear                   ( dcc_clear         ),
    .dcc_start                   ( dcc_start         ),
    .dcc_update                  ( dcc_update        ),
    .dcc_done                    ( dcc_done          ),

    .mdl_cal_mode                ( mdl_cal_mode      ),
    .mdl_cal_clk_en              ( mdl_cal_clk_en    ),
    .mdl_cal_en                  ( mdl_cal_en        ),
    .mdl_cal_en_out              ( mdl_cal_en_out    ),
    .mdl_cal_out                 ( mdl_cal_out       ),

    .lpbk_en                     ( lpbk_en           ),

    .wrlvl_mode                  ( wrlvl_mode        ),
    .wrlvl_din                   ( wrlvl_din         ),
    .dqs_gate_cnt                ( dqs_gate_cnt      ),
    .dqs_gate_status             ( dqs_gate_status   ),
    .dqs_pupd_en                 ( dqs_pupd_en       ),

    .bm_ac_rst_n                 ( bm_ac_rst_n       ),
    .bm_dx_rst_n                 ( bm_dx_rst_n       ),
    .bm_ac_fifo_rst_n            ( bm_ac_fifo_rst_n  ),
    .bm_dx_fifo_rst_n            ( bm_dx_fifo_rst_n  ),

    .bm_ctl_wdata                ( bm_ctl_wdata      ),
    .bm_ctl_rdata                ( bm_ctl_rdata      ),
    .bm_ctl_rdata_vld            ( bm_ctl_rdata_vld  ),
    .bm_ctl_gate                 ( bm_ctl_gate       ),
    .bm_ctl_pdr                  ( bm_ctl_pdr        ),
    .bm_ctl_ts                   ( bm_ctl_ts         ),
    .bm_ctl_te                   ( bm_ctl_te         ),

    .bm_dcp_sel                  ( bm_dcp_sel        ),
    .bm_dcp_addr                 ( bm_dcp_addr       ),
    .bm_dcp_data                 ( bm_dcp_data       ),
    .bm_dcp_gate                 ( bm_dcp_gate       ),
    .bm_dcp_rksel                ( bm_dcp_rksel      ),

    .bm_zqcal_clear              ( bm_zqcal_clear    ),
    .bm_zqcal_start              ( bm_zqcal_start    ),
    .bm_zqcal_update             ( bm_zqcal_update   ),
    .bm_zqcal_done               ( bm_zqcal_done     ),

    .bm_dcc_clear                ( bm_dcc_clear      ),
    .bm_dcc_start                ( bm_dcc_start      ),
    .bm_dcc_update               ( bm_dcc_update     ),
    .bm_dcc_done                 ( bm_dcc_done       ),

    .bm_mdl_cal_mode             ( bm_mdl_cal_mode   ),
    .bm_mdl_cal_clk_en           ( bm_mdl_cal_clk_en ),
    .bm_mdl_cal_en               ( bm_mdl_cal_en     ),
    .bm_mdl_cal_en_out           ( bm_mdl_cal_en_out ),
    .bm_mdl_cal_out              ( bm_mdl_cal_out    ),

    .bm_lpbk_en                  ( bm_lpbk_en        ),

    .bm_wrlvl_mode               ( bm_wrlvl_mode     ),
    .bm_indd                     ( bm_indd           ),
    .bm_dqs_gate_cnt             ( bm_dqs_gate_cnt   ),
    .bm_dqs_gate_status          ( bm_dqs_gate_status),
    .bm_dqs_pupd_en              ( bm_dqs_pupd_en    )
);

ph1_ddrphy_bank_wrapper #(
    .MC_IDX         ( MC_IDX      ),
    .MC_TCK         ( MC_TCK      ),

    .BK0_BYTE       ( BK0_BYTE    ),
    .BK1_BYTE       ( BK1_BYTE    ),
    .BK2_BYTE       ( BK2_BYTE    ),
    .BK0_DX_EN      ( BK0_DX_EN   ),
    .BK1_DX_EN      ( BK1_DX_EN   ),
    .BK2_DX_EN      ( BK2_DX_EN   ),

    .AC_NUM         ( AC_NUM      ),
    .DX_NUM         ( DX_NUM      ),

    .WDM            ( WDM         ),
    .WDBI           ( WDBI        ),
    .RDBI           ( RDBI        ),

    .CK_WIDTH       ( CK_WIDTH    ),
    .CKE_WIDTH      ( CKE_WIDTH   ),
    .ODT_WIDTH      ( ODT_WIDTH   ),
    .CS_WIDTH       ( CS_WIDTH    ),
    .ADR_WIDTH      ( ADR_WIDTH   ),
    .BG_WIDTH       ( BG_WIDTH    ),
    .BA_WIDTH       ( BA_WIDTH    ),
    .DQS_WIDTH      ( DQS_WIDTH   ),
    .DQ_WIDTH       ( DQ_WIDTH    ),
    .DM_WIDTH       ( DM_WIDTH    ),

    .RST_MAP        ( RST_MAP     ),
    .CK_MAP         ( CK_MAP      ),
    .CKE_MAP        ( CKE_MAP     ),
    .ODT_MAP        ( ODT_MAP     ),
    .CS_MAP         ( CS_MAP      ),
    .ACT_MAP        ( ACT_MAP     ),
    .RAS_MAP        ( RAS_MAP     ),
    .CAS_MAP        ( CAS_MAP     ),
    .WE_MAP         ( WE_MAP      ),
    .BG_MAP         ( BG_MAP      ),
    .BA_MAP         ( BA_MAP      ),
    .ADR_MAP        ( ADR_MAP     ),
    .PAR_MAP        ( PAR_MAP     ),
    .ALT_MAP        ( ALT_MAP     ),

    .DQS_MAP        ( DQS_MAP     ),
    .DM_MAP         ( DM_MAP      ),
    .DQ_MAP         ( DQ_MAP      )

) u_ddrphy_bank (

    .usr_clk                       ( usr_clk          ),
    .ctl_clk                       ( ctl_clk          ),
    .ddr_clk                       ( ddr_clk          ),

    .usr_rst_n                     ( usr_rst_n        ),

    .apb_prst_n                    ( phy_apb_prst_n   ),
    .apb_pclk                      ( phy_apb_pclk     ),
    .apb_psel                      ( phy_apb_psel     ),
    .apb_penable                   ( phy_apb_penable  ),
    .apb_pwrite                    ( phy_apb_pwrite   ),
    .apb_paddr                     ( phy_apb_paddr    ),
    .apb_pwdata                    ( phy_apb_pwdata   ),
    .apb_prdata                    ( phy_apb_prdata   ),
    .apb_pready                    ( phy_apb_pready   ),

    .zqcal_clear                   ( bm_zqcal_clear   ),
    .zqcal_start                   ( bm_zqcal_start   ),
    .zqcal_update                  ( bm_zqcal_update  ),
    .zqcal_done                    ( bm_zqcal_done    ),

    .ac_fifo_rst_n                 ( bm_ac_fifo_rst_n ),
    .dx_fifo_rst_n                 ( bm_dx_fifo_rst_n ),

    .ctl_pdr                       ( bm_ctl_pdr       ),
    .ctl_te                        ( bm_ctl_te        ),
    .ctl_ts                        ( bm_ctl_ts        ),

    .ctl_wdata                     ( bm_ctl_wdata     ),
    .ctl_rdata                     ( bm_ctl_rdata     ),
    .ctl_rdata_vld                 ( bm_ctl_rdata_vld ),
    .ctl_rdqs_gate                 ( bm_ctl_gate      ),

    .dcp_sel                       ( bm_dcp_sel       ),
    .dcp_addr                      ( bm_dcp_addr      ),
    .dcp_data                      ( bm_dcp_data      ),
    .dcp_gate                      ( bm_dcp_gate      ),
    .dcp_rksel                     ( bm_dcp_rksel     ),

    .dcc_clear                     ( bm_dcc_clear     ),
    .dcc_start                     ( bm_dcc_start     ),
    .dcc_done                      ( bm_dcc_done      ),

    .mdl_cal_mode                  ( bm_mdl_cal_mode  ),
    .mdl_cal_clk_en                ( bm_mdl_cal_clk_en),
    .mdl_cal_en                    ( bm_mdl_cal_en    ),
    .mdl_cal_en_out                ( bm_mdl_cal_en_out),
    .mdl_cal_out                   ( bm_mdl_cal_out   ),

    .indd                          ( bm_indd          ),

    .wrlvl_mdoe                    ( bm_wrlvl_mode    ),
    .dqs_pupd_en                   ( bm_dqs_pupd_en   ),
    .dqs_gate_status               ( bm_dqs_gate_status ),

`ifdef MC0_DRAM_DDR4
    .ddr_ck_t                      ( ddr_ck_t         ),
    .ddr_ck_c                      ( ddr_ck_c         ),
    .ddr_reset_n                   ( ddr_reset_n      ),
    .ddr_cke                       ( ddr_cke          ),
    .ddr_odt                       ( ddr_odt          ),
    .ddr_cs_n                      ( ddr_cs_n         ),
    .ddr_act_n                     ( ddr_act_n        ),
    .ddr_bg                        ( ddr_bg           ),
    .ddr_ba                        ( ddr_ba           ),
    .ddr_addr                      ( ddr_addr         ),

    .ddr_parity                    ( ddr_parity       ),
    .ddr_alert_n                   ( ddr_alert_n      ),

    .ddr_dqs_t                     ( ddr_dqs_t        ),
    .ddr_dqs_c                     ( ddr_dqs_c        ),
    .ddr_dq                        ( ddr_dq           ),
    .ddr_dm_n                      ( ddr_dm_n         )
`else
    .ddr_ck_p                      ( ddr_ck_p         ),
    .ddr_ck_n                      ( ddr_ck_n         ),
    .ddr_reset_n                   ( ddr_reset_n      ),
    .ddr_cke                       ( ddr_cke          ),
    .ddr_odt                       ( ddr_odt          ),
    .ddr_cs_n                      ( ddr_cs_n         ),
    .ddr_ras_n                     ( ddr_ras_n        ),
    .ddr_cas_n                     ( ddr_cas_n        ),
    .ddr_we_n                      ( ddr_we_n         ),
    .ddr_ba                        ( ddr_ba           ),
    .ddr_addr                      ( ddr_addr         ),

    .ddr_dqs_p                     ( ddr_dqs_p        ),
    .ddr_dqs_n                     ( ddr_dqs_n        ),
    .ddr_dq                        ( ddr_dq           ),
    .ddr_dm                        ( ddr_dm           )
`endif
);

endmodule

`timescale 1ps/1ps

module ph1_ddrphy_dfi_glue #(
    parameter DX_NUM    = 8,
    parameter BITS_CK   = 1,
    parameter BITS_CKE  = 1,
    parameter BITS_ODT  = 1,
    parameter BITS_CS   = 1,
    parameter BITS_BG   = 1,
    parameter BITS_BA   = 2,
    parameter BITS_COL  = 12,
    parameter BITS_ROW  = 17,
    parameter BITS_ADR  = 17,
    parameter BITS_DQS  = DX_NUM,
    parameter BITS_DQ   = DX_NUM*8,
    parameter BITS_DM   = DX_NUM

)(

    input                          clk                  ,
    input                          rst_n                ,

    input        [           3:0]  dfi_reset_n          ,
    input        [BITS_CKE*4-1:0]  dfi_cke              ,
    input        [BITS_ODT*4-1:0]  dfi_odt              ,
    input        [BITS_CS *4-1:0]  dfi_cs_n             ,
    input        [           3:0]  dfi_ras_n            ,
    input        [           3:0]  dfi_cas_n            ,
    input        [           3:0]  dfi_we_n             ,
`ifdef MC0_DRAM_DDR4
    input        [           3:0]  dfi_act_n            ,
    input        [BITS_BG *4-1:0]  dfi_bg               ,
`endif
    input        [BITS_BA *4-1:0]  dfi_bank             ,
    input        [BITS_ADR*4-1:0]  dfi_address          ,
`ifdef MC0_DRAM_DDR4
    input        [           3:0]  dfi_parity           ,
`endif
    output  reg  [           3:0]  dfi_alert_n          ,

    input        [BITS_DQS*4-1:0]  dfi_wrdata_en        ,
    input        [BITS_DQ *8-1:0]  dfi_wrdata           ,
    input        [BITS_DM *8-1:0]  dfi_wrdata_mask      ,
    input        [BITS_DQS*4-1:0]  dfi_rddata_en        ,
    output  reg  [BITS_DQS*4-1:0]  dfi_rddata_valid     ,
    output  reg  [BITS_DQ *8-1:0]  dfi_rddata           ,

    output  reg  [           3:0]  ppc_dfi_reset_n      ,
    output  reg  [           7:0]  ppc_dfi_cke          ,
    output  reg  [           7:0]  ppc_dfi_odt          ,
    output  reg  [           7:0]  ppc_dfi_cs_n         ,
    output  reg  [           3:0]  ppc_dfi_ras_n        ,
    output  reg  [           3:0]  ppc_dfi_cas_n        ,
    output  reg  [           3:0]  ppc_dfi_we_n         ,
    output  reg  [           3:0]  ppc_dfi_act_n        ,
    output  reg  [           7:0]  ppc_dfi_bg           ,
    output  reg  [          11:0]  ppc_dfi_bank         ,
    output  reg  [          71:0]  ppc_dfi_address      ,
    output  reg  [           3:0]  ppc_dfi_parity       ,
    input        [           3:0]  ppc_dfi_alert_n      ,
    output  reg  [          35:0]  ppc_dfi_wrdata_en    ,
    output  reg  [         575:0]  ppc_dfi_wrdata       ,
    output  reg  [          71:0]  ppc_dfi_wrdata_mask  ,
    output  reg  [          35:0]  ppc_dfi_rddata_en    ,
    input        [          35:0]  ppc_dfi_rddata_valid ,
    input        [         575:0]  ppc_dfi_rddata
);

integer n, p;

always @ (posedge clk or negedge rst_n)
begin
    if (rst_n == 1'b0) begin
        ppc_dfi_reset_n   <=  4'b1111;
        ppc_dfi_cke       <=  8'hff  ;
        ppc_dfi_odt       <=  8'h00  ;
        ppc_dfi_cs_n      <=  8'hff  ;
        ppc_dfi_ras_n     <=  4'hf   ;
        ppc_dfi_cas_n     <=  4'hf   ;
        ppc_dfi_we_n      <=  4'hf   ;
        ppc_dfi_act_n     <=  4'hf   ;
        ppc_dfi_parity    <=  4'h0   ;
    end else begin
        ppc_dfi_cke       <= (BITS_CKE == 2) ? dfi_cke  : {1'b1, dfi_cke [3], 1'b1, dfi_cke [2], 1'b1, dfi_cke [1], 1'b1, dfi_cke [0]};
        ppc_dfi_odt       <= (BITS_ODT == 2) ? dfi_odt  : {1'b1, dfi_odt [3], 1'b1, dfi_odt [2], 1'b1, dfi_odt [1], 1'b1, dfi_odt [0]};
        ppc_dfi_cs_n      <= (BITS_CS  == 2) ? dfi_cs_n : {1'b1, dfi_cs_n[3], 1'b1, dfi_cs_n[2], 1'b1, dfi_cs_n[1], 1'b1, dfi_cs_n[0]};

        ppc_dfi_ras_n     <=  dfi_ras_n ;
        ppc_dfi_cas_n     <=  dfi_cas_n ;
        ppc_dfi_we_n      <=  dfi_we_n  ;
`ifdef MC0_DRAM_DDR4
        ppc_dfi_act_n     <=  dfi_act_n ;
        ppc_dfi_parity    <=  dfi_parity;
`endif
    end
end

always @ (posedge clk or negedge rst_n)
begin
    if (rst_n == 1'b0) begin
        ppc_dfi_bg        <=  8'h00  ;
        ppc_dfi_bank      <=  12'h000;
        ppc_dfi_address   <=  72'h0  ;
    end else begin
        for (p = 0; p <= 4-1; p = p+1) begin
`ifdef MC0_DRAM_DDR4
            ppc_dfi_bg     [p*2  +: BITS_BG ] <= dfi_bg     [p*BITS_BG  +: BITS_BG ];
`endif
            ppc_dfi_bank   [p*3  +: BITS_BA ] <= dfi_bank   [p*BITS_BA  +: BITS_BA ];
            ppc_dfi_address[p*18 +: BITS_ADR] <= dfi_address[p*BITS_ADR +: BITS_ADR];
        end
    end
end

always @ (posedge clk or negedge rst_n)
begin
    if (rst_n == 1'b0) begin
        dfi_alert_n  <=  4'b1111;
    end else begin
        dfi_alert_n  <=  ppc_dfi_alert_n;
    end
end

always @ (posedge clk or negedge rst_n)
begin
    if (rst_n == 1'b0) begin
        ppc_dfi_rddata_en   <=  36'h0;
        ppc_dfi_wrdata_en   <=  36'h0;
    end else begin
        for (p = 0; p <= 4-1; p = p+1) begin
`ifdef MC0_PINGPONG_PHY
            ppc_dfi_rddata_en[9*p   +: DX_NUM/2] <= dfi_rddata_en[DX_NUM*p          +: DX_NUM/2];
            ppc_dfi_wrdata_en[9*p   +: DX_NUM/2] <= dfi_wrdata_en[DX_NUM*p          +: DX_NUM/2];

            ppc_dfi_rddata_en[9*p+4 +: DX_NUM/2] <= dfi_rddata_en[DX_NUM*p+DX_NUM/2 +: DX_NUM/2];
            ppc_dfi_wrdata_en[9*p+4 +: DX_NUM/2] <= dfi_wrdata_en[DX_NUM*p+DX_NUM/2 +: DX_NUM/2];
`else
            ppc_dfi_rddata_en[9*p +: DX_NUM] <= dfi_rddata_en[DX_NUM*p +: DX_NUM];
            ppc_dfi_wrdata_en[9*p +: DX_NUM] <= dfi_wrdata_en[DX_NUM*p +: DX_NUM];
`endif
        end
    end
end

always @ (posedge clk or negedge rst_n)
begin
    if (rst_n == 1'b0) begin
        ppc_dfi_wrdata      <= {576{1'b1}};
        ppc_dfi_wrdata_mask <= { 72{1'b1}};
    end else begin
        for (p = 0; p <= 7; p = p+1) begin
`ifdef MC0_PINGPONG_PHY
            ppc_dfi_wrdata     [9*p*8    +: (DX_NUM*8)/2] <= dfi_wrdata[DX_NUM*p*8              +: (DX_NUM*8)/2];
            ppc_dfi_wrdata     [9*p*8+32 +: (DX_NUM*8)/2] <= dfi_wrdata[DX_NUM*p*8+(DX_NUM*8)/2 +: (DX_NUM*8)/2];

            ppc_dfi_wrdata_mask[9*p   +: DX_NUM/2] <= dfi_wrdata_mask[DX_NUM*p          +: DX_NUM/2];
            ppc_dfi_wrdata_mask[9*p+4 +: DX_NUM/2] <= dfi_wrdata_mask[DX_NUM*p+DX_NUM/2 +: DX_NUM/2];
`else
            ppc_dfi_wrdata     [9*p*8 +: DX_NUM*8] <= dfi_wrdata     [DX_NUM*p*8 +: DX_NUM*8];
            ppc_dfi_wrdata_mask[9*p   +: DX_NUM  ] <= dfi_wrdata_mask[DX_NUM*p   +: DX_NUM];
`endif
        end
    end
end

always @ (posedge clk or negedge rst_n)
begin
    if (rst_n == 1'b0) begin
        dfi_rddata_valid <= {DX_NUM{4'h0}};
    end else begin
        for (p = 0; p <= 4-1; p = p+1) begin
`ifdef MC0_PINGPONG_PHY
            dfi_rddata_valid[DX_NUM*p +: DX_NUM] <= {ppc_dfi_rddata_valid[9*p+4 +: DX_NUM/2], ppc_dfi_rddata_valid[9*p +: DX_NUM/2]};
`else
            dfi_rddata_valid[DX_NUM*p +: DX_NUM] <=  ppc_dfi_rddata_valid[9*p +: DX_NUM];
`endif
        end
    end
end

always @ (posedge clk or negedge rst_n)
begin
    if (rst_n == 1'b0) begin
        dfi_rddata <= {DX_NUM{64'h0}};
    end else begin
        for (p = 0; p <= 7; p = p+1) begin
`ifdef MC0_PINGPONG_PHY
            dfi_rddata[DX_NUM*p*8 +: DX_NUM*8] <= {ppc_dfi_rddata[9*p*8+32 +: (DX_NUM*8)/2], ppc_dfi_rddata[9*p*8 +: (DX_NUM*8)/2]};
`else
            dfi_rddata[DX_NUM*p*8 +: DX_NUM*8] <=  ppc_dfi_rddata[9*p*8 +: DX_NUM*8];
`endif
        end
    end
end

endmodule

`timescale 1ps/1ps

module ph1_ddrphy_uram2apb (

    input              clk         ,
    input              rst         ,

    input              uram_update ,
    input       [15:0] uram_addr   ,
    input              uram_wen    ,
    input       [31:0] uram_wdata  ,
    input              uram_ren    ,
    output      [31:0] uram_rdata  ,

    output  reg        apb_psel    ,
    output  reg        apb_penable ,
    output  reg        apb_pwrite  ,
    output  reg [15:0] apb_paddr   ,
    output  reg [31:0] apb_pwdata  ,
    input       [31:0] apb_prdata  ,
    input              apb_pready  ,

    input              i_uram_clr  ,
    output  reg        o_uram_en   ,
    output      [ 7:0] o_uram_addr ,
    input       [31:0] i_uram_rdata

);

localparam [1:0]  S_IDLE   = 2'b00;
localparam [1:0]  S_SETUP  = 2'b01; 
localparam [1:0]  S_ACCESS = 2'b10;
localparam [1:0]  S_WAIT   = 2'b11;

reg  [ 1:0] apb_state; 

reg         apb_wen;
reg         apb_ren;
reg  [15:0] apb_addr;
reg  [31:0] apb_wdata;
reg  [31:0] apb_rdata;
wire        apb_done;

always @ (posedge clk or posedge rst)
begin
    if (rst == 1'b1) begin
        apb_wen   <= 1'b0;
        apb_ren   <= 1'b0;
        apb_addr  <= 16'h0;
        apb_wdata <= 32'h0;
    end else begin
        apb_wen   <= uram_wen ? 1'b1 : 1'b0;
        apb_ren   <= uram_ren ? 1'b1 : 1'b0;
        apb_wdata <= uram_wen ? uram_wdata : apb_wdata;
        apb_addr  <=(uram_wen | uram_ren) ? {uram_addr[13:0], 2'b00}  : apb_addr;
    end
end

always @ (posedge clk or posedge rst)
begin
    if (rst == 1'b1)
        apb_state <= S_IDLE;
    else begin
        case (apb_state)
            S_IDLE   : apb_state <= (apb_wen || apb_ren) ? S_SETUP : S_IDLE;
            S_SETUP  : apb_state <= S_ACCESS;
            S_ACCESS : apb_state <= S_WAIT;
            S_WAIT   : apb_state <= apb_done ? ((apb_wen || apb_ren) ? S_SETUP : S_IDLE) : S_WAIT;
            default  : apb_state <= S_IDLE;
        endcase
    end
end

always @ (posedge clk or posedge rst)
begin
    if (rst == 1'b1)
        apb_psel <= 1'b0;
    else
        apb_psel <= (apb_state == S_SETUP) ? 1'b1 : apb_done ? 1'b0 : apb_psel;
end

always @ (posedge clk or posedge rst)
begin
    if (rst == 1'b1)
        apb_penable <= 1'b0;
    else
        apb_penable <= (apb_state == S_ACCESS) ? 1'b1 : apb_done ? 1'b0 : apb_penable;
end

always @ (posedge clk or posedge rst)
begin
    if (rst == 1'b1)
        apb_pwrite <= 1'b0;
    else if (apb_wen == 1'b1)
        apb_pwrite <= 1'b1;
    else if (apb_ren == 1'b1)
        apb_pwrite <= 1'b0;
end

always @ (posedge clk or posedge rst)
begin
    if (rst == 1'b1)
        apb_paddr <= 16'h0;
    else if (apb_wen | apb_ren)
        apb_paddr <= apb_addr; 
end

always @ (posedge clk or posedge rst)
begin
    if (rst == 1'b1) begin
        apb_pwdata <= 32'h0;
    end else if (apb_wen == 1'b1) begin
        apb_pwdata <= apb_wdata;
    end
end

assign apb_done = apb_psel & apb_penable & apb_pready;

always @ (posedge clk or posedge rst)
begin
    if (rst == 1'b1) begin
        apb_rdata <= 32'h0;
    end else if (apb_done & (apb_pwrite == 1'b0)) begin
        apb_rdata <= apb_prdata;
    end
end

reg  [1:0] uram_en_r;

always @ (posedge clk or posedge rst)
begin
    if (rst == 1'b1) begin
        uram_en_r <= 2'b00;
    end else begin
        uram_en_r <= {uram_en_r[0], uram_update};
    end
end

always @ (posedge clk or posedge rst)
begin
    if (rst == 1'b1) begin
        o_uram_en <= 1'b0;
    end else if (uram_en_r[1:0] == 2'b01) begin
        o_uram_en <= 1'b1;
    end else if (i_uram_clr == 1'b1) begin
        o_uram_en <= 1'b0;
    end
end

assign o_uram_addr = uram_addr[7:0];
assign uram_rdata  = i_uram_rdata;

endmodule

`timescale 1ps / 1ps

module ph1_ddrphy_clk_gen #(
    parameter  PLL0_REFCLK_FREQ = "100",
    parameter  PLL0_REFCLK_DIV  =  1   ,
    parameter  PLL0_FBKCLK_DIV  =  12  ,
    parameter  PLL0_FRAC        = "DISABLE",
    parameter  PLL0_FRAC_SDM    =  0   ,
    parameter  PLL0_CLK2_DIV    =  3   ,
    parameter  PLL0_CLK3_DIV    =  24  ,
    parameter  PLL1_REFCLK_FREQ = "100",
    parameter  PLL1_REFCLK_DIV  =  1   ,
    parameter  PLL1_CLK0_DIV    =  12
)(
    input            sys_rst    , 
    input            ref_clk    , 

    output           cfg_clk    ,
    output           dfi_clk    ,
    output  [3-1:0]  ctl_clk    ,
    output  [3-1:0]  ddr_clk    ,
    output  [4-1:0]  usr_clk    ,
    output           pll_lock
);

wire  pll0_lock;
wire  pll1_lock;

wire  pll0_clk_0;
wire  pll0_clk_1;
wire  pll0_clk_2;
wire  pll0_clk_3;
wire  pll1_clk_0;
wire  pll1_clk_1;
wire  pll1_clk_2;
wire  pll1_clk_3;
wire  pll1_clk_4;

wire  pll0_mlclk_1;
wire  pll0_mlclk_2;

ph1_ddrphy_pll0 u_ddrphy_pll0 (
    .refclk       ( ref_clk    ),
    .reset        ( sys_rst    ),
    .clk0_out     ( pll0_clk_0 ),
    .clk1_out     ( pll0_clk_1 ),
    .clk2_out     ( pll0_clk_2 ),
    .clk3_out     ( pll0_clk_3 ),
    .lock         ( pll0_lock  )
);

ph1_ddrphy_pll1 u_ddrphy_pll1 (
    .refclk       ( pll0_clk_0 ),
    .reset        (~pll0_lock  ),
    .clk0_out     ( pll1_clk_0 ),
    .clk1_out     ( usr_clk[0] ),
    .clk2_out     ( usr_clk[1] ),
    .clk3_out     ( usr_clk[2] ),
    .clk4_out     ( usr_clk[3] ),
    .lock         ( pll1_lock  )
);

PH1_PHY_HP_MLCLK #(
    .MODE    ("HPS")
) u_mlclk_0  (
    .ce      ( 1'b1         ),
    .clkin   ( pll0_clk_1   ),
    .clkout  ( pll0_mlclk_1 )
);

PH1_PHY_HP_MLCLK #(
    .MODE    ("HPS")
) u_mlclk_1  (
    .ce      ( 1'b1         ),
    .clkin   ( pll0_clk_2   ),
    .clkout  ( pll0_mlclk_2 )
);

genvar n;
generate
for (n = 0; n <= 3-1; n = n+1) begin : ioclk
    PH1_PHY_HP_IOCLK #( 
        .MODE   ("HPS")
    ) u_ioclk_0 (
        .clkin  ( pll0_mlclk_1 ),
        .clkout ( ctl_clk[n]   )
    );

    PH1_PHY_HP_IOCLK #(
        .MODE   ("HPS")
    ) u_ioclk_1 (
        .clkin  ( pll0_mlclk_2 ),
        .clkout ( ddr_clk[n]   )
    );
end
endgenerate

assign pll_lock = pll1_lock;

`ifdef PH1_DDRPHY_SIM
assign cfg_clk  = pll0_clk_2;
`else
assign cfg_clk  = pll0_clk_3;
`endif

PH1_LOGIC_BUFG u_dfi_clk_bufg (
    .i ( pll1_clk_0 ),
    .o ( dfi_clk    ) 
);

endmodule

`timescale 1 ns / 100 fs

module ph1_ddrphy_pll0 (
  refclk,
  reset,
  lock,
  clk0_out,
  clk1_out,
  clk2_out,
  clk3_out,
  clkb1_out,
  clkb2_out 
);

  input refclk;
  input reset;
  output lock;
  output clk0_out;
  output clk1_out;
  output clk2_out;
  output clk3_out;
  output clkb1_out;
  output clkb2_out;

  PH1_PHY_PLL #(
    .DYN_PHASE_PATH_SEL("DISABLE"),
    .DYN_FPHASE_EN("DISABLE"),
    .MPHASE_ENABLE("DISABLE"),
    .FIN("100.000000"),
    .FEEDBK_MODE("NOCOMP"),
    .FBKCLK("VCO_PHASE0"),
    .FBKCLK_INT("VCO_PHASE0"),
    .PLL_FEED_TYPE("INTERNAL"),
    .PLL_USR_RST("ENABLE"),
    .GMC_GAIN(2),
    .ICP_CUR(5),
    .LPF_CAP(2),
    .LPF_RES(2),
    .REFCLK_DIV(1),
    .FBCLK_DIV(16),
    .CLKC0_ENABLE("ENABLE"),
    .CLKC0_DIV(12),
    .CLKC0_CPHASE(11),
    .CLKC0_FPHASE(3),
    .CLKC0_FPHASE_RSTSEL(0),
    .CLKC0_DUTY_INT(6),
    .CLKC0_DUTY50("ENABLE"),
    .CLKC1_ENABLE("ENABLE"),
    .CLKC1_DIV(12),
    .CLKC1_CPHASE(11),
    .CLKC1_FPHASE(0),
    .CLKC1_FPHASE_RSTSEL(0),
    .CLKC1_DUTY_INT(6),
    .CLKC1_DUTY50("ENABLE"),
    .CLKC2_ENABLE("ENABLE"),
    .CLKC2_DIV(3),
    .CLKC2_CPHASE(2),
    .CLKC2_FPHASE(0),
    .CLKC2_FPHASE_RSTSEL(0),
    .CLKC2_DUTY_INT(2),
    .CLKC2_DUTY50("ENABLE"),
    .CLKC3_ENABLE("ENABLE"),
    .CLKC3_DIV(32),
    .CLKC3_CPHASE(31),
    .CLKC3_FPHASE(0),
    .CLKC3_FPHASE_RSTSEL(0),
    .CLKC3_DUTY_INT(16),
    .CLKC3_DUTY50("ENABLE"),
    .INTPI(2),
    .HIGH_SPEED_EN("DISABLE"),
    .SSC_ENABLE("DISABLE"),
    .SSC_MODE("CENTER"),
    .SSC_AMP(0.0000),
    .SSC_FREQ_DIV(0),
    .SSC_RNGE(0),
    .FRAC_ENABLE("DISABLE"),
    .DITHER_ENABLE("DISABLE"),
    .SDM_FRAC(0) 
  ) pll_inst (
    .refclk(refclk),
    .pllreset(reset),
    .lock(lock),
    .pllpd(1'b0),
    .refclk_rst(1'b0),
    .wakeup(1'b0),
    .psclk(1'b0),
    .psdown(1'b0),
    .psstep(1'b0),
    .psclksel(3'b000),
    .psdone(ph1_ddrphy_pll0_open0),
    .cps_step(2'b00),
    .drp_clk(1'b0),
    .drp_rstn(1'b1),
    .drp_sel(1'b0),
    .drp_rd(1'b0),
    .drp_wr(1'b0),
    .drp_addr(8'b00000000),
    .drp_wdata(8'b00000000),
    .drp_err(ph1_ddrphy_pll0_open1),
    .drp_rdy(ph1_ddrphy_pll0_open2),
    .drp_rdata({ph1_ddrphy_pll0_open10, ph1_ddrphy_pll0_open9, ph1_ddrphy_pll0_open8, ph1_ddrphy_pll0_open7, ph1_ddrphy_pll0_open6, ph1_ddrphy_pll0_open5, ph1_ddrphy_pll0_open4, ph1_ddrphy_pll0_open3}),
    .fbclk(1'b0),
    .clkc({ph1_ddrphy_pll0_open19, ph1_ddrphy_pll0_open17, ph1_ddrphy_pll0_open15, ph1_ddrphy_pll0_open13, clk3_out, clk2_out, clk1_out, clk0_out}),
    .clkcb({ph1_ddrphy_pll0_open20, ph1_ddrphy_pll0_open18, ph1_ddrphy_pll0_open16, ph1_ddrphy_pll0_open14, ph1_ddrphy_pll0_open12, clkb2_out, clkb1_out, ph1_ddrphy_pll0_open11}),
    .clkc_en({8'b00001111}),
    .clkc_rst(2'b00),
    .ext_freq_mod_clk(1'b0),
    .ext_freq_mod_en(1'b0),
    .ext_freq_mod_val(17'b00000000000000000),
    .ssc_en(1'b0) 
  );

endmodule

`timescale 1 ns / 100 fs

module ph1_ddrphy_pll1 (
  refclk,
  reset,
  clk1_en,
  clk2_en,
  clk3_en,
  clk4_en,
  lock,
  clk0_out,
  clk1_out,
  clk2_out,
  clk3_out,
  clk4_out 
);

  input refclk;
  input reset;
  input clk1_en;
  input clk2_en;
  input clk3_en;
  input clk4_en;
  output lock;
  output clk0_out;
  output clk1_out;
  output clk2_out;
  output clk3_out;
  output clk4_out;

  wire clk0_buf;

  PH1_LOGIC_BUFG bufg_feedback (
    .i(clk0_buf),
    .o(clk0_out) 
  );

  PH1_PHY_PLL #(
    .DYN_PHASE_PATH_SEL("DISABLE"),
    .DYN_FPHASE_EN("DISABLE"),
    .MPHASE_ENABLE("DISABLE"),
    .FIN("133.250000"),
    .FEEDBK_MODE("NORMAL"),
    .FBKCLK("CLKC0_EXT"),
    .PLL_FEED_TYPE("EXTERNAL"),
    .PLL_USR_RST("ENABLE"),
    .GMC_GAIN(2),
    .ICP_CUR(5),
    .LPF_CAP(2),
    .LPF_RES(2),
    .REFCLK_DIV(1),
    .FBCLK_DIV(1),
    .CLKC0_ENABLE("ENABLE"),
    .CLKC0_DIV(9),
    .CLKC0_CPHASE(8),
    .CLKC0_FPHASE(0),
    .CLKC0_FPHASE_RSTSEL(0),
    .CLKC0_DUTY_INT(5),
    .CLKC0_DUTY50("ENABLE"),
    .CLKC1_ENABLE("ENABLE"),
    .CLKC1_DIV(12),
    .CLKC1_CPHASE(11),
    .CLKC1_FPHASE(0),
    .CLKC1_FPHASE_RSTSEL(0),
    .CLKC1_DUTY_INT(6),
    .CLKC1_DUTY50("ENABLE"),
    .CLKC2_ENABLE("ENABLE"),
    .CLKC2_DIV(12),
    .CLKC2_CPHASE(11),
    .CLKC2_FPHASE(0),
    .CLKC2_FPHASE_RSTSEL(0),
    .CLKC2_DUTY_INT(6),
    .CLKC2_DUTY50("ENABLE"),
    .CLKC3_ENABLE("ENABLE"),
    .CLKC3_DIV(12),
    .CLKC3_CPHASE(11),
    .CLKC3_FPHASE(0),
    .CLKC3_FPHASE_RSTSEL(0),
    .CLKC3_DUTY_INT(6),
    .CLKC3_DUTY50("ENABLE"),
    .CLKC4_ENABLE("ENABLE"),
    .CLKC4_DIV(12),
    .CLKC4_CPHASE(11),
    .CLKC4_FPHASE(0),
    .CLKC4_FPHASE_RSTSEL(0),
    .CLKC4_DUTY_INT(6),
    .CLKC4_DUTY50("ENABLE"),
    .INTPI(1),
    .HIGH_SPEED_EN("DISABLE"),
    .SSC_ENABLE("DISABLE"),
    .SSC_MODE("CENTER"),
    .SSC_AMP(0.0000),
    .SSC_FREQ_DIV(0),
    .SSC_RNGE(0),
    .FRAC_ENABLE("DISABLE"),
    .DITHER_ENABLE("DISABLE"),
    .SDM_FRAC(0) 
  ) pll_inst (
    .refclk(refclk),
    .pllreset(reset),
    .lock(lock),
    .pllpd(1'b0),
    .refclk_rst(1'b0),
    .wakeup(1'b0),
    .psclk(1'b0),
    .psdown(1'b0),
    .psstep(1'b0),
    .psclksel(3'b000),
    .psdone(ph1_ddrphy_pll1_open0),
    .cps_step(2'b00),
    .drp_clk(1'b0),
    .drp_rstn(1'b1),
    .drp_sel(1'b0),
    .drp_rd(1'b0),
    .drp_wr(1'b0),
    .drp_addr(8'b00000000),
    .drp_wdata(8'b00000000),
    .drp_err(ph1_ddrphy_pll1_open1),
    .drp_rdy(ph1_ddrphy_pll1_open2),
    .drp_rdata({ph1_ddrphy_pll1_open10, ph1_ddrphy_pll1_open9, ph1_ddrphy_pll1_open8, ph1_ddrphy_pll1_open7, ph1_ddrphy_pll1_open6, ph1_ddrphy_pll1_open5, ph1_ddrphy_pll1_open4, ph1_ddrphy_pll1_open3}),
    .fbclk(clk0_out),
    .clkc({ph1_ddrphy_pll1_open20, ph1_ddrphy_pll1_open18, ph1_ddrphy_pll1_open16, clk4_out, clk3_out, clk2_out, clk1_out, clk0_buf}),
    .clkcb({ph1_ddrphy_pll1_open21, ph1_ddrphy_pll1_open19, ph1_ddrphy_pll1_open17, ph1_ddrphy_pll1_open15, ph1_ddrphy_pll1_open14, ph1_ddrphy_pll1_open13, ph1_ddrphy_pll1_open12, ph1_ddrphy_pll1_open11}),
    .clkc_en({3'b000, clk4_en, clk3_en, clk2_en, clk1_en, 1'b1}),
    .clkc_rst(2'b00),
    .ext_freq_mod_clk(1'b0),
    .ext_freq_mod_en(1'b0),
    .ext_freq_mod_val(17'b00000000000000000),
    .ssc_en(1'b0) 
  );

endmodule

`timescale 1ps / 1ps

module ph1_ddrphy_ppc #(
    parameter DEVICE = "PH1A400",
    parameter DX_NUM = 8
)(

    input              usr_clk                  ,
    input              usr_rst_n                ,

    input  [  3:0]     dfi_reset_n              ,
    input  [  7:0]     dfi_cke                  ,
    input  [  7:0]     dfi_odt                  ,
    input  [  7:0]     dfi_cs_n                 ,
    input  [  3:0]     dfi_act_n                ,
    input  [  3:0]     dfi_ras_n                ,
    input  [  3:0]     dfi_cas_n                ,
    input  [  3:0]     dfi_we_n                 ,
    input  [  7:0]     dfi_bg                   ,
    input  [ 11:0]     dfi_bank                 ,
    input  [ 71:0]     dfi_addr                 ,

    input  [ 35:0]     dfi_wrdata_en            ,
    input  [575:0]     dfi_wrdata               ,
    input  [ 71:0]     dfi_wrdata_mask          ,
    input  [ 35:0]     dfi_rddata_en            ,
    output [ 35:0]     dfi_rddata_valid         ,
    output [575:0]     dfi_rddata               ,

    input  [  3:0]     dfi_parity               ,
    output [  3:0]     dfi_alert_n              ,

    input  [  1:0]     dfi_ctrlupd_req          ,
    output [  1:0]     dfi_ctrlupd_ack          ,

    output [  1:0]     dfi_phyupd_req           ,
    output [  3:0]     dfi_phyupd_type          ,
    input  [  1:0]     dfi_phyupd_ack           ,

    output             ctl_ac_rst_n         ,
    output [ 8:0]      ctl_dx_rst_n         ,
    output             ctl_ac_fifo_rst_n    ,
    output [ 8:0]      ctl_dx_fifo_rst_n    ,

    output [ 15:0]     ctl_ck               ,
    output [ 15:0]     ctl_cke              ,
    output [ 15:0]     ctl_odt              ,
    output [ 15:0]     ctl_cs_n             ,
    output [  7:0]     ctl_act_n            ,
    output [ 15:0]     ctl_bg               ,
    output [ 15:0]     ctl_ba               ,
    output [143:0]     ctl_addr             ,
    output [  7:0]     ctl_parity           ,
    input  [  7:0]     ctl_alert_n          ,
    output [575:0]     ctl_wdq              ,
    output [ 71:0]     ctl_wdm              ,
    output [ 71:0]     ctl_wdqs             ,
    output [ 71:0]     ctl_gate             ,
    input  [ 17:0]     ctl_rdq_vld          ,
    input  [575:0]     ctl_rdq              ,
    input  [ 71:0]     ctl_rdbi             ,

    output             ctl_ram_rst_n        ,
    output             ctl_ram_cke          ,

    output [ 71:0]     ctl_pdr              ,
    output [ 71:0]     ctl_te               ,
    output [ 71:0]     ctl_oe               ,

    input  [ 11:0]     dcc_done             ,
    output             dcc_clear            ,
    output             dcc_start            ,
    output             dcc_update           ,

    input  [  2:0]     zqcal_done           ,
    output             zqcal_clear          ,
    output             zqcal_start          ,
    output             zqcal_update         ,

    output [  8:0]     mdl_cal_mode         ,
    output [ 62:0]     mdl_cal_clk_en       ,
    output [ 62:0]     mdl_cal_en           ,
    input  [ 62:0]     mdl_cal_en_out       ,
    input  [ 62:0]     mdl_cal_out          ,

    output [ 12:0]     dcp_sel              ,
    output [ 59:0]     dcp_addr             ,
    output [ 89:0]     dcp_data             ,
    output [  9:0]     dcp_gate             ,
    output [  8:0]     dcp_rksel            ,

    output [  7:0]     lpbk_en              ,

    input  [ 71:0]     wrlvl_din            ,
    output [  8:0]     wrlvl_mode           ,
    output             dqs_pupd_en          ,
    input  [ 17:0]     dqs_gate_status      ,
    input  [ 17:0]     dqs_gate_cnt         ,

    input              apb_pclk             ,
    input              apb_prst_n           ,
    input              apb_psel             ,
    input              apb_penable          ,
    input              apb_pwrite           ,
    input  [ 15:0]     apb_paddr            ,
    input  [ 31:0]     apb_pwdata           ,
    output [ 31:0]     apb_prdata           ,
    output             apb_pready
);

wire  [ 15:0]    ctl_cke_p    ;
wire  [ 15:0]    ctl_odt_p    ;
wire  [ 15:0]    ctl_cs_p     ;
wire  [ 15:0]    ctl_bg_p     ;
wire  [ 15:0]    ctl_ba_p     ;
wire  [143:0]    ctl_addr_p   ;
wire  [ 15:0]    ctl_bg_r0    ;
wire  [ 15:0]    ctl_ba_r0    ;
wire  [143:0]    ctl_addr_r0  ;
wire  [ 15:0]    ctl_bg_r1    ;
wire  [ 15:0]    ctl_ba_r1    ;
wire  [143:0]    ctl_addr_r1  ;

wire  [575:0]    ctl_rdq_p    ;
wire  [575:0]    ctl_wdq_p    ;

wire  [ 71:0]    ctl_gate_pre ;

reg   [  1:0]    apb_rk_en    ;
reg   [  1:0]    ctl_rk_en    ;

wire             ppc_apb_pclk    ;
wire             ppc_apb_prst_n  ;
wire             ppc_apb_psel    ;
wire             ppc_apb_penable ;
wire             ppc_apb_pwrite  ;
wire  [ 15:0]    ppc_apb_paddr   ;
wire  [ 31:0]    ppc_apb_pwdata  ;
wire  [ 31:0]    ppc_apb_prdata  ;
wire             ppc_apb_pready  ;

wire             cfg_apb_pclk    ;
wire             cfg_apb_prst_n  ;
wire             cfg_apb_psel    ;
wire             cfg_apb_penable ;
wire             cfg_apb_pwrite  ;
wire  [ 15:0]    cfg_apb_paddr   ;
wire  [ 31:0]    cfg_apb_pwdata  ;
wire  [ 31:0]    cfg_apb_prdata  ;
wire             cfg_apb_pready  ;

assign ppc_apb_pclk     = apb_pclk    ;
assign ppc_apb_prst_n   = apb_prst_n  ;
assign ppc_apb_penable  = apb_penable ;
assign ppc_apb_pwrite   = apb_pwrite  ;
assign ppc_apb_paddr    = apb_paddr   ;
assign ppc_apb_pwdata   = apb_pwdata  ;

assign cfg_apb_pclk     = apb_pclk    ;
assign cfg_apb_prst_n   = apb_prst_n  ;
assign cfg_apb_penable  = apb_penable ;
assign cfg_apb_pwrite   = apb_pwrite  ;
assign cfg_apb_paddr    = apb_paddr   ;
assign cfg_apb_pwdata   = apb_pwdata  ;

assign ppc_apb_psel     = (apb_paddr[10] == 1'b0) ? apb_psel : 1'b0;
assign cfg_apb_psel     = (apb_paddr[10] == 1'b1) ? apb_psel : 1'b0;

assign apb_pready       = (apb_paddr[10] == 1'b0) ? ppc_apb_pready :
                          (apb_paddr[10] == 1'b1) ? cfg_apb_pready : 1'b1;
assign apb_prdata       = (apb_paddr[10] == 1'b0) ? ppc_apb_prdata :
                          (apb_paddr[10] == 1'b1) ? cfg_apb_prdata : 32'hdeadbeef;

genvar n,p,b;

for (p = 0; p < 8; p = p+1) begin : ac_pIdx
    for (n=0; n<18; n=n+1) begin : addr_bIdx
        assign ctl_addr_r0[n*8 + p] = ctl_ram_rst_n ? ctl_addr_p[p*18 + n] : 1'b0;
    end
    for (n=0; n<2 ; n=n+1) begin : ac_bIdx
        assign ctl_bg_r0[n*8 + p] = ctl_ram_rst_n ? ctl_bg_p  [p*2  + n] : 1'b0;
        assign ctl_ba_r0[n*8 + p] = ctl_ram_rst_n ? ctl_ba_p  [p*2  + n] : 1'b0;
        assign ctl_cs_n [n*8 + p] = ctl_ram_rst_n ? ctl_cs_p  [p*2  + n] : 1'b1;
        assign ctl_odt  [n*8 + p] = ctl_ram_rst_n ? ctl_odt_p [p*2  + n] : 1'b0;
        assign ctl_cke  [n*8 + p] = ctl_ram_rst_n ? ctl_cke_p [p*2  + n] : 1'b0;
    end
end

assign ctl_ram_cke = &ctl_cke_p;

for (b = 0; b < 9; b = b+1) begin : rdx_bId
    for (p = 0; p < 8; p = p+1) begin : rdx_pIdx
        for (n = 0; n < 8; n = n+1) begin : rdx_nIdx
            assign ctl_rdq_p[n+8*(p+b*8)] = ctl_rdq[p+8*(n+b*8)];
         end
    end
end

for (b = 0; b < 9; b = b+1) begin : wdx_bIdx
    for (p = 0; p < 8; p = p+1) begin : wdx_pIdx
        for (n = 0; n < 8; n = n+1) begin : wdx_nIdx
            assign ctl_wdq[p+8*(n+b*8)] = ctl_wdq_p[n+8*(p+b*8)];
        end
    end
end

`ifdef MC0_DRAM_DDR4
`ifdef MC0_DDR4_X8
assign ctl_bg_r1   = {ctl_bg_r0[ 7:0], ctl_bg_r0[15:8]};
`else
assign ctl_bg_r1   = {ctl_bg_r0[15:8], ctl_bg_r0[ 7:0]};
`endif
assign ctl_ba_r1   = {ctl_ba_r0[ 7:0], ctl_ba_r0[15:8]};
assign ctl_addr_r1 = {ctl_addr_r0[18*8-1:14*8],
                      ctl_addr_r0[11*8+:8], ctl_addr_r0[12*8+:8], ctl_addr_r0[13*8+:8],
                      ctl_addr_r0[10*8+:8], ctl_addr_r0[ 9*8+:8],
                      ctl_addr_r0[ 7*8+:8], ctl_addr_r0[ 8*8+:8],
                      ctl_addr_r0[ 5*8+:8], ctl_addr_r0[ 6*8+:8],
                      ctl_addr_r0[ 3*8+:8], ctl_addr_r0[ 4*8+:8], ctl_addr_r0[0*8+:3*8]};
`else
assign ctl_bg_r1   = {ctl_bg_r0[15:8], ctl_bg_r0[ 7:0]};
assign ctl_ba_r1   = {ctl_ba_r0[ 7:0], ctl_ba_r0[15:8]};
assign ctl_addr_r1 = {ctl_addr_r0[18*8-1:9*8],
                      ctl_addr_r0[7*8+:8], ctl_addr_r0[8*8+:8],
                      ctl_addr_r0[5*8+:8], ctl_addr_r0[6*8+:8],
                      ctl_addr_r0[3*8+:8], ctl_addr_r0[4*8+:8], ctl_addr_r0[0*8+:3*8]};
`endif

`ifdef MC0_ADDR_MIRROR

assign ctl_bg   = (ctl_cs_n[15:8] != 8'hff) ? ctl_bg_r1   : ctl_bg_r0;
assign ctl_ba   = (ctl_cs_n[15:8] != 8'hff) ? ctl_ba_r1   : ctl_ba_r0;
assign ctl_addr = (ctl_cs_n[15:8] != 8'hff) ? ctl_addr_r1 : ctl_addr_r0;
`else
assign ctl_bg   = ctl_bg_r0;
assign ctl_ba   = ctl_ba_r0;
assign ctl_addr = ctl_addr_r0;
`endif

PH1_PHY_DDR4_CAL #(
    .DEVICE  (DEVICE)
) u_ddrppc (

    .hctrl_clk                  ( usr_clk              ),
    .hctrl_rst_n                ( usr_rst_n            ),
    .rstn_low                   ( ctl_ac_rst_n         ),
    .rstn_upp                   ( ctl_dx_rst_n         ),
    .hctrl_gpr0                 (                      ),
    .hctrl_ctl_idle             ( 1'b0                 ),

    .dfi_dram_clk_disable       ( 2'b00                ),
    .dfi_reset_n                ( dfi_reset_n          ),
    .dfi_cke                    ( dfi_cke              ),
    .dfi_odt                    ( dfi_odt              ),
    .dfi_cs_n                   ( dfi_cs_n             ),
    .dfi_act_n                  ( dfi_act_n            ),
    .dfi_ras_n                  ( dfi_ras_n            ),
    .dfi_cas_n                  ( dfi_cas_n            ),
    .dfi_we_n                   ( dfi_we_n             ),
    .dfi_bg                     ( dfi_bg               ),
    .dfi_bank                   ( dfi_bank             ),
    .dfi_address                ( dfi_addr             ),
    .dfi_parity_in              ( dfi_parity           ),
    .dfi_alert_n                ( dfi_alert_n          ),
    .dfi_wrdata_en              ( dfi_wrdata_en        ),
    .dfi_wrdata                 ( dfi_wrdata           ),
    .dfi_wrdata_mask            ( dfi_wrdata_mask      ),
    .dfi_rddata_en              ( dfi_rddata_en        ),
    .dfi_rddata_valid           ( dfi_rddata_valid     ),
    .dfi_rddata                 ( dfi_rddata           ),
    .dfi_rddata_dbi_n           (                      ),

    .dfi_init_start             ( 1'b0                 ),
    .dfi_init_complete          (                      ),
    .dfi_data_byte_disable      ( 9'b0                 ),
    .dfi_lp_ctrl_req            ( 2'b0                 ),
    .dfi_lp_data_req            ( 2'b0                 ),
    .dfi_lp_wakeup              ( 8'b0                 ),
    .dfi_lp_ack                 (                      ),
    .dfi_ctrlupd_req            ( dfi_ctrlupd_req      ),
    .dfi_ctrlupd_ack            ( dfi_ctrlupd_ack      ),
    .dfi_phyupd_req             ( dfi_phyupd_req       ),
    .dfi_phyupd_type            ( dfi_phyupd_type      ),
    .dfi_phyupd_ack             ( dfi_phyupd_ack       ),

    .hctrl2mem_ram_rst_n        ( ctl_ram_rst_n        ),
    .hctrl2mem_ck               ( ctl_ck               ),
    .hctrl2mem_cke              ( ctl_cke_p            ),
    .hctrl2mem_odt              ( ctl_odt_p            ),
    .hctrl2mem_cs_n             ( ctl_cs_p             ),
    .hctrl2mem_act_n            ( ctl_act_n            ),
    .hctrl2mem_ba               ( ctl_ba_p             ),
    .hctrl2mem_bg               ( ctl_bg_p             ),
    .hctrl2mem_addr             ( ctl_addr_p           ),
    .hctrl2mem_parity           ( ctl_parity           ),
    .hctrl_alert_n              ( ctl_alert_n          ),

    .hctrl2mem_wdqsout          ( ctl_wdqs             ),
    .hctrl2mem_dqout            ( ctl_wdq_p            ),
    .hctrl2mem_dmout            ( ctl_wdm              ),
    .hctrl2mem_rdqs_en          ( ctl_gate_pre         ),
    .hctrl_datain_en_upp        ( ctl_rdq_vld          ),
    .hctrl_dqin                 ( ctl_rdq_p            ),
    .hctrl_dmin                 ( ctl_rdbi             ),

    .hctrl2mem_dataout_en       ( ctl_oe               ),
    .hctrl2io_pdr               ( ctl_pdr              ),
    .hctrl2io_odt_en            ( ctl_te               ),

    .dcc_vt_update_en_in        ( 12'b0                ),
    .dcc_done_bank              ( dcc_done             ),
    .dcc_clrcfg                 ( dcc_clear            ),
    .dcc_start                  ( dcc_start            ),
    .dcc_update_en              ( dcc_update           ),
    .dcc_vt_update_en_out       (                      ),

    .zqcal_done_bank            ( zqcal_done           ),
    .zqcal_clrcfg               ( zqcal_clear          ),
    .zqcal_start                ( zqcal_start          ),
    .zqcal_update_en            ( zqcal_update         ),
    .zqcal_vt_update_en_out     (                      ),
    .zqcal_vt_update_en_in      ( 3'b0                 ),

    .delay_dti_low              ( 3'b0                 ),
    .delay_dti_upp              ( 9'b0                 ),

    .delay_cal_mode_low         (                      ),
    .delay_cal_clk_en_low       (                      ),
    .delay_cal_en_out_low       (                      ),
    .delay_cal_en_in_low        ( 2'b11                ),
    .delay_cal_in_low           ( 2'b11                ),

    .delay_cal_mode_upp         ( mdl_cal_mode         ),
    .delay_cal_clk_en_upp       ( mdl_cal_clk_en       ),
    .delay_cal_en_out_upp       ( mdl_cal_en           ),
    .delay_cal_en_in_upp        ( mdl_cal_en_out       ),
    .delay_cal_in_upp           ( mdl_cal_out          ),

    .apb_dly_sel                ( dcp_sel              ),
    .apb_dly_addr               ( dcp_addr             ),
    .apb_dly_data               ( dcp_data             ),
    .apb_dly_gate               ( dcp_gate             ),
    .delay_gate                 ( dcp_rksel            ),

    .loopback_en_out            ( lpbk_en              ),
    .loopback_clk_sel           (                      ),
    .loopback_mode              (                      ),
    .loopback_clknum_sel        (                      ),
    .loopback_fifo_resp_low     (                      ),
    .loopback_fifo_resp_upp     (                      ),
    .loopback_fifo_dataout_low  (                      ),
    .loopback_fifo_dataout_upp  (                      ),
    .loopback_fifo_rstn_low     ( ctl_ac_fifo_rst_n    ),
    .loopback_fifo_rstn_upp     ( ctl_dx_fifo_rst_n    ),

    .vref_value_low             (                      ),
    .vref_value_upp             (                      ),
    .hctrl_vref_rank_sel_upp    (                      ),

    .wrlvl_qin                  ( wrlvl_din            ),
    .wrlvl_mode                 ( wrlvl_mode           ),
    .dqs_pupd_en                ( dqs_pupd_en          ),
    .dqs_gate_in                ( 72'b0                ),
    .phy_status                 ( dqs_gate_status      ),
    .phy_dqs_cnt                ( dqs_gate_cnt         ),

    .hctrl_addr                 ( 144'b0               ),
    .hctrl_act_n                (   8'b0               ),
    .hctrl_ba                   (  16'b0               ),
    .hctrl_bg                   (  16'b0               ),
    .hctrl_cke                  (  16'b0               ),
    .hctrl_cs_n                 (  16'b0               ),
    .hctrl_odt                  (  16'b0               ),
    .hctrl_parity               (   8'b0               ),

    .delay_testmode_en          (                      ),
    .delay_osc_sel_low          (                      ),
    .delay_osc_div              (                      ),
    .delay_osc_chain_en         (                      ),
    .delay_osc_wdata_sel        (                      ),
    .delay_osc_wrlvl_sel        (                      ),

    .hctrl_datain_en_low        ( 1'b0                 ),
    .ctrlclk_en_gate_low        (                      ),
    .ctrlclk_en_gate_upp        (                      ),
    .ddrclk_en_gate_low         (                      ),
    .ddrclk_en_gate_upp         (                      ),
    .rdclk_en_gate_low          (                      ),
    .rdclk_en_gate_upp          (                      ),
    .apb_dfi_io_pd              (                      ),

    .hctrl_scan_atpg_mode       ( 1'b0                 ),
    .ctrlclk_en_low             ( 1'b0                 ),
    .ctrlclk_en_upp             ( 9'b0                 ),
    .ddrclk_en_low              ( 1'b0                 ),
    .ddrclk_en_upp              ( 9'b0                 ),
    .rdclk_en_low               ( 1'b0                 ),
    .rdclk_en_upp               ( 9'b0                 ),

    .apb_sync_path_sel          ( 1'b0                 ),
    .hctrl_apb_clk              ( ppc_apb_pclk         ),
    .hctrl_apb_rst_n            ( ppc_apb_prst_n       ),
    .hctrl_apb_sel              ( ppc_apb_psel         ),
    .hctrl_apb_enable           ( ppc_apb_penable      ),
    .hctrl_apb_wr_rdn           ( ppc_apb_pwrite       ),
    .hctrl_apb_addr             ( ppc_apb_paddr[9:0]   ),
    .hctrl_apb_wdata            ( ppc_apb_pwdata       ),
    .hctrl_apb_rdata            ( ppc_apb_prdata       ),
    .hctrl_apb_rdy              ( ppc_apb_pready       ),
    .hctrl_apb_error            (                      ),

    .ioloopback_sel_low         (                      ),
    .ioloopback_sel_upp         (                      ),
    .apb_age_toggle_inv         (                      ),
    .apb_age_toggle             (                      ),
    .hctrl_scan_clk             ( 1'b0                 ),
    .hctrl_scan_rst_n           ( 1'b0                 ),
    .hctrl_scan_enable          ( 1'b0                 ),
    .hctrl_scan_in              ( 12'b0                ),
    .hctrl_scan_compress_mode   ( 1'b0                 ),
    .hctrl_scan_out             (                      ),
    .offcal_done_bank           ( 12'b0                ),
    .offcal_vt_update_en_in     ( 12'b0                ),
    .offcal_clrcfg              (                      ),
    .offcal_vt_update_en_out    (                      ),
    .offcal_start               (                      ),
    .offcal_update_en           (                      ),
    .phy2hctrl_dti_low          ( 2'b0                 ),
    .phy2hctrl_dti_upp          ( 18'b0                ),
    .hctrl2phy_dto              (                      )

);

always @ (posedge ppc_apb_pclk or negedge ppc_apb_prst_n)
begin
    if (ppc_apb_prst_n == 1'b0)
        apb_rk_en <= 2'b00;
    else if (ppc_apb_psel && ppc_apb_penable && ppc_apb_pwrite && (ppc_apb_paddr[9:0] == 10'h81) && ppc_apb_pready)
        apb_rk_en <= ppc_apb_pwdata[17:16];
end

always @ (posedge usr_clk) begin
    ctl_rk_en <= apb_rk_en;
end

generate
if (DEVICE == "PH1A400") begin : u_gate_gen
ph1_ddrphy_gate_gen #(
    .DX_NUM         ( DX_NUM             )
) u_ddrppc_gate_gen (

    .clk            ( usr_clk            ),
    .rst_n          ( usr_rst_n          ),
    .dfi_rddata_en  ( dfi_rddata_en      ),
    .gate_pre       ( ctl_gate_pre       ),
    .gate_out       ( ctl_gate           ),

    .apb_pclk       ( cfg_apb_pclk       ),
    .apb_prst_n     ( cfg_apb_prst_n     ),
    .apb_psel       ( cfg_apb_psel       ),
    .apb_penable    ( cfg_apb_penable    ),
    .apb_paddr      ( cfg_apb_paddr[7:0] ),
    .apb_pwrite     ( cfg_apb_pwrite     ),
    .apb_pwdata     ( cfg_apb_pwdata     ),
    .apb_prdata     ( cfg_apb_prdata     ),
    .apb_pready     ( cfg_apb_pready     )
);
end else begin
assign ctl_gate = ctl_gate_pre;
assign cfg_apb_pready = 1'b1;
assign cfg_apb_prdata = 32'h20250401;
end
endgenerate

endmodule

`timescale 1ps / 1ps
module ph1_ddrphy_bus_matrix #(

    parameter BK_NUM      = 3,
    parameter BYTE_NUM    = 4,

    parameter WDM         = "ENABLE",
    parameter WDBI        = "DISABLE",
    parameter RDBI        = "DISABLE",

    parameter AC_NUM      = 3,
    parameter DX_NUM      = 9,
    parameter CK_WIDTH    = 1,
    parameter ODT_WIDTH   = 1,
    parameter CKE_WIDTH   = 1,
    parameter CS_WIDTH    = 1,
    parameter BG_WIDTH    = 2,
    parameter BA_WIDTH    = 2,
    parameter ADR_WIDTH   = 17,

    parameter DQS_WIDTH   = 9,
    parameter DQ_WIDTH    = 72,
    parameter DM_WIDTH    = 9,

    parameter BK0_BYTE    = 4'b1111,
    parameter BK1_BYTE    = 4'b1111,
    parameter BK2_BYTE    = 4'b1111,
    parameter BK0_DX_EN   = 4'b1000,
    parameter BK1_DX_EN   = 4'b1111,
    parameter BK2_DX_EN   = 4'b1111,

    parameter CK_MAP      = 48'h004_005,
    parameter RST_MAP     = 12'h027,
    parameter CKE_MAP     = 24'h020,
    parameter ODT_MAP     = 24'h000_023,
    parameter CS_MAP      = 24'h000_022,
    parameter RAS_MAP     = 12'h000,
    parameter CAS_MAP     = 12'h000,
    parameter WE_MAP      = 12'h000,
    parameter ACT_MAP     = 12'h026,

    parameter BG_MAP      = 24'h020_019,
    parameter BA_MAP      = 36'h000_025_024,
    parameter ADR_MAP     = 216'h000_018_016_017_014_015_012_013_010_011_008_009_006_007_002_003_000_001,

    parameter PAR_MAP     = 12'h028,
    parameter ALT_MAP     = 12'h029,

    parameter DQS_MAP     = 216'h235_234_225_224_215_214_205_204_135_134_125_124_115_114_105_104_035_034,
    parameter DM_MAP      = 108'h23a_22a_21a_20a_13a_12a_11a_10a_03a,
    parameter DQ_MAP      = 864'h0,

    parameter AC_BYTE_MAP = 32'h00_02_01_00,
    parameter DX_BYTE_MAP = 72'h23_22_21_20_13_12_11_10_03
)(

    input                            clk                 ,
    input                            rst_n               ,

    input                            cal_done            ,

    input                            ctl_ac_rst_n        ,
    input        [  8:0]             ctl_dx_rst_n        ,
    input                            ctl_ac_fifo_rst_n   ,
    input        [  8:0]             ctl_dx_fifo_rst_n   ,

    input                            ctl_rst_n           ,
    input        [ 15:0]             ctl_ck              ,
    input        [ 15:0]             ctl_cke             ,
    input        [ 15:0]             ctl_odt             ,
    input        [ 15:0]             ctl_cs_n            ,
    input        [  7:0]             ctl_act_n           ,
    input        [ 15:0]             ctl_bg              ,
    input        [ 15:0]             ctl_ba              ,
    input        [143:0]             ctl_addr            ,

    input        [ 71:0]             ctl_wdqs            ,
    input        [575:0]             ctl_wdq             ,
    input        [ 71:0]             ctl_wdm             ,
    input        [ 71:0]             ctl_gate            ,
    output       [ 17:0]             ctl_rdq_vld         ,
    output       [575:0]             ctl_rdq             ,
    output       [ 71:0]             ctl_rdbi            ,

    input        [  7:0]             ctl_parity          ,
    output       [  7:0]             ctl_alert_n         ,
    input        [ 71:0]             ctl_oe              ,
    input        [ 71:0]             ctl_te              ,
    input        [ 71:0]             ctl_pdr             ,

    input        [ 12:0]             dcp_sel             ,
    input        [ 59:0]             dcp_addr            ,
    input        [ 89:0]             dcp_data            ,
    input        [  9:0]             dcp_gate            ,
    input        [  8:0]             dcp_rksel           ,

    input                            zqcal_clear         ,
    input                            zqcal_start         ,
    input                            zqcal_update        ,
    output       [  2:0]             zqcal_done          ,

    input                            dcc_clear           ,
    input                            dcc_start           ,
    input                            dcc_update          ,
    output       [ 11:0]             dcc_done            ,

    input        [  8:0]             mdl_cal_mode        ,
    input        [ 62:0]             mdl_cal_clk_en      ,
    input        [ 62:0]             mdl_cal_en          ,
    output       [ 62:0]             mdl_cal_en_out      ,
    output       [ 62:0]             mdl_cal_out         ,

    input        [  7:0]             lpbk_en             ,

    input        [  8:0]             wrlvl_mode          ,
    output       [ 71:0]             wrlvl_din           ,

    input                            dqs_pupd_en         ,
    output  reg  [ 17:0]             dqs_gate_status     ,
    output       [ 17:0]             dqs_gate_cnt        ,

    output                           bm_zqcal_clear      ,
    output                           bm_zqcal_start      ,
    output                           bm_zqcal_update     ,
    input        [  2:0]             bm_zqcal_done       ,

    output       [ 11:0]             bm_ac_rst_n         ,
    output       [ 11:0]             bm_dx_rst_n         ,
    output       [ 11:0]             bm_ac_fifo_rst_n    ,
    output       [ 11:0]             bm_dx_fifo_rst_n    ,

    output       [  7:0]             bm_ctl_wdata [0:3*4*13-1],
    input        [  7:0]             bm_ctl_rdata [0:3*4*13-1],
    input        [ 11:0]             bm_ctl_rdata_vld         ,
    output  reg  [  7:0]             bm_ctl_gate  [0:3*4-1],
    output  reg  [  7:0]             bm_ctl_pdr   [0:3*4-1],
    output  reg  [  7:0]             bm_ctl_ts    [0:3*4-1],
    output  reg  [  7:0]             bm_ctl_te    [0:3*4-1],

    output  reg  [ 11:0]             bm_dcp_sel          ,
    output  reg  [  5:0]             bm_dcp_addr[0:3*4-1],
    output  reg  [  8:0]             bm_dcp_data[0:3*4-1],
    output  reg  [ 11:0]             bm_dcp_gate         ,
    output  reg  [ 11:0]             bm_dcp_rksel        ,

    output                           bm_dcc_clear        ,
    output                           bm_dcc_start        ,
    output                           bm_dcc_update       ,
    input        [ 11:0]             bm_dcc_done         ,

    input        [  6:0]             bm_mdl_cal_en_out[0:3*4-1],
    input        [  6:0]             bm_mdl_cal_out   [0:3*4-1],
    output       [ 11:0]             bm_mdl_cal_mode           ,
    output       [  6:0]             bm_mdl_cal_clk_en[0:3*4-1],
    output       [  6:0]             bm_mdl_cal_en    [0:3*4-1],

    output       [  7:0]             bm_lpbk_en   [0:3*4-1],

    output       [ 11:0]             bm_wrlvl_mode           ,
    input        [155:0]             bm_indd                 ,
    input        [  1:0]             bm_dqs_gate_cnt   [0:11],
    input        [  1:0]             bm_dqs_gate_status[0:11],
    output       [ 11:0]             bm_dqs_pupd_en          ,
    output       [  7:0]             bm_wrlvl_wrqout   [0:11],

    output       [ 11:0]             bm_phy_clk_wren_gt      ,
    output       [ 11:0]             bm_phy_clk_rden_gt      ,
    output       [  3:0]             bm_phy_ddr_clk_gate0    ,
    output       [  3:0]             bm_phy_ddr_clk_gate1    ,
    output       [  3:0]             bm_phy_ddr_clk_gate2    ,

    output       [  3:0]             bm_dqs_rstn0              ,
    output       [  3:0]             bm_dqs_rstn1              ,
    output       [  3:0]             bm_dqs_rstn2              ,
    output       [  7:0]             bm_phy_rd_dqs_pdr[0:3*4-1],
    output       [  7:0]             bm_phy_rd_dqs_te [0:3*4-1],
    output       [  7:0]             bm_dqs_rd_gate_en[0:3*4-1]
);

localparam integer m = (DX_NUM == 8) ? 0 : (DX_NUM == 4) ? 2 : (DX_NUM == 2) ? 3 : 0; 

genvar n;

ph1_ddrphy_bm_wdata #(

    .WDM           ( WDM           ),
    .WDBI          ( WDBI          ),

    .CK_WIDTH      ( CK_WIDTH      ),
    .CS_WIDTH      ( CS_WIDTH      ),
    .CKE_WIDTH     ( CKE_WIDTH     ),
    .ODT_WIDTH     ( ODT_WIDTH     ),
    .BG_WIDTH      ( BG_WIDTH      ),
    .BA_WIDTH      ( BA_WIDTH      ),
    .ADR_WIDTH     ( ADR_WIDTH     ),
    .DQS_WIDTH     ( DQS_WIDTH     ),
    .DQ_WIDTH      ( DQ_WIDTH      ),
    .DM_WIDTH      ( DM_WIDTH      ),

    .CK_MAP        ( CK_MAP        ),
    .RST_MAP       ( RST_MAP       ),
    .CKE_MAP       ( CKE_MAP       ),
    .ODT_MAP       ( ODT_MAP       ),
    .CS_MAP        ( CS_MAP        ),
    .ACT_MAP       ( ACT_MAP       ),
    .RAS_MAP       ( RAS_MAP       ),
    .CAS_MAP       ( CAS_MAP       ),
    .WE_MAP        ( WE_MAP        ),
    .BA_MAP        ( BA_MAP        ),
    .BG_MAP        ( BG_MAP        ),
    .ADR_MAP       ( ADR_MAP       ),
    .PAR_MAP       ( PAR_MAP       ),
    .DQS_MAP       ( DQS_MAP       ),
    .DQ_MAP        ( DQ_MAP        ),
    .DM_MAP        ( DM_MAP        )
) u_bm_wdata   (
    .clk           ( clk           ),
    .rst_n         ( rst_n         ),

    .cal_done      ( cal_done      ),
    .ctl_rst_n     ( ctl_rst_n     ),
    .ctl_ck        ( ctl_ck        ),
    .ctl_cke       ( ctl_cke       ),
    .ctl_odt       ( ctl_odt       ),
    .ctl_cs_n      ( ctl_cs_n      ),
    .ctl_act_n     ( ctl_act_n     ),
    .ctl_bg        ( ctl_bg        ),
    .ctl_ba        ( ctl_ba        ),
    .ctl_addr      ( ctl_addr      ),
    .ctl_wdqs      ( ctl_wdqs      ),
    .ctl_wdq       ( ctl_wdq       ),
    .ctl_wdm       ( ctl_wdm       ),
    .ctl_parity    ( ctl_parity    ),

    .bm_ctl_wdata  ( bm_ctl_wdata  )
);

ph1_ddrphy_bm_rdata #(
    .RDBI         ( RDBI         ),
    .DX_NUM       ( DX_NUM       ),
    .DQ_WIDTH     ( DQ_WIDTH     ),
    .DM_WIDTH     ( DM_WIDTH     ),
    .ALT_MAP      ( ALT_MAP      ),
    .DM_MAP       ( DM_MAP       ),
    .DQ_MAP       ( DQ_MAP       ),
    .DX_BYTE_MAP  ( DX_BYTE_MAP  )
) u_bm_rdata (
    .clk              ( clk           ),
    .rst_n            ( rst_n         ),

    .bm_ctl_rdata_vld ( bm_ctl_rdata_vld ),
    .bm_ctl_rdata     ( bm_ctl_rdata     ),

    .ctl_alert_n      ( ctl_alert_n      ),
    .ctl_rdq_vld      ( ctl_rdq_vld      ),
    .ctl_rdbi         ( ctl_rdbi         ),
    .ctl_rdq          ( ctl_rdq          )
);

generate
for (n = 0; n < AC_NUM; n = n+1) begin : ac_io_map
always @ (posedge clk) begin
    bm_ctl_gate[4*AC_BYTE_MAP[n*8+4 +:4] + AC_BYTE_MAP[n*8 +:4]] <= 8'hff;
    bm_ctl_pdr [4*AC_BYTE_MAP[n*8+4 +:4] + AC_BYTE_MAP[n*8 +:4]] <= 8'hff;
    bm_ctl_ts  [4*AC_BYTE_MAP[n*8+4 +:4] + AC_BYTE_MAP[n*8 +:4]] <= 8'h00;
    bm_ctl_te  [4*AC_BYTE_MAP[n*8+4 +:4] + AC_BYTE_MAP[n*8 +:4]] <= 8'h00;
end
end
endgenerate

generate
for (n = 0; n < DX_NUM; n = n+1) begin : dx_io_map
always @ (posedge clk) begin
`ifdef MC0_PINGPONG_PHY
    bm_ctl_gate[4*DX_BYTE_MAP[n*8+4 +:4] + DX_BYTE_MAP[n*8 +:4]] <= (n < DX_NUM/2) ?  ctl_gate[n*8 +: 8] :  ctl_gate[(4+n-DX_NUM/2)*8 +: 8];
    bm_ctl_pdr [4*DX_BYTE_MAP[n*8+4 +:4] + DX_BYTE_MAP[n*8 +:4]] <= (n < DX_NUM/2) ?  ctl_pdr [n*8 +: 8] :  ctl_pdr [(4+n-DX_NUM/2)*8 +: 8];
    bm_ctl_ts  [4*DX_BYTE_MAP[n*8+4 +:4] + DX_BYTE_MAP[n*8 +:4]] <= (n < DX_NUM/2) ? ~ctl_oe  [n*8 +: 8] : ~ctl_oe  [(4+n-DX_NUM/2)*8 +: 8];
    bm_ctl_te  [4*DX_BYTE_MAP[n*8+4 +:4] + DX_BYTE_MAP[n*8 +:4]] <= (n < DX_NUM/2) ?  ctl_te  [n*8 +: 8] :  ctl_te  [(4+n-DX_NUM/2)*8 +: 8];
`else
    bm_ctl_gate[4*DX_BYTE_MAP[n*8+4 +:4] + DX_BYTE_MAP[n*8 +:4]] <= ctl_gate[n*8 +: 8];
    bm_ctl_pdr [4*DX_BYTE_MAP[n*8+4 +:4] + DX_BYTE_MAP[n*8 +:4]] <= ctl_pdr [n*8 +: 8];
    bm_ctl_ts  [4*DX_BYTE_MAP[n*8+4 +:4] + DX_BYTE_MAP[n*8 +:4]] <=~ctl_oe  [n*8 +: 8];
    bm_ctl_te  [4*DX_BYTE_MAP[n*8+4 +:4] + DX_BYTE_MAP[n*8 +:4]] <= ctl_te  [n*8 +: 8];
`endif
end
end
endgenerate

assign bm_zqcal_clear  = zqcal_clear ;
assign bm_zqcal_start  = zqcal_start ;
assign bm_zqcal_update = zqcal_update;
assign zqcal_done[0]   = (BK0_BYTE == 4'h0) ? 1'b1 : bm_zqcal_done[0];
assign zqcal_done[1]   = (BK1_BYTE == 4'h0) ? 1'b1 : bm_zqcal_done[1];
assign zqcal_done[2]   = (BK2_BYTE == 4'h0) ? 1'b1 : bm_zqcal_done[2];

generate
for (n = 0; n < AC_NUM; n = n+1) begin : ac_rst_map
    assign bm_ac_rst_n     [4*AC_BYTE_MAP[n*8+4 +:4] + AC_BYTE_MAP[n*8 +:4]] = ctl_ac_rst_n     ;
    assign bm_ac_fifo_rst_n[4*AC_BYTE_MAP[n*8+4 +:4] + AC_BYTE_MAP[n*8 +:4]] = ctl_ac_fifo_rst_n;
end
endgenerate

generate
for (n = 0; n < DX_NUM; n = n+1) begin : dx_rst_map
    assign bm_dx_rst_n     [4*DX_BYTE_MAP[n*8+4 +:4] + DX_BYTE_MAP[n*8 +:4]] = ctl_dx_rst_n     [0];
    assign bm_dx_fifo_rst_n[4*DX_BYTE_MAP[n*8+4 +:4] + DX_BYTE_MAP[n*8 +:4]] = ctl_dx_fifo_rst_n[0];
end
endgenerate

generate
for (n = 0; n < AC_NUM; n = n+1) begin : ac_dcp_map
always @ (posedge clk) begin
    bm_dcp_sel [4*AC_BYTE_MAP[n*8+4 +:4] + AC_BYTE_MAP[n*8 +:4]] <= dcp_sel [n];
    bm_dcp_addr[4*AC_BYTE_MAP[n*8+4 +:4] + AC_BYTE_MAP[n*8 +:4]] <= dcp_addr[5:0];
    bm_dcp_data[4*AC_BYTE_MAP[n*8+4 +:4] + AC_BYTE_MAP[n*8 +:4]] <= dcp_data[8:0];
    bm_dcp_gate[4*AC_BYTE_MAP[n*8+4 +:4] + AC_BYTE_MAP[n*8 +:4]] <= dcp_gate[0];
end
end
endgenerate

generate
for (n = 0; n < DX_NUM; n = n+1) begin : dx_dcp_map
always @ (posedge clk) begin
`ifdef MC0_PINGPONG_PHY
    bm_dcp_sel  [4*DX_BYTE_MAP[n*8+4 +:4] + DX_BYTE_MAP[n*8 +:4]] <= (n < DX_NUM/2) ? dcp_sel [(4+n)]        : dcp_sel [(4+(4+n-DX_NUM/2))]       ;
    bm_dcp_addr [4*DX_BYTE_MAP[n*8+4 +:4] + DX_BYTE_MAP[n*8 +:4]] <= (n < DX_NUM/2) ? dcp_addr[(1+n)*6 +: 6] : dcp_addr[(1+(4+n-DX_NUM/2))*6 +: 6];
    bm_dcp_data [4*DX_BYTE_MAP[n*8+4 +:4] + DX_BYTE_MAP[n*8 +:4]] <= (n < DX_NUM/2) ? dcp_data[(1+n)*9 +: 9] : dcp_data[(1+(4+n-DX_NUM/2))*9 +: 9];
    bm_dcp_gate [4*DX_BYTE_MAP[n*8+4 +:4] + DX_BYTE_MAP[n*8 +:4]] <= (n < DX_NUM/2) ? dcp_gate[(1+n)]        : dcp_gate[(1+(4+n-DX_NUM/2))]       ;

    bm_dcp_rksel[4*DX_BYTE_MAP[n*8+4 +:4] + DX_BYTE_MAP[n*8 +:4]] <= (n < DX_NUM/2) ? 1'b0 : 1'b1; 
`else
    bm_dcp_sel  [4*DX_BYTE_MAP[n*8+4 +:4] + DX_BYTE_MAP[n*8 +:4]] <= dcp_sel [(4+n)];
    bm_dcp_addr [4*DX_BYTE_MAP[n*8+4 +:4] + DX_BYTE_MAP[n*8 +:4]] <= dcp_addr[(1+n)*6 +: 6];
    bm_dcp_data [4*DX_BYTE_MAP[n*8+4 +:4] + DX_BYTE_MAP[n*8 +:4]] <= dcp_data[(1+n)*9 +: 9];
    bm_dcp_gate [4*DX_BYTE_MAP[n*8+4 +:4] + DX_BYTE_MAP[n*8 +:4]] <= dcp_gate[(1+n)];
    bm_dcp_rksel[4*DX_BYTE_MAP[n*8+4 +:4] + DX_BYTE_MAP[n*8 +:4]] <= 1'b0; 
`endif
end
end
endgenerate

assign bm_dcc_clear  = dcc_clear ;
assign bm_dcc_start  = dcc_start ;
assign bm_dcc_update = dcc_update;

wire [11:0] ac_dcc_done;
wire [11:0] dx_dcc_done;

generate
for (n = 0; n < 12; n = n+1) begin : dcc_done_map
    assign ac_dcc_done[n] = (n < AC_NUM) ? bm_dcc_done[4*AC_BYTE_MAP[n*8+4 +:4] + AC_BYTE_MAP[n*8 +:4]] : 1'b1;
    assign dx_dcc_done[n] = (n < DX_NUM) ? bm_dcc_done[4*DX_BYTE_MAP[n*8+4 +:4] + DX_BYTE_MAP[n*8 +:4]] : 1'b1;
end
endgenerate

assign dcc_done = ac_dcc_done & dx_dcc_done;

generate
for (n = 0; n < AC_NUM; n = n+1) begin : ac_mdl_map
    assign bm_mdl_cal_mode  [4*AC_BYTE_MAP[n*8+4 +:4] + AC_BYTE_MAP[n*8 +:4]] = 1'b0;
    assign bm_mdl_cal_clk_en[4*AC_BYTE_MAP[n*8+4 +:4] + AC_BYTE_MAP[n*8 +:4]] = 7'h00;
    assign bm_mdl_cal_en    [4*AC_BYTE_MAP[n*8+4 +:4] + AC_BYTE_MAP[n*8 +:4]] = 7'h00;
end
endgenerate

generate
for (n = 0; n < DX_NUM; n = n+1) begin : dx_mdl_o_map
`ifdef MC0_PINGPONG_PHY
    assign bm_mdl_cal_mode  [4*DX_BYTE_MAP[n*8+4 +:4] + DX_BYTE_MAP[n*8 +:4]] = (n < DX_NUM/2) ? mdl_cal_mode  [n]        : mdl_cal_mode  [  (4+n-DX_NUM/2)]     ;
    assign bm_mdl_cal_clk_en[4*DX_BYTE_MAP[n*8+4 +:4] + DX_BYTE_MAP[n*8 +:4]] = (n < DX_NUM/2) ? mdl_cal_clk_en[7*n +: 7] : mdl_cal_clk_en[7*(4+n-DX_NUM/2) +: 7];
    assign bm_mdl_cal_en    [4*DX_BYTE_MAP[n*8+4 +:4] + DX_BYTE_MAP[n*8 +:4]] = (n < DX_NUM/2) ? mdl_cal_en    [7*n +: 7] : mdl_cal_en    [7*(4+n-DX_NUM/2) +: 7];
`else
    assign bm_mdl_cal_mode  [4*DX_BYTE_MAP[n*8+4 +:4] + DX_BYTE_MAP[n*8 +:4]] = mdl_cal_mode  [n];
    assign bm_mdl_cal_clk_en[4*DX_BYTE_MAP[n*8+4 +:4] + DX_BYTE_MAP[n*8 +:4]] = mdl_cal_clk_en[7*n +: 7];
    assign bm_mdl_cal_en    [4*DX_BYTE_MAP[n*8+4 +:4] + DX_BYTE_MAP[n*8 +:4]] = mdl_cal_en    [7*n +: 7];
`endif
end
endgenerate

generate
for (n = 0; n < 9; n = n+1) begin : dx_mdl_i_map
`ifdef MC0_PINGPONG_PHY
    assign mdl_cal_en_out[7*n +: 7] = ((n >= 0) && (n < 0+DX_NUM/2)) ? bm_mdl_cal_en_out[4*DX_BYTE_MAP[(n  )*8+4 +:4] + DX_BYTE_MAP[(n  )*8 +:4]] :
                                      ((n >= 4) && (n < 4+DX_NUM/2)) ? bm_mdl_cal_en_out[4*DX_BYTE_MAP[(n-m)*8+4 +:4] + DX_BYTE_MAP[(n-m)*8 +:4]] : 7'h7f;
    assign mdl_cal_out   [7*n +: 7] = ((n >= 0) && (n < 0+DX_NUM/2)) ? bm_mdl_cal_out   [4*DX_BYTE_MAP[(n  )*8+4 +:4] + DX_BYTE_MAP[(n  )*8 +:4]] :
                                      ((n >= 4) && (n < 4+DX_NUM/2)) ? bm_mdl_cal_out   [4*DX_BYTE_MAP[(n-m)*8+4 +:4] + DX_BYTE_MAP[(n-m)*8 +:4]] : 7'h7f;
`else
    assign mdl_cal_en_out[7*n +: 7] = (n < DX_NUM) ? bm_mdl_cal_en_out[4*DX_BYTE_MAP[n*8+4 +:4] + DX_BYTE_MAP[n*8 +:4]] : 7'h7f;
    assign mdl_cal_out   [7*n +: 7] = (n < DX_NUM) ? bm_mdl_cal_out   [4*DX_BYTE_MAP[n*8+4 +:4] + DX_BYTE_MAP[n*8 +:4]] : 7'h7f;
`endif
end
endgenerate

generate
for (n = 0; n < AC_NUM; n = n+1) begin : ac_misc_map
    assign bm_lpbk_en    [4*AC_BYTE_MAP[n*8+4 +:4] + AC_BYTE_MAP[n*8 +:4]] = 8'h00;
    assign bm_wrlvl_mode [4*AC_BYTE_MAP[n*8+4 +:4] + AC_BYTE_MAP[n*8 +:4]] = 1'b0;
    assign bm_dqs_pupd_en[4*AC_BYTE_MAP[n*8+4 +:4] + AC_BYTE_MAP[n*8 +:4]] = 1'b0;
end
endgenerate

generate
for (n = 0; n < DX_NUM; n = n+1) begin : dx_msic_map
    assign bm_lpbk_en    [4*DX_BYTE_MAP[n*8+4 +:4] + DX_BYTE_MAP[n*8 +:4]] = lpbk_en;
    assign bm_wrlvl_mode [4*DX_BYTE_MAP[n*8+4 +:4] + DX_BYTE_MAP[n*8 +:4]] = wrlvl_mode[0];
    assign bm_dqs_pupd_en[4*DX_BYTE_MAP[n*8+4 +:4] + DX_BYTE_MAP[n*8 +:4]] = dqs_pupd_en;
end
endgenerate

generate
for (n = 0; n < 9; n = n+1) begin : dx_wrlvl_map
`ifdef MC0_PINGPONG_PHY
    assign wrlvl_din[n*8 +: 8] = ((n >= 0) && (n < 0+DX_NUM/2)) ? {8{bm_indd[4*13*DQ_MAP[12*(8*(n  ))+8 +: 4] + 13*DQ_MAP[12*(8*(n  ))+4 +: 4] + DQ_MAP[12*(8*(n  )) +: 4]]}} :
                                 ((n >= 4) && (n < 4+DX_NUM/2)) ? {8{bm_indd[4*13*DQ_MAP[12*(8*(n-m))+8 +: 4] + 13*DQ_MAP[12*(8*(n-m))+4 +: 4] + DQ_MAP[12*(8*(n-m)) +: 4]]}} : 8'hff;
`else
    assign wrlvl_din[n*8 +: 8] = (n < DX_NUM) ? {8{bm_indd[4*13*DQ_MAP[12*(8*n)+8 +: 4] + 13*DQ_MAP[12*(8*n)+4 +: 4] + DQ_MAP[12*(8*n) +: 4]]}} : 8'hff;
`endif
end
endgenerate

generate
for (n = 0; n < 9; n = n+1) begin : dx_gate_map
always @ (posedge clk) begin
`ifdef MC0_PINGPONG_PHY
    dqs_gate_status[n*2 +: 2] <= ((n >= 0) && (n < 0+DX_NUM/2)) ? bm_dqs_gate_status[4*DX_BYTE_MAP[(n  )*8+4 +: 4] + DX_BYTE_MAP[(n  )*8 +: 4]] :
                                 ((n >= 4) && (n < 4+DX_NUM/2)) ? bm_dqs_gate_status[4*DX_BYTE_MAP[(n-m)*8+4 +: 4] + DX_BYTE_MAP[(n-m)*8 +: 4]] : 2'b00;
`else
    dqs_gate_status[n*2 +: 2] <= (n < DX_NUM) ? bm_dqs_gate_status[4*DX_BYTE_MAP[n*8+4 +: 4] + DX_BYTE_MAP[n*8 +: 4]] : 2'b00;
`endif
end
end
endgenerate

endmodule

`timescale 1ps / 1ps

module ph1_ddrphy_bm_rdata #(
    parameter RDBI        = "DISABLE",
    parameter DX_NUM      = 9,
    parameter DM_WIDTH    = 9,
    parameter DQ_WIDTH    = 72,
    parameter ALT_MAP     = 12'h000,
    parameter DX_BYTE_MAP = 72'h23_22_21_20_13_12_11_10_03,
    parameter DM_MAP      = 108'h105_218_200_228_231_018_039_00a_020,
    parameter DQ_MAP      = 864'h0
)(
    input                 clk   ,
    input                 rst_n ,

    input        [ 11:0]  bm_ctl_rdata_vld         ,
    input        [  7:0]  bm_ctl_rdata [0:3*4*13-1],

    output  reg  [  7:0]  ctl_alert_n            ,
    output  reg  [ 17:0]  ctl_rdq_vld            ,
    output  reg  [ 71:0]  ctl_rdbi               ,
    output  reg  [575:0]  ctl_rdq
);

localparam integer m = (DX_NUM == 8) ? 0 : (DX_NUM == 4) ? 2 : (DX_NUM == 2) ? 3 : 0; 

always @ (posedge clk or negedge rst_n) begin
    if (rst_n == 1'b0) begin
        ctl_alert_n <= 8'hff;
    end else begin
        ctl_alert_n <= (ALT_MAP == 12'hfff) ? 8'hff : bm_ctl_rdata[52*ALT_MAP[11:8] + 13*ALT_MAP[7:4] + ALT_MAP[3:0]];
    end
end

genvar n;

generate
if (RDBI == "ENABLE") begin : rdbi_en
for (n = 0; n < 9; n = n+1) begin : rdbi_map
always @ (posedge clk or negedge rst_n) begin
    if (rst_n == 1'b0) begin
        ctl_rdbi[n*8 +: 8] <= 8'hff;
    end else begin
`ifdef MC0_PINGPONG_PHY
        ctl_rdbi[n*8 +: 8] <= ((n >= 0) && (n < 0+DM_WIDTH/2)) ? bm_ctl_rdata[52*DM_MAP[(12*(n  )+8)+:4] + 13*DM_MAP[(12*(n  )+4)+:4] + DM_MAP[12*(n  )+:4]] :
                              ((n >= 4) && (n < 4+DM_WIDTH/2)) ? bm_ctl_rdata[52*DM_MAP[(12*(n-m)+8)+:4] + 13*DM_MAP[(12*(n-m)+4)+:4] + DM_MAP[12*(n-m)+:4]] : 8'hff;
`else
        ctl_rdbi[n*8 +: 8] <= (n < DM_WIDTH) ? bm_ctl_rdata[52*DM_MAP[(12*n+8)+:4] + 13*DM_MAP[(12*n+4)+:4] + DM_MAP[12*n+:4]] : 8'hff;
`endif
    end   
end 
end 

end else begin : rdbi_dis

always @ (*) begin
    ctl_rdbi = {72{1'b1}};
end 

end
endgenerate

generate
for (n = 0; n < 72; n = n+1) begin : rdq_map
always @ (posedge clk or negedge rst_n) begin
    if (rst_n == 1'b0) begin
        ctl_rdq[n*8 +: 8] <= 8'hff;
    end else begin
`ifdef MC0_PINGPONG_PHY
        ctl_rdq[n*8 +: 8] <= ((n >=  0) && (n < 0 +DQ_WIDTH/2)) ? bm_ctl_rdata[52*DQ_MAP[(12*(n    )+8)+:4] + 13*DQ_MAP[(12*(n    )+4)+:4] + DQ_MAP[12*(n    )+:4]] :
                             ((n >= 32) && (n < 32+DQ_WIDTH/2)) ? bm_ctl_rdata[52*DQ_MAP[(12*(n-m*8)+8)+:4] + 13*DQ_MAP[(12*(n-m*8)+4)+:4] + DQ_MAP[12*(n-m*8)+:4]] : 8'hff;
`else
        ctl_rdq[n*8 +: 8] <= (n < DQ_WIDTH) ? bm_ctl_rdata[52*DQ_MAP[(12*n+8)+:4] + 13*DQ_MAP[(12*n+4)+:4] + DQ_MAP[12*n+:4]] : 8'hff;
`endif
    end
end
end
endgenerate

generate
for (n = 0; n < 9; n = n+1) begin : rvld_map
always @ (posedge clk or negedge rst_n) begin
    if (rst_n == 1'b0) begin
        ctl_rdq_vld[n*2 +: 2] <= 2'b00;
    end else begin
`ifdef MC0_PINGPONG_PHY
        ctl_rdq_vld[n*2 +: 2] <= ((n >= 0) && (n < 0+DX_NUM/2)) ? {2{bm_ctl_rdata_vld[4*DX_BYTE_MAP[(n  )*8+4 +:4] + DX_BYTE_MAP[(n  )*8 +:4]]}} :
                                 ((n >= 4) && (n < 4+DX_NUM/2)) ? {2{bm_ctl_rdata_vld[4*DX_BYTE_MAP[(n-m)*8+4 +:4] + DX_BYTE_MAP[(n-m)*8 +:4]]}} : 2'b00;
`else
        ctl_rdq_vld[n*2 +: 2] <= (n < DX_NUM) ? {2{bm_ctl_rdata_vld[4*DX_BYTE_MAP[n*8+4 +:4] + DX_BYTE_MAP[n*8 +:4]]}} : 2'b00;
`endif
    end
end
end
endgenerate

endmodule

`timescale 1ps / 1ps

module ph1_ddrphy_bm_wdata #(

    parameter WDM        = "ENABLE",
    parameter WDBI       = "DISABLE",

    parameter CK_WIDTH   = 1,
    parameter CS_WIDTH   = 1,
    parameter CKE_WIDTH  = 1,
    parameter ODT_WIDTH  = 1,
    parameter BG_WIDTH   = 2,
    parameter BA_WIDTH   = 2,
    parameter ADR_WIDTH  = 17,
    parameter DQS_WIDTH  = 9,
    parameter DQ_WIDTH   = 72,
    parameter DM_WIDTH   = 9,

    parameter CK_MAP     = 48'h137_136_117_116,
    parameter RST_MAP    = 12'h11a,
    parameter CKE_MAP    = 24'h134_133,
    parameter ODT_MAP    = 24'h11b_120,
    parameter CS_MAP     = 24'h118_128,
    parameter ACT_MAP    = 12'h000,
    parameter RAS_MAP    = 12'h000,
    parameter CAS_MAP    = 12'h000,
    parameter WE_MAP     = 12'h000,
    parameter BG_MAP     = 24'h000_000,
    parameter BA_MAP     = 36'h000_135_114,
    parameter ADR_MAP    = 216'h000_138_139_12b_13a_130_119_129_127_12a_13b_124_122_113_132_115_121_126,
    parameter PAR_MAP    = 12'h000,

    parameter DQS_MAP    = 216'h107_106_217_216_207_206_227_226_237_236_017_016_037_036_007_006_027_026,
    parameter DM_MAP     = 108'h105_218_200_228_231_018_039_00a_020,
    parameter DQ_MAP     = 864'h0

)(
    input           clk        ,
    input           rst_n      ,

    input           cal_done   ,

    input           ctl_rst_n  ,
    input   [ 15:0] ctl_ck     ,
    input   [ 15:0] ctl_cke    ,
    input   [ 15:0] ctl_odt    ,
    input   [ 15:0] ctl_cs_n   ,
    input   [  7:0] ctl_act_n  ,
    input   [ 15:0] ctl_bg     ,
    input   [ 15:0] ctl_ba     ,
    input   [143:0] ctl_addr   ,
    input   [ 71:0] ctl_wdqs   ,
    input   [575:0] ctl_wdq    ,
    input   [ 71:0] ctl_wdm    ,
    input   [  7:0] ctl_parity ,

    output reg [7:0] bm_ctl_wdata [0:3*4*13-1]
);

genvar n;

always @ (posedge clk) begin
    if (RST_MAP != 12'hfff) bm_ctl_wdata[52*RST_MAP[11:8] + 13*RST_MAP[7:4] + RST_MAP[3:0]] <= {8{ctl_rst_n}};
    if (RAS_MAP != 12'hfff) bm_ctl_wdata[52*RAS_MAP[11:8] + 13*RAS_MAP[7:4] + RAS_MAP[3:0]] <= (ctl_cs_n == 16'hffff) ? 8'hff : ctl_act_n[7:0];
    if (CAS_MAP != 12'hfff) bm_ctl_wdata[52*CAS_MAP[11:8] + 13*CAS_MAP[7:4] + CAS_MAP[3:0]] <= (ctl_cs_n == 16'hffff) ? 8'hff : ctl_addr [17*8 +: 8];
    if (WE_MAP  != 12'hfff) bm_ctl_wdata[52* WE_MAP[11:8] + 13* WE_MAP[7:4] +  WE_MAP[3:0]] <= (ctl_cs_n == 16'hffff) ? 8'hff : ctl_addr [16*8 +: 8];
    if (ACT_MAP != 12'hfff) bm_ctl_wdata[52*ACT_MAP[11:8] + 13*ACT_MAP[7:4] + ACT_MAP[3:0]] <= (ctl_cs_n == 16'hffff) ? 8'hff : ctl_act_n[7:0];
    if (PAR_MAP != 12'hfff) bm_ctl_wdata[52*PAR_MAP[11:8] + 13*PAR_MAP[7:4] + PAR_MAP[3:0]] <= ctl_parity[7:0];
end

generate
for (n = 0; n < CK_WIDTH; n = n+1) begin : map_ck
always @ (posedge clk) begin
    bm_ctl_wdata[52*CK_MAP[(12* 2*n   +8)+:4] + 13*CK_MAP[(12* 2*n   +4)+:4] + CK_MAP[12* 2*n   +:4]] <=  ctl_ck[8*0+:8];
    bm_ctl_wdata[52*CK_MAP[(12*(2*n+1)+8)+:4] + 13*CK_MAP[(12*(2*n+1)+4)+:4] + CK_MAP[12*(2*n+1)+:4]] <= ~ctl_ck[8*0+:8];
end
end
endgenerate

generate
for (n = 0; n < CKE_WIDTH; n = n+1) begin : map_cke
always @ (posedge clk) begin
`ifdef MC0_PINGPONG_PHY

    bm_ctl_wdata[52*CKE_MAP[(12*n+8)+:4] + 13*CKE_MAP[(12*n+4)+:4] + CKE_MAP[(12*n)+:4]] <= ctl_cke[8*n+:8];
`elsif MC0_DUAL_RANK
    bm_ctl_wdata[52*CKE_MAP[(12*n+8)+:4] + 13*CKE_MAP[(12*n+4)+:4] + CKE_MAP[(12*n)+:4]] <= ctl_cke[8*n+:8];
`else
    bm_ctl_wdata[52*CKE_MAP[(12*n+8)+:4] + 13*CKE_MAP[(12*n+4)+:4] + CKE_MAP[(12*n)+:4]] <= ctl_cke[8*0+:8];
`endif
end
end
endgenerate

generate
for (n = 0; n < ODT_WIDTH; n = n+1) begin : map_odt
always @ (posedge clk) begin
`ifdef MC0_PINGPONG_PHY

    bm_ctl_wdata[52*ODT_MAP[(12*n+8)+:4] + 13*ODT_MAP[(12*n+4)+:4] + ODT_MAP[(12*n)+:4]] <= ctl_odt[8*n+:8];
`elsif MC0_DUAL_RANK
    bm_ctl_wdata[52*ODT_MAP[(12*n+8)+:4] + 13*ODT_MAP[(12*n+4)+:4] + ODT_MAP[(12*n)+:4]] <= ctl_odt[8*n+:8];
`else
    bm_ctl_wdata[52*ODT_MAP[(12*n+8)+:4] + 13*ODT_MAP[(12*n+4)+:4] + ODT_MAP[(12*n)+:4]] <= ctl_odt[8*0+:8];
`endif
end
end
endgenerate

generate
for (n = 0; n < CS_WIDTH; n = n+1) begin : map_cs
always @ (posedge clk) begin
`ifdef MC0_PINGPONG_PHY

    bm_ctl_wdata[52*CS_MAP[(12*n+8)+:4] + 13*CS_MAP[(12*n+4)+:4] + CS_MAP[(12*n)+:4]] <= ctl_cs_n[8*n+:8];
`elsif MC0_DUAL_RANK
    bm_ctl_wdata[52*CS_MAP[(12*n+8)+:4] + 13*CS_MAP[(12*n+4)+:4] + CS_MAP[(12*n)+:4]] <= ctl_cs_n[8*n+:8];
`else
    bm_ctl_wdata[52*CS_MAP[(12*n+8)+:4] + 13*CS_MAP[(12*n+4)+:4] + CS_MAP[(12*n)+:4]] <= ctl_cs_n[8*0+:8];
`endif
end
end
endgenerate

generate
for (n = 0; n < BG_WIDTH; n = n+1) begin : map_bg
always @ (posedge clk) begin
    bm_ctl_wdata[52*BG_MAP[(12*n+8)+:4] + 13*BG_MAP[(12*n+4)+:4] + BG_MAP[(12*n)+:4]] <= ctl_bg[8*n+:8];
end
end
endgenerate

generate
for (n = 0; n < BA_WIDTH; n = n+1) begin : map_ba
always @ (posedge clk) begin
    bm_ctl_wdata[52*BA_MAP[(12*n+8)+:4] + 13*BA_MAP[(12*n+4)+:4] + BA_MAP[(12*n)+:4]] <= (n <= 1) ? ctl_ba[8*n+:8] : ctl_bg[7:0];
end
end
endgenerate

generate
for (n = 0; n < ADR_WIDTH; n = n+1) begin : map_addr
always @ (posedge clk) begin
`ifdef MC0_DRAM_DDR3
    bm_ctl_wdata[52*ADR_MAP[(12*n+8)+:4] + 13*ADR_MAP[(12*n+4)+:4] + ADR_MAP[(12*n)+:4]] <= ctl_addr[8*n+:8];
`else 
    if (n >= 14)
        bm_ctl_wdata[52*ADR_MAP[(12*n+8)+:4] + 13*ADR_MAP[(12*n+4)+:4] + ADR_MAP[(12*n)+:4]] <= (ctl_cs_n == 16'hffff) ? 8'hff : ctl_addr[8*n+:8];
    else
        bm_ctl_wdata[52*ADR_MAP[(12*n+8)+:4] + 13*ADR_MAP[(12*n+4)+:4] + ADR_MAP[(12*n)+:4]] <= ctl_addr[8*n+:8];
`endif
end
end
endgenerate

generate
for (n = 0; n < DQS_WIDTH; n = n+1) begin : map_wdqs
always @ (posedge clk) begin
`ifdef MC0_PINGPONG_PHY
    bm_ctl_wdata[52*DQS_MAP[(12*(2*n+0)+8)+:4] + 13*DQS_MAP[(12*(2*n+0)+4)+:4] + DQS_MAP[(12*(2*n+0))+:4]] <= (n < DQS_WIDTH/2) ? ctl_wdqs[8*n+:8] : ctl_wdqs[8*(4+(n-DQS_WIDTH/2))+:8];
    bm_ctl_wdata[52*DQS_MAP[(12*(2*n+1)+8)+:4] + 13*DQS_MAP[(12*(2*n+1)+4)+:4] + DQS_MAP[(12*(2*n+1))+:4]] <= (n < DQS_WIDTH/2) ?~ctl_wdqs[8*n+:8] :~ctl_wdqs[8*(4+(n-DQS_WIDTH/2))+:8];
`else
    bm_ctl_wdata[52*DQS_MAP[(12*(2*n+0)+8)+:4] + 13*DQS_MAP[(12*(2*n+0)+4)+:4] + DQS_MAP[(12*(2*n+0))+:4]] <=  ctl_wdqs[8*n+:8];
    bm_ctl_wdata[52*DQS_MAP[(12*(2*n+1)+8)+:4] + 13*DQS_MAP[(12*(2*n+1)+4)+:4] + DQS_MAP[(12*(2*n+1))+:4]] <= ~ctl_wdqs[8*n+:8];
`endif
end
end
endgenerate

generate
if ((WDM == "ENABLE") || (WDBI == "ENABLE")) begin : wdm_en
for (n = 0; n < DM_WIDTH; n = n+1) begin : map_wdm
always @ (posedge clk) begin
`ifdef MC0_PINGPONG_PHY
    bm_ctl_wdata[52*DM_MAP[(12*n+8)+:4] + 13*DM_MAP[(12*n+4)+:4] + DM_MAP[(12*n)+:4]] <= (n < DM_WIDTH/2) ? ctl_wdm[8*n+:8] : ctl_wdm[8*(4+(n-DM_WIDTH/2))+:8];
`else
    bm_ctl_wdata[52*DM_MAP[(12*n+8)+:4] + 13*DM_MAP[(12*n+4)+:4] + DM_MAP[(12*n)+:4]] <= ctl_wdm[8*n+:8];
`endif
end 
end 
end 
endgenerate

generate
for (n = 0; n < DQ_WIDTH; n = n+1) begin : map_wdq
always @ (posedge clk) begin
`ifdef MC0_PINGPONG_PHY
    bm_ctl_wdata[52*DQ_MAP[(12*n+8)+:4] + 13*DQ_MAP[(12*n+4)+:4] + DQ_MAP[(12*n)+:4]] <= (n < DQ_WIDTH/2) ? ctl_wdq[8*n+:8] : ctl_wdq[8*(32+(n-DQ_WIDTH/2))+:8];
`else
    bm_ctl_wdata[52*DQ_MAP[(12*n+8)+:4] + 13*DQ_MAP[(12*n+4)+:4] + DQ_MAP[(12*n)+:4]] <= ctl_wdq[8*n+:8];
`endif
end
end
endgenerate

endmodule

`timescale 1ps / 1ps

module ph1_ddrphy_bank_wrapper #(
    parameter MC_IDX      = 0,
    parameter MC_TCK      = 1250,

    parameter WDM         = "ENABLE",
    parameter WDBI        = "DISABLE",
    parameter RDBI        = "DISABLE",

    parameter AC_NUM      = 3,
    parameter DX_NUM      = 9,
    parameter CK_WIDTH    = 1,
    parameter ODT_WIDTH   = 1,
    parameter CKE_WIDTH   = 1,
    parameter CS_WIDTH    = 1,
    parameter BG_WIDTH    = 2,
    parameter BA_WIDTH    = 2,
    parameter ADR_WIDTH   = 17,

    parameter DQS_WIDTH   = 9,
    parameter DQ_WIDTH    = 72,
    parameter DM_WIDTH    = 9,

    parameter BK0_BYTE    = 4'b1111,
    parameter BK1_BYTE    = 4'b1111,
    parameter BK2_BYTE    = 4'b1111,
    parameter BK0_DX_EN   = 4'b1000,
    parameter BK1_DX_EN   = 4'b1111,
    parameter BK2_DX_EN   = 4'b1111,

    parameter CK_MAP      = 48'h004_005,
    parameter RST_MAP     = 12'h027,
    parameter CKE_MAP     = 24'h020,
    parameter ODT_MAP     = 24'h000_023,
    parameter CS_MAP      = 24'h000_022,
    parameter RAS_MAP     = 12'h000,
    parameter CAS_MAP     = 12'h000,
    parameter WE_MAP      = 12'h000,
    parameter ACT_MAP     = 12'h026,

    parameter BG_MAP      = 24'h020_019,
    parameter BA_MAP      = 36'h000_025_024,
    parameter ADR_MAP     = 216'h000_018_016_017_014_015_012_013_010_011_008_009_006_007_002_003_000_001,

    parameter PAR_MAP     = 12'h028,
    parameter ALT_MAP     = 12'h029,

    parameter DQS_MAP     = 216'h235_234_225_224_215_214_205_204_135_134_125_124_115_114_105_104_035_034,
    parameter DM_MAP      = 108'h23a_22a_21a_20a_13a_12a_11a_10a_03a,
    parameter DQ_MAP      = 864'h0

)(

    input            usr_rst_n      ,

    input            usr_clk        ,
    input  [2:0]     ctl_clk        ,
    input  [2:0]     ddr_clk        ,

    input            zqcal_clear    ,
    input            zqcal_start    ,
    input            zqcal_update   ,
    output [2:0]     zqcal_done     ,

    input            apb_pclk    ,
    input            apb_prst_n  ,
    input            apb_psel    ,
    input            apb_penable ,
    input            apb_pwrite  ,
    input  [15:0]    apb_paddr   ,
    input  [31:0]    apb_pwdata  ,
    output [31:0]    apb_prdata  ,
    output           apb_pready  ,

    input  [3*4-1:0]   ac_fifo_rst_n            ,
    input  [3*4-1:0]   dx_fifo_rst_n            ,

    input  [    7:0]   ctl_pdr[0:3*4-1]         ,
    input  [    7:0]   ctl_te [0:3*4-1]         ,
    input  [    7:0]   ctl_ts [0:3*4-1]         ,

    input  [    7:0]   ctl_wdata    [0:3*4*13-1],
    output [    7:0]   ctl_rdata    [0:3*4*13-1],
    input  [    7:0]   ctl_rdqs_gate[0:3*4   -1],
    output [3*4-1:0]   ctl_rdata_vld            ,

    input  [3*4-1:0]   dcp_sel                  ,
    input  [  5  :0]   dcp_addr [0:3*4-1]       ,
    input  [  8  :0]   dcp_data [0:3*4-1]       ,
    input  [3*4-1:0]   dcp_gate                 ,
    input  [3*4-1:0]   dcp_rksel                ,

    input              dcc_clear                ,
    input              dcc_start                ,
    output [3*4-1:0]   dcc_done                 ,

    input  [3*4-1:0]   mdl_cal_mode             ,
    input  [  6  :0]   mdl_cal_clk_en[0:3*4-1]  ,
    input  [  6  :0]   mdl_cal_en    [0:3*4-1]  ,
    output [  6  :0]   mdl_cal_en_out[0:3*4-1]  ,
    output [  6  :0]   mdl_cal_out   [0:3*4-1]  ,

    output [156-1:0]   indd                     ,
    input  [3*4-1:0]   wrlvl_mdoe               ,
    input  [3*4-1:0]   dqs_pupd_en              ,
    output [    1:0]   dqs_gate_status[0:3*4-1] ,

`ifdef MC0_DRAM_DDR4
    output [ CK_WIDTH-1:0]  ddr_ck_t    ,
    output [ CK_WIDTH-1:0]  ddr_ck_c    ,
    output                  ddr_reset_n ,
    output [CKE_WIDTH-1:0]  ddr_cke     ,
    output [ODT_WIDTH-1:0]  ddr_odt     ,
    output [ CS_WIDTH-1:0]  ddr_cs_n    ,
    output                  ddr_act_n   ,
    output [ BG_WIDTH-1:0]  ddr_bg      ,
    output [ BA_WIDTH-1:0]  ddr_ba      ,
    output [ADR_WIDTH-1:0]  ddr_addr    ,
    output                  ddr_parity  ,
    input                   ddr_alert_n ,
    inout  [DQS_WIDTH-1:0]  ddr_dqs_t   ,
    inout  [DQS_WIDTH-1:0]  ddr_dqs_c   ,
    inout  [ DQ_WIDTH-1:0]  ddr_dq      ,
    inout  [ DM_WIDTH-1:0]  ddr_dm_n
`elsif MC0_DRAM_DDR3
    output [ CK_WIDTH-1:0]  ddr_ck_p    ,
    output [ CK_WIDTH-1:0]  ddr_ck_n    ,
    output                  ddr_reset_n ,
    output [CKE_WIDTH-1:0]  ddr_cke     ,
    output [ODT_WIDTH-1:0]  ddr_odt     ,
    output [ CS_WIDTH-1:0]  ddr_cs_n    ,
    output                  ddr_ras_n   ,
    output                  ddr_cas_n   ,
    output                  ddr_we_n    ,
    output [ BA_WIDTH-1:0]  ddr_ba      ,
    output [ADR_WIDTH-1:0]  ddr_addr    ,
    inout  [DQS_WIDTH-1:0]  ddr_dqs_p   ,
    inout  [DQS_WIDTH-1:0]  ddr_dqs_n   ,
    inout  [ DQ_WIDTH-1:0]  ddr_dq      ,
    inout  [ DM_WIDTH-1:0]  ddr_dm
`endif
);

localparam [0:0] BK0_USED   = (BK0_BYTE == 4'h0) ? 1'b0 : 1'b1;
localparam [0:0] BK1_USED   = (BK1_BYTE == 4'h0) ? 1'b0 : 1'b1;
localparam [0:0] BK2_USED   = (BK2_BYTE == 4'h0) ? 1'b0 : 1'b1;
localparam [2:0] BANK_USED  = {BK2_USED, BK1_USED, BK0_USED};

localparam [2:0] BK_T0_EN   = {BK2_BYTE[0], BK1_BYTE[0], BK0_BYTE[0]};
localparam [2:0] BK_T1_EN   = {BK2_BYTE[1], BK1_BYTE[1], BK0_BYTE[1]};
localparam [2:0] BK_T2_EN   = {BK2_BYTE[2], BK1_BYTE[2], BK0_BYTE[2]};
localparam [2:0] BK_T3_EN   = {BK2_BYTE[3], BK1_BYTE[3], BK0_BYTE[3]};

localparam [2:0] BK_T0_TYPE = {BK2_DX_EN[0], BK1_DX_EN[0], BK0_DX_EN[0]};
localparam [2:0] BK_T1_TYPE = {BK2_DX_EN[1], BK1_DX_EN[1], BK0_DX_EN[1]};
localparam [2:0] BK_T2_TYPE = {BK2_DX_EN[2], BK1_DX_EN[2], BK0_DX_EN[2]};
localparam [2:0] BK_T3_TYPE = {BK2_DX_EN[3], BK1_DX_EN[3], BK0_DX_EN[3]};

wire [8*13   -1:0]  ctl_wdata_int[0:3*4-1];
wire [8*13   -1:0]  ctl_rdata_int[0:3*4-1];

wire [3*4    -1:0]  bk_phyclk      ;
wire [3*4    -1:0]  bk_ctlclk_ac   ;
wire [3*4    -1:0]  bk_ctlclk_dqs  ;
wire [3*4    -1:0]  bk_ctlclk_wdq  ;
wire [3*4    -1:0]  bk_ddrclk_ac   ;
wire [3*4    -1:0]  bk_ddrclk_dqs  ;
wire [3*4    -1:0]  bk_ddrclk_wdq  ;
wire [3*4    -1:0]  bk_ac_wr_rst_n ;
wire [3*4    -1:0]  bk_dx_wr_rst_n ;
wire [3*4    -1:0]  bk_ac_rd_rst_n ;
wire [3*4    -1:0]  bk_dx_rd_rst_n ;

wire [3*4*104-1:0]  bk_rdata       ;
wire [3*4*104-1:0]  bk_wdata       ;
wire [3*4*13 -1:0]  bk_indd        ;

wire [3*4    -1:0]  bk_rdqs_p      ;
wire [3*4    -1:0]  bk_rdqs_n      ;
wire [3*4    -1:0]  bk_rdqs_r      ;
wire [3*4    -1:0]  bk_rdqs_f      ;

wire [3*4*26 -1:0]  bk_oe_md       ;
wire [3*4*26 -1:0]  bk_te_md       ;
wire [3*4*26 -1:0]  bk_pdr_md      ;

wire [3*4    -1:0]  bk_oe_dq       ;
wire [3*4    -1:0]  bk_oe_dqs      ;
wire [3*4    -1:0]  bk_oe_dqsn     ;
wire [3*4    -1:0]  bk_te_dq       ;
wire [3*4    -1:0]  bk_te_dqs      ;
wire [3*4    -1:0]  bk_te_dqsn     ;
wire [3*4    -1:0]  bk_pdr_dq      ;
wire [3*4    -1:0]  bk_pdr_dqs     ;
wire [3*4    -1:0]  bk_pdr_dqsn    ;

wire [3*4*13 -1:0]  bk_wr_bdl_byp  ;
wire [3*4*13 -1:0]  bk_rd_bdl_byp  ;
wire [3*4*78 -1:0]  bk_wr_bdl_dly  ;
wire [3*4*78 -1:0]  bk_rd_bdl_dly  ;

wire                bk_apb_pclk    ;
wire                bk_apb_prst_n  ;
wire [        2:0]  bk_apb_psel    ;
wire                bk_apb_penable ;
wire                bk_apb_pwrite  ;
wire [     16-1:0]  bk_apb_paddr   ;
wire [     32-1:0]  bk_apb_pwdata  ;
wire [   3*32-1:0]  bk_apb_prdata  ;
wire [        2:0]  bk_apb_pready  ;

assign bk_apb_pclk    = apb_pclk   ;
assign bk_apb_prst_n  = apb_prst_n ;
assign bk_apb_penable = apb_penable;
assign bk_apb_pwrite  = apb_pwrite ;
assign bk_apb_paddr   = apb_paddr  ;
assign bk_apb_pwdata  = apb_pwdata ;

assign bk_apb_psel[0] = (apb_paddr[13:10] == 4'b0100) ? apb_psel : 1'b0;
assign bk_apb_psel[1] = (apb_paddr[13:10] == 4'b0101) ? apb_psel : 1'b0;
assign bk_apb_psel[2] = (apb_paddr[13:10] == 4'b0110) ? apb_psel : 1'b0;

assign apb_prdata     = (apb_paddr[13:10] == 4'b0100) ? bk_apb_prdata[31: 0] :
                        (apb_paddr[13:10] == 4'b0101) ? bk_apb_prdata[63:32] :
                        (apb_paddr[13:10] == 4'b0110) ? bk_apb_prdata[95:64] : 32'hdeadbeef;

assign apb_pready     = (apb_paddr[13:10] == 4'b0100) ? bk_apb_pready[0] :
                        (apb_paddr[13:10] == 4'b0101) ? bk_apb_pready[1] :
                        (apb_paddr[13:10] == 4'b0110) ? bk_apb_pready[2] : 1'b1;

genvar n, bk, t;
generate
for (bk = 0; bk < 3; bk = bk+1) begin : ctl_data_bkIdx
    for (t = 0; t < 4; t = t+1) begin : ctl_data_byteIdx
        for (n = 0; n < 13; n = n+1) begin : ctl_data_nIdx
            assign ctl_wdata_int[bk*4+t][n*8 +: 8] = ctl_wdata[bk*4*13+t*13+n];

            assign ctl_rdata[bk*4*13+t*13+n] = ctl_rdata_int[bk*4+t][n*8 +: 8];
        end
    end
end
endgenerate

assign indd = bk_indd;

generate
for (n=0; n < 3; n = n+1) begin : bkIdx
if (BANK_USED[n] == 1'b1) begin : bk_used
ph1_ddrphy_bank_top #(
    .MC_IDX        ( MC_IDX                                        ),
    .MC_TCK        ( MC_TCK                                        ),
    .T0_BYTE_EN    ((BK_T0_EN  [n] == 1'b1) ? "ENABLE" : "DISABLE" ),
    .T0_BYTE_TYPE  ((BK_T0_TYPE[n] == 1'b1) ? "DX"     : "AC"      ),
    .T1_BYTE_EN    ((BK_T1_EN  [n] == 1'b1) ? "ENABLE" : "DISABLE" ),
    .T1_BYTE_TYPE  ((BK_T1_TYPE[n] == 1'b1) ? "DX"     : "AC"      ),
    .T2_BYTE_EN    ((BK_T2_EN  [n] == 1'b1) ? "ENABLE" : "DISABLE" ),
    .T2_BYTE_TYPE  ((BK_T2_TYPE[n] == 1'b1) ? "DX"     : "AC"      ),
    .T3_BYTE_EN    ((BK_T3_EN  [n] == 1'b1) ? "ENABLE" : "DISABLE" ),
    .T3_BYTE_TYPE  ((BK_T3_TYPE[n] == 1'b1) ? "DX"     : "AC"      )

) u_ddrbank_top (

    .pzq_usr_rst_n       ( usr_rst_n          ),
    .pzq_usr_clk         ( usr_clk            ),

    .apb_prst_n          ( bk_apb_prst_n      ),
    .apb_pclk            ( bk_apb_pclk        ),
    .apb_psel            ( bk_apb_psel  [n]   ),
    .apb_penable         ( bk_apb_penable     ),
    .apb_pwrite          ( bk_apb_pwrite      ),
    .apb_paddr           ( bk_apb_paddr       ),
    .apb_pwdata          ( bk_apb_pwdata      ),
    .apb_prdata          ( bk_apb_prdata[32*n +: 32] ),
    .apb_pready          ( bk_apb_pready[n]   ),

    .zqcal_clear         ( zqcal_clear      ),
    .zqcal_start         ( zqcal_start      ),
    .zqcal_update        ( zqcal_update     ),
    .zqcal_done          ( zqcal_done[n]    ),

    .t0_ioclk              ((MC_IDX == 0) ? {2'b00, ddr_clk[n], ctl_clk[n]} : {ddr_clk[n], ctl_clk[n], 2'b00}),
    .t0_usr_clk            ( usr_clk                  ),
    .t0_ac_rst_n           ( usr_rst_n                ),
    .t0_dx_rst_n           ( usr_rst_n                ),
    .t0_ctl_rst_n          ( usr_rst_n                ),
    .t0_dqs_rst_n          ( usr_rst_n                ),
    .t0_ac_fifo_rst_n      ( ac_fifo_rst_n  [(4*n+0)] ),
    .t0_dx_fifo_rst_n      ( dx_fifo_rst_n  [(4*n+0)] ),

    .t0_ctl_pdr            ( ctl_pdr        [(4*n+0)] ),
    .t0_ctl_te             ( ctl_te         [(4*n+0)] ),
    .t0_ctl_ts             ( ctl_ts         [(4*n+0)] ),

    .t0_ctl_wdata          ( ctl_wdata_int  [(4*n+0)] ),
    .t0_ctl_rdata          ( ctl_rdata_int  [(4*n+0)] ),
    .t0_ctl_rdata_vld      ( ctl_rdata_vld  [(4*n+0)] ),
    .t0_ctl_rdqs_gate      ( ctl_rdqs_gate  [(4*n+0)] ),
    .t0_qs_gate            ( 1'b0                 ),

    .t0_dqs_pupd_en        ( dqs_pupd_en    [(4*n+0)] ),
    .t0_wrlvl_mdoe         ( wrlvl_mdoe     [(4*n+0)] ),
    .t0_dqs_gate_status    ( dqs_gate_status[(4*n+0)] ),

    .t0_dcp_sel             ( dcp_sel       [(4*n+0)] ),
    .t0_dcp_addr            ( dcp_addr      [(4*n+0)] ),
    .t0_dcp_data            ( dcp_data      [(4*n+0)] ),
    .t0_dcp_gate            ( dcp_gate      [(4*n+0)] ),
    .t0_dcp_rksel           ( dcp_rksel     [(4*n+0)] ),

    .t0_cal_mode            ( mdl_cal_mode  [(4*n+0)] ),
    .t0_cal_clk_en          ( mdl_cal_clk_en[(4*n+0)] ),
    .t0_cal_en              ( mdl_cal_en    [(4*n+0)] ),
    .t0_cal_en_out          ( mdl_cal_en_out[(4*n+0)] ),
    .t0_cal_out             ( mdl_cal_out   [(4*n+0)] ),

    .t0_dcc_clear           ( dcc_clear               ),
    .t0_dcc_start           ( dcc_start               ),
    .t0_dcc_done            ( dcc_done      [(4*n+0)] ),

    .t0_lb_en               ( 8'b0                    ),

    .t0_phy_phyclk          ( bk_phyclk     [(4*n+0)]             ),
    .t0_phy_ctlclk_ac       ( bk_ctlclk_ac  [(4*n+0)]             ),
    .t0_phy_ctlclk_dqs      ( bk_ctlclk_dqs [(4*n+0)]             ),
    .t0_phy_ctlclk_wdq      ( bk_ctlclk_wdq [(4*n+0)]             ),
    .t0_phy_ddrclk_ac       ( bk_ddrclk_ac  [(4*n+0)]             ),
    .t0_phy_ddrclk_dqs      ( bk_ddrclk_dqs [(4*n+0)]             ),
    .t0_phy_ddrclk_wdq      ( bk_ddrclk_wdq [(4*n+0)]             ),
    .t0_phy_ac_wr_rst_n     ( bk_ac_wr_rst_n[(4*n+0)]             ),
    .t0_phy_dx_wr_rst_n     ( bk_dx_wr_rst_n[(4*n+0)]             ),
    .t0_phy_ac_rd_rst_n     ( bk_ac_rd_rst_n[(4*n+0)]             ),
    .t0_phy_dx_rd_rst_n     ( bk_dx_rd_rst_n[(4*n+0)]             ),

    .t0_phy_rdata           ( bk_rdata      [(4*n+0)*104 +: 104 ] ),
    .t0_phy_wdata           ( bk_wdata      [(4*n+0)*104 +: 104 ] ),

    .t0_phy_rdqs_p          ( bk_rdqs_p     [(4*n+0)]             ),
    .t0_phy_rdqs_n          ( bk_rdqs_n     [(4*n+0)]             ),
    .t0_phy_rdqs_o          ( bk_rdqs_r     [(4*n+0)]             ),
    .t0_phy_rdqs_gate       ( bk_rdqs_f     [(4*n+0)]             ),

    .t0_phy_oe_md           ( bk_oe_md      [(4*n+0)*26 +: 26]    ),
    .t0_phy_te_md           ( bk_te_md      [(4*n+0)*26 +: 26]    ),
    .t0_phy_pdr_md          ( bk_pdr_md     [(4*n+0)*26 +: 26]    ),
    .t0_phy_oe_dq           ( bk_oe_dq      [(4*n+0)]             ),
    .t0_phy_oe_dqs          ( bk_oe_dqs     [(4*n+0)]             ),
    .t0_phy_oe_dqsn         ( bk_oe_dqsn    [(4*n+0)]             ),
    .t0_phy_te_dq           ( bk_te_dq      [(4*n+0)]             ),
    .t0_phy_te_dqs          ( bk_te_dqs     [(4*n+0)]             ),
    .t0_phy_te_dqsn         ( bk_te_dqsn    [(4*n+0)]             ),
    .t0_phy_pdr_dq          ( bk_pdr_dq     [(4*n+0)]             ),
    .t0_phy_pdr_dqs         ( bk_pdr_dqs    [(4*n+0)]             ),
    .t0_phy_pdr_dqsn        ( bk_pdr_dqsn   [(4*n+0)]             ),

    .t0_phy_rd_bdl_dly      ( bk_rd_bdl_dly [(4*n+0)*78 +: 78]    ),
    .t0_phy_wr_bdl_dly      ( bk_wr_bdl_dly [(4*n+0)*78 +: 78]    ),
    .t0_phy_rd_bdl_byp      ( bk_rd_bdl_byp [(4*n+0)*13 +: 13]    ),
    .t0_phy_wr_bdl_byp      ( bk_wr_bdl_byp [(4*n+0)*13 +: 13]    ),

    .t1_ioclk              ((MC_IDX == 0) ? {2'b00, ddr_clk[n], ctl_clk[n]} : {ddr_clk[n], ctl_clk[n], 2'b00}),
    .t1_usr_clk            ( usr_clk                  ),
    .t1_ac_rst_n           ( usr_rst_n                ),
    .t1_dx_rst_n           ( usr_rst_n                ),
    .t1_ctl_rst_n          ( usr_rst_n                ),
    .t1_dqs_rst_n          ( usr_rst_n                ),
    .t1_ac_fifo_rst_n      ( ac_fifo_rst_n  [(4*n+1)] ),
    .t1_dx_fifo_rst_n      ( dx_fifo_rst_n  [(4*n+1)] ),

    .t1_ctl_pdr            ( ctl_pdr        [(4*n+1)] ),
    .t1_ctl_te             ( ctl_te         [(4*n+1)] ),
    .t1_ctl_ts             ( ctl_ts         [(4*n+1)] ),

    .t1_ctl_wdata          ( ctl_wdata_int  [(4*n+1)] ),
    .t1_ctl_rdata          ( ctl_rdata_int  [(4*n+1)] ),
    .t1_ctl_rdata_vld      ( ctl_rdata_vld  [(4*n+1)] ),
    .t1_ctl_rdqs_gate      ( ctl_rdqs_gate  [(4*n+1)] ),
    .t1_qs_gate            ( 1'b0                 ),

    .t1_dqs_pupd_en        ( dqs_pupd_en    [(4*n+1)] ),
    .t1_wrlvl_mdoe         ( wrlvl_mdoe     [(4*n+1)] ),
    .t1_dqs_gate_status    ( dqs_gate_status[(4*n+1)] ),

    .t1_dcp_sel             ( dcp_sel       [(4*n+1)] ),
    .t1_dcp_addr            ( dcp_addr      [(4*n+1)] ),
    .t1_dcp_data            ( dcp_data      [(4*n+1)] ),
    .t1_dcp_gate            ( dcp_gate      [(4*n+1)] ),
    .t1_dcp_rksel           ( dcp_rksel     [(4*n+1)] ),

    .t1_cal_mode            ( mdl_cal_mode  [(4*n+1)] ),
    .t1_cal_clk_en          ( mdl_cal_clk_en[(4*n+1)] ),
    .t1_cal_en              ( mdl_cal_en    [(4*n+1)] ),
    .t1_cal_en_out          ( mdl_cal_en_out[(4*n+1)] ),
    .t1_cal_out             ( mdl_cal_out   [(4*n+1)] ),

    .t1_dcc_clear           ( dcc_clear               ),
    .t1_dcc_start           ( dcc_start               ),
    .t1_dcc_done            ( dcc_done      [(4*n+1)] ),

    .t1_lb_en               ( 8'b0                    ),

    .t1_phy_phyclk          ( bk_phyclk     [(4*n+1)]             ),
    .t1_phy_ctlclk_ac       ( bk_ctlclk_ac  [(4*n+1)]             ),
    .t1_phy_ctlclk_dqs      ( bk_ctlclk_dqs [(4*n+1)]             ),
    .t1_phy_ctlclk_wdq      ( bk_ctlclk_wdq [(4*n+1)]             ),
    .t1_phy_ddrclk_ac       ( bk_ddrclk_ac  [(4*n+1)]             ),
    .t1_phy_ddrclk_dqs      ( bk_ddrclk_dqs [(4*n+1)]             ),
    .t1_phy_ddrclk_wdq      ( bk_ddrclk_wdq [(4*n+1)]             ),
    .t1_phy_ac_wr_rst_n     ( bk_ac_wr_rst_n[(4*n+1)]             ),
    .t1_phy_dx_wr_rst_n     ( bk_dx_wr_rst_n[(4*n+1)]             ),
    .t1_phy_ac_rd_rst_n     ( bk_ac_rd_rst_n[(4*n+1)]             ),
    .t1_phy_dx_rd_rst_n     ( bk_dx_rd_rst_n[(4*n+1)]             ),

    .t1_phy_rdata           ( bk_rdata      [(4*n+1)*104 +: 104 ] ),
    .t1_phy_wdata           ( bk_wdata      [(4*n+1)*104 +: 104 ] ),

    .t1_phy_rdqs_p          ( bk_rdqs_p     [(4*n+1)]             ),
    .t1_phy_rdqs_n          ( bk_rdqs_n     [(4*n+1)]             ),
    .t1_phy_rdqs_o          ( bk_rdqs_r     [(4*n+1)]             ),
    .t1_phy_rdqs_gate       ( bk_rdqs_f     [(4*n+1)]             ),

    .t1_phy_oe_md           ( bk_oe_md      [(4*n+1)*26 +: 26]    ),
    .t1_phy_te_md           ( bk_te_md      [(4*n+1)*26 +: 26]    ),
    .t1_phy_pdr_md          ( bk_pdr_md     [(4*n+1)*26 +: 26]    ),
    .t1_phy_oe_dq           ( bk_oe_dq      [(4*n+1)]             ),
    .t1_phy_oe_dqs          ( bk_oe_dqs     [(4*n+1)]             ),
    .t1_phy_oe_dqsn         ( bk_oe_dqsn    [(4*n+1)]             ),
    .t1_phy_te_dq           ( bk_te_dq      [(4*n+1)]             ),
    .t1_phy_te_dqs          ( bk_te_dqs     [(4*n+1)]             ),
    .t1_phy_te_dqsn         ( bk_te_dqsn    [(4*n+1)]             ),
    .t1_phy_pdr_dq          ( bk_pdr_dq     [(4*n+1)]             ),
    .t1_phy_pdr_dqs         ( bk_pdr_dqs    [(4*n+1)]             ),
    .t1_phy_pdr_dqsn        ( bk_pdr_dqsn   [(4*n+1)]             ),

    .t1_phy_rd_bdl_dly      ( bk_rd_bdl_dly [(4*n+1)*78 +: 78]    ),
    .t1_phy_wr_bdl_dly      ( bk_wr_bdl_dly [(4*n+1)*78 +: 78]    ),
    .t1_phy_rd_bdl_byp      ( bk_rd_bdl_byp [(4*n+1)*13 +: 13]    ),
    .t1_phy_wr_bdl_byp      ( bk_wr_bdl_byp [(4*n+1)*13 +: 13]    ),

    .t2_ioclk              ((MC_IDX == 0) ? {2'b00, ddr_clk[n], ctl_clk[n]} : {ddr_clk[n], ctl_clk[n], 2'b00}),
    .t2_usr_clk            ( usr_clk                  ),
    .t2_ac_rst_n           ( usr_rst_n                ),
    .t2_dx_rst_n           ( usr_rst_n                ),
    .t2_ctl_rst_n          ( usr_rst_n                ),
    .t2_dqs_rst_n          ( usr_rst_n                ),
    .t2_ac_fifo_rst_n      ( ac_fifo_rst_n  [(4*n+2)] ),
    .t2_dx_fifo_rst_n      ( dx_fifo_rst_n  [(4*n+2)] ),

    .t2_ctl_pdr            ( ctl_pdr        [(4*n+2)] ),
    .t2_ctl_te             ( ctl_te         [(4*n+2)] ),
    .t2_ctl_ts             ( ctl_ts         [(4*n+2)] ),

    .t2_ctl_wdata          ( ctl_wdata_int  [(4*n+2)] ),
    .t2_ctl_rdata          ( ctl_rdata_int  [(4*n+2)] ),
    .t2_ctl_rdata_vld      ( ctl_rdata_vld  [(4*n+2)] ),
    .t2_ctl_rdqs_gate      ( ctl_rdqs_gate  [(4*n+2)] ),
    .t2_qs_gate            ( 1'b0                 ),

    .t2_dqs_pupd_en        ( dqs_pupd_en    [(4*n+2)] ),
    .t2_wrlvl_mdoe         ( wrlvl_mdoe     [(4*n+2)] ),
    .t2_dqs_gate_status    ( dqs_gate_status[(4*n+2)] ),

    .t2_dcp_sel             ( dcp_sel       [(4*n+2)] ),
    .t2_dcp_addr            ( dcp_addr      [(4*n+2)] ),
    .t2_dcp_data            ( dcp_data      [(4*n+2)] ),
    .t2_dcp_gate            ( dcp_gate      [(4*n+2)] ),
    .t2_dcp_rksel           ( dcp_rksel     [(4*n+2)] ),

    .t2_cal_mode            ( mdl_cal_mode  [(4*n+2)] ),
    .t2_cal_clk_en          ( mdl_cal_clk_en[(4*n+2)] ),
    .t2_cal_en              ( mdl_cal_en    [(4*n+2)] ),
    .t2_cal_en_out          ( mdl_cal_en_out[(4*n+2)] ),
    .t2_cal_out             ( mdl_cal_out   [(4*n+2)] ),

    .t2_dcc_clear           ( dcc_clear               ),
    .t2_dcc_start           ( dcc_start               ),
    .t2_dcc_done            ( dcc_done      [(4*n+2)] ),

    .t2_lb_en               ( 8'b0                    ),

    .t2_phy_phyclk          ( bk_phyclk     [(4*n+2)]             ),
    .t2_phy_ctlclk_ac       ( bk_ctlclk_ac  [(4*n+2)]             ),
    .t2_phy_ctlclk_dqs      ( bk_ctlclk_dqs [(4*n+2)]             ),
    .t2_phy_ctlclk_wdq      ( bk_ctlclk_wdq [(4*n+2)]             ),
    .t2_phy_ddrclk_ac       ( bk_ddrclk_ac  [(4*n+2)]             ),
    .t2_phy_ddrclk_dqs      ( bk_ddrclk_dqs [(4*n+2)]             ),
    .t2_phy_ddrclk_wdq      ( bk_ddrclk_wdq [(4*n+2)]             ),
    .t2_phy_ac_wr_rst_n     ( bk_ac_wr_rst_n[(4*n+2)]             ),
    .t2_phy_dx_wr_rst_n     ( bk_dx_wr_rst_n[(4*n+2)]             ),
    .t2_phy_ac_rd_rst_n     ( bk_ac_rd_rst_n[(4*n+2)]             ),
    .t2_phy_dx_rd_rst_n     ( bk_dx_rd_rst_n[(4*n+2)]             ),

    .t2_phy_rdata           ( bk_rdata      [(4*n+2)*104 +: 104 ] ),
    .t2_phy_wdata           ( bk_wdata      [(4*n+2)*104 +: 104 ] ),

    .t2_phy_rdqs_p          ( bk_rdqs_p     [(4*n+2)]             ),
    .t2_phy_rdqs_n          ( bk_rdqs_n     [(4*n+2)]             ),
    .t2_phy_rdqs_o          ( bk_rdqs_r     [(4*n+2)]             ),
    .t2_phy_rdqs_gate       ( bk_rdqs_f     [(4*n+2)]             ),

    .t2_phy_oe_md           ( bk_oe_md      [(4*n+2)*26 +: 26]    ),
    .t2_phy_te_md           ( bk_te_md      [(4*n+2)*26 +: 26]    ),
    .t2_phy_pdr_md          ( bk_pdr_md     [(4*n+2)*26 +: 26]    ),
    .t2_phy_oe_dq           ( bk_oe_dq      [(4*n+2)]             ),
    .t2_phy_oe_dqs          ( bk_oe_dqs     [(4*n+2)]             ),
    .t2_phy_oe_dqsn         ( bk_oe_dqsn    [(4*n+2)]             ),
    .t2_phy_te_dq           ( bk_te_dq      [(4*n+2)]             ),
    .t2_phy_te_dqs          ( bk_te_dqs     [(4*n+2)]             ),
    .t2_phy_te_dqsn         ( bk_te_dqsn    [(4*n+2)]             ),
    .t2_phy_pdr_dq          ( bk_pdr_dq     [(4*n+2)]             ),
    .t2_phy_pdr_dqs         ( bk_pdr_dqs    [(4*n+2)]             ),
    .t2_phy_pdr_dqsn        ( bk_pdr_dqsn   [(4*n+2)]             ),

    .t2_phy_rd_bdl_dly      ( bk_rd_bdl_dly [(4*n+2)*78 +: 78]    ),
    .t2_phy_wr_bdl_dly      ( bk_wr_bdl_dly [(4*n+2)*78 +: 78]    ),
    .t2_phy_rd_bdl_byp      ( bk_rd_bdl_byp [(4*n+2)*13 +: 13]    ),
    .t2_phy_wr_bdl_byp      ( bk_wr_bdl_byp [(4*n+2)*13 +: 13]    ),

    .t3_ioclk              ((MC_IDX == 0) ? {2'b00, ddr_clk[n], ctl_clk[n]} : {ddr_clk[n], ctl_clk[n], 2'b00}),
    .t3_usr_clk            ( usr_clk                  ),
    .t3_ac_rst_n           ( usr_rst_n                ),
    .t3_dx_rst_n           ( usr_rst_n                ),
    .t3_ctl_rst_n          ( usr_rst_n                ),
    .t3_dqs_rst_n          ( usr_rst_n                ),
    .t3_ac_fifo_rst_n      ( ac_fifo_rst_n  [(4*n+3)] ),
    .t3_dx_fifo_rst_n      ( dx_fifo_rst_n  [(4*n+3)] ),

    .t3_ctl_pdr            ( ctl_pdr        [(4*n+3)] ),
    .t3_ctl_te             ( ctl_te         [(4*n+3)] ),
    .t3_ctl_ts             ( ctl_ts         [(4*n+3)] ),

    .t3_ctl_wdata          ( ctl_wdata_int  [(4*n+3)] ),
    .t3_ctl_rdata          ( ctl_rdata_int  [(4*n+3)] ),
    .t3_ctl_rdata_vld      ( ctl_rdata_vld  [(4*n+3)] ),
    .t3_ctl_rdqs_gate      ( ctl_rdqs_gate  [(4*n+3)] ),
    .t3_qs_gate            ( 1'b0                 ),

    .t3_dqs_pupd_en        ( dqs_pupd_en    [(4*n+3)] ),
    .t3_wrlvl_mdoe         ( wrlvl_mdoe     [(4*n+3)] ),
    .t3_dqs_gate_status    ( dqs_gate_status[(4*n+3)] ),

    .t3_dcp_sel             ( dcp_sel       [(4*n+3)] ),
    .t3_dcp_addr            ( dcp_addr      [(4*n+3)] ),
    .t3_dcp_data            ( dcp_data      [(4*n+3)] ),
    .t3_dcp_gate            ( dcp_gate      [(4*n+3)] ),
    .t3_dcp_rksel           ( dcp_rksel     [(4*n+3)] ),

    .t3_cal_mode            ( mdl_cal_mode  [(4*n+3)] ),
    .t3_cal_clk_en          ( mdl_cal_clk_en[(4*n+3)] ),
    .t3_cal_en              ( mdl_cal_en    [(4*n+3)] ),
    .t3_cal_en_out          ( mdl_cal_en_out[(4*n+3)] ),
    .t3_cal_out             ( mdl_cal_out   [(4*n+3)] ),

    .t3_dcc_clear           ( dcc_clear               ),
    .t3_dcc_start           ( dcc_start               ),
    .t3_dcc_done            ( dcc_done      [(4*n+3)] ),

    .t3_lb_en               ( 8'b0                    ),

    .t3_phy_phyclk          ( bk_phyclk     [(4*n+3)]             ),
    .t3_phy_ctlclk_ac       ( bk_ctlclk_ac  [(4*n+3)]             ),
    .t3_phy_ctlclk_dqs      ( bk_ctlclk_dqs [(4*n+3)]             ),
    .t3_phy_ctlclk_wdq      ( bk_ctlclk_wdq [(4*n+3)]             ),
    .t3_phy_ddrclk_ac       ( bk_ddrclk_ac  [(4*n+3)]             ),
    .t3_phy_ddrclk_dqs      ( bk_ddrclk_dqs [(4*n+3)]             ),
    .t3_phy_ddrclk_wdq      ( bk_ddrclk_wdq [(4*n+3)]             ),
    .t3_phy_ac_wr_rst_n     ( bk_ac_wr_rst_n[(4*n+3)]             ),
    .t3_phy_dx_wr_rst_n     ( bk_dx_wr_rst_n[(4*n+3)]             ),
    .t3_phy_ac_rd_rst_n     ( bk_ac_rd_rst_n[(4*n+3)]             ),
    .t3_phy_dx_rd_rst_n     ( bk_dx_rd_rst_n[(4*n+3)]             ),

    .t3_phy_rdata           ( bk_rdata      [(4*n+3)*104 +: 104 ] ),
    .t3_phy_wdata           ( bk_wdata      [(4*n+3)*104 +: 104 ] ),

    .t3_phy_rdqs_p          ( bk_rdqs_p     [(4*n+3)]             ),
    .t3_phy_rdqs_n          ( bk_rdqs_n     [(4*n+3)]             ),
    .t3_phy_rdqs_o          ( bk_rdqs_r     [(4*n+3)]             ),
    .t3_phy_rdqs_gate       ( bk_rdqs_f     [(4*n+3)]             ),

    .t3_phy_oe_md           ( bk_oe_md      [(4*n+3)*26 +: 26]    ),
    .t3_phy_te_md           ( bk_te_md      [(4*n+3)*26 +: 26]    ),
    .t3_phy_pdr_md          ( bk_pdr_md     [(4*n+3)*26 +: 26]    ),
    .t3_phy_oe_dq           ( bk_oe_dq      [(4*n+3)]             ),
    .t3_phy_oe_dqs          ( bk_oe_dqs     [(4*n+3)]             ),
    .t3_phy_oe_dqsn         ( bk_oe_dqsn    [(4*n+3)]             ),
    .t3_phy_te_dq           ( bk_te_dq      [(4*n+3)]             ),
    .t3_phy_te_dqs          ( bk_te_dqs     [(4*n+3)]             ),
    .t3_phy_te_dqsn         ( bk_te_dqsn    [(4*n+3)]             ),
    .t3_phy_pdr_dq          ( bk_pdr_dq     [(4*n+3)]             ),
    .t3_phy_pdr_dqs         ( bk_pdr_dqs    [(4*n+3)]             ),
    .t3_phy_pdr_dqsn        ( bk_pdr_dqsn   [(4*n+3)]             ),

    .t3_phy_rd_bdl_dly      ( bk_rd_bdl_dly [(4*n+3)*78 +: 78]    ),
    .t3_phy_wr_bdl_dly      ( bk_wr_bdl_dly [(4*n+3)*78 +: 78]    ),
    .t3_phy_rd_bdl_byp      ( bk_rd_bdl_byp [(4*n+3)*13 +: 13]    ),
    .t3_phy_wr_bdl_byp      ( bk_wr_bdl_byp [(4*n+3)*13 +: 13]    )
);
end else begin : bk_unused
assign bk_apb_prdata[n*32 +:32] = 32'hdeadbeef;
assign bk_apb_pready[n]         = 1'b1;
end 
end 
endgenerate

ph1_ddrphy_pad_wrapper #(
    .WDM            ( WDM         ),
    .WDBI           ( WDBI        ),
    .RDBI           ( RDBI        ),

    .CK_WIDTH       ( CK_WIDTH    ),
    .CKE_WIDTH      ( CKE_WIDTH   ),
    .ODT_WIDTH      ( ODT_WIDTH   ),
    .CS_WIDTH       ( CS_WIDTH    ),
    .ADR_WIDTH      ( ADR_WIDTH   ),
    .BG_WIDTH       ( BG_WIDTH    ),
    .BA_WIDTH       ( BA_WIDTH    ),
    .DQS_WIDTH      ( DQS_WIDTH   ),
    .DQ_WIDTH       ( DQ_WIDTH    ),
    .DM_WIDTH       ( DM_WIDTH    ),

    .RST_MAP        ( RST_MAP     ),
    .CK_MAP         ( CK_MAP      ),
    .CKE_MAP        ( CKE_MAP     ),
    .ODT_MAP        ( ODT_MAP     ),
    .CS_MAP         ( CS_MAP      ),
    .ACT_MAP        ( ACT_MAP     ),
    .RAS_MAP        ( RAS_MAP     ),
    .CAS_MAP        ( CAS_MAP     ),
    .WE_MAP         ( WE_MAP      ),
    .BG_MAP         ( BG_MAP      ),
    .BA_MAP         ( BA_MAP      ),
    .ADR_MAP        ( ADR_MAP     ),
    .PAR_MAP        ( PAR_MAP     ),
    .ALT_MAP        ( ALT_MAP     ),

    .DQS_MAP        ( DQS_MAP     ),
    .DM_MAP         ( DM_MAP      ),
    .DQ_MAP         ( DQ_MAP      )
) u_ddrphy_pad_wraper (

    .phy_clk     ( bk_phyclk      ),
    .ctlclk_ac   ( bk_ctlclk_ac   ),
    .ctlclk_dqs  ( bk_ctlclk_dqs  ),
    .ctlclk_wdq  ( bk_ctlclk_wdq  ),
    .ddrclk_ac   ( bk_ddrclk_ac   ),
    .ddrclk_dqs  ( bk_ddrclk_dqs  ),
    .ddrclk_wdq  ( bk_ddrclk_wdq  ),
    .ac_wr_rst_n ( bk_ac_wr_rst_n ),
    .dx_wr_rst_n ( bk_dx_wr_rst_n ),
    .ac_rd_rst_n ( bk_ac_rd_rst_n ),
    .dx_rd_rst_n ( bk_dx_rd_rst_n ),

    .rdata       ( bk_rdata       ),
    .wdata       ( bk_wdata       ),
    .indd        ( bk_indd        ),

    .rdqs_p      ( bk_rdqs_p      ),
    .rdqs_n      ( bk_rdqs_n      ),
    .rdqs_r      ( bk_rdqs_r      ),
    .rdqs_f      ( bk_rdqs_f      ),

    .oe_md       ( bk_oe_md       ),
    .te_md       ( bk_te_md       ),
    .pdr_md      ( bk_pdr_md      ),

    .oe_dq       ( bk_oe_dq       ),
    .oe_dqs      ( bk_oe_dqs      ),
    .oe_dqsn     ( bk_oe_dqsn     ),
    .te_dq       ( bk_te_dq       ),
    .te_dqs      ( bk_te_dqs      ),
    .te_dqsn     ( bk_te_dqsn     ),
    .pdr_dq      ( bk_pdr_dq      ),
    .pdr_dqs     ( bk_pdr_dqs     ),
    .pdr_dqsn    ( bk_pdr_dqsn    ),

    .wr_bdl_byp  ( bk_wr_bdl_byp  ),
    .rd_bdl_byp  ( bk_rd_bdl_byp  ),
    .wr_bdl_dly  ( bk_wr_bdl_dly  ),
    .rd_bdl_dly  ( bk_rd_bdl_dly  ),

`ifdef MC0_DRAM_DDR4
    .ddr_ck_p    ( ddr_ck_t       ),
    .ddr_ck_n    ( ddr_ck_c       ),
    .ddr_reset_n ( ddr_reset_n    ),
    .ddr_cke     ( ddr_cke        ),
    .ddr_odt     ( ddr_odt        ),
    .ddr_cs_n    ( ddr_cs_n       ),
    .ddr_act_n   ( ddr_act_n      ),
    .ddr_bg      ( ddr_bg         ),
    .ddr_ba      ( ddr_ba         ),
    .ddr_addr    ( ddr_addr       ),

    .ddr_parity  ( ddr_parity     ),
    .ddr_alert_n ( ddr_alert_n    ),

    .ddr_dqs_p   ( ddr_dqs_t      ),
    .ddr_dqs_n   ( ddr_dqs_c      ),
    .ddr_dq      ( ddr_dq         ),
    .ddr_dm      ( ddr_dm_n       )
`else
    .ddr_ck_p    ( ddr_ck_p       ),
    .ddr_ck_n    ( ddr_ck_n       ),
    .ddr_reset_n ( ddr_reset_n    ),
    .ddr_cke     ( ddr_cke        ),
    .ddr_odt     ( ddr_odt        ),
    .ddr_cs_n    ( ddr_cs_n       ),
    .ddr_ras_n   ( ddr_ras_n      ),
    .ddr_cas_n   ( ddr_cas_n      ),
    .ddr_we_n    ( ddr_we_n       ),
    .ddr_ba      ( ddr_ba         ),
    .ddr_addr    ( ddr_addr       ),

    .ddr_dqs_p   ( ddr_dqs_p      ),
    .ddr_dqs_n   ( ddr_dqs_n      ),
    .ddr_dq      ( ddr_dq         ),
    .ddr_dm      ( ddr_dm         )
`endif
);

endmodule

`timescale 1ps / 1ps

module ph1_ddrphy_bank_top #(
    parameter MC_IDX         = 0          , 
    parameter MC_TCK         = 1876       ,
    parameter DCC_VREF       = 0          ,

    parameter T0_BYTE_EN     = "DISABLE"  ,
    parameter T0_BYTE_TYPE   = "DX"       , 
    parameter T1_BYTE_EN     = "DISABLE"  ,
    parameter T1_BYTE_TYPE   = "DX"       , 
    parameter T2_BYTE_EN     = "DISABLE"  ,
    parameter T2_BYTE_TYPE   = "DX"       , 
    parameter T3_BYTE_EN     = "DISABLE"  ,
    parameter T3_BYTE_TYPE   = "DX"         

)(

    

    
    input             pzq_usr_rst_n          ,
    input             pzq_usr_clk            ,

    input             apb_prst_n             ,
    input             apb_pclk               ,
    input             apb_psel               ,
    input  [ 15:0]    apb_paddr              ,
    input             apb_penable            ,
    input  [ 31:0]    apb_pwdata             ,
    input             apb_pwrite             ,
    output [ 31:0]    apb_prdata             ,
    output            apb_pready             ,

    input             zqcal_clear            ,
    input             zqcal_start            ,
    input             zqcal_update           ,
    output            zqcal_done             ,

    

    
    input            t0_usr_clk             ,
    input  [  3:0]   t0_ioclk               ,
    input            t0_ac_rst_n            ,
    input            t0_dx_rst_n            ,
    input            t0_dqs_rst_n           ,
    input            t0_ctl_rst_n           ,
    input            t0_ac_fifo_rst_n       ,
    input            t0_dx_fifo_rst_n       ,

    input  [  7:0]   t0_ctl_pdr             ,
    input  [  7:0]   t0_ctl_te              ,
    input  [  7:0]   t0_ctl_ts              ,

    input  [103:0]   t0_ctl_wdata           ,
    output [103:0]   t0_ctl_rdata           ,
    output           t0_ctl_rdata_vld       ,
    input  [  7:0]   t0_ctl_rdqs_gate       ,
    input            t0_qs_gate             ,

    input            t0_dcp_sel             ,
    input  [  5:0]   t0_dcp_addr            ,
    input  [  8:0]   t0_dcp_data            ,
    input            t0_dcp_gate            ,
    input            t0_dcp_rksel           ,

    input            t0_cal_mode            ,
    input  [  6:0]   t0_cal_clk_en          ,
    input  [  6:0]   t0_cal_en              ,
    output [  6:0]   t0_cal_en_out          ,
    output [  6:0]   t0_cal_out             ,

    input            t0_dcc_clear           ,
    input            t0_dcc_start           ,
    output           t0_dcc_done            ,

    input  [  7:0]   t0_lb_en               ,
    input            t0_dqs_pupd_en         ,
    input            t0_wrlvl_mdoe          ,
    output [  1:0]   t0_dqs_gate_status     ,
    output [  1:0]   t0_dqsn_cnt            ,
    output [ 15:0]   t0_o_debug             ,

    

    
    output           t0_phy_ctlclk_ac       ,
    output           t0_phy_ctlclk_dqs      ,
    output           t0_phy_ctlclk_wdq      ,
    output           t0_phy_ddrclk_ac       ,
    output           t0_phy_ddrclk_dqs      ,
    output           t0_phy_ddrclk_wdq      ,
    output           t0_phy_phyclk          ,
    output           t0_phy_ac_wr_rst_n     ,
    output           t0_phy_dx_wr_rst_n     ,
    output           t0_phy_ac_rd_rst_n     ,
    output           t0_phy_dx_rd_rst_n     ,

    input  [103:0]   t0_phy_rdata           ,
    output [103:0]   t0_phy_wdata           ,

    input            t0_phy_rdqs_p          ,
    input            t0_phy_rdqs_n          ,
    output           t0_phy_rdqs_o          ,
    output           t0_phy_rdqs_gate       ,

    output [ 25:0]   t0_phy_oe_md           ,
    output [ 25:0]   t0_phy_te_md           ,
    output [ 25:0]   t0_phy_pdr_md          ,

    output           t0_phy_oe_dq           ,
    output           t0_phy_oe_dqs          ,
    output           t0_phy_oe_dqsn         ,
    output           t0_phy_te_dq           ,
    output           t0_phy_te_dqs          ,
    output           t0_phy_te_dqsn         ,
    output           t0_phy_pdr_dq          ,
    output           t0_phy_pdr_dqs         ,
    output           t0_phy_pdr_dqsn        ,

    output [ 77:0]   t0_phy_rd_bdl_dly      ,
    output [ 12:0]   t0_phy_rd_bdl_byp      ,

    output [ 77:0]   t0_phy_wr_bdl_dly      ,
    output [ 12:0]   t0_phy_wr_bdl_byp      ,

    

    
    input            t1_usr_clk             ,
    input  [  3:0]   t1_ioclk               ,
    input            t1_ac_rst_n            ,
    input            t1_dx_rst_n            ,
    input            t1_dqs_rst_n           ,
    input            t1_ctl_rst_n           ,
    input            t1_ac_fifo_rst_n       ,
    input            t1_dx_fifo_rst_n       ,

    input  [  7:0]   t1_ctl_pdr             ,
    input  [  7:0]   t1_ctl_te              ,
    input  [  7:0]   t1_ctl_ts              ,

    input  [103:0]   t1_ctl_wdata           ,
    output [103:0]   t1_ctl_rdata           ,
    output           t1_ctl_rdata_vld       ,
    input  [  7:0]   t1_ctl_rdqs_gate       ,
    input            t1_qs_gate             ,

    input            t1_dqs_pupd_en         ,
    input            t1_wrlvl_mdoe          ,
    output [  1:0]   t1_dqs_gate_status     ,

    input            t1_dcp_sel             ,
    input  [  5:0]   t1_dcp_addr            ,
    input  [  8:0]   t1_dcp_data            ,
    input            t1_dcp_gate            ,
    input            t1_dcp_rksel           ,

    input            t1_cal_mode            ,
    input  [  6:0]   t1_cal_clk_en          ,
    input  [  6:0]   t1_cal_en              ,
    output [  6:0]   t1_cal_en_out          ,
    output [  6:0]   t1_cal_out             ,

    input            t1_dcc_clear           ,
    input            t1_dcc_start           ,
    output           t1_dcc_done            ,

    input  [  7:0]   t1_lb_en               ,

    output [  1:0]   t1_dqsn_cnt            ,
    output [ 15:0]   t1_o_debug             ,

    

    
    output           t1_phy_ctlclk_ac       ,
    output           t1_phy_ctlclk_dqs      ,
    output           t1_phy_ctlclk_wdq      ,
    output           t1_phy_ddrclk_ac       ,
    output           t1_phy_ddrclk_dqs      ,
    output           t1_phy_ddrclk_wdq      ,
    output           t1_phy_phyclk          ,
    output           t1_phy_ac_wr_rst_n     ,
    output           t1_phy_dx_wr_rst_n     ,
    output           t1_phy_ac_rd_rst_n     ,
    output           t1_phy_dx_rd_rst_n     ,

    input  [103:0]   t1_phy_rdata           ,
    output [103:0]   t1_phy_wdata           ,

    input            t1_phy_rdqs_p          ,
    input            t1_phy_rdqs_n          ,
    output           t1_phy_rdqs_o          ,
    output           t1_phy_rdqs_gate       ,

    output [ 25:0]   t1_phy_oe_md           ,
    output [ 25:0]   t1_phy_te_md           ,
    output [ 25:0]   t1_phy_pdr_md          ,

    output           t1_phy_oe_dq           ,
    output           t1_phy_oe_dqs          ,
    output           t1_phy_oe_dqsn         ,
    output           t1_phy_te_dq           ,
    output           t1_phy_te_dqs          ,
    output           t1_phy_te_dqsn         ,
    output           t1_phy_pdr_dq          ,
    output           t1_phy_pdr_dqs         ,
    output           t1_phy_pdr_dqsn        ,

    output [ 77:0]   t1_phy_rd_bdl_dly      ,
    output [ 12:0]   t1_phy_rd_bdl_byp      ,

    output [ 77:0]   t1_phy_wr_bdl_dly      ,
    output [ 12:0]   t1_phy_wr_bdl_byp      ,

    

    
    input            t2_usr_clk             ,
    input  [  3:0]   t2_ioclk               ,
    input            t2_ac_rst_n            ,
    input            t2_dx_rst_n            ,
    input            t2_dqs_rst_n           ,
    input            t2_ctl_rst_n           ,
    input            t2_ac_fifo_rst_n       ,
    input            t2_dx_fifo_rst_n       ,

    input  [  7:0]   t2_ctl_pdr             ,
    input  [  7:0]   t2_ctl_te              ,
    input  [  7:0]   t2_ctl_ts              ,

    input  [103:0]   t2_ctl_wdata           ,
    output [103:0]   t2_ctl_rdata           ,
    output           t2_ctl_rdata_vld       ,
    input  [ 7:0]    t2_ctl_rdqs_gate       ,
    input            t2_qs_gate             ,

    input            t2_dqs_pupd_en         ,
    input            t2_wrlvl_mdoe          ,
    output [  1:0]   t2_dqs_gate_status     ,

    input            t2_dcp_sel             ,
    input  [  5:0]   t2_dcp_addr            ,
    input  [  8:0]   t2_dcp_data            ,
    input            t2_dcp_gate            ,
    input            t2_dcp_rksel           ,

    input            t2_cal_mode            ,
    input  [  6:0]   t2_cal_clk_en          ,
    input  [  6:0]   t2_cal_en              ,
    output [  6:0]   t2_cal_en_out          ,
    output [  6:0]   t2_cal_out             ,

    input            t2_dcc_clear           ,
    input            t2_dcc_start           ,
    output           t2_dcc_done            ,

    input  [  7:0]   t2_lb_en               ,

    output [  1:0]   t2_dqsn_cnt            ,
    output [ 15:0]   t2_o_debug             ,

    

    
    output           t2_phy_ctlclk_ac       ,
    output           t2_phy_ctlclk_dqs      ,
    output           t2_phy_ctlclk_wdq      ,
    output           t2_phy_ddrclk_ac       ,
    output           t2_phy_ddrclk_dqs      ,
    output           t2_phy_ddrclk_wdq      ,
    output           t2_phy_phyclk          ,
    output           t2_phy_ac_wr_rst_n     ,
    output           t2_phy_dx_wr_rst_n     ,
    output           t2_phy_ac_rd_rst_n     ,
    output           t2_phy_dx_rd_rst_n     ,

    input  [103:0]   t2_phy_rdata           ,
    output [103:0]   t2_phy_wdata           ,

    input            t2_phy_rdqs_p          ,
    input            t2_phy_rdqs_n          ,
    output           t2_phy_rdqs_o          ,
    output           t2_phy_rdqs_gate       ,

    output [ 25:0]   t2_phy_oe_md           ,
    output [ 25:0]   t2_phy_te_md           ,
    output [ 25:0]   t2_phy_pdr_md          ,

    output           t2_phy_oe_dq           ,
    output           t2_phy_oe_dqs          ,
    output           t2_phy_oe_dqsn         ,
    output           t2_phy_te_dq           ,
    output           t2_phy_te_dqs          ,
    output           t2_phy_te_dqsn         ,
    output           t2_phy_pdr_dq          ,
    output           t2_phy_pdr_dqs         ,
    output           t2_phy_pdr_dqsn        ,

    output [ 77:0]   t2_phy_rd_bdl_dly      ,
    output [ 12:0]   t2_phy_rd_bdl_byp      ,

    output [ 77:0]   t2_phy_wr_bdl_dly      ,
    output [ 12:0]   t2_phy_wr_bdl_byp      ,

    

    
    input            t3_usr_clk             ,
    input  [  3:0]   t3_ioclk               ,
    input            t3_ac_rst_n            ,
    input            t3_dx_rst_n            ,
    input            t3_dqs_rst_n           ,
    input            t3_ctl_rst_n           ,
    input            t3_ac_fifo_rst_n       ,
    input            t3_dx_fifo_rst_n       ,

    input  [  7:0]   t3_ctl_pdr             ,
    input  [  7:0]   t3_ctl_te              ,
    input  [  7:0]   t3_ctl_ts              ,

    input  [103:0]   t3_ctl_wdata           ,
    output [103:0]   t3_ctl_rdata           ,
    output           t3_ctl_rdata_vld       ,
    input  [  7:0]   t3_ctl_rdqs_gate       ,
    input            t3_qs_gate             ,

    input            t3_dqs_pupd_en         ,
    input            t3_wrlvl_mdoe          ,
    output [  1:0]   t3_dqs_gate_status     ,

    input            t3_dcp_sel             ,
    input  [  5:0]   t3_dcp_addr            ,
    input  [  8:0]   t3_dcp_data            ,
    input            t3_dcp_gate            ,
    input            t3_dcp_rksel           ,

    input            t3_cal_mode            ,
    input  [  6:0]   t3_cal_clk_en          ,
    input  [  6:0]   t3_cal_en              ,
    output [  6:0]   t3_cal_en_out          ,
    output [  6:0]   t3_cal_out             ,

    input            t3_dcc_clear           ,
    input            t3_dcc_start           ,
    output           t3_dcc_done            ,

    input  [  7:0]   t3_lb_en               ,

    output [  1:0]   t3_dqsn_cnt            ,
    output [ 15:0]   t3_o_debug             ,

    

    
    output           t3_phy_ctlclk_ac       ,
    output           t3_phy_ctlclk_dqs      ,
    output           t3_phy_ctlclk_wdq      ,
    output           t3_phy_ddrclk_ac       ,
    output           t3_phy_ddrclk_dqs      ,
    output           t3_phy_ddrclk_wdq      ,
    output           t3_phy_phyclk          ,
    output           t3_phy_ac_wr_rst_n     ,
    output           t3_phy_dx_wr_rst_n     ,
    output           t3_phy_ac_rd_rst_n     ,
    output           t3_phy_dx_rd_rst_n     ,

    input  [103:0]   t3_phy_rdata           ,
    output [103:0]   t3_phy_wdata           ,

    input            t3_phy_rdqs_p          ,
    input            t3_phy_rdqs_n          ,
    output           t3_phy_rdqs_o          ,
    output           t3_phy_rdqs_gate       ,

    output [ 25:0]   t3_phy_oe_md           ,
    output [ 25:0]   t3_phy_te_md           ,
    output [ 25:0]   t3_phy_pdr_md          ,

    output           t3_phy_oe_dq           ,
    output           t3_phy_oe_dqs          ,
    output           t3_phy_oe_dqsn         ,
    output           t3_phy_te_dq           ,
    output           t3_phy_te_dqs          ,
    output           t3_phy_te_dqsn         ,
    output           t3_phy_pdr_dq          ,
    output           t3_phy_pdr_dqs         ,
    output           t3_phy_pdr_dqsn        ,

    
    output [ 77:0]   t3_phy_rd_bdl_dly      ,
    output [ 12:0]   t3_phy_rd_bdl_byp      ,

    output [ 77:0]   t3_phy_wr_bdl_dly      ,
    output [ 12:0]   t3_phy_wr_bdl_byp
);

localparam T0_DDR_SIGNAL_TYPE     = T0_BYTE_TYPE;
localparam T0_DDR_SIGNAL_TYPE_DQS = T0_BYTE_TYPE;
localparam T0_CTL_CLK_SWI_SEL     = (MC_IDX == 0) ? "IOCLK0" : "IOCLK2";
localparam T0_DDR_CLK_SWI_SEL     = (MC_IDX == 0) ? "IOCLK1" : "IOCLK3";
localparam T0_DLY_CAL_MODE        = (MC_TCK       >= 2500     ) ? "HALF"    : "FULL"  ;
localparam T0_DCC_EN              = (T0_BYTE_EN   == "DISABLE") ? "DISABLE" : "ENABLE";
localparam T0_DCC_CLK_SEL         = (T0_BYTE_TYPE == "DX"     ) ? "CLK_WL"  : "CLK_IO";
localparam T0_WL_GATE_DIS_EN      = "ENABLE"   ;
localparam T0_DQS_GATE_TYPE       = "DQS"      ;
localparam T0_DLY_TEST_EN         = "DISABLE"  ;

localparam T1_DDR_SIGNAL_TYPE     = T1_BYTE_TYPE;
localparam T1_DDR_SIGNAL_TYPE_DQS = T1_BYTE_TYPE;
localparam T1_CTL_CLK_SWI_SEL     = (MC_IDX == 0) ? "IOCLK0" : "IOCLK2";
localparam T1_DDR_CLK_SWI_SEL     = (MC_IDX == 0) ? "IOCLK1" : "IOCLK3";
localparam T1_DLY_CAL_MODE        = (MC_TCK       >= 2500     ) ? "HALF"    : "FULL"  ;
localparam T1_DCC_EN              = (T1_BYTE_EN   == "DISABLE") ? "DISABLE" : "ENABLE";
localparam T1_DCC_CLK_SEL         = (T1_BYTE_TYPE == "DX"     ) ? "CLK_WL"  : "CLK_IO";
localparam T1_WL_GATE_DIS_EN      = "ENABLE"   ;
localparam T1_DQS_GATE_TYPE       = "DQS"      ;
localparam T1_DLY_TEST_EN         = "DISABLE"  ;

localparam T2_DDR_SIGNAL_TYPE     = T2_BYTE_TYPE;
localparam T2_DDR_SIGNAL_TYPE_DQS = T2_BYTE_TYPE;
localparam T2_CTL_CLK_SWI_SEL     = (MC_IDX == 0) ? "IOCLK0" : "IOCLK2";
localparam T2_DDR_CLK_SWI_SEL     = (MC_IDX == 0) ? "IOCLK1" : "IOCLK3";
localparam T2_DLY_CAL_MODE        = (MC_TCK       >= 2500     ) ? "HALF"    : "FULL"  ;
localparam T2_DCC_EN              = (T2_BYTE_EN   == "DISABLE") ? "DISABLE" : "ENABLE";
localparam T2_DCC_CLK_SEL         = (T2_BYTE_TYPE == "DX"     ) ? "CLK_WL"  : "CLK_IO";
localparam T2_WL_GATE_DIS_EN      = "ENABLE"   ;
localparam T2_DQS_GATE_TYPE       = "DQS"      ;
localparam T2_DLY_TEST_EN         = "DISABLE"  ;

localparam T3_DDR_SIGNAL_TYPE     = T3_BYTE_TYPE;
localparam T3_DDR_SIGNAL_TYPE_DQS = T3_BYTE_TYPE;
localparam T3_CTL_CLK_SWI_SEL     = (MC_IDX == 0) ? "IOCLK0" : "IOCLK2";
localparam T3_DDR_CLK_SWI_SEL     = (MC_IDX == 0) ? "IOCLK1" : "IOCLK3";
localparam T3_DLY_CAL_MODE        = (MC_TCK       >= 2500     ) ? "HALF"    : "FULL"  ;
localparam T3_DCC_EN              = (T3_BYTE_EN   == "DISABLE") ? "DISABLE" : "ENABLE";
localparam T3_DCC_CLK_SEL         = (T3_BYTE_TYPE == "DX"     ) ? "CLK_WL"  : "CLK_IO";
localparam T3_WL_GATE_DIS_EN      = "ENABLE"   ;
localparam T3_DQS_GATE_TYPE       = "DQS"      ;
localparam T3_DLY_TEST_EN         = "DISABLE"  ;

wire [ 23:0]   t0_phy_oe_md_int  ;
wire [ 23:0]   t0_phy_te_md_int  ;
wire [ 23:0]   t0_phy_pdr_md_int ;

wire [ 23:0]   t1_phy_oe_md_int  ;
wire [ 23:0]   t1_phy_te_md_int  ;
wire [ 23:0]   t1_phy_pdr_md_int ;

wire [ 23:0]   t2_phy_oe_md_int  ;
wire [ 23:0]   t2_phy_te_md_int  ;
wire [ 23:0]   t2_phy_pdr_md_int ;

wire [ 23:0]   t3_phy_oe_md_int  ;
wire [ 23:0]   t3_phy_te_md_int  ;
wire [ 23:0]   t3_phy_pdr_md_int ;

wire           t0_apb_prst_n     ;
wire           t0_apb_pclk       ;
wire           t0_apb_psel       ;
wire [ 15:0]   t0_apb_paddr      ;
wire           t0_apb_penable    ;
wire [ 31:0]   t0_apb_pwdata     ;
wire           t0_apb_pwrite     ;
wire [ 31:0]   t0_apb_prdata     ;
wire           t0_apb_pready     ;

wire           t1_apb_prst_n     ;
wire           t1_apb_pclk       ;
wire           t1_apb_psel       ;
wire [ 15:0]   t1_apb_paddr      ;
wire           t1_apb_penable    ;
wire [ 31:0]   t1_apb_pwdata     ;
wire           t1_apb_pwrite     ;
wire [ 31:0]   t1_apb_prdata     ;
wire           t1_apb_pready     ;

wire           t2_apb_prst_n     ;
wire           t2_apb_pclk       ;
wire           t2_apb_psel       ;
wire [ 15:0]   t2_apb_paddr      ;
wire           t2_apb_penable    ;
wire [ 31:0]   t2_apb_pwdata     ;
wire           t2_apb_pwrite     ;
wire [ 31:0]   t2_apb_prdata     ;
wire           t2_apb_pready     ;

wire           t3_apb_prst_n     ;
wire           t3_apb_pclk       ;
wire           t3_apb_psel       ;
wire [ 15:0]   t3_apb_paddr      ;
wire           t3_apb_penable    ;
wire [ 31:0]   t3_apb_pwdata     ;
wire           t3_apb_pwrite     ;
wire [ 31:0]   t3_apb_prdata     ;
wire           t3_apb_pready     ;

wire           bk_apb_prst_n     ;
wire           bk_apb_pclk       ;
wire           bk_apb_psel       ;
wire [ 15:0]   bk_apb_paddr      ;
wire           bk_apb_penable    ;
wire [ 31:0]   bk_apb_pwdata     ;
wire           bk_apb_pwrite     ;
wire [ 31:0]   bk_apb_prdata     ;
wire           bk_apb_pready     ;

assign t0_apb_prst_n  = apb_prst_n   ;
assign t0_apb_pclk    = apb_pclk     ;
assign t0_apb_paddr   = {5'h0, apb_paddr[4:0]};
assign t0_apb_penable = apb_penable  ;
assign t0_apb_pwdata  = apb_pwdata   ;
assign t0_apb_pwrite  = apb_pwrite   ;

assign t1_apb_prst_n  = apb_prst_n   ;
assign t1_apb_pclk    = apb_pclk     ;
assign t1_apb_paddr   = {5'h0, apb_paddr[4:0]};
assign t1_apb_penable = apb_penable  ;
assign t1_apb_pwdata  = apb_pwdata   ;
assign t1_apb_pwrite  = apb_pwrite   ;

assign t2_apb_prst_n  = apb_prst_n   ;
assign t2_apb_pclk    = apb_pclk     ;
assign t2_apb_paddr   = {5'h0, apb_paddr[4:0]};
assign t2_apb_penable = apb_penable  ;
assign t2_apb_pwdata  = apb_pwdata   ;
assign t2_apb_pwrite  = apb_pwrite   ;

assign t3_apb_prst_n  = apb_prst_n   ;
assign t3_apb_pclk    = apb_pclk     ;
assign t3_apb_paddr   = {5'h0, apb_paddr[4:0]};
assign t3_apb_penable = apb_penable  ;
assign t3_apb_pwdata  = apb_pwdata   ;
assign t3_apb_pwrite  = apb_pwrite   ;

assign bk_apb_prst_n  = apb_prst_n   ;
assign bk_apb_pclk    = apb_pclk     ;
assign bk_apb_paddr   = {5'h0, apb_paddr[4:0]};
assign bk_apb_penable = apb_penable  ;
assign bk_apb_pwdata  = apb_pwdata   ;
assign bk_apb_pwrite  = apb_pwrite   ;

assign t0_apb_psel    = (apb_paddr[9:6] == 4'h0) ? apb_psel : 1'b0;
assign t1_apb_psel    = (apb_paddr[9:6] == 4'h1) ? apb_psel : 1'b0;
assign t2_apb_psel    = (apb_paddr[9:6] == 4'h2) ? apb_psel : 1'b0;
assign t3_apb_psel    = (apb_paddr[9:6] == 4'h3) ? apb_psel : 1'b0;
assign bk_apb_psel    = (apb_paddr[9:6] == 4'h4) ? apb_psel : 1'b0;

assign apb_prdata     = (apb_paddr[9:6] == 4'h0) ? t0_apb_prdata :
                        (apb_paddr[9:6] == 4'h1) ? t1_apb_prdata :
                        (apb_paddr[9:6] == 4'h2) ? t2_apb_prdata :
                        (apb_paddr[9:6] == 4'h3) ? t3_apb_prdata :
                        (apb_paddr[9:6] == 4'h4) ? bk_apb_prdata : 32'hdeadbeef;

assign apb_pready     = (apb_paddr[9:6] == 4'h0) ? t0_apb_pready :
                        (apb_paddr[9:6] == 4'h1) ? t1_apb_pready :
                        (apb_paddr[9:6] == 4'h2) ? t2_apb_pready :
                        (apb_paddr[9:6] == 4'h3) ? t3_apb_pready :
                        (apb_paddr[9:6] == 4'h4) ? bk_apb_pready : 1'b1;

assign t0_phy_oe_md  = {t0_phy_oe_md_int [23:14], t0_phy_oe_md_int [13:12], t0_phy_oe_md_int [13:12], t0_phy_oe_md_int [11:0]};
assign t0_phy_te_md  = {t0_phy_te_md_int [23:14], t0_phy_te_md_int [13:12], t0_phy_te_md_int [13:12], t0_phy_te_md_int [11:0]};
assign t0_phy_pdr_md = {t0_phy_pdr_md_int[23:14], t0_phy_pdr_md_int[13:12], t0_phy_pdr_md_int[13:12], t0_phy_pdr_md_int[11:0]};

assign t1_phy_oe_md  = {t1_phy_oe_md_int [23:14], t1_phy_oe_md_int [13:12], t1_phy_oe_md_int [13:12], t1_phy_oe_md_int [11:0]};
assign t1_phy_te_md  = {t1_phy_te_md_int [23:14], t1_phy_te_md_int [13:12], t1_phy_te_md_int [13:12], t1_phy_te_md_int [11:0]};
assign t1_phy_pdr_md = {t1_phy_pdr_md_int[23:14], t1_phy_pdr_md_int[13:12], t1_phy_pdr_md_int[13:12], t1_phy_pdr_md_int[11:0]};

assign t2_phy_oe_md  = {t2_phy_oe_md_int [23:14], t2_phy_oe_md_int [13:12], t2_phy_oe_md_int [13:12], t2_phy_oe_md_int [11:0]};
assign t2_phy_te_md  = {t2_phy_te_md_int [23:14], t2_phy_te_md_int [13:12], t2_phy_te_md_int [13:12], t2_phy_te_md_int [11:0]};
assign t2_phy_pdr_md = {t2_phy_pdr_md_int[23:14], t2_phy_pdr_md_int[13:12], t2_phy_pdr_md_int[13:12], t2_phy_pdr_md_int[11:0]};

assign t3_phy_oe_md  = {t3_phy_oe_md_int [23:14], t3_phy_oe_md_int [13:12], t3_phy_oe_md_int [13:12], t3_phy_oe_md_int [11:0]};
assign t3_phy_te_md  = {t3_phy_te_md_int [23:14], t3_phy_te_md_int [13:12], t3_phy_te_md_int [13:12], t3_phy_te_md_int [11:0]};
assign t3_phy_pdr_md = {t3_phy_pdr_md_int[23:14], t3_phy_pdr_md_int[13:12], t3_phy_pdr_md_int[13:12], t3_phy_pdr_md_int[11:0]};

PH1_PHY_DDR_BANK #(

    .A_BYTE_TYPE           ( T0_BYTE_TYPE         ),
    .A_DDR_CLK_SWI_SEL     ( T0_DDR_CLK_SWI_SEL   ),
    .A_CTL_CLK_SWI_SEL     ( T0_CTL_CLK_SWI_SEL   ),
    .A_DLY_TEST_EN         ( T0_DLY_TEST_EN       ),
    .A_DLY_CAL_MODE        ( T0_DLY_CAL_MODE      ),
    .A_WL_GATE_DIS_EN      ( T0_WL_GATE_DIS_EN    ),
    .A_DQS_GATE_TYPE       ( T0_DQS_GATE_TYPE     ),
    .A_DCC_VREF            ( DCC_VREF             ),
    .A_DCC_EN              ( T0_DCC_EN            ),
    .A_DCC_CLK_SEL         ( T0_DCC_CLK_SEL       ),
    .A_DDR_SIGNAL_TYPE     ( T0_BYTE_TYPE         ),
    .A_DDR_SIGNAL_TYPE_DQS ( T0_BYTE_TYPE         ),

    .B_BYTE_TYPE           ( T1_BYTE_TYPE         ),
    .B_DDR_CLK_SWI_SEL     ( T1_DDR_CLK_SWI_SEL   ),
    .B_CTL_CLK_SWI_SEL     ( T1_CTL_CLK_SWI_SEL   ),
    .B_DLY_TEST_EN         ( T1_DLY_TEST_EN       ),
    .B_DLY_CAL_MODE        ( T1_DLY_CAL_MODE      ),
    .B_WL_GATE_DIS_EN      ( T1_WL_GATE_DIS_EN    ),
    .B_DQS_GATE_TYPE       ( T1_DQS_GATE_TYPE     ),
    .B_DCC_VREF            ( DCC_VREF             ),
    .B_DCC_EN              ( T1_DCC_EN            ),
    .B_DCC_CLK_SEL         ( T1_DCC_CLK_SEL       ),
    .B_DDR_SIGNAL_TYPE     ( T1_BYTE_TYPE         ),
    .B_DDR_SIGNAL_TYPE_DQS ( T1_BYTE_TYPE         ),

    .C_BYTE_TYPE           ( T2_BYTE_TYPE         ),
    .C_DDR_CLK_SWI_SEL     ( T2_DDR_CLK_SWI_SEL   ),
    .C_CTL_CLK_SWI_SEL     ( T2_CTL_CLK_SWI_SEL   ),
    .C_DLY_TEST_EN         ( T2_DLY_TEST_EN       ),
    .C_DLY_CAL_MODE        ( T2_DLY_CAL_MODE      ),
    .C_WL_GATE_DIS_EN      ( T2_WL_GATE_DIS_EN    ),
    .C_DQS_GATE_TYPE       ( T2_DQS_GATE_TYPE     ),
    .C_DCC_VREF            ( DCC_VREF             ),
    .C_DCC_EN              ( T2_DCC_EN            ),
    .C_DCC_CLK_SEL         ( T2_DCC_CLK_SEL       ),
    .C_DDR_SIGNAL_TYPE     ( T2_BYTE_TYPE         ),
    .C_DDR_SIGNAL_TYPE_DQS ( T2_BYTE_TYPE         ),

    .D_BYTE_TYPE           ( T3_BYTE_TYPE         ),
    .D_DDR_CLK_SWI_SEL     ( T3_DDR_CLK_SWI_SEL   ),
    .D_CTL_CLK_SWI_SEL     ( T3_CTL_CLK_SWI_SEL   ),
    .D_DLY_TEST_EN         ( T3_DLY_TEST_EN       ),
    .D_DLY_CAL_MODE        ( T3_DLY_CAL_MODE      ),
    .D_WL_GATE_DIS_EN      ( T3_WL_GATE_DIS_EN    ),
    .D_DQS_GATE_TYPE       ( T3_DQS_GATE_TYPE     ),
    .D_DCC_VREF            ( DCC_VREF             ),
    .D_DCC_EN              ( T3_DCC_EN            ),
    .D_DCC_CLK_SEL         ( T3_DCC_CLK_SEL       ),
    .D_DDR_SIGNAL_TYPE     ( T3_BYTE_TYPE         ),
    .D_DDR_SIGNAL_TYPE_DQS ( T3_BYTE_TYPE         ),

    .A_APPS                ( "DDR_DRAM"           ),
    .A_DATA_WIDTH          ( "X8"                 ),
    .A_IOCLK0D2S_EN        ( "DISABLE"            ),
    .A_IOCLK1D2S_EN        ( "DISABLE"            ),
    .A_IOCLK2D2S_EN        ( "DISABLE"            ),
    .A_IOCLK3D2S_EN        ( "DISABLE"            ),

    .B_APPS                ( "DDR_DRAM"           ),
    .B_DATA_WIDTH          ( "X8"                 ),
    .B_IOCLK0D2S_EN        ( "DISABLE"            ),
    .B_IOCLK1D2S_EN        ( "DISABLE"            ),
    .B_IOCLK2D2S_EN        ( "DISABLE"            ),
    .B_IOCLK3D2S_EN        ( "DISABLE"            ),

    .C_APPS                ( "DDR_DRAM"           ),
    .C_DATA_WIDTH          ( "X8"                 ),
    .C_IOCLK0D2S_EN        ( "DISABLE"            ),
    .C_IOCLK1D2S_EN        ( "DISABLE"            ),
    .C_IOCLK2D2S_EN        ( "DISABLE"            ),
    .C_IOCLK3D2S_EN        ( "DISABLE"            ),

    .D_APPS                ( "DDR_DRAM"           ),
    .D_DATA_WIDTH          ( "X8"                 ),
    .D_IOCLK0D2S_EN        ( "DISABLE"            ),
    .D_IOCLK1D2S_EN        ( "DISABLE"            ),
    .D_IOCLK2D2S_EN        ( "DISABLE"            ),
    .D_IOCLK3D2S_EN        ( "DISABLE"            ),

    .A_DQS_BYTE_EN         ( T0_BYTE_EN           ),
    .B_DQS_BYTE_EN         ( T1_BYTE_EN           ),
    .C_DQS_BYTE_EN         ( T2_BYTE_EN           ),
    .D_DQS_BYTE_EN         ( T3_BYTE_EN           ),

    .AC_LOOPBACK_EN        ( "DISABLE"  ),
    .BANKREF_EN            ( "ENABLE"   ),
    .DCI_EN                ( "ENABLE"   ),
    .APPS_PZQ              ( "DDR_DRAM" ),
    .ZQ_VALUE              ( 100        ),
    .VREF0_MODE            ( "DDR_DRAM" ),
    .VREF1_RANK0_MODE      ( "DDR_DRAM" ),
    .VREF1_RANK1_MODE      ( "DDR_DRAM" ),
    .VREF2_RANK0_MODE      ( "DDR_DRAM" ),
    .VREF2_RANK1_MODE      ( "DDR_DRAM" ),
    .VREF3_RANK0_MODE      ( "DDR_DRAM" ),
    .VREF3_RANK1_MODE      ( "DDR_DRAM" ),
    .VREF4_RANK0_MODE      ( "DDR_DRAM" ),
    .VREF4_RANK1_MODE      ( "DDR_DRAM" ),
    .VREF1_RANK0_RANG      ( "RANG2"    ),
    .VREF1_RANK1_RANG      ( "RANG2"    ),
    .VREF2_RANK0_RANG      ( "RANG2"    ),
    .VREF2_RANK1_RANG      ( "RANG2"    ),
    .VREF3_RANK0_RANG      ( "RANG2"    ),
    .VREF3_RANK1_RANG      ( "RANG2"    ),
    .VREF4_RANK0_RANG      ( "RANG2"    ),
    .VREF4_RANK1_RANG      ( "RANG2"    ),
    .VREF1_RANK0_VAL       ( 0          ),
    .VREF1_RANK1_VAL       ( 0          ),
    .VREF2_RANK0_VAL       ( 0          ),
    .VREF2_RANK1_VAL       ( 0          ),
    .VREF3_RANK0_VAL       ( 0          ),
    .VREF3_RANK1_VAL       ( 0          ),
    .VREF4_RANK0_VAL       ( 0          ),
    .VREF4_RANK1_VAL       ( 0          ),

    .ODTINIT_VALUE         ( 3'b0       ),
    .ATO                   ( 0          ),
    .VOD                   ( "0MV"      ),
    .LVDSTX_EN             ( "DISABLE"  ),
    .RXCM                  ( "DISABLE"  )

) u_ddrbank (

    

    .clb2phy_vref1                 ( 8'hff                                    ),
    .clb2phy_vref2                 ( 8'hff                                    ),
    .clb2phy_vref3                 ( 8'hff                                    ),
    .clb2phy_vref4                 ( 8'hff                                    ),
    .pzq_ctl_rst_n                 ( pzq_usr_rst_n                            ),
    .pzq_user_clk                  ( pzq_usr_clk                              ),

    .pzq_apb_sync_path_sel         ( 1'b0                                     ),
    .pzq_apb_rst_n                 ( bk_apb_prst_n                            ),
    .pzq_apb_clk                   ( bk_apb_pclk                              ),
    .pzq_apb_sel                   ( bk_apb_psel                              ),
    .pzq_apb_addr                  ( bk_apb_paddr[10:0]                       ),
    .pzq_apb_enable                ( bk_apb_penable                           ),
    .pzq_apb_wdata                 ( bk_apb_pwdata                            ),
    .pzq_apb_wr_rdn                ( bk_apb_pwrite                            ),
    .pzq_apb_rdata                 ( bk_apb_prdata                            ),
    .pzq_apb_rdy                   ( bk_apb_pready                            ),
    .pzq_apb_error                 (                                          ),

    .pzq_atpg_mode                 ( 1'b0                                     ),
    .pzq_scan_clk                  ( 1'b0                                     ),
    .pzq_scan_enable               ( 1'b0                                     ),
    .pzq_scan_in                   ( 2'b0                                     ),
    .pzq_scan_rst_n                ( 1'b1                                     ),
    .pzq_scancompress_mode         ( 1'b0                                     ),
    .pzq_scan_out                  (                                          ),

    .zqcal_clrcfg                  ( zqcal_clear                              ),
    .zqcal_code                    ( {56{1'b1}}                               ),
    .zqcal_start                   ( zqcal_start                              ),
    .zqcal_update_en               ( zqcal_update                             ),
    .zqcal_done                    ( zqcal_done                               ),
    .zqcal_code_o                  (                                          ),  
    .zqcal_debug_data              (                                          ),  
    .zqcal_vt_update_en_in         ( 1'b0                                     ),
    .zqcal_vt_update_en_out        (                                          ),  

    .pzq_vref_value_sel            ( 4'h0                                     ),
    .vref_ctrl_value               ( {56{1'b1}}                               ),

    

    
    .A_user_clk                   ( t0_usr_clk                                ),
    .A_ioclk                      ( t0_ioclk                                  ),
    .A_lclk                       ( 4'b1111                                   ),
    .A_loopback_fifo_rstn_low     ( t0_ac_fifo_rst_n                          ),
    .A_loopback_fifo_rstn_upp     ( t0_dx_fifo_rst_n                          ),
    .A_phy_rstn_low               ( t0_ac_rst_n                               ),
    .A_phy_rstn_upp               ( t0_dx_rst_n                               ),
    .A_dqs_rstn                   ( t0_dqs_rst_n                              ),
    .A_ctl_rst_n                  ( t0_ctl_rst_n                              ),
    .A_ctl_ddr_clk_gate           ( 1'b1                                      ),
    .A_ctl_rdclk_gt               ( 1'b1                                      ),
    .A_ctrlclk_en_gt              ( 1'b1                                      ),

    .A_phy_rd_dqs_pdr             ( t0_ctl_pdr                                ),
    .A_phy_rd_dqs_te              ( t0_ctl_te                                 ),
    .A_phy_wdata_en               ( t0_ctl_ts                                 ),

    .A_loopback_fifo_datain_low   ( 1'b0                                      ),
    .A_loopback_fifo_resp_low     ( 1'b0                                      ),
    .A_loopback_fifo_datain_upp   ( 1'b0                                      ),
    .A_loopback_fifo_resp_upp     ( 1'b0                                      ),

    .A_phy_wdata                  ({t0_ctl_wdata[ 79:64],t0_ctl_wdata[47:0]}  ),
    .A_phy_wr_dqsp                ( t0_ctl_wdata[ 55:48]                      ),
    .A_phy_wr_dqsn                ( t0_ctl_wdata[ 63:56]                      ),
    .A_phy_wr_dm                  ( t0_ctl_wdata[ 87:80]                      ),
    .A_phy_rd_dqs_en_shadow       ( t0_ctl_wdata[ 95:88]                      ),
    .A_phy_wrdata_se              ( t0_ctl_wdata[103:96]                      ),
    .A_phy_rdata                  ({t0_ctl_rdata[ 79:64],t0_ctl_rdata[47:0]}  ),
    .A_phy_rd_dqsp                ( t0_ctl_rdata[ 55:48]                      ),
    .A_phy_rd_dqsn                ( t0_ctl_rdata[ 63:56]                      ),
    .A_phy_rd_dm                  ( t0_ctl_rdata[ 87:80]                      ),
    .A_phy_iogate_rdata           ( t0_ctl_rdata[ 95:88]                      ),
    .A_phy_rdata_se               ( t0_ctl_rdata[103:96]                      ),
    .A_phy_rdata_en               ( t0_ctl_rdata_vld                          ),
    .A_phy_rd_dqs_en              ( t0_ctl_rdqs_gate                          ),
    .A_dqs_valid_sample_window    ( t0_qs_gate                                ),

    .A_dqs_pupd_en                ( t0_dqs_pupd_en                            ),
    .A_wrlvl_mode                 ( t0_wrlvl_mdoe                             ),
    .A_wrlvl_qin                  ( 8'hff                                     ),
    .A_wrlvl_qout                 (                                           ),
    .A_dqs_rd_gate_status         ( t0_dqs_gate_status                        ),
    .A_dqs_rd_gate_status_p       (                                           ),

    .A_dqsgr_apb_sync_path_sel    ( 1'b0                                      ),
    .A_dqsgr_apb_rst_n            ( t0_apb_prst_n                             ),
    .A_dqsgr_apb_clk              ( t0_apb_pclk                               ),
    .A_offcal_psel                ( t0_apb_psel                               ),
    .A_dqsgr_apb_addr             ( t0_apb_paddr[9:0]                         ),
    .A_dqsgr_apb_enable           ( t0_apb_penable                            ),
    .A_dqsgr_apb_wdata            ( t0_apb_pwdata                             ),
    .A_dqsgr_apb_wr_rdn           ( t0_apb_pwrite                             ),
    .A_dqsgr_apb_rdata            ( t0_apb_prdata                             ),
    .A_dqsgr_apb_ready            ( t0_apb_pready                             ),
    .A_dqsgr_apb_error            (                                           ),

    .A_delay_ranksel              ( t0_dcp_rksel                              ),
    .A_delay_sel                  ( t0_dcp_sel                                ),
    .A_delay_paddr                ( t0_dcp_addr                               ),
    .A_delay_data                 ( t0_dcp_data                               ),
    .A_delay_gate                 ( t0_dcp_gate                               ),

    .A_delay_cal_mode             ( t0_cal_mode                               ),
    .A_delay_cal_clk_en           ({t0_cal_clk_en[3], t0_cal_clk_en[6], t0_cal_clk_en[4], t0_cal_clk_en[2], t0_cal_clk_en[1], t0_cal_clk_en[0], t0_cal_clk_en[5]}),
    .A_delay_cal_en_in            ({t0_cal_en    [3], t0_cal_en    [6], t0_cal_en    [4], t0_cal_en    [2], t0_cal_en    [1], t0_cal_en    [0], t0_cal_en    [5]}),
    .A_delay_cal_en_out           ({t0_cal_en_out[3], t0_cal_en_out[6], t0_cal_en_out[4], t0_cal_en_out[2], t0_cal_en_out[1], t0_cal_en_out[0], t0_cal_en_out[5]}),
    .A_delay_cal_value            ({t0_cal_out   [3], t0_cal_out   [6], t0_cal_out   [4], t0_cal_out   [2], t0_cal_out   [1], t0_cal_out   [0], t0_cal_out   [5]}),

    .A_dcc_clrcfg                 ( t0_dcc_clear                              ),
    .A_dcc_start                  ( t0_dcc_start                              ),
    .A_dcc_cfg_done               ( t0_dcc_done                               ),
    .A_dcc_update_en_in           ( 1'b0                                      ),
    .A_dcc_vt_update_en_in        ( 1'b0                                      ),
    .A_dcc_vt_update_en_out       (                                           ), 

    .A_delay_testmode_en          ( 1'b0                                      ),
    .A_delay_osc_div              ( 4'hf                                      ),
    .A_delay_osc_en               ( 1'b0                                      ),
    .A_delay_osc_wdq_sel          ( 2'b11                                     ),
    .A_delay_osc_wrlvl_sel        ( 2'b11                                     ),
    .A_delay_dto                  (                                           ),

    .A_loopback_mode              ( 1'b1                                      ),
    .A_phy_loopback_en            ( t0_lb_en                                  ),
    .A_loopback_clknum_sel        ( 2'b11                                     ),
    .A_loopback_clk_sel           ( 2'b11                                     ),

    .A_dqsgr_atpg_mode            (  1'b0                                     ),
    .A_dqsgr_scan_rst_n           (  1'b1                                     ),
    .A_dqsgr_scan_clk             (  1'b0                                     ),
    .A_dqsgr_scan_enable          (  1'b0                                     ),
    .A_dqsgr_scan_in              (  3'b0                                     ),
    .A_dqsgr_scancompress_mode    (  1'b0                                     ),
    .A_dqsgr_scan_out             (                                           ),

    .A_offcal_clrcfg              ( 1'b0                                      ), 
    .A_offcal_start               ( 1'b0                                      ), 
    .A_offcal_update_en           ( 1'b0                                      ), 
    .A_offcal_done                (                                           ), 
    .A_offcal_vt_update_en_in     ( 1'b0                                      ), 
    .A_offcal_vt_update_en_out    (                                           ), 

    .A_age_toggle_en              ( 1'b0                                      ),
    .A_age_toggle_inv             ( 1'b0                                      ),
    .A_dfi_io_pd                  ( 1'b0                                      ),
    .A_phy_dqs_cnt                ( t0_dqsn_cnt                               ),
    .A_debug_data                 ( t0_o_debug                                ),

    

    
    .A_ctl_clk_ac                 ( t0_phy_ctlclk_ac                          ),
    .A_ctl_clk_dqs                ( t0_phy_ctlclk_dqs                         ),
    .A_ctl_clk_wdq                ( t0_phy_ctlclk_wdq                         ),
    .A_ddr_clk_ac                 ( t0_phy_ddrclk_ac                          ),
    .A_ddr_clk_dqs                ( t0_phy_ddrclk_dqs                         ),
    .A_ddr_clk_wdq                ( t0_phy_ddrclk_wdq                         ),
    .A_ctl_phy_clk                ( t0_phy_phyclk                             ),
    .A_wr_path_rstn_low           ( t0_phy_ac_wr_rst_n                        ),
    .A_wr_path_rstn_upp           ( t0_phy_dx_wr_rst_n                        ),
    .A_rd_path_rstn_low           ( t0_phy_ac_rd_rst_n                        ),
    .A_rd_path_rstn_upp           ( t0_phy_dx_rd_rst_n                        ),

    .A_diq                        ({t0_phy_rdata[95:0], t0_phy_rdata[103:96]} ),
    .A_doq                        ({t0_phy_wdata[95:64],t0_phy_wdata[47:0]}   ),
    .A_dosp                       ( t0_phy_wdata[ 55:48]                      ),
    .A_dosn                       ( t0_phy_wdata[ 63:56]                      ),
    .A_doq_se                     ( t0_phy_wdata[103:96]                      ),

    .A_rdqs_in                    ( t0_phy_rdqs_p                             ),
    .A_rdqs_n_in                  ( t0_phy_rdqs_n                             ),
    .A_rdqs                       ( t0_phy_rdqs_o                             ),
    .A_rdqs_n_gated               ( t0_phy_rdqs_gate                          ),

    .A_dq_ts_md                   ({t0_phy_oe_md_int [21:14], t0_phy_oe_md_int[11:0]}  ),
    .A_dqs_ts_md                  ( t0_phy_oe_md_int [13:12]                           ),
    .A_dq_se_ts_md                ( t0_phy_oe_md_int [23:22]                           ),
    .A_dq_te_md                   ({t0_phy_te_md_int [21:14], t0_phy_te_md_int[11:0]}  ),
    .A_dqs_te_md                  ( t0_phy_te_md_int [13:12]                           ),
    .A_dq_se_te_md                ( t0_phy_te_md_int [23:22]                           ),
    .A_dq_pdr_md                  ({t0_phy_pdr_md_int[21:14], t0_phy_pdr_md_int[11:0]} ),
    .A_dqs_pdr_md                 ( t0_phy_pdr_md_int[13:12]                           ),
    .A_dq_se_pdr_md               ( t0_phy_pdr_md_int[23:22]                           ),
    .A_ts_dq                      ( t0_phy_oe_dq                              ),
    .A_ts_dqs                     ( t0_phy_oe_dqs                             ),
    .A_ts_dqsn                    ( t0_phy_oe_dqsn                            ),
    .A_te_dq                      ( t0_phy_te_dq                              ),
    .A_te_dqs                     ( t0_phy_te_dqs                             ),
    .A_te_dqsn                    ( t0_phy_te_dqsn                            ),
    .A_pdr                        ( t0_phy_pdr_dq                             ),
    .A_pdr_dqs                    ( t0_phy_pdr_dqs                            ),
    .A_pdr_dqsn                   ( t0_phy_pdr_dqsn                           ),

    .A_in_bdl_dly                 ({t0_phy_rd_bdl_dly[8*6  +: 4*6], t0_phy_rd_bdl_dly[0 +: 6*6]}  ),
    .A_in_dqsn_bdl_dly            ( t0_phy_rd_bdl_dly[7*6  +:   6]                                ),
    .A_in_dqsp_bdl_dly            ( t0_phy_rd_bdl_dly[6*6  +:   6]                                ),
    .A_in_se_bdl_dly              ( t0_phy_rd_bdl_dly[12*6 +:   6]                                ),
    .A_in_bdl_byp                 ({t0_phy_rd_bdl_byp[8    +:   4], t0_phy_rd_bdl_byp[0 +:   6]}  ),
    .A_in_dqsn_bdl_byp            ( t0_phy_rd_bdl_byp[7]                                          ),
    .A_in_dqsp_bdl_byp            ( t0_phy_rd_bdl_byp[6]                                          ),
    .A_in_se_bdl_byp              ( t0_phy_rd_bdl_byp[12]                                         ),
    .A_out_bdl_dly                ({t0_phy_wr_bdl_dly[8*6  +: 4*6], t0_phy_wr_bdl_dly[0 +: 6*6]}  ),
    .A_out_dqsn_bdl_dly           ( t0_phy_wr_bdl_dly[7*6  +:   6]                                ),
    .A_out_dqsp_bdl_dly           ( t0_phy_wr_bdl_dly[6*6  +:   6]                                ),
    .A_out_se_bdl_dly             ( t0_phy_wr_bdl_dly[12*6 +:   6]                                ),
    .A_out_bdl_byp                ({t0_phy_wr_bdl_byp[8    +:   4], t0_phy_wr_bdl_byp[0 +:   6]}  ),
    .A_out_dqsn_bdl_byp           ( t0_phy_wr_bdl_byp[7]                                          ),
    .A_out_dqsp_bdl_byp           ( t0_phy_wr_bdl_byp[6]                                          ),
    .A_out_se_bdl_byp             ( t0_phy_wr_bdl_byp[12]                                         ),

    

    
    .B_user_clk                   ( t1_usr_clk                                ),
    .B_ioclk                      ( t1_ioclk                                  ),
    .B_lclk                       ( 4'b0                                      ),
    .B_loopback_fifo_rstn_low     ( t1_ac_fifo_rst_n                          ),
    .B_loopback_fifo_rstn_upp     ( t1_dx_fifo_rst_n                          ),
    .B_phy_rstn_low               ( t1_ac_rst_n                               ),
    .B_phy_rstn_upp               ( t1_dx_rst_n                               ),
    .B_dqs_rstn                   ( t1_dqs_rst_n                              ),
    .B_ctl_rst_n                  ( t1_ctl_rst_n                              ),
    .B_ctl_ddr_clk_gate           ( 1'b1                                      ),
    .B_ctl_rdclk_gt               ( 1'b1                                      ),
    .B_ctrlclk_en_gt              ( 1'b1                                      ),

    .B_phy_rd_dqs_pdr             ( t1_ctl_pdr                                ),
    .B_phy_rd_dqs_te              ( t1_ctl_te                                 ),
    .B_phy_wdata_en               ( t1_ctl_ts                                 ),

    .B_loopback_fifo_datain_low   ( 1'b0                                      ),
    .B_loopback_fifo_resp_low     ( 1'b0                                      ),
    .B_loopback_fifo_datain_upp   ( 1'b0                                      ),
    .B_loopback_fifo_resp_upp     ( 1'b0                                      ),

    .B_phy_wdata                  ({t1_ctl_wdata[ 79:64], t1_ctl_wdata[47:0]} ),
    .B_phy_wr_dqsp                ( t1_ctl_wdata[ 55:48]                      ),
    .B_phy_wr_dqsn                ( t1_ctl_wdata[ 63:56]                      ),
    .B_phy_wr_dm                  ( t1_ctl_wdata[ 87:80]                      ),
    .B_phy_rd_dqs_en_shadow       ( t1_ctl_wdata[ 95:88]                      ),
    .B_phy_rdata                  ({t1_ctl_rdata[ 79:64], t1_ctl_rdata[47:0]} ),
    .B_phy_rd_dqsp                ( t1_ctl_rdata[ 55:48]                      ),
    .B_phy_rd_dqsn                ( t1_ctl_rdata[ 63:56]                      ),
    .B_phy_rd_dm                  ( t1_ctl_rdata[ 87:80]                      ),
    .B_phy_iogate_rdata           ( t1_ctl_rdata[ 95:88]                      ),
    .B_phy_rdata_en               ( t1_ctl_rdata_vld                          ),
    .B_phy_rd_dqs_en              ( t1_ctl_rdqs_gate                          ),
    .B_dqs_valid_sample_window    ( t1_qs_gate                                ),

    .B_dqs_pupd_en                ( t1_dqs_pupd_en                            ),
    .B_wrlvl_mode                 ( t1_wrlvl_mdoe                             ),
    .B_wrlvl_qin                  ( 8'hff                                     ),
    .B_wrlvl_qout                 (                                           ),
    .B_dqs_rd_gate_status         ( t1_dqs_gate_status                        ),
    .B_dqs_rd_gate_status_p       (                                           ),

    .B_dqsgr_apb_sync_path_sel    ( 1'b0                                      ),
    .B_dqsgr_apb_rst_n            ( t1_apb_prst_n                             ),
    .B_dqsgr_apb_clk              ( t1_apb_pclk                               ),
    .B_offcal_psel                ( t1_apb_psel                               ),
    .B_dqsgr_apb_addr             ( t1_apb_paddr[9:0]                         ),
    .B_dqsgr_apb_enable           ( t1_apb_penable                            ),
    .B_dqsgr_apb_wdata            ( t1_apb_pwdata                             ),
    .B_dqsgr_apb_wr_rdn           ( t1_apb_pwrite                             ),
    .B_dqsgr_apb_rdata            ( t1_apb_prdata                             ),
    .B_dqsgr_apb_ready            ( t1_apb_pready                             ),
    .B_dqsgr_apb_error            (                                           ),

    .B_delay_ranksel              ( t1_dcp_rksel                              ),
    .B_delay_sel                  ( t1_dcp_sel                                ),
    .B_delay_paddr                ( t1_dcp_addr                               ),
    .B_delay_data                 ( t1_dcp_data                               ),
    .B_delay_gate                 ( t1_dcp_gate                               ),

    .B_delay_cal_mode             ( t1_cal_mode                               ),
    .B_delay_cal_clk_en           ({t1_cal_clk_en[3], t1_cal_clk_en[6], t1_cal_clk_en[4], t1_cal_clk_en[2], t1_cal_clk_en[1], t1_cal_clk_en[0], t1_cal_clk_en[5]}),
    .B_delay_cal_en_in            ({t1_cal_en    [3], t1_cal_en    [6], t1_cal_en    [4], t1_cal_en    [2], t1_cal_en    [1], t1_cal_en    [0], t1_cal_en    [5]}),
    .B_delay_cal_en_out           ({t1_cal_en_out[3], t1_cal_en_out[6], t1_cal_en_out[4], t1_cal_en_out[2], t1_cal_en_out[1], t1_cal_en_out[0], t1_cal_en_out[5]}),
    .B_delay_cal_value            ({t1_cal_out   [3], t1_cal_out   [6], t1_cal_out   [4], t1_cal_out   [2], t1_cal_out   [1], t1_cal_out   [0], t1_cal_out   [5]}),

    .B_dcc_clrcfg                 ( t1_dcc_clear                              ),
    .B_dcc_start                  ( t1_dcc_start                              ),
    .B_dcc_cfg_done               ( t1_dcc_done                               ),
    .B_dcc_update_en_in           ( 1'b0                                      ),
    .B_dcc_vt_update_en_in        ( 1'b0                                      ),
    .B_dcc_vt_update_en_out       (                                           ), 

    .B_delay_testmode_en          ( 1'b0                                      ),
    .B_delay_osc_div              ( 4'hf                                      ),
    .B_delay_osc_en               ( 1'b0                                      ),
    .B_delay_osc_wdq_sel          ( 2'b11                                     ),
    .B_delay_osc_wrlvl_sel        ( 2'b11                                     ),
    .B_delay_dto                  (                                           ),

    .B_loopback_mode              ( 1'b1                                      ),
    .B_phy_loopback_en            ( t1_lb_en                                  ),
    .B_loopback_clknum_sel        ( 2'b11                                     ),
    .B_loopback_clk_sel           ( 2'b11                                     ),

    .B_dqsgr_atpg_mode            ( 1'b0                                      ),
    .B_dqsgr_scan_rst_n           ( 1'b1                                      ),
    .B_dqsgr_scan_clk             ( 1'b0                                      ),
    .B_dqsgr_scan_enable          ( 1'b0                                      ),
    .B_dqsgr_scan_in              ( 3'b0                                      ),
    .B_dqsgr_scancompress_mode    ( 1'b0                                      ),
    .B_dqsgr_scan_out             (                                           ),

    .B_offcal_clrcfg              ( 1'b0                                      ), 
    .B_offcal_start               ( 1'b0                                      ), 
    .B_offcal_update_en           ( 1'b0                                      ), 
    .B_offcal_done                (                                           ), 
    .B_offcal_vt_update_en_in     ( 1'b0                                      ), 
    .B_offcal_vt_update_en_out    (                                           ), 

    .B_age_toggle_en              ( 1'b0                                      ),
    .B_age_toggle_inv             ( 1'b0                                      ),
    .B_dfi_io_pd                  ( 1'b0                                      ),
    .B_phy_dqs_cnt                ( t1_dqsn_cnt                               ),
    .B_debug_data                 ( t1_o_debug                                ),

    

    
    .B_ctl_clk_ac                 ( t1_phy_ctlclk_ac                          ),
    .B_ctl_clk_dqs                ( t1_phy_ctlclk_dqs                         ),
    .B_ctl_clk_wdq                ( t1_phy_ctlclk_wdq                         ),
    .B_ddr_clk_ac                 ( t1_phy_ddrclk_ac                          ),
    .B_ddr_clk_dqs                ( t1_phy_ddrclk_dqs                         ),
    .B_ddr_clk_wdq                ( t1_phy_ddrclk_wdq                         ),
    .B_ctl_phy_clk                ( t1_phy_phyclk                             ),
    .B_wr_path_rstn_low           ( t1_phy_ac_wr_rst_n                        ),
    .B_wr_path_rstn_upp           ( t1_phy_dx_wr_rst_n                        ),
    .B_rd_path_rstn_low           ( t1_phy_ac_rd_rst_n                        ),
    .B_rd_path_rstn_upp           ( t1_phy_dx_rd_rst_n                        ),

    .B_diq                        ( t1_phy_rdata[ 95: 0]                      ),
    .B_doq                        ({t1_phy_wdata[ 95:64], t1_phy_wdata[47:0]} ),
    .B_dosp                       ( t1_phy_wdata[ 55:48]                      ),
    .B_dosn                       ( t1_phy_wdata[ 63:56]                      ),

    .B_rdqs_in                    ( t1_phy_rdqs_p                             ),
    .B_rdqs_n_in                  ( t1_phy_rdqs_n                             ),
    .B_rdqs                       ( t1_phy_rdqs_o                             ),
    .B_rdqs_n_gated               ( t1_phy_rdqs_gate                          ),

    .B_dq_ts_md                   ({t1_phy_oe_md_int [21:14], t1_phy_oe_md_int[11:0]}  ),
    .B_dqs_ts_md                  ( t1_phy_oe_md_int [13:12]                           ),
    .B_dq_te_md                   ({t1_phy_te_md_int [21:14], t1_phy_te_md_int[11:0]}  ),
    .B_dqs_te_md                  ( t1_phy_te_md_int [13:12]                           ),
    .B_dq_pdr_md                  ({t1_phy_pdr_md_int[21:14], t1_phy_pdr_md_int[11:0]} ),
    .B_dqs_pdr_md                 ( t1_phy_pdr_md_int[13:12]                           ),
    .B_ts_dq                      ( t1_phy_oe_dq                              ),
    .B_ts_dqs                     ( t1_phy_oe_dqs                             ),
    .B_ts_dqsn                    ( t1_phy_oe_dqsn                            ),
    .B_te_dq                      ( t1_phy_te_dq                              ),
    .B_te_dqs                     ( t1_phy_te_dqs                             ),
    .B_te_dqsn                    ( t1_phy_te_dqsn                            ),
    .B_pdr                        ( t1_phy_pdr_dq                             ),
    .B_pdr_dqs                    ( t1_phy_pdr_dqs                            ),
    .B_pdr_dqsn                   ( t1_phy_pdr_dqsn                           ),

    .B_in_bdl_dly                 ({t1_phy_rd_bdl_dly[8*6  +: 4*6], t1_phy_rd_bdl_dly[0 +: 6*6]} ),
    .B_in_dqsn_bdl_dly            ( t1_phy_rd_bdl_dly[7*6  +:   6]                               ),
    .B_in_dqsp_bdl_dly            ( t1_phy_rd_bdl_dly[6*6  +:   6]                               ),
    .B_in_bdl_byp                 ({t1_phy_rd_bdl_byp[8    +:   4], t1_phy_rd_bdl_byp[0 +:   6]} ),
    .B_in_dqsn_bdl_byp            ( t1_phy_rd_bdl_byp[7]                                         ),
    .B_in_dqsp_bdl_byp            ( t1_phy_rd_bdl_byp[6]                                         ),
    .B_out_bdl_dly                ({t1_phy_wr_bdl_dly[8*6  +: 4*6], t1_phy_wr_bdl_dly[0 +: 6*6]} ),
    .B_out_dqsn_bdl_dly           ( t1_phy_wr_bdl_dly[7*6  +:   6]                               ),
    .B_out_dqsp_bdl_dly           ( t1_phy_wr_bdl_dly[6*6  +:   6]                               ),
    .B_out_bdl_byp                ({t1_phy_wr_bdl_byp[8    +:   4], t1_phy_wr_bdl_byp[0 +:   6]} ),
    .B_out_dqsn_bdl_byp           ( t1_phy_wr_bdl_byp[7]                                         ),
    .B_out_dqsp_bdl_byp           ( t1_phy_wr_bdl_byp[6]                                         ),

    

    
    .C_user_clk                   ( t2_usr_clk                                ),
    .C_ioclk                      ( t2_ioclk                                  ),
    .C_lclk                       ( 4'h0                                      ),
    .C_loopback_fifo_rstn_low     ( t2_ac_fifo_rst_n                          ),
    .C_loopback_fifo_rstn_upp     ( t2_dx_fifo_rst_n                          ),
    .C_phy_rstn_low               ( t2_ac_rst_n                               ),
    .C_phy_rstn_upp               ( t2_dx_rst_n                               ),
    .C_dqs_rstn                   ( t2_dqs_rst_n                              ),
    .C_ctl_rst_n                  ( t2_ctl_rst_n                              ),
    .C_ctl_ddr_clk_gate           ( 1'b1                                      ),
    .C_ctl_rdclk_gt               ( 1'b1                                      ),
    .C_ctrlclk_en_gt              ( 1'b1                                      ),

    .C_phy_rd_dqs_pdr             ( t2_ctl_pdr                                ),
    .C_phy_rd_dqs_te              ( t2_ctl_te                                 ),
    .C_phy_wdata_en               ( t2_ctl_ts                                 ),

    .C_loopback_fifo_datain_low   ( 1'b0                                      ),
    .C_loopback_fifo_resp_low     ( 1'b0                                      ),
    .C_loopback_fifo_datain_upp   ( 1'b0                                      ),
    .C_loopback_fifo_resp_upp     ( 1'b0                                      ),

    .C_phy_wdata                  ({t2_ctl_wdata[79:64], t2_ctl_wdata[47:0]} ),
    .C_phy_wr_dqsp                ( t2_ctl_wdata[55:48]                      ),
    .C_phy_wr_dqsn                ( t2_ctl_wdata[63:56]                      ),
    .C_phy_wr_dm                  ( t2_ctl_wdata[87:80]                      ),
    .C_phy_rd_dqs_en_shadow       ( t2_ctl_wdata[95:88]                      ),
    .C_phy_rdata                  ({t2_ctl_rdata[79:64], t2_ctl_rdata[47:0]} ),
    .C_phy_rd_dqsp                ( t2_ctl_rdata[55:48]                      ),
    .C_phy_rd_dqsn                ( t2_ctl_rdata[63:56]                      ),
    .C_phy_rd_dm                  ( t2_ctl_rdata[87:80]                      ),
    .C_phy_iogate_rdata           ( t2_ctl_rdata[95:88]                      ),
    .C_phy_rdata_en               ( t2_ctl_rdata_vld                          ),
    .C_phy_rd_dqs_en              ( t2_ctl_rdqs_gate                          ),
    .C_dqs_valid_sample_window    ( t2_qs_gate                                ),

    .C_dqs_pupd_en                ( t2_dqs_pupd_en                            ),
    .C_wrlvl_mode                 ( t2_wrlvl_mdoe                             ),
    .C_wrlvl_qin                  ( 8'hff                                     ),
    .C_wrlvl_qout                 (                                           ),
    .C_dqs_rd_gate_status         ( t2_dqs_gate_status                        ),
    .C_dqs_rd_gate_status_p       (                                           ),

    .C_dqsgr_apb_sync_path_sel    ( 1'b0                                      ),
    .C_dqsgr_apb_rst_n            ( t2_apb_prst_n                             ),
    .C_dqsgr_apb_clk              ( t2_apb_pclk                               ),
    .C_offcal_psel                ( t2_apb_psel                               ),
    .C_dqsgr_apb_addr             ( t2_apb_paddr[9:0]                         ),
    .C_dqsgr_apb_enable           ( t2_apb_penable                            ),
    .C_dqsgr_apb_wdata            ( t2_apb_pwdata                             ),
    .C_dqsgr_apb_wr_rdn           ( t2_apb_pwrite                             ),
    .C_dqsgr_apb_rdata            ( t2_apb_prdata                             ),
    .C_dqsgr_apb_ready            ( t2_apb_pready                             ),
    .C_dqsgr_apb_error            (                                           ),

    .C_delay_ranksel              ( t2_dcp_rksel                              ),
    .C_delay_sel                  ( t2_dcp_sel                                ),
    .C_delay_paddr                ( t2_dcp_addr                               ),
    .C_delay_data                 ( t2_dcp_data                               ),
    .C_delay_gate                 ( t2_dcp_gate                               ),

    .C_delay_cal_mode             ( t2_cal_mode                               ),
    .C_delay_cal_clk_en           ({t2_cal_clk_en[3], t2_cal_clk_en[6], t2_cal_clk_en[4], t2_cal_clk_en[2], t2_cal_clk_en[1], t2_cal_clk_en[0], t2_cal_clk_en[5]}),
    .C_delay_cal_en_in            ({t2_cal_en    [3], t2_cal_en    [6], t2_cal_en    [4], t2_cal_en    [2], t2_cal_en    [1], t2_cal_en    [0], t2_cal_en    [5]}),
    .C_delay_cal_en_out           ({t2_cal_en_out[3], t2_cal_en_out[6], t2_cal_en_out[4], t2_cal_en_out[2], t2_cal_en_out[1], t2_cal_en_out[0], t2_cal_en_out[5]}),
    .C_delay_cal_value            ({t2_cal_out   [3], t2_cal_out   [6], t2_cal_out   [4], t2_cal_out   [2], t2_cal_out   [1], t2_cal_out   [0], t2_cal_out   [5]}),

    .C_dcc_clrcfg                 ( t2_dcc_clear                              ),
    .C_dcc_start                  ( t2_dcc_start                              ),
    .C_dcc_cfg_done               ( t2_dcc_done                               ),
    .C_dcc_update_en_in           ( 1'b0                                      ),
    .C_dcc_vt_update_en_in        ( 1'b0                                      ),
    .C_dcc_vt_update_en_out       (                                           ), 

    .C_delay_testmode_en          ( 1'b0                                      ),
    .C_delay_osc_div              ( 4'hf                                      ),
    .C_delay_osc_en               ( 1'b0                                      ),
    .C_delay_osc_wdq_sel          ( 2'b11                                     ),
    .C_delay_osc_wrlvl_sel        ( 2'b11                                     ),
    .C_delay_dto                  (                                           ),

    .C_loopback_mode              ( 1'b1                                      ),
    .C_phy_loopback_en            ( t2_lb_en                                  ),
    .C_loopback_clknum_sel        ( 2'b11                                     ),
    .C_loopback_clk_sel           ( 2'b11                                     ),

    .C_dqsgr_atpg_mode            ( 1'b0                                      ),
    .C_dqsgr_scan_rst_n           ( 1'b1                                      ),
    .C_dqsgr_scan_clk             ( 1'b0                                      ),
    .C_dqsgr_scan_enable          ( 1'b0                                      ),
    .C_dqsgr_scan_in              ( 3'b0                                      ),
    .C_dqsgr_scancompress_mode    ( 1'b0                                      ),
    .C_dqsgr_scan_out             (                                           ),

    .C_offcal_clrcfg              ( 1'b0                                      ), 
    .C_offcal_start               ( 1'b0                                      ), 
    .C_offcal_update_en           ( 1'b0                                      ), 
    .C_offcal_done                (                                           ), 
    .C_offcal_vt_update_en_in     ( 1'b0                                      ), 
    .C_offcal_vt_update_en_out    (                                           ), 

    .C_age_toggle_en              ( 1'b0                                      ),
    .C_age_toggle_inv             ( 1'b0                                      ),
    .C_dfi_io_pd                  ( 1'b0                                      ),
    .C_phy_dqs_cnt                ( t2_dqsn_cnt                               ),
    .C_debug_data                 ( t2_o_debug                                ),

    

    
    .C_ctl_clk_ac                 ( t2_phy_ctlclk_ac                          ),
    .C_ctl_clk_dqs                ( t2_phy_ctlclk_dqs                         ),
    .C_ctl_clk_wdq                ( t2_phy_ctlclk_wdq                         ),
    .C_ddr_clk_ac                 ( t2_phy_ddrclk_ac                          ),
    .C_ddr_clk_dqs                ( t2_phy_ddrclk_dqs                         ),
    .C_ddr_clk_wdq                ( t2_phy_ddrclk_wdq                         ),
    .C_ctl_phy_clk                ( t2_phy_phyclk                             ),
    .C_wr_path_rstn_low           ( t2_phy_ac_wr_rst_n                        ),
    .C_wr_path_rstn_upp           ( t2_phy_dx_wr_rst_n                        ),
    .C_rd_path_rstn_low           ( t2_phy_ac_rd_rst_n                        ),
    .C_rd_path_rstn_upp           ( t2_phy_dx_rd_rst_n                        ),

    .C_diq                        ( t2_phy_rdata[ 95: 0]                      ),
    .C_doq                        ({t2_phy_wdata[ 95:64], t2_phy_wdata[47:0]} ),
    .C_dosp                       ( t2_phy_wdata[ 55:48]                      ),
    .C_dosn                       ( t2_phy_wdata[ 63:56]                      ),

    .C_rdqs_in                    ( t2_phy_rdqs_p                             ),
    .C_rdqs_n_in                  ( t2_phy_rdqs_n                             ),
    .C_rdqs                       ( t2_phy_rdqs_o                             ),
    .C_rdqs_n_gated               ( t2_phy_rdqs_gate                          ),

    .C_dq_ts_md                   ({t2_phy_oe_md_int [21:14], t2_phy_oe_md_int[11:0]}  ),
    .C_dqs_ts_md                  ( t2_phy_oe_md_int [13:12]                           ),
    .C_dq_te_md                   ({t2_phy_te_md_int [21:14], t2_phy_te_md_int[11:0]}  ),
    .C_dqs_te_md                  ( t2_phy_te_md_int [13:12]                           ),
    .C_dq_pdr_md                  ({t2_phy_pdr_md_int[21:14], t2_phy_pdr_md_int[11:0]} ),
    .C_dqs_pdr_md                 ( t2_phy_pdr_md_int[13:12]                           ),
    .C_ts_dq                      ( t2_phy_oe_dq                              ),
    .C_ts_dqs                     ( t2_phy_oe_dqs                             ),
    .C_ts_dqsn                    ( t2_phy_oe_dqsn                            ),
    .C_te_dq                      ( t2_phy_te_dq                              ),
    .C_te_dqs                     ( t2_phy_te_dqs                             ),
    .C_te_dqsn                    ( t2_phy_te_dqsn                            ),
    .C_pdr                        ( t2_phy_pdr_dq                             ),
    .C_pdr_dqs                    ( t2_phy_pdr_dqs                            ),
    .C_pdr_dqsn                   ( t2_phy_pdr_dqsn                           ),

    .C_in_bdl_dly                 ({t2_phy_rd_bdl_dly[8*6  +: 4*6], t2_phy_rd_bdl_dly[0 +: 6*6]} ),
    .C_in_dqsn_bdl_dly            ( t2_phy_rd_bdl_dly[7*6  +:   6]                               ),
    .C_in_dqsp_bdl_dly            ( t2_phy_rd_bdl_dly[6*6  +:   6]                               ),
    .C_in_bdl_byp                 ({t2_phy_rd_bdl_byp[8    +:   4], t2_phy_rd_bdl_byp[0 +:   6]} ),
    .C_in_dqsn_bdl_byp            ( t2_phy_rd_bdl_byp[7]                                         ),
    .C_in_dqsp_bdl_byp            ( t2_phy_rd_bdl_byp[6]                                         ),
    .C_out_bdl_dly                ({t2_phy_wr_bdl_dly[8*6  +: 4*6], t2_phy_wr_bdl_dly[0 +: 6*6]} ),
    .C_out_dqsn_bdl_dly           ( t2_phy_wr_bdl_dly[7*6  +:   6]                               ),
    .C_out_dqsp_bdl_dly           ( t2_phy_wr_bdl_dly[6*6  +:   6]                               ),
    .C_out_bdl_byp                ({t2_phy_wr_bdl_byp[8    +:   4], t2_phy_wr_bdl_byp[0 +:   6]} ),
    .C_out_dqsn_bdl_byp           ( t2_phy_wr_bdl_byp[7]                                         ),
    .C_out_dqsp_bdl_byp           ( t2_phy_wr_bdl_byp[6]                                         ),

    

    
    .D_user_clk                   ( t3_usr_clk                                ),
    .D_ioclk                      ( t3_ioclk                                  ),
    .D_lclk                       ( 4'h0                                      ),
    .D_loopback_fifo_rstn_low     ( t3_ac_fifo_rst_n                          ),
    .D_loopback_fifo_rstn_upp     ( t3_dx_fifo_rst_n                          ),
    .D_phy_rstn_low               ( t3_ac_rst_n                               ),
    .D_phy_rstn_upp               ( t3_dx_rst_n                               ),
    .D_dqs_rstn                   ( t3_dqs_rst_n                              ),
    .D_ctl_rst_n                  ( t3_ctl_rst_n                              ),
    .D_ctl_ddr_clk_gate           ( 1'b1                                      ),
    .D_ctl_rdclk_gt               ( 1'b1                                      ),
    .D_ctrlclk_en_gt              ( 1'b1                                      ),

    .D_phy_rd_dqs_pdr             ( t3_ctl_pdr                                ),
    .D_phy_rd_dqs_te              ( t3_ctl_te                                 ),
    .D_phy_wdata_en               ( t3_ctl_ts                                 ),

    .D_loopback_fifo_datain_low   ( 1'b0                                      ),
    .D_loopback_fifo_resp_low     ( 1'b0                                      ),
    .D_loopback_fifo_datain_upp   ( 1'b0                                      ),
    .D_loopback_fifo_resp_upp     ( 1'b0                                      ),

    .D_phy_wdata                  ({t3_ctl_wdata[ 79:64], t3_ctl_wdata[47:0]} ),
    .D_phy_wr_dqsp                ( t3_ctl_wdata[ 55:48]                      ),
    .D_phy_wr_dqsn                ( t3_ctl_wdata[ 63:56]                      ),
    .D_phy_wr_dm                  ( t3_ctl_wdata[ 87:80]                      ),
    .D_phy_rd_dqs_en_shadow       ( t3_ctl_wdata[ 95:88]                      ),
    .D_phy_wrdata_se              ( t3_ctl_wdata[103:96]                      ),
    .D_phy_rdata                  ({t3_ctl_rdata[ 79:64], t3_ctl_rdata[47:0]} ),
    .D_phy_rd_dqsp                ( t3_ctl_rdata[ 55:48]                      ),
    .D_phy_rd_dqsn                ( t3_ctl_rdata[ 63:56]                      ),
    .D_phy_rd_dm                  ( t3_ctl_rdata[ 87:80]                      ),
    .D_phy_iogate_rdata           ( t3_ctl_rdata[ 95:88]                      ),
    .D_phy_rdata_se               ( t3_ctl_rdata[103:96]                      ),
    .D_phy_rdata_en               ( t3_ctl_rdata_vld                          ),
    .D_phy_rd_dqs_en              ( t3_ctl_rdqs_gate                          ),
    .D_dqs_valid_sample_window    ( t3_qs_gate                                ),

    .D_dqs_pupd_en                ( t3_dqs_pupd_en                            ),
    .D_wrlvl_mode                 ( t3_wrlvl_mdoe                             ),
    .D_wrlvl_qin                  ( 8'hff                                     ),
    .D_wrlvl_qout                 (                                           ),
    .D_dqs_rd_gate_status         ( t3_dqs_gate_status                        ),
    .D_dqs_rd_gate_status_p       (                                           ),

    .D_dqsgr_apb_sync_path_sel    ( 1'b0                                      ),
    .D_dqsgr_apb_rst_n            ( t3_apb_prst_n                             ),
    .D_dqsgr_apb_clk              ( t3_apb_pclk                               ),
    .D_offcal_psel                ( t3_apb_psel                               ),
    .D_dqsgr_apb_addr             ( t3_apb_paddr[9:0]                         ),
    .D_dqsgr_apb_enable           ( t3_apb_penable                            ),
    .D_dqsgr_apb_wdata            ( t3_apb_pwdata                             ),
    .D_dqsgr_apb_wr_rdn           ( t3_apb_pwrite                             ),
    .D_dqsgr_apb_rdata            ( t3_apb_prdata                             ),
    .D_dqsgr_apb_ready            ( t3_apb_pready                             ),
    .D_dqsgr_apb_error            (                                           ),

    .D_delay_ranksel              ( t3_dcp_rksel                              ),
    .D_delay_sel                  ( t3_dcp_sel                                ),
    .D_delay_paddr                ( t3_dcp_addr                               ),
    .D_delay_data                 ( t3_dcp_data                               ),
    .D_delay_gate                 ( t3_dcp_gate                               ),

    .D_delay_cal_mode             ( t3_cal_mode                               ),
    .D_delay_cal_clk_en           ({t3_cal_clk_en[3], t3_cal_clk_en[6], t3_cal_clk_en[4], t3_cal_clk_en[2], t3_cal_clk_en[1], t3_cal_clk_en[0], t3_cal_clk_en[5]}),
    .D_delay_cal_en_in            ({t3_cal_en    [3], t3_cal_en    [6], t3_cal_en    [4], t3_cal_en    [2], t3_cal_en    [1], t3_cal_en    [0], t3_cal_en    [5]}),
    .D_delay_cal_en_out           ({t3_cal_en_out[3], t3_cal_en_out[6], t3_cal_en_out[4], t3_cal_en_out[2], t3_cal_en_out[1], t3_cal_en_out[0], t3_cal_en_out[5]}),
    .D_delay_cal_value            ({t3_cal_out   [3], t3_cal_out   [6], t3_cal_out   [4], t3_cal_out   [2], t3_cal_out   [1], t3_cal_out   [0], t3_cal_out   [5]}),

    .D_dcc_clrcfg                 ( t3_dcc_clear                              ),
    .D_dcc_start                  ( t3_dcc_start                              ),
    .D_dcc_cfg_done               ( t3_dcc_done                               ),
    .D_dcc_update_en_in           ( 1'b0                                      ),
    .D_dcc_vt_update_en_in        ( 1'b0                                      ),
    .D_dcc_vt_update_en_out       (                                           ), 

    .D_delay_testmode_en          ( 1'b0                                      ),
    .D_delay_osc_div              ( 4'hf                                      ),
    .D_delay_osc_en               ( 1'b0                                      ),
    .D_delay_osc_wdq_sel          ( 2'b11                                     ),
    .D_delay_osc_wrlvl_sel        ( 2'b11                                     ),
    .D_delay_dto                  (                                           ),

    .D_loopback_mode              ( 1'b1                                      ),
    .D_phy_loopback_en            ( t3_lb_en                                  ),
    .D_loopback_clknum_sel        ( 2'b11                                     ),
    .D_loopback_clk_sel           ( 2'b11                                     ),

    .D_dqsgr_atpg_mode            ( 1'b0                                      ),
    .D_dqsgr_scan_rst_n           ( 1'b1                                      ),
    .D_dqsgr_scan_clk             ( 1'b0                                      ),
    .D_dqsgr_scan_enable          ( 1'b0                                      ),
    .D_dqsgr_scan_in              ( 3'b0                                      ),
    .D_dqsgr_scancompress_mode    ( 1'b0                                      ),
    .D_dqsgr_scan_out             (                                           ),

    .D_offcal_clrcfg              ( 1'b0                                      ), 
    .D_offcal_start               ( 1'b0                                      ), 
    .D_offcal_update_en           ( 1'b0                                      ), 
    .D_offcal_done                (                                           ), 
    .D_offcal_vt_update_en_in     ( 1'b0                                      ), 
    .D_offcal_vt_update_en_out    (                                           ), 

    .D_age_toggle_en              ( 1'b0                                      ),
    .D_age_toggle_inv             ( 1'b0                                      ),
    .D_dfi_io_pd                  ( 1'b0                                      ),
    .D_phy_dqs_cnt                ( t3_dqsn_cnt                               ),
    .D_debug_data                 ( t3_o_debug                                ),

    

    
    .D_ctl_clk_ac                 ( t3_phy_ctlclk_ac                          ),
    .D_ctl_clk_dqs                ( t3_phy_ctlclk_dqs                         ),
    .D_ctl_clk_wdq                ( t3_phy_ctlclk_wdq                         ),
    .D_ddr_clk_ac                 ( t3_phy_ddrclk_ac                          ),
    .D_ddr_clk_dqs                ( t3_phy_ddrclk_dqs                         ),
    .D_ddr_clk_wdq                ( t3_phy_ddrclk_wdq                         ),
    .D_ctl_phy_clk                ( t3_phy_phyclk                             ),
    .D_wr_path_rstn_low           ( t3_phy_ac_wr_rst_n                        ),
    .D_wr_path_rstn_upp           ( t3_phy_dx_wr_rst_n                        ),
    .D_rd_path_rstn_low           ( t3_phy_ac_rd_rst_n                        ),
    .D_rd_path_rstn_upp           ( t3_phy_dx_rd_rst_n                        ),

    .D_diq                        ( t3_phy_rdata                              ),
    .D_doq                        ({t3_phy_wdata[ 95:64], t3_phy_wdata[47:0]} ),
    .D_dosp                       ( t3_phy_wdata[ 55:48]                      ),
    .D_dosn                       ( t3_phy_wdata[ 63:56]                      ),
    .D_doq_se                     ( t3_phy_wdata[103:96]                      ),

    .D_rdqs_in                    ( t3_phy_rdqs_p                             ),
    .D_rdqs_n_in                  ( t3_phy_rdqs_n                             ),
    .D_rdqs                       ( t3_phy_rdqs_o                             ),
    .D_rdqs_n_gated               ( t3_phy_rdqs_gate                          ),

    .D_dq_ts_md                   ({t3_phy_oe_md_int [21:14], t3_phy_oe_md_int [11:0]} ),
    .D_dqs_ts_md                  ( t3_phy_oe_md_int [13:12]                           ),
    .D_dq_se_ts_md                ( t3_phy_oe_md_int [23:22]                           ),
    .D_dq_te_md                   ({t3_phy_te_md_int [21:14], t3_phy_te_md_int [11:0]} ),
    .D_dqs_te_md                  ( t3_phy_te_md_int [13:12]                           ),
    .D_dq_se_te_md                ( t3_phy_te_md_int [23:22]                           ),
    .D_dq_pdr_md                  ({t3_phy_pdr_md_int[21:14], t3_phy_pdr_md_int[11:0]} ),
    .D_dqs_pdr_md                 ( t3_phy_pdr_md_int[13:12]                           ),
    .D_dq_se_pdr_md               ( t3_phy_pdr_md_int[23:22]                           ),
    .D_ts_dq                      ( t3_phy_oe_dq                              ),
    .D_ts_dqs                     ( t3_phy_oe_dqs                             ),
    .D_ts_dqsn                    ( t3_phy_oe_dqsn                            ),
    .D_te_dq                      ( t3_phy_te_dq                              ),
    .D_te_dqs                     ( t3_phy_te_dqs                             ),
    .D_te_dqsn                    ( t3_phy_te_dqsn                            ),
    .D_pdr                        ( t3_phy_pdr_dq                             ),
    .D_pdr_dqs                    ( t3_phy_pdr_dqs                            ),
    .D_pdr_dqsn                   ( t3_phy_pdr_dqsn                           ),

    .D_in_bdl_dly                 ({t3_phy_rd_bdl_dly[8*6  +: 4*6], t3_phy_rd_bdl_dly[0 +: 6*6]} ),
    .D_in_dqsp_bdl_dly            ( t3_phy_rd_bdl_dly[6*6  +:   6]                               ),
    .D_in_dqsn_bdl_dly            ( t3_phy_rd_bdl_dly[7*6  +:   6]                               ),
    .D_in_se_bdl_dly              ( t3_phy_rd_bdl_dly[12*6 +:   6]                               ),
    .D_in_bdl_byp                 ({t3_phy_rd_bdl_byp[8    +:   4], t3_phy_rd_bdl_byp[0 +:   6]} ),
    .D_in_dqsp_bdl_byp            ( t3_phy_rd_bdl_byp[6]                                         ),
    .D_in_dqsn_bdl_byp            ( t3_phy_rd_bdl_byp[7]                                         ),
    .D_in_se_bdl_byp              ( t3_phy_rd_bdl_byp[12]                                        ),

    .D_out_bdl_dly                ({t3_phy_wr_bdl_dly[8*6  +: 4*6], t3_phy_wr_bdl_dly[0 +: 6*6]} ),
    .D_out_dqsp_bdl_dly           ( t3_phy_wr_bdl_dly[6*6  +:   6]                               ),
    .D_out_dqsn_bdl_dly           ( t3_phy_wr_bdl_dly[7*6  +:   6]                               ),
    .D_out_se_bdl_dly             ( t3_phy_wr_bdl_dly[12*6 +:   6]                               ),
    .D_out_bdl_byp                ({t3_phy_wr_bdl_byp[8    +:   4], t3_phy_wr_bdl_byp[0 +:   6]} ),
    .D_out_dqsp_bdl_byp           ( t3_phy_wr_bdl_byp[6]                                         ),
    .D_out_dqsn_bdl_byp           ( t3_phy_wr_bdl_byp[7]                                         ),
    .D_out_se_bdl_byp             ( t3_phy_wr_bdl_byp[12]                                        )
);

endmodule

`timescale 1ps / 1ps
module ph1_ddrphy_pad_wrapper # (

    parameter WDM        = "ENABLE",
    parameter WDBI       = "DISABLE",
    parameter RDBI       = "DISABLE",

    parameter CK_WIDTH   = 1,
    parameter CS_WIDTH   = 1,
    parameter CKE_WIDTH  = 1,
    parameter ODT_WIDTH  = 1,
    parameter ADR_WIDTH  = 17,
    parameter BG_WIDTH   = 2,
    parameter BA_WIDTH   = 2,
    parameter DQS_WIDTH  = 9,
    parameter DM_WIDTH   = 9,
    parameter DQ_WIDTH   = 72,

    parameter CK_MAP     = 48'h137_136_117_116,
    parameter RST_MAP    = 12'h11a,
    parameter CKE_MAP    = 24'h134_133,
    parameter ODT_MAP    = 24'h11b_120,
    parameter CS_MAP     = 24'h118_128,
    parameter ACT_MAP    = 12'h000,
    parameter RAS_MAP    = 12'h000,
    parameter CAS_MAP    = 12'h000,
    parameter WE_MAP     = 12'h000,
    parameter BG_MAP     = 24'h000_000,
    parameter BA_MAP     = 36'h000_135_114,
    parameter ADR_MAP    = 216'h000_138_139_12b_13a_130_119_129_127_12a_13b_124_122_113_132_115_121_126,
    parameter PAR_MAP    = 12'h000,
    parameter ALT_MAP    = 12'h000,

    parameter DQS_MAP     = 216'h107_106_217_216_207_206_227_226_237_236_017_016_037_036_007_006_027_026,
    parameter DM_MAP      = 108'h105_218_200_228_231_018_039_00a_020,
    parameter DQ_MAP      = 864'h0

)(

    input  [3*4    -1:0]  phy_clk     ,
    input  [3*4    -1:0]  ctlclk_ac   ,
    input  [3*4    -1:0]  ctlclk_dqs  ,
    input  [3*4    -1:0]  ctlclk_wdq  ,
    input  [3*4    -1:0]  ddrclk_ac   ,
    input  [3*4    -1:0]  ddrclk_dqs  ,
    input  [3*4    -1:0]  ddrclk_wdq  ,
    input  [3*4    -1:0]  ac_wr_rst_n ,
    input  [3*4    -1:0]  dx_wr_rst_n ,
    input  [3*4    -1:0]  ac_rd_rst_n ,
    input  [3*4    -1:0]  dx_rd_rst_n ,

    output [3*4*104-1:0]  rdata       ,
    input  [3*4*104-1:0]  wdata       ,
    output [3*4*13 -1:0]  indd        ,

    output [3*4    -1:0]  rdqs_p      ,
    output [3*4    -1:0]  rdqs_n      ,
    input  [3*4    -1:0]  rdqs_r      ,
    input  [3*4    -1:0]  rdqs_f      ,

    input  [3*4*26 -1:0]  oe_md       ,
    input  [3*4*26 -1:0]  te_md       ,
    input  [3*4*26 -1:0]  pdr_md      ,

    input  [3*4    -1:0]  oe_dq       ,
    input  [3*4    -1:0]  oe_dqs      ,
    input  [3*4    -1:0]  oe_dqsn     ,
    input  [3*4    -1:0]  te_dq       ,
    input  [3*4    -1:0]  te_dqs      ,
    input  [3*4    -1:0]  te_dqsn     ,
    input  [3*4    -1:0]  pdr_dq      ,
    input  [3*4    -1:0]  pdr_dqs     ,
    input  [3*4    -1:0]  pdr_dqsn    ,

    input  [3*4*13 -1:0]  wr_bdl_byp  ,
    input  [3*4*13 -1:0]  rd_bdl_byp  ,
    input  [3*4*78 -1:0]  wr_bdl_dly  ,
    input  [3*4*78 -1:0]  rd_bdl_dly  ,

`ifdef MC0_DRAM_DDR4
    output [ CK_WIDTH-1:0]  ddr_ck_p    ,
    output [ CK_WIDTH-1:0]  ddr_ck_n    ,
    output                  ddr_reset_n ,
    output [CKE_WIDTH-1:0]  ddr_cke     ,
    output [ODT_WIDTH-1:0]  ddr_odt     ,
    output [ CS_WIDTH-1:0]  ddr_cs_n    ,
    output                  ddr_act_n   ,
    output [ BG_WIDTH-1:0]  ddr_bg      ,
    output [ BA_WIDTH-1:0]  ddr_ba      ,
    output [ADR_WIDTH-1:0]  ddr_addr    ,
    output                  ddr_parity  ,
    input                   ddr_alert_n ,
    inout  [DQS_WIDTH-1:0]  ddr_dqs_p   ,
    inout  [DQS_WIDTH-1:0]  ddr_dqs_n   ,
    inout  [ DQ_WIDTH-1:0]  ddr_dq      ,
    inout  [ DM_WIDTH-1:0]  ddr_dm
`elsif MC0_DRAM_DDR3
    output [ CK_WIDTH-1:0]  ddr_ck_p    ,
    output [ CK_WIDTH-1:0]  ddr_ck_n    ,
    output                  ddr_reset_n ,
    output [CKE_WIDTH-1:0]  ddr_cke     ,
    output [ODT_WIDTH-1:0]  ddr_odt     ,
    output [ CS_WIDTH-1:0]  ddr_cs_n    ,
    output                  ddr_ras_n   ,
    output                  ddr_cas_n   ,
    output                  ddr_we_n    ,
    output [ BA_WIDTH-1:0]  ddr_ba      ,
    output [ADR_WIDTH-1:0]  ddr_addr    ,
    inout  [DQS_WIDTH-1:0]  ddr_dqs_p   ,
    inout  [DQS_WIDTH-1:0]  ddr_dqs_n   ,
    inout  [ DQ_WIDTH-1:0]  ddr_dq      ,
    inout  [ DM_WIDTH-1:0]  ddr_dm
`endif

);

localparam LOOPBACK_EN = "DISABLE";

genvar n;
wire  [ 3:0] ddr_ck;

generate
for (n = 0; n < CK_WIDTH; n = n+1) begin : ddrio_ck_o
assign ddr_ck_p[n] = ddr_ck[2*n];
assign ddr_ck_n[n] = ddr_ck[2*n+1];
end
endgenerate

generate
for (n = 0; n < CK_WIDTH*2; n = n+1) begin : ddrio_ck
ph1_ddrphy_pad # (
    .TYPE        ( "DDRAC"     ),
    .LOOPBACK_EN ( LOOPBACK_EN )
) u_ddrio (

    .ctl_phy_clk      ( phy_clk    [4*CK_MAP[12*n+8 +: 4] + CK_MAP[12*n+4 +: 4]]   ),
    .ctl_clk_ac       ( ctlclk_ac  [4*CK_MAP[12*n+8 +: 4] + CK_MAP[12*n+4 +: 4]]   ),
    .ctl_clk_wdq      ( ctlclk_wdq [4*CK_MAP[12*n+8 +: 4] + CK_MAP[12*n+4 +: 4]]   ),
    .ctl_clk_dqs      ( ctlclk_dqs [4*CK_MAP[12*n+8 +: 4] + CK_MAP[12*n+4 +: 4]]   ),
    .ddr_clk_ac       ( ddrclk_ac  [4*CK_MAP[12*n+8 +: 4] + CK_MAP[12*n+4 +: 4]]   ),
    .ddr_clk_wdq      ( ddrclk_wdq [4*CK_MAP[12*n+8 +: 4] + CK_MAP[12*n+4 +: 4]]   ),
    .ddr_clk_dqs      ( ddrclk_dqs [4*CK_MAP[12*n+8 +: 4] + CK_MAP[12*n+4 +: 4]]   ),

    .ac_wr_rst_n      ( ac_wr_rst_n[4*CK_MAP[12*n+8 +: 4] + CK_MAP[12*n+4 +: 4]]  ),
    .dx_wr_rst_n      ( dx_wr_rst_n[4*CK_MAP[12*n+8 +: 4] + CK_MAP[12*n+4 +: 4]]  ),
    .ac_rd_rst_n      ( ac_rd_rst_n[4*CK_MAP[12*n+8 +: 4] + CK_MAP[12*n+4 +: 4]]  ),
    .dx_rd_rst_n      ( dx_rd_rst_n[4*CK_MAP[12*n+8 +: 4] + CK_MAP[12*n+4 +: 4]]  ),

    .wr_bdl_byp       ( wr_bdl_byp [4*13*CK_MAP[12*n+8 +: 4] + 13*CK_MAP[12*n+4 +: 4] +   CK_MAP[12*n +: 4]]       ),
    .rd_bdl_byp       ( rd_bdl_byp [4*13*CK_MAP[12*n+8 +: 4] + 13*CK_MAP[12*n+4 +: 4] +   CK_MAP[12*n +: 4]]       ),
    .wr_bdl_dly       ( wr_bdl_dly [4*78*CK_MAP[12*n+8 +: 4] + 78*CK_MAP[12*n+4 +: 4] + 6*CK_MAP[12*n +: 4] +: 6]  ),
    .rd_bdl_dly       ( rd_bdl_dly [4*78*CK_MAP[12*n+8 +: 4] + 78*CK_MAP[12*n+4 +: 4] + 6*CK_MAP[12*n +: 4] +: 6]  ),

    .doq              ( wdata      [4*104*CK_MAP[12*n+8 +: 4] + 104*CK_MAP[12*n+4 +: 4] + 8*CK_MAP[12*n +: 4] +: 8]  ),

    .pdr_md           ( pdr_md     [4*26*CK_MAP[12*n+8 +: 4] + 26*CK_MAP[12*n+4 +: 4] + 2*CK_MAP[12*n +: 4] +: 2]  ),
    .te_md            ( te_md      [4*26*CK_MAP[12*n+8 +: 4] + 26*CK_MAP[12*n+4 +: 4] + 2*CK_MAP[12*n +: 4] +: 2]  ),
    .ts_md            ( oe_md      [4*26*CK_MAP[12*n+8 +: 4] + 26*CK_MAP[12*n+4 +: 4] + 2*CK_MAP[12*n +: 4] +: 2]  ),

    .pdr_dq           ( pdr_dq     [4*CK_MAP[12*n+8 +: 4] + CK_MAP[12*n+4 +: 4]]  ),
    .pdr_dqs          ( pdr_dqs    [4*CK_MAP[12*n+8 +: 4] + CK_MAP[12*n+4 +: 4]]  ),
    .pdr_dqsn         ( pdr_dqsn   [4*CK_MAP[12*n+8 +: 4] + CK_MAP[12*n+4 +: 4]]  ),
    .ts_dq            ( oe_dq      [4*CK_MAP[12*n+8 +: 4] + CK_MAP[12*n+4 +: 4]]  ),
    .ts_dqs           ( oe_dqs     [4*CK_MAP[12*n+8 +: 4] + CK_MAP[12*n+4 +: 4]]  ),
    .ts_dqsn          ( oe_dqsn    [4*CK_MAP[12*n+8 +: 4] + CK_MAP[12*n+4 +: 4]]  ),
    .te_dq            ( te_dq      [4*CK_MAP[12*n+8 +: 4] + CK_MAP[12*n+4 +: 4]]  ),
    .te_dqs           ( te_dqs     [4*CK_MAP[12*n+8 +: 4] + CK_MAP[12*n+4 +: 4]]  ),
    .te_dqsn          ( te_dqsn    [4*CK_MAP[12*n+8 +: 4] + CK_MAP[12*n+4 +: 4]]  ),

    .pad              ( ddr_ck[n] )

);
end
endgenerate

generate
if (RST_MAP != 12'hfff) begin : ddrio_rst
ph1_ddrphy_pad # (
    .TYPE        ( "DDRAC"     ),
    .LOOPBACK_EN ( LOOPBACK_EN )
) u_ddrio (

    .ctl_phy_clk      ( phy_clk    [4*RST_MAP[8 +: 4] + RST_MAP[4 +: 4]]   ),
    .ctl_clk_ac       ( ctlclk_ac  [4*RST_MAP[8 +: 4] + RST_MAP[4 +: 4]]   ),
    .ctl_clk_wdq      ( ctlclk_wdq [4*RST_MAP[8 +: 4] + RST_MAP[4 +: 4]]   ),
    .ctl_clk_dqs      ( ctlclk_dqs [4*RST_MAP[8 +: 4] + RST_MAP[4 +: 4]]   ),
    .ddr_clk_ac       ( ddrclk_ac  [4*RST_MAP[8 +: 4] + RST_MAP[4 +: 4]]   ),
    .ddr_clk_wdq      ( ddrclk_wdq [4*RST_MAP[8 +: 4] + RST_MAP[4 +: 4]]   ),
    .ddr_clk_dqs      ( ddrclk_dqs [4*RST_MAP[8 +: 4] + RST_MAP[4 +: 4]]   ),

    .ac_wr_rst_n      ( ac_wr_rst_n[4*RST_MAP[8 +: 4] + RST_MAP[4 +: 4]]  ),
    .dx_wr_rst_n      ( dx_wr_rst_n[4*RST_MAP[8 +: 4] + RST_MAP[4 +: 4]]  ),
    .ac_rd_rst_n      ( ac_rd_rst_n[4*RST_MAP[8 +: 4] + RST_MAP[4 +: 4]]  ),
    .dx_rd_rst_n      ( dx_rd_rst_n[4*RST_MAP[8 +: 4] + RST_MAP[4 +: 4]]  ),

    .wr_bdl_byp       ( wr_bdl_byp [4*13*RST_MAP[8 +: 4] + 13*RST_MAP[4 +: 4] +   RST_MAP[0 +: 4]]       ),
    .rd_bdl_byp       ( rd_bdl_byp [4*13*RST_MAP[8 +: 4] + 13*RST_MAP[4 +: 4] +   RST_MAP[0 +: 4]]       ),
    .wr_bdl_dly       ( wr_bdl_dly [4*78*RST_MAP[8 +: 4] + 78*RST_MAP[4 +: 4] + 6*RST_MAP[0 +: 4] +: 6]  ),
    .rd_bdl_dly       ( rd_bdl_dly [4*78*RST_MAP[8 +: 4] + 78*RST_MAP[4 +: 4] + 6*RST_MAP[0 +: 4] +: 6]  ),

    .doq              ( wdata      [4*104*RST_MAP[8 +: 4] + 104*RST_MAP[4 +: 4] + 8*RST_MAP[0 +: 4] +: 8]  ),

    .pdr_md           ( pdr_md     [4*26*RST_MAP[8 +: 4] + 26*RST_MAP[4 +: 4] + 2*RST_MAP[0 +: 4] +: 2]  ),
    .te_md            ( te_md      [4*26*RST_MAP[8 +: 4] + 26*RST_MAP[4 +: 4] + 2*RST_MAP[0 +: 4] +: 2]  ),
    .ts_md            ( oe_md      [4*26*RST_MAP[8 +: 4] + 26*RST_MAP[4 +: 4] + 2*RST_MAP[0 +: 4] +: 2]  ),

    .pdr_dq           ( pdr_dq     [4*RST_MAP[8 +: 4] + RST_MAP[4 +: 4]]  ),
    .pdr_dqs          ( pdr_dqs    [4*RST_MAP[8 +: 4] + RST_MAP[4 +: 4]]  ),
    .pdr_dqsn         ( pdr_dqsn   [4*RST_MAP[8 +: 4] + RST_MAP[4 +: 4]]  ),
    .ts_dq            ( oe_dq      [4*RST_MAP[8 +: 4] + RST_MAP[4 +: 4]]  ),
    .ts_dqs           ( oe_dqs     [4*RST_MAP[8 +: 4] + RST_MAP[4 +: 4]]  ),
    .ts_dqsn          ( oe_dqsn    [4*RST_MAP[8 +: 4] + RST_MAP[4 +: 4]]  ),
    .te_dq            ( te_dq      [4*RST_MAP[8 +: 4] + RST_MAP[4 +: 4]]  ),
    .te_dqs           ( te_dqs     [4*RST_MAP[8 +: 4] + RST_MAP[4 +: 4]]  ),
    .te_dqsn          ( te_dqsn    [4*RST_MAP[8 +: 4] + RST_MAP[4 +: 4]]  ),

    .pad              ( ddr_reset_n )

);
end
endgenerate

generate
for (n = 0; n < CKE_WIDTH; n = n+1) begin : ddrio_cke
ph1_ddrphy_pad # (
    .TYPE        ( "DDRAC"     ),
    .LOOPBACK_EN ( LOOPBACK_EN )
) u_ddrio (

    .ctl_phy_clk      ( phy_clk    [4*CKE_MAP[12*n+8 +: 4] + CKE_MAP[12*n+4 +: 4]]   ),
    .ctl_clk_ac       ( ctlclk_ac  [4*CKE_MAP[12*n+8 +: 4] + CKE_MAP[12*n+4 +: 4]]   ),
    .ctl_clk_wdq      ( ctlclk_wdq [4*CKE_MAP[12*n+8 +: 4] + CKE_MAP[12*n+4 +: 4]]   ),
    .ctl_clk_dqs      ( ctlclk_dqs [4*CKE_MAP[12*n+8 +: 4] + CKE_MAP[12*n+4 +: 4]]   ),
    .ddr_clk_ac       ( ddrclk_ac  [4*CKE_MAP[12*n+8 +: 4] + CKE_MAP[12*n+4 +: 4]]   ),
    .ddr_clk_wdq      ( ddrclk_wdq [4*CKE_MAP[12*n+8 +: 4] + CKE_MAP[12*n+4 +: 4]]   ),
    .ddr_clk_dqs      ( ddrclk_dqs [4*CKE_MAP[12*n+8 +: 4] + CKE_MAP[12*n+4 +: 4]]   ),

    .ac_wr_rst_n      ( ac_wr_rst_n[4*CKE_MAP[12*n+8 +: 4] + CKE_MAP[12*n+4 +: 4]]  ),
    .dx_wr_rst_n      ( dx_wr_rst_n[4*CKE_MAP[12*n+8 +: 4] + CKE_MAP[12*n+4 +: 4]]  ),
    .ac_rd_rst_n      ( ac_rd_rst_n[4*CKE_MAP[12*n+8 +: 4] + CKE_MAP[12*n+4 +: 4]]  ),
    .dx_rd_rst_n      ( dx_rd_rst_n[4*CKE_MAP[12*n+8 +: 4] + CKE_MAP[12*n+4 +: 4]]  ),

    .wr_bdl_byp       ( wr_bdl_byp [4*13*CKE_MAP[12*n+8 +: 4] + 13*CKE_MAP[12*n+4 +: 4] +   CKE_MAP[12*n +: 4]]       ),
    .rd_bdl_byp       ( rd_bdl_byp [4*13*CKE_MAP[12*n+8 +: 4] + 13*CKE_MAP[12*n+4 +: 4] +   CKE_MAP[12*n +: 4]]       ),
    .wr_bdl_dly       ( wr_bdl_dly [4*78*CKE_MAP[12*n+8 +: 4] + 78*CKE_MAP[12*n+4 +: 4] + 6*CKE_MAP[12*n +: 4] +: 6]  ),
    .rd_bdl_dly       ( rd_bdl_dly [4*78*CKE_MAP[12*n+8 +: 4] + 78*CKE_MAP[12*n+4 +: 4] + 6*CKE_MAP[12*n +: 4] +: 6]  ),

    .doq              ( wdata      [4*104*CKE_MAP[12*n+8 +: 4] + 104*CKE_MAP[12*n+4 +: 4] + 8*CKE_MAP[12*n +: 4] +: 8]  ),

    .pdr_md           ( pdr_md     [4*26*CKE_MAP[12*n+8 +: 4] + 26*CKE_MAP[12*n+4 +: 4] + 2*CKE_MAP[12*n +: 4] +: 2]  ),
    .te_md            ( te_md      [4*26*CKE_MAP[12*n+8 +: 4] + 26*CKE_MAP[12*n+4 +: 4] + 2*CKE_MAP[12*n +: 4] +: 2]  ),
    .ts_md            ( oe_md      [4*26*CKE_MAP[12*n+8 +: 4] + 26*CKE_MAP[12*n+4 +: 4] + 2*CKE_MAP[12*n +: 4] +: 2]  ),

    .pdr_dq           ( pdr_dq     [4*CKE_MAP[12*n+8 +: 4] + CKE_MAP[12*n+4 +: 4]]  ),
    .pdr_dqs          ( pdr_dqs    [4*CKE_MAP[12*n+8 +: 4] + CKE_MAP[12*n+4 +: 4]]  ),
    .pdr_dqsn         ( pdr_dqsn   [4*CKE_MAP[12*n+8 +: 4] + CKE_MAP[12*n+4 +: 4]]  ),
    .ts_dq            ( oe_dq      [4*CKE_MAP[12*n+8 +: 4] + CKE_MAP[12*n+4 +: 4]]  ),
    .ts_dqs           ( oe_dqs     [4*CKE_MAP[12*n+8 +: 4] + CKE_MAP[12*n+4 +: 4]]  ),
    .ts_dqsn          ( oe_dqsn    [4*CKE_MAP[12*n+8 +: 4] + CKE_MAP[12*n+4 +: 4]]  ),
    .te_dq            ( te_dq      [4*CKE_MAP[12*n+8 +: 4] + CKE_MAP[12*n+4 +: 4]]  ),
    .te_dqs           ( te_dqs     [4*CKE_MAP[12*n+8 +: 4] + CKE_MAP[12*n+4 +: 4]]  ),
    .te_dqsn          ( te_dqsn    [4*CKE_MAP[12*n+8 +: 4] + CKE_MAP[12*n+4 +: 4]]  ),

    .pad              ( ddr_cke[n] )

);
end
endgenerate

generate
for (n = 0; n < ODT_WIDTH; n = n+1) begin : ddrio_odt
ph1_ddrphy_pad # (
    .TYPE        ( "DDRAC"     ),
    .LOOPBACK_EN ( LOOPBACK_EN )
) u_ddrio (

    .ctl_phy_clk      ( phy_clk    [4*ODT_MAP[12*n+8 +: 4] + ODT_MAP[12*n+4 +: 4]]   ),
    .ctl_clk_ac       ( ctlclk_ac  [4*ODT_MAP[12*n+8 +: 4] + ODT_MAP[12*n+4 +: 4]]   ),
    .ctl_clk_wdq      ( ctlclk_wdq [4*ODT_MAP[12*n+8 +: 4] + ODT_MAP[12*n+4 +: 4]]   ),
    .ctl_clk_dqs      ( ctlclk_dqs [4*ODT_MAP[12*n+8 +: 4] + ODT_MAP[12*n+4 +: 4]]   ),
    .ddr_clk_ac       ( ddrclk_ac  [4*ODT_MAP[12*n+8 +: 4] + ODT_MAP[12*n+4 +: 4]]   ),
    .ddr_clk_wdq      ( ddrclk_wdq [4*ODT_MAP[12*n+8 +: 4] + ODT_MAP[12*n+4 +: 4]]   ),
    .ddr_clk_dqs      ( ddrclk_dqs [4*ODT_MAP[12*n+8 +: 4] + ODT_MAP[12*n+4 +: 4]]   ),

    .ac_wr_rst_n      ( ac_wr_rst_n[4*ODT_MAP[12*n+8 +: 4] + ODT_MAP[12*n+4 +: 4]]  ),
    .dx_wr_rst_n      ( dx_wr_rst_n[4*ODT_MAP[12*n+8 +: 4] + ODT_MAP[12*n+4 +: 4]]  ),
    .ac_rd_rst_n      ( ac_rd_rst_n[4*ODT_MAP[12*n+8 +: 4] + ODT_MAP[12*n+4 +: 4]]  ),
    .dx_rd_rst_n      ( dx_rd_rst_n[4*ODT_MAP[12*n+8 +: 4] + ODT_MAP[12*n+4 +: 4]]  ),

    .wr_bdl_byp       ( wr_bdl_byp [4*13*ODT_MAP[12*n+8 +: 4] + 13*ODT_MAP[12*n+4 +: 4] +   ODT_MAP[12*n +: 4]]       ),
    .rd_bdl_byp       ( rd_bdl_byp [4*13*ODT_MAP[12*n+8 +: 4] + 13*ODT_MAP[12*n+4 +: 4] +   ODT_MAP[12*n +: 4]]       ),
    .wr_bdl_dly       ( wr_bdl_dly [4*78*ODT_MAP[12*n+8 +: 4] + 78*ODT_MAP[12*n+4 +: 4] + 6*ODT_MAP[12*n +: 4] +: 6]  ),
    .rd_bdl_dly       ( rd_bdl_dly [4*78*ODT_MAP[12*n+8 +: 4] + 78*ODT_MAP[12*n+4 +: 4] + 6*ODT_MAP[12*n +: 4] +: 6]  ),

    .doq              ( wdata      [4*104*ODT_MAP[12*n+8 +: 4] + 104*ODT_MAP[12*n+4 +: 4] + 8*ODT_MAP[12*n +: 4] +: 8]  ),

    .pdr_md           ( pdr_md     [4*26*ODT_MAP[12*n+8 +: 4] + 26*ODT_MAP[12*n+4 +: 4] + 2*ODT_MAP[12*n +: 4] +: 2]  ),
    .te_md            ( te_md      [4*26*ODT_MAP[12*n+8 +: 4] + 26*ODT_MAP[12*n+4 +: 4] + 2*ODT_MAP[12*n +: 4] +: 2]  ),
    .ts_md            ( oe_md      [4*26*ODT_MAP[12*n+8 +: 4] + 26*ODT_MAP[12*n+4 +: 4] + 2*ODT_MAP[12*n +: 4] +: 2]  ),

    .pdr_dq           ( pdr_dq     [4*ODT_MAP[12*n+8 +: 4] + ODT_MAP[12*n+4 +: 4]]  ),
    .pdr_dqs          ( pdr_dqs    [4*ODT_MAP[12*n+8 +: 4] + ODT_MAP[12*n+4 +: 4]]  ),
    .pdr_dqsn         ( pdr_dqsn   [4*ODT_MAP[12*n+8 +: 4] + ODT_MAP[12*n+4 +: 4]]  ),
    .ts_dq            ( oe_dq      [4*ODT_MAP[12*n+8 +: 4] + ODT_MAP[12*n+4 +: 4]]  ),
    .ts_dqs           ( oe_dqs     [4*ODT_MAP[12*n+8 +: 4] + ODT_MAP[12*n+4 +: 4]]  ),
    .ts_dqsn          ( oe_dqsn    [4*ODT_MAP[12*n+8 +: 4] + ODT_MAP[12*n+4 +: 4]]  ),
    .te_dq            ( te_dq      [4*ODT_MAP[12*n+8 +: 4] + ODT_MAP[12*n+4 +: 4]]  ),
    .te_dqs           ( te_dqs     [4*ODT_MAP[12*n+8 +: 4] + ODT_MAP[12*n+4 +: 4]]  ),
    .te_dqsn          ( te_dqsn    [4*ODT_MAP[12*n+8 +: 4] + ODT_MAP[12*n+4 +: 4]]  ),

    .pad              ( ddr_odt[n] )

);
end
endgenerate

generate
for (n = 0; n < CS_WIDTH; n = n+1) begin : ddrio_cs
ph1_ddrphy_pad # (
    .TYPE        ( "DDRAC"     ),
    .LOOPBACK_EN ( LOOPBACK_EN )
) u_ddrio (

    .ctl_phy_clk      ( phy_clk    [4*CS_MAP[12*n+8 +: 4] + CS_MAP[12*n+4 +: 4]]   ),
    .ctl_clk_ac       ( ctlclk_ac  [4*CS_MAP[12*n+8 +: 4] + CS_MAP[12*n+4 +: 4]]   ),
    .ctl_clk_wdq      ( ctlclk_wdq [4*CS_MAP[12*n+8 +: 4] + CS_MAP[12*n+4 +: 4]]   ),
    .ctl_clk_dqs      ( ctlclk_dqs [4*CS_MAP[12*n+8 +: 4] + CS_MAP[12*n+4 +: 4]]   ),
    .ddr_clk_ac       ( ddrclk_ac  [4*CS_MAP[12*n+8 +: 4] + CS_MAP[12*n+4 +: 4]]   ),
    .ddr_clk_wdq      ( ddrclk_wdq [4*CS_MAP[12*n+8 +: 4] + CS_MAP[12*n+4 +: 4]]   ),
    .ddr_clk_dqs      ( ddrclk_dqs [4*CS_MAP[12*n+8 +: 4] + CS_MAP[12*n+4 +: 4]]   ),

    .ac_wr_rst_n      ( ac_wr_rst_n[4*CS_MAP[12*n+8 +: 4] + CS_MAP[12*n+4 +: 4]]  ),
    .dx_wr_rst_n      ( dx_wr_rst_n[4*CS_MAP[12*n+8 +: 4] + CS_MAP[12*n+4 +: 4]]  ),
    .ac_rd_rst_n      ( ac_rd_rst_n[4*CS_MAP[12*n+8 +: 4] + CS_MAP[12*n+4 +: 4]]  ),
    .dx_rd_rst_n      ( dx_rd_rst_n[4*CS_MAP[12*n+8 +: 4] + CS_MAP[12*n+4 +: 4]]  ),

    .wr_bdl_byp       ( wr_bdl_byp [4*13*CS_MAP[12*n+8 +: 4] + 13*CS_MAP[12*n+4 +: 4] +   CS_MAP[12*n +: 4]]       ),
    .rd_bdl_byp       ( rd_bdl_byp [4*13*CS_MAP[12*n+8 +: 4] + 13*CS_MAP[12*n+4 +: 4] +   CS_MAP[12*n +: 4]]       ),
    .wr_bdl_dly       ( wr_bdl_dly [4*78*CS_MAP[12*n+8 +: 4] + 78*CS_MAP[12*n+4 +: 4] + 6*CS_MAP[12*n +: 4] +: 6]  ),
    .rd_bdl_dly       ( rd_bdl_dly [4*78*CS_MAP[12*n+8 +: 4] + 78*CS_MAP[12*n+4 +: 4] + 6*CS_MAP[12*n +: 4] +: 6]  ),

    .doq              ( wdata      [4*104*CS_MAP[12*n+8 +: 4] + 104*CS_MAP[12*n+4 +: 4] + 8*CS_MAP[12*n +: 4] +: 8]  ),

    .pdr_md           ( pdr_md     [4*26*CS_MAP[12*n+8 +: 4] + 26*CS_MAP[12*n+4 +: 4] + 2*CS_MAP[12*n +: 4] +: 2]  ),
    .te_md            ( te_md      [4*26*CS_MAP[12*n+8 +: 4] + 26*CS_MAP[12*n+4 +: 4] + 2*CS_MAP[12*n +: 4] +: 2]  ),
    .ts_md            ( oe_md      [4*26*CS_MAP[12*n+8 +: 4] + 26*CS_MAP[12*n+4 +: 4] + 2*CS_MAP[12*n +: 4] +: 2]  ),

    .pdr_dq           ( pdr_dq     [4*CS_MAP[12*n+8 +: 4] + CS_MAP[12*n+4 +: 4]]  ),
    .pdr_dqs          ( pdr_dqs    [4*CS_MAP[12*n+8 +: 4] + CS_MAP[12*n+4 +: 4]]  ),
    .pdr_dqsn         ( pdr_dqsn   [4*CS_MAP[12*n+8 +: 4] + CS_MAP[12*n+4 +: 4]]  ),
    .ts_dq            ( oe_dq      [4*CS_MAP[12*n+8 +: 4] + CS_MAP[12*n+4 +: 4]]  ),
    .ts_dqs           ( oe_dqs     [4*CS_MAP[12*n+8 +: 4] + CS_MAP[12*n+4 +: 4]]  ),
    .ts_dqsn          ( oe_dqsn    [4*CS_MAP[12*n+8 +: 4] + CS_MAP[12*n+4 +: 4]]  ),
    .te_dq            ( te_dq      [4*CS_MAP[12*n+8 +: 4] + CS_MAP[12*n+4 +: 4]]  ),
    .te_dqs           ( te_dqs     [4*CS_MAP[12*n+8 +: 4] + CS_MAP[12*n+4 +: 4]]  ),
    .te_dqsn          ( te_dqsn    [4*CS_MAP[12*n+8 +: 4] + CS_MAP[12*n+4 +: 4]]  ),

    .pad              ( ddr_cs_n[n] )

);
end
endgenerate

generate
if (ACT_MAP != 12'hfff) begin : ddrio_act
ph1_ddrphy_pad # (
    .TYPE        ( "DDRAC"     ),
    .LOOPBACK_EN ( LOOPBACK_EN )
) u_ddrio (

    .ctl_phy_clk      ( phy_clk    [4*ACT_MAP[8 +: 4] + ACT_MAP[4 +: 4]]   ),
    .ctl_clk_ac       ( ctlclk_ac  [4*ACT_MAP[8 +: 4] + ACT_MAP[4 +: 4]]   ),
    .ctl_clk_wdq      ( ctlclk_wdq [4*ACT_MAP[8 +: 4] + ACT_MAP[4 +: 4]]   ),
    .ctl_clk_dqs      ( ctlclk_dqs [4*ACT_MAP[8 +: 4] + ACT_MAP[4 +: 4]]   ),
    .ddr_clk_ac       ( ddrclk_ac  [4*ACT_MAP[8 +: 4] + ACT_MAP[4 +: 4]]   ),
    .ddr_clk_wdq      ( ddrclk_wdq [4*ACT_MAP[8 +: 4] + ACT_MAP[4 +: 4]]   ),
    .ddr_clk_dqs      ( ddrclk_dqs [4*ACT_MAP[8 +: 4] + ACT_MAP[4 +: 4]]   ),

    .ac_wr_rst_n      ( ac_wr_rst_n[4*ACT_MAP[8 +: 4] + ACT_MAP[4 +: 4]]  ),
    .dx_wr_rst_n      ( dx_wr_rst_n[4*ACT_MAP[8 +: 4] + ACT_MAP[4 +: 4]]  ),
    .ac_rd_rst_n      ( ac_rd_rst_n[4*ACT_MAP[8 +: 4] + ACT_MAP[4 +: 4]]  ),
    .dx_rd_rst_n      ( dx_rd_rst_n[4*ACT_MAP[8 +: 4] + ACT_MAP[4 +: 4]]  ),

    .wr_bdl_byp       ( wr_bdl_byp [4*13*ACT_MAP[8 +: 4] + 13*ACT_MAP[4 +: 4] +   ACT_MAP[0 +: 4]]       ),
    .rd_bdl_byp       ( rd_bdl_byp [4*13*ACT_MAP[8 +: 4] + 13*ACT_MAP[4 +: 4] +   ACT_MAP[0 +: 4]]       ),
    .wr_bdl_dly       ( wr_bdl_dly [4*78*ACT_MAP[8 +: 4] + 78*ACT_MAP[4 +: 4] + 6*ACT_MAP[0 +: 4] +: 6]  ),
    .rd_bdl_dly       ( rd_bdl_dly [4*78*ACT_MAP[8 +: 4] + 78*ACT_MAP[4 +: 4] + 6*ACT_MAP[0 +: 4] +: 6]  ),

    .doq              ( wdata      [4*104*ACT_MAP[8 +: 4] + 104*ACT_MAP[4 +: 4] + 8*ACT_MAP[0 +: 4] +: 8]  ),

    .pdr_md           ( pdr_md     [4*26*ACT_MAP[8 +: 4] + 26*ACT_MAP[4 +: 4] + 2*ACT_MAP[0 +: 4] +: 2]  ),
    .te_md            ( te_md      [4*26*ACT_MAP[8 +: 4] + 26*ACT_MAP[4 +: 4] + 2*ACT_MAP[0 +: 4] +: 2]  ),
    .ts_md            ( oe_md      [4*26*ACT_MAP[8 +: 4] + 26*ACT_MAP[4 +: 4] + 2*ACT_MAP[0 +: 4] +: 2]  ),

    .pdr_dq           ( pdr_dq     [4*ACT_MAP[8 +: 4] + ACT_MAP[4 +: 4]]  ),
    .pdr_dqs          ( pdr_dqs    [4*ACT_MAP[8 +: 4] + ACT_MAP[4 +: 4]]  ),
    .pdr_dqsn         ( pdr_dqsn   [4*ACT_MAP[8 +: 4] + ACT_MAP[4 +: 4]]  ),
    .ts_dq            ( oe_dq      [4*ACT_MAP[8 +: 4] + ACT_MAP[4 +: 4]]  ),
    .ts_dqs           ( oe_dqs     [4*ACT_MAP[8 +: 4] + ACT_MAP[4 +: 4]]  ),
    .ts_dqsn          ( oe_dqsn    [4*ACT_MAP[8 +: 4] + ACT_MAP[4 +: 4]]  ),
    .te_dq            ( te_dq      [4*ACT_MAP[8 +: 4] + ACT_MAP[4 +: 4]]  ),
    .te_dqs           ( te_dqs     [4*ACT_MAP[8 +: 4] + ACT_MAP[4 +: 4]]  ),
    .te_dqsn          ( te_dqsn    [4*ACT_MAP[8 +: 4] + ACT_MAP[4 +: 4]]  ),

    .pad              ( ddr_act_n )

);
end
endgenerate

generate
if (RAS_MAP != 12'hfff) begin : ddrio_ras
ph1_ddrphy_pad # (
    .TYPE        ( "DDRAC"     ),
    .LOOPBACK_EN ( LOOPBACK_EN )
) u_ddrio (

    .ctl_phy_clk      ( phy_clk    [4*RAS_MAP[8 +: 4] + RAS_MAP[4 +: 4]]   ),
    .ctl_clk_ac       ( ctlclk_ac  [4*RAS_MAP[8 +: 4] + RAS_MAP[4 +: 4]]   ),
    .ctl_clk_wdq      ( ctlclk_wdq [4*RAS_MAP[8 +: 4] + RAS_MAP[4 +: 4]]   ),
    .ctl_clk_dqs      ( ctlclk_dqs [4*RAS_MAP[8 +: 4] + RAS_MAP[4 +: 4]]   ),
    .ddr_clk_ac       ( ddrclk_ac  [4*RAS_MAP[8 +: 4] + RAS_MAP[4 +: 4]]   ),
    .ddr_clk_wdq      ( ddrclk_wdq [4*RAS_MAP[8 +: 4] + RAS_MAP[4 +: 4]]   ),
    .ddr_clk_dqs      ( ddrclk_dqs [4*RAS_MAP[8 +: 4] + RAS_MAP[4 +: 4]]   ),

    .ac_wr_rst_n      ( ac_wr_rst_n[4*RAS_MAP[8 +: 4] + RAS_MAP[4 +: 4]]  ),
    .dx_wr_rst_n      ( dx_wr_rst_n[4*RAS_MAP[8 +: 4] + RAS_MAP[4 +: 4]]  ),
    .ac_rd_rst_n      ( ac_rd_rst_n[4*RAS_MAP[8 +: 4] + RAS_MAP[4 +: 4]]  ),
    .dx_rd_rst_n      ( dx_rd_rst_n[4*RAS_MAP[8 +: 4] + RAS_MAP[4 +: 4]]  ),

    .wr_bdl_byp       ( wr_bdl_byp [4*13*RAS_MAP[8 +: 4] + 13*RAS_MAP[4 +: 4] +   RAS_MAP[0 +: 4]]       ),
    .rd_bdl_byp       ( rd_bdl_byp [4*13*RAS_MAP[8 +: 4] + 13*RAS_MAP[4 +: 4] +   RAS_MAP[0 +: 4]]       ),
    .wr_bdl_dly       ( wr_bdl_dly [4*78*RAS_MAP[8 +: 4] + 78*RAS_MAP[4 +: 4] + 6*RAS_MAP[0 +: 4] +: 6]  ),
    .rd_bdl_dly       ( rd_bdl_dly [4*78*RAS_MAP[8 +: 4] + 78*RAS_MAP[4 +: 4] + 6*RAS_MAP[0 +: 4] +: 6]  ),

    .doq              ( wdata      [4*104*RAS_MAP[8 +: 4] + 104*RAS_MAP[4 +: 4] + 8*RAS_MAP[0 +: 4] +: 8]  ),

    .pdr_md           ( pdr_md     [4*26*RAS_MAP[8 +: 4] + 26*RAS_MAP[4 +: 4] + 2*RAS_MAP[0 +: 4] +: 2]  ),
    .te_md            ( te_md      [4*26*RAS_MAP[8 +: 4] + 26*RAS_MAP[4 +: 4] + 2*RAS_MAP[0 +: 4] +: 2]  ),
    .ts_md            ( oe_md      [4*26*RAS_MAP[8 +: 4] + 26*RAS_MAP[4 +: 4] + 2*RAS_MAP[0 +: 4] +: 2]  ),

    .pdr_dq           ( pdr_dq     [4*RAS_MAP[8 +: 4] + RAS_MAP[4 +: 4]]  ),
    .pdr_dqs          ( pdr_dqs    [4*RAS_MAP[8 +: 4] + RAS_MAP[4 +: 4]]  ),
    .pdr_dqsn         ( pdr_dqsn   [4*RAS_MAP[8 +: 4] + RAS_MAP[4 +: 4]]  ),
    .ts_dq            ( oe_dq      [4*RAS_MAP[8 +: 4] + RAS_MAP[4 +: 4]]  ),
    .ts_dqs           ( oe_dqs     [4*RAS_MAP[8 +: 4] + RAS_MAP[4 +: 4]]  ),
    .ts_dqsn          ( oe_dqsn    [4*RAS_MAP[8 +: 4] + RAS_MAP[4 +: 4]]  ),
    .te_dq            ( te_dq      [4*RAS_MAP[8 +: 4] + RAS_MAP[4 +: 4]]  ),
    .te_dqs           ( te_dqs     [4*RAS_MAP[8 +: 4] + RAS_MAP[4 +: 4]]  ),
    .te_dqsn          ( te_dqsn    [4*RAS_MAP[8 +: 4] + RAS_MAP[4 +: 4]]  ),

    .pad              ( ddr_ras_n )

);
end
endgenerate

generate
if (CAS_MAP != 12'hfff) begin : ddrio_cas
ph1_ddrphy_pad # (
    .TYPE        ( "DDRAC"     ),
    .LOOPBACK_EN ( LOOPBACK_EN )
) u_ddrio (

    .ctl_phy_clk      ( phy_clk    [4*CAS_MAP[8 +: 4] + CAS_MAP[4 +: 4]]   ),
    .ctl_clk_ac       ( ctlclk_ac  [4*CAS_MAP[8 +: 4] + CAS_MAP[4 +: 4]]   ),
    .ctl_clk_wdq      ( ctlclk_wdq [4*CAS_MAP[8 +: 4] + CAS_MAP[4 +: 4]]   ),
    .ctl_clk_dqs      ( ctlclk_dqs [4*CAS_MAP[8 +: 4] + CAS_MAP[4 +: 4]]   ),
    .ddr_clk_ac       ( ddrclk_ac  [4*CAS_MAP[8 +: 4] + CAS_MAP[4 +: 4]]   ),
    .ddr_clk_wdq      ( ddrclk_wdq [4*CAS_MAP[8 +: 4] + CAS_MAP[4 +: 4]]   ),
    .ddr_clk_dqs      ( ddrclk_dqs [4*CAS_MAP[8 +: 4] + CAS_MAP[4 +: 4]]   ),

    .ac_wr_rst_n      ( ac_wr_rst_n[4*CAS_MAP[8 +: 4] + CAS_MAP[4 +: 4]]  ),
    .dx_wr_rst_n      ( dx_wr_rst_n[4*CAS_MAP[8 +: 4] + CAS_MAP[4 +: 4]]  ),
    .ac_rd_rst_n      ( ac_rd_rst_n[4*CAS_MAP[8 +: 4] + CAS_MAP[4 +: 4]]  ),
    .dx_rd_rst_n      ( dx_rd_rst_n[4*CAS_MAP[8 +: 4] + CAS_MAP[4 +: 4]]  ),

    .wr_bdl_byp       ( wr_bdl_byp [4*13*CAS_MAP[8 +: 4] + 13*CAS_MAP[4 +: 4] +   CAS_MAP[0 +: 4]]       ),
    .rd_bdl_byp       ( rd_bdl_byp [4*13*CAS_MAP[8 +: 4] + 13*CAS_MAP[4 +: 4] +   CAS_MAP[0 +: 4]]       ),
    .wr_bdl_dly       ( wr_bdl_dly [4*78*CAS_MAP[8 +: 4] + 78*CAS_MAP[4 +: 4] + 6*CAS_MAP[0 +: 4] +: 6]  ),
    .rd_bdl_dly       ( rd_bdl_dly [4*78*CAS_MAP[8 +: 4] + 78*CAS_MAP[4 +: 4] + 6*CAS_MAP[0 +: 4] +: 6]  ),

    .doq              ( wdata      [4*104*CAS_MAP[8 +: 4] + 104*CAS_MAP[4 +: 4] + 8*CAS_MAP[0 +: 4] +: 8]  ),

    .pdr_md           ( pdr_md     [4*26*CAS_MAP[8 +: 4] + 26*CAS_MAP[4 +: 4] + 2*CAS_MAP[0 +: 4] +: 2]  ),
    .te_md            ( te_md      [4*26*CAS_MAP[8 +: 4] + 26*CAS_MAP[4 +: 4] + 2*CAS_MAP[0 +: 4] +: 2]  ),
    .ts_md            ( oe_md      [4*26*CAS_MAP[8 +: 4] + 26*CAS_MAP[4 +: 4] + 2*CAS_MAP[0 +: 4] +: 2]  ),

    .pdr_dq           ( pdr_dq     [4*CAS_MAP[8 +: 4] + CAS_MAP[4 +: 4]]  ),
    .pdr_dqs          ( pdr_dqs    [4*CAS_MAP[8 +: 4] + CAS_MAP[4 +: 4]]  ),
    .pdr_dqsn         ( pdr_dqsn   [4*CAS_MAP[8 +: 4] + CAS_MAP[4 +: 4]]  ),
    .ts_dq            ( oe_dq      [4*CAS_MAP[8 +: 4] + CAS_MAP[4 +: 4]]  ),
    .ts_dqs           ( oe_dqs     [4*CAS_MAP[8 +: 4] + CAS_MAP[4 +: 4]]  ),
    .ts_dqsn          ( oe_dqsn    [4*CAS_MAP[8 +: 4] + CAS_MAP[4 +: 4]]  ),
    .te_dq            ( te_dq      [4*CAS_MAP[8 +: 4] + CAS_MAP[4 +: 4]]  ),
    .te_dqs           ( te_dqs     [4*CAS_MAP[8 +: 4] + CAS_MAP[4 +: 4]]  ),
    .te_dqsn          ( te_dqsn    [4*CAS_MAP[8 +: 4] + CAS_MAP[4 +: 4]]  ),

    .pad              ( ddr_cas_n )

);
end
endgenerate

generate
if (WE_MAP != 12'hfff) begin : ddrio_we
ph1_ddrphy_pad # (
    .TYPE        ( "DDRAC"     ),
    .LOOPBACK_EN ( LOOPBACK_EN )
) u_ddrio (

    .ctl_phy_clk      ( phy_clk    [4*WE_MAP[8 +: 4] + WE_MAP[4 +: 4]]   ),
    .ctl_clk_ac       ( ctlclk_ac  [4*WE_MAP[8 +: 4] + WE_MAP[4 +: 4]]   ),
    .ctl_clk_wdq      ( ctlclk_wdq [4*WE_MAP[8 +: 4] + WE_MAP[4 +: 4]]   ),
    .ctl_clk_dqs      ( ctlclk_dqs [4*WE_MAP[8 +: 4] + WE_MAP[4 +: 4]]   ),
    .ddr_clk_ac       ( ddrclk_ac  [4*WE_MAP[8 +: 4] + WE_MAP[4 +: 4]]   ),
    .ddr_clk_wdq      ( ddrclk_wdq [4*WE_MAP[8 +: 4] + WE_MAP[4 +: 4]]   ),
    .ddr_clk_dqs      ( ddrclk_dqs [4*WE_MAP[8 +: 4] + WE_MAP[4 +: 4]]   ),

    .ac_wr_rst_n      ( ac_wr_rst_n[4*WE_MAP[8 +: 4] + WE_MAP[4 +: 4]]  ),
    .dx_wr_rst_n      ( dx_wr_rst_n[4*WE_MAP[8 +: 4] + WE_MAP[4 +: 4]]  ),
    .ac_rd_rst_n      ( ac_rd_rst_n[4*WE_MAP[8 +: 4] + WE_MAP[4 +: 4]]  ),
    .dx_rd_rst_n      ( dx_rd_rst_n[4*WE_MAP[8 +: 4] + WE_MAP[4 +: 4]]  ),

    .wr_bdl_byp       ( wr_bdl_byp [4*13*WE_MAP[8 +: 4] + 13*WE_MAP[4 +: 4] +   WE_MAP[0 +: 4]]       ),
    .rd_bdl_byp       ( rd_bdl_byp [4*13*WE_MAP[8 +: 4] + 13*WE_MAP[4 +: 4] +   WE_MAP[0 +: 4]]       ),
    .wr_bdl_dly       ( wr_bdl_dly [4*78*WE_MAP[8 +: 4] + 78*WE_MAP[4 +: 4] + 6*WE_MAP[0 +: 4] +: 6]  ),
    .rd_bdl_dly       ( rd_bdl_dly [4*78*WE_MAP[8 +: 4] + 78*WE_MAP[4 +: 4] + 6*WE_MAP[0 +: 4] +: 6]  ),

    .doq              ( wdata      [4*104*WE_MAP[8 +: 4] + 104*WE_MAP[4 +: 4] + 8*WE_MAP[0 +: 4] +: 8]  ),

    .pdr_md           ( pdr_md     [4*26*WE_MAP[8 +: 4] + 26*WE_MAP[4 +: 4] + 2*WE_MAP[0 +: 4] +: 2]  ),
    .te_md            ( te_md      [4*26*WE_MAP[8 +: 4] + 26*WE_MAP[4 +: 4] + 2*WE_MAP[0 +: 4] +: 2]  ),
    .ts_md            ( oe_md      [4*26*WE_MAP[8 +: 4] + 26*WE_MAP[4 +: 4] + 2*WE_MAP[0 +: 4] +: 2]  ),

    .pdr_dq           ( pdr_dq     [4*WE_MAP[8 +: 4] + WE_MAP[4 +: 4]]  ),
    .pdr_dqs          ( pdr_dqs    [4*WE_MAP[8 +: 4] + WE_MAP[4 +: 4]]  ),
    .pdr_dqsn         ( pdr_dqsn   [4*WE_MAP[8 +: 4] + WE_MAP[4 +: 4]]  ),
    .ts_dq            ( oe_dq      [4*WE_MAP[8 +: 4] + WE_MAP[4 +: 4]]  ),
    .ts_dqs           ( oe_dqs     [4*WE_MAP[8 +: 4] + WE_MAP[4 +: 4]]  ),
    .ts_dqsn          ( oe_dqsn    [4*WE_MAP[8 +: 4] + WE_MAP[4 +: 4]]  ),
    .te_dq            ( te_dq      [4*WE_MAP[8 +: 4] + WE_MAP[4 +: 4]]  ),
    .te_dqs           ( te_dqs     [4*WE_MAP[8 +: 4] + WE_MAP[4 +: 4]]  ),
    .te_dqsn          ( te_dqsn    [4*WE_MAP[8 +: 4] + WE_MAP[4 +: 4]]  ),

    .pad              ( ddr_we_n )

);
end
endgenerate

`ifdef MC0_DRAM_DDR4
generate
for (n = 0; n < BG_WIDTH; n = n+1) begin : ddrio_bg
ph1_ddrphy_pad # (
    .TYPE        ( "DDRAC"     ),
    .LOOPBACK_EN ( LOOPBACK_EN )
) u_ddrio (

    .ctl_phy_clk      ( phy_clk    [4*BG_MAP[12*n+8 +: 4] + BG_MAP[12*n+4 +: 4]]   ),
    .ctl_clk_ac       ( ctlclk_ac  [4*BG_MAP[12*n+8 +: 4] + BG_MAP[12*n+4 +: 4]]   ),
    .ctl_clk_wdq      ( ctlclk_wdq [4*BG_MAP[12*n+8 +: 4] + BG_MAP[12*n+4 +: 4]]   ),
    .ctl_clk_dqs      ( ctlclk_dqs [4*BG_MAP[12*n+8 +: 4] + BG_MAP[12*n+4 +: 4]]   ),
    .ddr_clk_ac       ( ddrclk_ac  [4*BG_MAP[12*n+8 +: 4] + BG_MAP[12*n+4 +: 4]]   ),
    .ddr_clk_wdq      ( ddrclk_wdq [4*BG_MAP[12*n+8 +: 4] + BG_MAP[12*n+4 +: 4]]   ),
    .ddr_clk_dqs      ( ddrclk_dqs [4*BG_MAP[12*n+8 +: 4] + BG_MAP[12*n+4 +: 4]]   ),

    .ac_wr_rst_n      ( ac_wr_rst_n[4*BG_MAP[12*n+8 +: 4] + BG_MAP[12*n+4 +: 4]]  ),
    .dx_wr_rst_n      ( dx_wr_rst_n[4*BG_MAP[12*n+8 +: 4] + BG_MAP[12*n+4 +: 4]]  ),
    .ac_rd_rst_n      ( ac_rd_rst_n[4*BG_MAP[12*n+8 +: 4] + BG_MAP[12*n+4 +: 4]]  ),
    .dx_rd_rst_n      ( dx_rd_rst_n[4*BG_MAP[12*n+8 +: 4] + BG_MAP[12*n+4 +: 4]]  ),

    .wr_bdl_byp       ( wr_bdl_byp [4*13*BG_MAP[12*n+8 +: 4] + 13*BG_MAP[12*n+4 +: 4] +   BG_MAP[12*n +: 4]]       ),
    .rd_bdl_byp       ( rd_bdl_byp [4*13*BG_MAP[12*n+8 +: 4] + 13*BG_MAP[12*n+4 +: 4] +   BG_MAP[12*n +: 4]]       ),
    .wr_bdl_dly       ( wr_bdl_dly [4*78*BG_MAP[12*n+8 +: 4] + 78*BG_MAP[12*n+4 +: 4] + 6*BG_MAP[12*n +: 4] +: 6]  ),
    .rd_bdl_dly       ( rd_bdl_dly [4*78*BG_MAP[12*n+8 +: 4] + 78*BG_MAP[12*n+4 +: 4] + 6*BG_MAP[12*n +: 4] +: 6]  ),

    .doq              ( wdata      [4*104*BG_MAP[12*n+8 +: 4] + 104*BG_MAP[12*n+4 +: 4] + 8*BG_MAP[12*n +: 4] +: 8]  ),

    .pdr_md           ( pdr_md     [4*26*BG_MAP[12*n+8 +: 4] + 26*BG_MAP[12*n+4 +: 4] + 2*BG_MAP[12*n +: 4] +: 2]  ),
    .te_md            ( te_md      [4*26*BG_MAP[12*n+8 +: 4] + 26*BG_MAP[12*n+4 +: 4] + 2*BG_MAP[12*n +: 4] +: 2]  ),
    .ts_md            ( oe_md      [4*26*BG_MAP[12*n+8 +: 4] + 26*BG_MAP[12*n+4 +: 4] + 2*BG_MAP[12*n +: 4] +: 2]  ),

    .pdr_dq           ( pdr_dq     [4*BG_MAP[12*n+8 +: 4] + BG_MAP[12*n+4 +: 4]]  ),
    .pdr_dqs          ( pdr_dqs    [4*BG_MAP[12*n+8 +: 4] + BG_MAP[12*n+4 +: 4]]  ),
    .pdr_dqsn         ( pdr_dqsn   [4*BG_MAP[12*n+8 +: 4] + BG_MAP[12*n+4 +: 4]]  ),
    .ts_dq            ( oe_dq      [4*BG_MAP[12*n+8 +: 4] + BG_MAP[12*n+4 +: 4]]  ),
    .ts_dqs           ( oe_dqs     [4*BG_MAP[12*n+8 +: 4] + BG_MAP[12*n+4 +: 4]]  ),
    .ts_dqsn          ( oe_dqsn    [4*BG_MAP[12*n+8 +: 4] + BG_MAP[12*n+4 +: 4]]  ),
    .te_dq            ( te_dq      [4*BG_MAP[12*n+8 +: 4] + BG_MAP[12*n+4 +: 4]]  ),
    .te_dqs           ( te_dqs     [4*BG_MAP[12*n+8 +: 4] + BG_MAP[12*n+4 +: 4]]  ),
    .te_dqsn          ( te_dqsn    [4*BG_MAP[12*n+8 +: 4] + BG_MAP[12*n+4 +: 4]]  ),

    .pad              ( ddr_bg[n] )

);
end
endgenerate
`endif

generate
for (n = 0; n < BA_WIDTH; n = n+1) begin : ddrio_ba
ph1_ddrphy_pad # (
    .TYPE        ( "DDRAC"     ),
    .LOOPBACK_EN ( LOOPBACK_EN )
) u_ddriob_ba (

    .ctl_phy_clk      ( phy_clk    [4*BA_MAP[12*n+8 +: 4] + BA_MAP[12*n+4 +: 4]]   ),
    .ctl_clk_ac       ( ctlclk_ac  [4*BA_MAP[12*n+8 +: 4] + BA_MAP[12*n+4 +: 4]]   ),
    .ctl_clk_wdq      ( ctlclk_wdq [4*BA_MAP[12*n+8 +: 4] + BA_MAP[12*n+4 +: 4]]   ),
    .ctl_clk_dqs      ( ctlclk_dqs [4*BA_MAP[12*n+8 +: 4] + BA_MAP[12*n+4 +: 4]]   ),
    .ddr_clk_ac       ( ddrclk_ac  [4*BA_MAP[12*n+8 +: 4] + BA_MAP[12*n+4 +: 4]]   ),
    .ddr_clk_wdq      ( ddrclk_wdq [4*BA_MAP[12*n+8 +: 4] + BA_MAP[12*n+4 +: 4]]   ),
    .ddr_clk_dqs      ( ddrclk_dqs [4*BA_MAP[12*n+8 +: 4] + BA_MAP[12*n+4 +: 4]]   ),

    .ac_wr_rst_n      ( ac_wr_rst_n[4*BA_MAP[12*n+8 +: 4] + BA_MAP[12*n+4 +: 4]]  ),
    .dx_wr_rst_n      ( dx_wr_rst_n[4*BA_MAP[12*n+8 +: 4] + BA_MAP[12*n+4 +: 4]]  ),
    .ac_rd_rst_n      ( ac_rd_rst_n[4*BA_MAP[12*n+8 +: 4] + BA_MAP[12*n+4 +: 4]]  ),
    .dx_rd_rst_n      ( dx_rd_rst_n[4*BA_MAP[12*n+8 +: 4] + BA_MAP[12*n+4 +: 4]]  ),

    .wr_bdl_byp       ( wr_bdl_byp [4*13*BA_MAP[12*n+8 +: 4] + 13*BA_MAP[12*n+4 +: 4] +   BA_MAP[12*n +: 4]]       ),
    .rd_bdl_byp       ( rd_bdl_byp [4*13*BA_MAP[12*n+8 +: 4] + 13*BA_MAP[12*n+4 +: 4] +   BA_MAP[12*n +: 4]]       ),
    .wr_bdl_dly       ( wr_bdl_dly [4*78*BA_MAP[12*n+8 +: 4] + 78*BA_MAP[12*n+4 +: 4] + 6*BA_MAP[12*n +: 4] +: 6]  ),
    .rd_bdl_dly       ( rd_bdl_dly [4*78*BA_MAP[12*n+8 +: 4] + 78*BA_MAP[12*n+4 +: 4] + 6*BA_MAP[12*n +: 4] +: 6]  ),

    .doq              ( wdata      [4*104*BA_MAP[12*n+8 +: 4] + 104*BA_MAP[12*n+4 +: 4] + 8*BA_MAP[12*n +: 4] +: 8]  ),

    .pdr_md           ( pdr_md     [4*26*BA_MAP[12*n+8 +: 4] + 26*BA_MAP[12*n+4 +: 4] + 2*BA_MAP[12*n +: 4] +: 2]  ),
    .te_md            ( te_md      [4*26*BA_MAP[12*n+8 +: 4] + 26*BA_MAP[12*n+4 +: 4] + 2*BA_MAP[12*n +: 4] +: 2]  ),
    .ts_md            ( oe_md      [4*26*BA_MAP[12*n+8 +: 4] + 26*BA_MAP[12*n+4 +: 4] + 2*BA_MAP[12*n +: 4] +: 2]  ),

    .pdr_dq           ( pdr_dq     [4*BA_MAP[12*n+8 +: 4] + BA_MAP[12*n+4 +: 4]]  ),
    .pdr_dqs          ( pdr_dqs    [4*BA_MAP[12*n+8 +: 4] + BA_MAP[12*n+4 +: 4]]  ),
    .pdr_dqsn         ( pdr_dqsn   [4*BA_MAP[12*n+8 +: 4] + BA_MAP[12*n+4 +: 4]]  ),
    .ts_dq            ( oe_dq      [4*BA_MAP[12*n+8 +: 4] + BA_MAP[12*n+4 +: 4]]  ),
    .ts_dqs           ( oe_dqs     [4*BA_MAP[12*n+8 +: 4] + BA_MAP[12*n+4 +: 4]]  ),
    .ts_dqsn          ( oe_dqsn    [4*BA_MAP[12*n+8 +: 4] + BA_MAP[12*n+4 +: 4]]  ),
    .te_dq            ( te_dq      [4*BA_MAP[12*n+8 +: 4] + BA_MAP[12*n+4 +: 4]]  ),
    .te_dqs           ( te_dqs     [4*BA_MAP[12*n+8 +: 4] + BA_MAP[12*n+4 +: 4]]  ),
    .te_dqsn          ( te_dqsn    [4*BA_MAP[12*n+8 +: 4] + BA_MAP[12*n+4 +: 4]]  ),

    .pad              ( ddr_ba[n] )

);
end
endgenerate

generate
for (n = 0; n < ADR_WIDTH; n = n+1) begin : ddrio_addr
ph1_ddrphy_pad # (
    .TYPE        ( "DDRAC"     ),
    .MAP_INFO    ( ADR_MAP[12*n +: 12] ),
    .LOOPBACK_EN ( LOOPBACK_EN )
) u_ddrio (

    .ctl_phy_clk      ( phy_clk    [4*ADR_MAP[12*n+8 +: 4] + ADR_MAP[12*n+4 +: 4]]   ),
    .ctl_clk_ac       ( ctlclk_ac  [4*ADR_MAP[12*n+8 +: 4] + ADR_MAP[12*n+4 +: 4]]   ),
    .ctl_clk_wdq      ( ctlclk_wdq [4*ADR_MAP[12*n+8 +: 4] + ADR_MAP[12*n+4 +: 4]]   ),
    .ctl_clk_dqs      ( ctlclk_dqs [4*ADR_MAP[12*n+8 +: 4] + ADR_MAP[12*n+4 +: 4]]   ),
    .ddr_clk_ac       ( ddrclk_ac  [4*ADR_MAP[12*n+8 +: 4] + ADR_MAP[12*n+4 +: 4]]   ),
    .ddr_clk_wdq      ( ddrclk_wdq [4*ADR_MAP[12*n+8 +: 4] + ADR_MAP[12*n+4 +: 4]]   ),
    .ddr_clk_dqs      ( ddrclk_dqs [4*ADR_MAP[12*n+8 +: 4] + ADR_MAP[12*n+4 +: 4]]   ),

    .ac_wr_rst_n      ( ac_wr_rst_n[4*ADR_MAP[12*n+8 +: 4] + ADR_MAP[12*n+4 +: 4]]  ),
    .dx_wr_rst_n      ( dx_wr_rst_n[4*ADR_MAP[12*n+8 +: 4] + ADR_MAP[12*n+4 +: 4]]  ),
    .ac_rd_rst_n      ( ac_rd_rst_n[4*ADR_MAP[12*n+8 +: 4] + ADR_MAP[12*n+4 +: 4]]  ),
    .dx_rd_rst_n      ( dx_rd_rst_n[4*ADR_MAP[12*n+8 +: 4] + ADR_MAP[12*n+4 +: 4]]  ),

    .wr_bdl_byp       ( wr_bdl_byp [4*13*ADR_MAP[12*n+8 +: 4] + 13*ADR_MAP[12*n+4 +: 4] +   ADR_MAP[12*n +: 4]]       ),
    .rd_bdl_byp       ( rd_bdl_byp [4*13*ADR_MAP[12*n+8 +: 4] + 13*ADR_MAP[12*n+4 +: 4] +   ADR_MAP[12*n +: 4]]       ),
    .wr_bdl_dly       ( wr_bdl_dly [4*78*ADR_MAP[12*n+8 +: 4] + 78*ADR_MAP[12*n+4 +: 4] + 6*ADR_MAP[12*n +: 4] +: 6]  ),
    .rd_bdl_dly       ( rd_bdl_dly [4*78*ADR_MAP[12*n+8 +: 4] + 78*ADR_MAP[12*n+4 +: 4] + 6*ADR_MAP[12*n +: 4] +: 6]  ),

    .doq              ( wdata      [4*104*ADR_MAP[12*n+8 +: 4] + 104*ADR_MAP[12*n+4 +: 4] + 8*ADR_MAP[12*n +: 4] +: 8]  ),

    .pdr_md           ( pdr_md     [4*26*ADR_MAP[12*n+8 +: 4] + 26*ADR_MAP[12*n+4 +: 4] + 2*ADR_MAP[12*n +: 4] +: 2]  ),
    .te_md            ( te_md      [4*26*ADR_MAP[12*n+8 +: 4] + 26*ADR_MAP[12*n+4 +: 4] + 2*ADR_MAP[12*n +: 4] +: 2]  ),
    .ts_md            ( oe_md      [4*26*ADR_MAP[12*n+8 +: 4] + 26*ADR_MAP[12*n+4 +: 4] + 2*ADR_MAP[12*n +: 4] +: 2]  ),

    .pdr_dq           ( pdr_dq     [4*ADR_MAP[12*n+8 +: 4] + ADR_MAP[12*n+4 +: 4]]  ),
    .pdr_dqs          ( pdr_dqs    [4*ADR_MAP[12*n+8 +: 4] + ADR_MAP[12*n+4 +: 4]]  ),
    .pdr_dqsn         ( pdr_dqsn   [4*ADR_MAP[12*n+8 +: 4] + ADR_MAP[12*n+4 +: 4]]  ),
    .ts_dq            ( oe_dq      [4*ADR_MAP[12*n+8 +: 4] + ADR_MAP[12*n+4 +: 4]]  ),
    .ts_dqs           ( oe_dqs     [4*ADR_MAP[12*n+8 +: 4] + ADR_MAP[12*n+4 +: 4]]  ),
    .ts_dqsn          ( oe_dqsn    [4*ADR_MAP[12*n+8 +: 4] + ADR_MAP[12*n+4 +: 4]]  ),
    .te_dq            ( te_dq      [4*ADR_MAP[12*n+8 +: 4] + ADR_MAP[12*n+4 +: 4]]  ),
    .te_dqs           ( te_dqs     [4*ADR_MAP[12*n+8 +: 4] + ADR_MAP[12*n+4 +: 4]]  ),
    .te_dqsn          ( te_dqsn    [4*ADR_MAP[12*n+8 +: 4] + ADR_MAP[12*n+4 +: 4]]  ),

    .pad              ( ddr_addr[n] )

);
end
endgenerate

generate
if (PAR_MAP != 12'hfff) begin : ddrio_par
ph1_ddrphy_pad # (
    .TYPE        ( "DDRAC"     ),
    .LOOPBACK_EN ( LOOPBACK_EN )
) u_ddrio (

    .ctl_phy_clk      ( phy_clk    [4*PAR_MAP[8 +: 4] + PAR_MAP[4 +: 4]]   ),
    .ctl_clk_ac       ( ctlclk_ac  [4*PAR_MAP[8 +: 4] + PAR_MAP[4 +: 4]]   ),
    .ctl_clk_wdq      ( ctlclk_wdq [4*PAR_MAP[8 +: 4] + PAR_MAP[4 +: 4]]   ),
    .ctl_clk_dqs      ( ctlclk_dqs [4*PAR_MAP[8 +: 4] + PAR_MAP[4 +: 4]]   ),
    .ddr_clk_ac       ( ddrclk_ac  [4*PAR_MAP[8 +: 4] + PAR_MAP[4 +: 4]]   ),
    .ddr_clk_wdq      ( ddrclk_wdq [4*PAR_MAP[8 +: 4] + PAR_MAP[4 +: 4]]   ),
    .ddr_clk_dqs      ( ddrclk_dqs [4*PAR_MAP[8 +: 4] + PAR_MAP[4 +: 4]]   ),

    .ac_wr_rst_n      ( ac_wr_rst_n[4*PAR_MAP[8 +: 4] + PAR_MAP[4 +: 4]]  ),
    .dx_wr_rst_n      ( dx_wr_rst_n[4*PAR_MAP[8 +: 4] + PAR_MAP[4 +: 4]]  ),
    .ac_rd_rst_n      ( ac_rd_rst_n[4*PAR_MAP[8 +: 4] + PAR_MAP[4 +: 4]]  ),
    .dx_rd_rst_n      ( dx_rd_rst_n[4*PAR_MAP[8 +: 4] + PAR_MAP[4 +: 4]]  ),

    .wr_bdl_byp       ( wr_bdl_byp [4*13*PAR_MAP[8 +: 4] + 13*PAR_MAP[4 +: 4] +   PAR_MAP[0 +: 4]]       ),
    .rd_bdl_byp       ( rd_bdl_byp [4*13*PAR_MAP[8 +: 4] + 13*PAR_MAP[4 +: 4] +   PAR_MAP[0 +: 4]]       ),
    .wr_bdl_dly       ( wr_bdl_dly [4*78*PAR_MAP[8 +: 4] + 78*PAR_MAP[4 +: 4] + 6*PAR_MAP[0 +: 4] +: 6]  ),
    .rd_bdl_dly       ( rd_bdl_dly [4*78*PAR_MAP[8 +: 4] + 78*PAR_MAP[4 +: 4] + 6*PAR_MAP[0 +: 4] +: 6]  ),

    .doq              ( wdata      [4*104*PAR_MAP[8 +: 4] + 104*PAR_MAP[4 +: 4] + 8*PAR_MAP[0 +: 4] +: 8]  ),

    .pdr_md           ( pdr_md     [4*26*PAR_MAP[8 +: 4] + 26*PAR_MAP[4 +: 4] + 2*PAR_MAP[0 +: 4] +: 2]  ),
    .te_md            ( te_md      [4*26*PAR_MAP[8 +: 4] + 26*PAR_MAP[4 +: 4] + 2*PAR_MAP[0 +: 4] +: 2]  ),
    .ts_md            ( oe_md      [4*26*PAR_MAP[8 +: 4] + 26*PAR_MAP[4 +: 4] + 2*PAR_MAP[0 +: 4] +: 2]  ),

    .pdr_dq           ( pdr_dq     [4*PAR_MAP[8 +: 4] + PAR_MAP[4 +: 4]]  ),
    .pdr_dqs          ( pdr_dqs    [4*PAR_MAP[8 +: 4] + PAR_MAP[4 +: 4]]  ),
    .pdr_dqsn         ( pdr_dqsn   [4*PAR_MAP[8 +: 4] + PAR_MAP[4 +: 4]]  ),
    .ts_dq            ( oe_dq      [4*PAR_MAP[8 +: 4] + PAR_MAP[4 +: 4]]  ),
    .ts_dqs           ( oe_dqs     [4*PAR_MAP[8 +: 4] + PAR_MAP[4 +: 4]]  ),
    .ts_dqsn          ( oe_dqsn    [4*PAR_MAP[8 +: 4] + PAR_MAP[4 +: 4]]  ),
    .te_dq            ( te_dq      [4*PAR_MAP[8 +: 4] + PAR_MAP[4 +: 4]]  ),
    .te_dqs           ( te_dqs     [4*PAR_MAP[8 +: 4] + PAR_MAP[4 +: 4]]  ),
    .te_dqsn          ( te_dqsn    [4*PAR_MAP[8 +: 4] + PAR_MAP[4 +: 4]]  ),

    .pad              ( ddr_parity )

);
end
endgenerate

generate
if (ALT_MAP != 12'hfff) begin : ddrio_alt
ph1_ddrphy_pad # (
    .TYPE        ( "DDRDQ"     ),
    .LOOPBACK_EN ( LOOPBACK_EN )
) u_ddrio (

    .ctl_phy_clk      ( phy_clk    [4*ALT_MAP[8 +: 4] + ALT_MAP[4 +: 4]]   ),
    .ctl_clk_ac       ( ctlclk_ac  [4*ALT_MAP[8 +: 4] + ALT_MAP[4 +: 4]]   ),
    .ctl_clk_wdq      ( ctlclk_wdq [4*ALT_MAP[8 +: 4] + ALT_MAP[4 +: 4]]   ),
    .ctl_clk_dqs      ( ctlclk_dqs [4*ALT_MAP[8 +: 4] + ALT_MAP[4 +: 4]]   ),
    .ddr_clk_ac       ( ddrclk_ac  [4*ALT_MAP[8 +: 4] + ALT_MAP[4 +: 4]]   ),
    .ddr_clk_wdq      ( ddrclk_wdq [4*ALT_MAP[8 +: 4] + ALT_MAP[4 +: 4]]   ),
    .ddr_clk_dqs      ( ddrclk_dqs [4*ALT_MAP[8 +: 4] + ALT_MAP[4 +: 4]]   ),

    .ac_wr_rst_n      ( ac_wr_rst_n[4*ALT_MAP[8 +: 4] + ALT_MAP[4 +: 4]]  ),
    .dx_wr_rst_n      ( dx_wr_rst_n[4*ALT_MAP[8 +: 4] + ALT_MAP[4 +: 4]]  ),
    .ac_rd_rst_n      ( ac_rd_rst_n[4*ALT_MAP[8 +: 4] + ALT_MAP[4 +: 4]]  ),
    .dx_rd_rst_n      ( dx_rd_rst_n[4*ALT_MAP[8 +: 4] + ALT_MAP[4 +: 4]]  ),

    .wr_bdl_byp       ( wr_bdl_byp [4*13*ALT_MAP[8 +: 4] + 13*ALT_MAP[4 +: 4] +   ALT_MAP[0 +: 4]]       ),
    .rd_bdl_byp       ( rd_bdl_byp [4*13*ALT_MAP[8 +: 4] + 13*ALT_MAP[4 +: 4] +   ALT_MAP[0 +: 4]]       ),
    .wr_bdl_dly       ( wr_bdl_dly [4*78*ALT_MAP[8 +: 4] + 78*ALT_MAP[4 +: 4] + 6*ALT_MAP[0 +: 4] +: 6]  ),
    .rd_bdl_dly       ( rd_bdl_dly [4*78*ALT_MAP[8 +: 4] + 78*ALT_MAP[4 +: 4] + 6*ALT_MAP[0 +: 4] +: 6]  ),

    .diq              ( rdata      [4*104*ALT_MAP[8 +: 4] + 104*ALT_MAP[4 +: 4] + 8*ALT_MAP[0 +: 4] +: 8]  ),
    .indd             ( indd       [4* 13*ALT_MAP[8 +: 4] +  13*ALT_MAP[4 +: 4] +   ALT_MAP[0 +: 4]]       ),

    .pdr_md           ( pdr_md     [4*26*ALT_MAP[8 +: 4] + 26*ALT_MAP[4 +: 4] + 2*ALT_MAP[0 +: 4] +: 2]  ),
    .te_md            ( te_md      [4*26*ALT_MAP[8 +: 4] + 26*ALT_MAP[4 +: 4] + 2*ALT_MAP[0 +: 4] +: 2]  ),
    .ts_md            ( oe_md      [4*26*ALT_MAP[8 +: 4] + 26*ALT_MAP[4 +: 4] + 2*ALT_MAP[0 +: 4] +: 2]  ),

    .pdr_dq           ( pdr_dq     [4*ALT_MAP[8 +: 4] + ALT_MAP[4 +: 4]]  ),
    .pdr_dqs          ( pdr_dqs    [4*ALT_MAP[8 +: 4] + ALT_MAP[4 +: 4]]  ),
    .pdr_dqsn         ( pdr_dqsn   [4*ALT_MAP[8 +: 4] + ALT_MAP[4 +: 4]]  ),
    .ts_dq            ( oe_dq      [4*ALT_MAP[8 +: 4] + ALT_MAP[4 +: 4]]  ),
    .ts_dqs           ( oe_dqs     [4*ALT_MAP[8 +: 4] + ALT_MAP[4 +: 4]]  ),
    .ts_dqsn          ( oe_dqsn    [4*ALT_MAP[8 +: 4] + ALT_MAP[4 +: 4]]  ),
    .te_dq            ( te_dq      [4*ALT_MAP[8 +: 4] + ALT_MAP[4 +: 4]]  ),
    .te_dqs           ( te_dqs     [4*ALT_MAP[8 +: 4] + ALT_MAP[4 +: 4]]  ),
    .te_dqsn          ( te_dqsn    [4*ALT_MAP[8 +: 4] + ALT_MAP[4 +: 4]]  ),

    .pad              ( ddr_alert_n )

);
end
endgenerate

generate
for (n = 0; n < DQS_WIDTH; n = n+1) begin : ddrio_dqs
ph1_ddrphy_pad # (
    .TYPE        ("DDRDQSP"    ),
    .MAP_INFO    ( DQS_MAP[12*(2*n+0) +: 12] ),
    .LOOPBACK_EN ( LOOPBACK_EN )
) u_ddrio_p (

    .ctl_phy_clk      ( phy_clk    [4*DQS_MAP[12*(2*n+0)+8 +: 4] + DQS_MAP[12*(2*n+0)+4 +: 4]]   ),
    .ctl_clk_ac       ( ctlclk_ac  [4*DQS_MAP[12*(2*n+0)+8 +: 4] + DQS_MAP[12*(2*n+0)+4 +: 4]]   ),
    .ctl_clk_wdq      ( ctlclk_wdq [4*DQS_MAP[12*(2*n+0)+8 +: 4] + DQS_MAP[12*(2*n+0)+4 +: 4]]   ),
    .ctl_clk_dqs      ( ctlclk_dqs [4*DQS_MAP[12*(2*n+0)+8 +: 4] + DQS_MAP[12*(2*n+0)+4 +: 4]]   ),
    .ddr_clk_ac       ( ddrclk_ac  [4*DQS_MAP[12*(2*n+0)+8 +: 4] + DQS_MAP[12*(2*n+0)+4 +: 4]]   ),
    .ddr_clk_wdq      ( ddrclk_wdq [4*DQS_MAP[12*(2*n+0)+8 +: 4] + DQS_MAP[12*(2*n+0)+4 +: 4]]   ),
    .ddr_clk_dqs      ( ddrclk_dqs [4*DQS_MAP[12*(2*n+0)+8 +: 4] + DQS_MAP[12*(2*n+0)+4 +: 4]]   ),

    .ac_wr_rst_n      ( ac_wr_rst_n[4*DQS_MAP[12*(2*n+0)+8 +: 4] + DQS_MAP[12*(2*n+0)+4 +: 4]]  ),
    .dx_wr_rst_n      ( dx_wr_rst_n[4*DQS_MAP[12*(2*n+0)+8 +: 4] + DQS_MAP[12*(2*n+0)+4 +: 4]]  ),
    .ac_rd_rst_n      ( ac_rd_rst_n[4*DQS_MAP[12*(2*n+0)+8 +: 4] + DQS_MAP[12*(2*n+0)+4 +: 4]]  ),
    .dx_rd_rst_n      ( dx_rd_rst_n[4*DQS_MAP[12*(2*n+0)+8 +: 4] + DQS_MAP[12*(2*n+0)+4 +: 4]]  ),

    .wr_bdl_byp       ( wr_bdl_byp [4*13*DQS_MAP[12*(2*n+0)+8 +: 4] + 13*DQS_MAP[12*(2*n+0)+4 +: 4] +   DQS_MAP[12*(2*n+0) +: 4]]       ),
    .rd_bdl_byp       ( rd_bdl_byp [4*13*DQS_MAP[12*(2*n+0)+8 +: 4] + 13*DQS_MAP[12*(2*n+0)+4 +: 4] +   DQS_MAP[12*(2*n+0) +: 4]]       ),
    .wr_bdl_dly       ( wr_bdl_dly [4*78*DQS_MAP[12*(2*n+0)+8 +: 4] + 78*DQS_MAP[12*(2*n+0)+4 +: 4] + 6*DQS_MAP[12*(2*n+0) +: 4] +: 6]  ),
    .rd_bdl_dly       ( rd_bdl_dly [4*78*DQS_MAP[12*(2*n+0)+8 +: 4] + 78*DQS_MAP[12*(2*n+0)+4 +: 4] + 6*DQS_MAP[12*(2*n+0) +: 4] +: 6]  ),

    .doq              ( wdata      [4*104*DQS_MAP[12*(2*n+0)+8 +: 4] + 104*DQS_MAP[12*(2*n+0)+4 +: 4] + 8*DQS_MAP[12*(2*n+0) +: 4] +: 8]  ),
    .diq              ( rdata      [4*104*DQS_MAP[12*(2*n+0)+8 +: 4] + 104*DQS_MAP[12*(2*n+0)+4 +: 4] + 8*DQS_MAP[12*(2*n+0) +: 4] +: 8]  ),
    .indd             ( indd       [4* 13*DQS_MAP[12*(2*n+0)+8 +: 4] +  13*DQS_MAP[12*(2*n+0)+4 +: 4] +   DQS_MAP[12*(2*n+0) +: 4]]       ),

    .rdqs_o           ( rdqs_p     [4*DQS_MAP[12*(2*n+0)+8 +: 4] + DQS_MAP[12*(2*n+0)+4 +: 4]]  ),
    .rdqs_p           ( rdqs_r     [4*DQS_MAP[12*(2*n+0)+8 +: 4] + DQS_MAP[12*(2*n+0)+4 +: 4]]  ),
    .rdqs_n           ( rdqs_f     [4*DQS_MAP[12*(2*n+0)+8 +: 4] + DQS_MAP[12*(2*n+0)+4 +: 4]]  ),

    .pdr_md           ( pdr_md     [4*26*DQS_MAP[12*(2*n+0)+8 +: 4] + 26*DQS_MAP[12*(2*n+0)+4 +: 4] + 2*DQS_MAP[12*(2*n+0) +: 4] +: 2]  ),
    .te_md            ( te_md      [4*26*DQS_MAP[12*(2*n+0)+8 +: 4] + 26*DQS_MAP[12*(2*n+0)+4 +: 4] + 2*DQS_MAP[12*(2*n+0) +: 4] +: 2]  ),
    .ts_md            ( oe_md      [4*26*DQS_MAP[12*(2*n+0)+8 +: 4] + 26*DQS_MAP[12*(2*n+0)+4 +: 4] + 2*DQS_MAP[12*(2*n+0) +: 4] +: 2]  ),

    .pdr_dq           ( pdr_dq     [4*DQS_MAP[12*(2*n+0)+8 +: 4] + DQS_MAP[12*(2*n+0)+4 +: 4]]  ),
    .pdr_dqs          ( pdr_dqs    [4*DQS_MAP[12*(2*n+0)+8 +: 4] + DQS_MAP[12*(2*n+0)+4 +: 4]]  ),
    .pdr_dqsn         ( pdr_dqsn   [4*DQS_MAP[12*(2*n+0)+8 +: 4] + DQS_MAP[12*(2*n+0)+4 +: 4]]  ),
    .ts_dq            ( oe_dq      [4*DQS_MAP[12*(2*n+0)+8 +: 4] + DQS_MAP[12*(2*n+0)+4 +: 4]]  ),
    .ts_dqs           ( oe_dqs     [4*DQS_MAP[12*(2*n+0)+8 +: 4] + DQS_MAP[12*(2*n+0)+4 +: 4]]  ),
    .ts_dqsn          ( oe_dqsn    [4*DQS_MAP[12*(2*n+0)+8 +: 4] + DQS_MAP[12*(2*n+0)+4 +: 4]]  ),
    .te_dq            ( te_dq      [4*DQS_MAP[12*(2*n+0)+8 +: 4] + DQS_MAP[12*(2*n+0)+4 +: 4]]  ),
    .te_dqs           ( te_dqs     [4*DQS_MAP[12*(2*n+0)+8 +: 4] + DQS_MAP[12*(2*n+0)+4 +: 4]]  ),
    .te_dqsn          ( te_dqsn    [4*DQS_MAP[12*(2*n+0)+8 +: 4] + DQS_MAP[12*(2*n+0)+4 +: 4]]  ),

    .pad              ( ddr_dqs_p[n] )
);

ph1_ddrphy_pad # (
    .TYPE        ("DDRDQSN"    ),
    .MAP_INFO    ( DQS_MAP[12*(2*n+1) +: 12] ),
    .LOOPBACK_EN ( LOOPBACK_EN )
) u_ddrio_n (

    .ctl_phy_clk      ( phy_clk    [4*DQS_MAP[12*(2*n+1)+8 +: 4] + DQS_MAP[12*(2*n+1)+4 +: 4]]   ),
    .ctl_clk_ac       ( ctlclk_ac  [4*DQS_MAP[12*(2*n+1)+8 +: 4] + DQS_MAP[12*(2*n+1)+4 +: 4]]   ),
    .ctl_clk_wdq      ( ctlclk_wdq [4*DQS_MAP[12*(2*n+1)+8 +: 4] + DQS_MAP[12*(2*n+1)+4 +: 4]]   ),
    .ctl_clk_dqs      ( ctlclk_dqs [4*DQS_MAP[12*(2*n+1)+8 +: 4] + DQS_MAP[12*(2*n+1)+4 +: 4]]   ),
    .ddr_clk_ac       ( ddrclk_ac  [4*DQS_MAP[12*(2*n+1)+8 +: 4] + DQS_MAP[12*(2*n+1)+4 +: 4]]   ),
    .ddr_clk_wdq      ( ddrclk_wdq [4*DQS_MAP[12*(2*n+1)+8 +: 4] + DQS_MAP[12*(2*n+1)+4 +: 4]]   ),
    .ddr_clk_dqs      ( ddrclk_dqs [4*DQS_MAP[12*(2*n+1)+8 +: 4] + DQS_MAP[12*(2*n+1)+4 +: 4]]   ),

    .ac_wr_rst_n      ( ac_wr_rst_n[4*DQS_MAP[12*(2*n+1)+8 +: 4] + DQS_MAP[12*(2*n+1)+4 +: 4]]  ),
    .dx_wr_rst_n      ( dx_wr_rst_n[4*DQS_MAP[12*(2*n+1)+8 +: 4] + DQS_MAP[12*(2*n+1)+4 +: 4]]  ),
    .ac_rd_rst_n      ( ac_rd_rst_n[4*DQS_MAP[12*(2*n+1)+8 +: 4] + DQS_MAP[12*(2*n+1)+4 +: 4]]  ),
    .dx_rd_rst_n      ( dx_rd_rst_n[4*DQS_MAP[12*(2*n+1)+8 +: 4] + DQS_MAP[12*(2*n+1)+4 +: 4]]  ),

    .wr_bdl_byp       ( wr_bdl_byp [4*13*DQS_MAP[12*(2*n+1)+8 +: 4] + 13*DQS_MAP[12*(2*n+1)+4 +: 4] +   DQS_MAP[12*(2*n+1) +: 4]]       ),
    .rd_bdl_byp       ( rd_bdl_byp [4*13*DQS_MAP[12*(2*n+1)+8 +: 4] + 13*DQS_MAP[12*(2*n+1)+4 +: 4] +   DQS_MAP[12*(2*n+1) +: 4]]       ),
    .wr_bdl_dly       ( wr_bdl_dly [4*78*DQS_MAP[12*(2*n+1)+8 +: 4] + 78*DQS_MAP[12*(2*n+1)+4 +: 4] + 6*DQS_MAP[12*(2*n+1) +: 4] +: 6]  ),
    .rd_bdl_dly       ( rd_bdl_dly [4*78*DQS_MAP[12*(2*n+1)+8 +: 4] + 78*DQS_MAP[12*(2*n+1)+4 +: 4] + 6*DQS_MAP[12*(2*n+1) +: 4] +: 6]  ),

    .doq              ( wdata      [4*104*DQS_MAP[12*(2*n+1)+8 +: 4] + 104*DQS_MAP[12*(2*n+1)+4 +: 4] + 8*DQS_MAP[12*(2*n+1) +: 4] +: 8]  ),
    .diq              ( rdata      [4*104*DQS_MAP[12*(2*n+1)+8 +: 4] + 104*DQS_MAP[12*(2*n+1)+4 +: 4] + 8*DQS_MAP[12*(2*n+1) +: 4] +: 8]  ),
    .indd             ( indd       [4* 13*DQS_MAP[12*(2*n+1)+8 +: 4] +  13*DQS_MAP[12*(2*n+1)+4 +: 4] +   DQS_MAP[12*(2*n+1) +: 4]]       ),

    .rdqs_o           ( rdqs_n     [4*DQS_MAP[12*(2*n+1)+8 +: 4] + DQS_MAP[12*(2*n+1)+4 +: 4]]  ),
    .rdqs_p           ( rdqs_r     [4*DQS_MAP[12*(2*n+1)+8 +: 4] + DQS_MAP[12*(2*n+1)+4 +: 4]]  ),
    .rdqs_n           ( rdqs_f     [4*DQS_MAP[12*(2*n+1)+8 +: 4] + DQS_MAP[12*(2*n+1)+4 +: 4]]  ),

    .pdr_md           ( pdr_md     [4*26*DQS_MAP[12*(2*n+1)+8 +: 4] + 26*DQS_MAP[12*(2*n+1)+4 +: 4] + 2*DQS_MAP[12*(2*n+1) +: 4] +: 2]  ),
    .te_md            ( te_md      [4*26*DQS_MAP[12*(2*n+1)+8 +: 4] + 26*DQS_MAP[12*(2*n+1)+4 +: 4] + 2*DQS_MAP[12*(2*n+1) +: 4] +: 2]  ),
    .ts_md            ( oe_md      [4*26*DQS_MAP[12*(2*n+1)+8 +: 4] + 26*DQS_MAP[12*(2*n+1)+4 +: 4] + 2*DQS_MAP[12*(2*n+1) +: 4] +: 2]  ),

    .pdr_dq           ( pdr_dq     [4*DQS_MAP[12*(2*n+1)+8 +: 4] + DQS_MAP[12*(2*n+1)+4 +: 4]]  ),
    .pdr_dqs          ( pdr_dqs    [4*DQS_MAP[12*(2*n+1)+8 +: 4] + DQS_MAP[12*(2*n+1)+4 +: 4]]  ),
    .pdr_dqsn         ( pdr_dqsn   [4*DQS_MAP[12*(2*n+1)+8 +: 4] + DQS_MAP[12*(2*n+1)+4 +: 4]]  ),
    .ts_dq            ( oe_dq      [4*DQS_MAP[12*(2*n+1)+8 +: 4] + DQS_MAP[12*(2*n+1)+4 +: 4]]  ),
    .ts_dqs           ( oe_dqs     [4*DQS_MAP[12*(2*n+1)+8 +: 4] + DQS_MAP[12*(2*n+1)+4 +: 4]]  ),
    .ts_dqsn          ( oe_dqsn    [4*DQS_MAP[12*(2*n+1)+8 +: 4] + DQS_MAP[12*(2*n+1)+4 +: 4]]  ),
    .te_dq            ( te_dq      [4*DQS_MAP[12*(2*n+1)+8 +: 4] + DQS_MAP[12*(2*n+1)+4 +: 4]]  ),
    .te_dqs           ( te_dqs     [4*DQS_MAP[12*(2*n+1)+8 +: 4] + DQS_MAP[12*(2*n+1)+4 +: 4]]  ),
    .te_dqsn          ( te_dqsn    [4*DQS_MAP[12*(2*n+1)+8 +: 4] + DQS_MAP[12*(2*n+1)+4 +: 4]]  ),

    .pad              ( ddr_dqs_n[n] )
);

end
endgenerate

generate
for (n = 0; n < DQ_WIDTH; n = n+1) begin : ddrio_dq
ph1_ddrphy_pad # (
    .TYPE        ( "DDRDQ"     ),
    .MAP_INFO    ( DQ_MAP[12*n +: 12] ),
    .LOOPBACK_EN ( LOOPBACK_EN )
) u_ddrio (

    .ctl_phy_clk      ( phy_clk    [4*DQ_MAP[12*n+8 +: 4] + DQ_MAP[12*n+4 +: 4]]   ),
    .ctl_clk_ac       ( ctlclk_ac  [4*DQ_MAP[12*n+8 +: 4] + DQ_MAP[12*n+4 +: 4]]   ),
    .ctl_clk_wdq      ( ctlclk_wdq [4*DQ_MAP[12*n+8 +: 4] + DQ_MAP[12*n+4 +: 4]]   ),
    .ctl_clk_dqs      ( ctlclk_dqs [4*DQ_MAP[12*n+8 +: 4] + DQ_MAP[12*n+4 +: 4]]   ),
    .ddr_clk_ac       ( ddrclk_ac  [4*DQ_MAP[12*n+8 +: 4] + DQ_MAP[12*n+4 +: 4]]   ),
    .ddr_clk_wdq      ( ddrclk_wdq [4*DQ_MAP[12*n+8 +: 4] + DQ_MAP[12*n+4 +: 4]]   ),
    .ddr_clk_dqs      ( ddrclk_dqs [4*DQ_MAP[12*n+8 +: 4] + DQ_MAP[12*n+4 +: 4]]   ),

    .ac_wr_rst_n      ( ac_wr_rst_n[4*DQ_MAP[12*n+8 +: 4] + DQ_MAP[12*n+4 +: 4]]  ),
    .dx_wr_rst_n      ( dx_wr_rst_n[4*DQ_MAP[12*n+8 +: 4] + DQ_MAP[12*n+4 +: 4]]  ),
    .ac_rd_rst_n      ( ac_rd_rst_n[4*DQ_MAP[12*n+8 +: 4] + DQ_MAP[12*n+4 +: 4]]  ),
    .dx_rd_rst_n      ( dx_rd_rst_n[4*DQ_MAP[12*n+8 +: 4] + DQ_MAP[12*n+4 +: 4]]  ),

    .wr_bdl_byp       ( wr_bdl_byp [4*13*DQ_MAP[12*n+8 +: 4] + 13*DQ_MAP[12*n+4 +: 4] +   DQ_MAP[12*n +: 4]]       ),
    .rd_bdl_byp       ( rd_bdl_byp [4*13*DQ_MAP[12*n+8 +: 4] + 13*DQ_MAP[12*n+4 +: 4] +   DQ_MAP[12*n +: 4]]       ),
    .wr_bdl_dly       ( wr_bdl_dly [4*78*DQ_MAP[12*n+8 +: 4] + 78*DQ_MAP[12*n+4 +: 4] + 6*DQ_MAP[12*n +: 4] +: 6]  ),
    .rd_bdl_dly       ( rd_bdl_dly [4*78*DQ_MAP[12*n+8 +: 4] + 78*DQ_MAP[12*n+4 +: 4] + 6*DQ_MAP[12*n +: 4] +: 6]  ),

    .doq              ( wdata      [4*104*DQ_MAP[12*n+8 +: 4] + 104*DQ_MAP[12*n+4 +: 4] + 8*DQ_MAP[12*n +: 4] +: 8]  ),
    .diq              ( rdata      [4*104*DQ_MAP[12*n+8 +: 4] + 104*DQ_MAP[12*n+4 +: 4] + 8*DQ_MAP[12*n +: 4] +: 8]  ),
    .indd             ( indd       [4* 13*DQ_MAP[12*n+8 +: 4] +  13*DQ_MAP[12*n+4 +: 4] +   DQ_MAP[12*n +: 4]]       ),

    .rdqs_p           ( rdqs_r     [4*DQ_MAP[12*n+8 +: 4] + DQ_MAP[12*n+4 +: 4]]  ),
    .rdqs_n           ( rdqs_f     [4*DQ_MAP[12*n+8 +: 4] + DQ_MAP[12*n+4 +: 4]]  ),

    .pdr_md           ( pdr_md     [4*26*DQ_MAP[12*n+8 +: 4] + 26*DQ_MAP[12*n+4 +: 4] + 2*DQ_MAP[12*n +: 4] +: 2]  ),
    .te_md            ( te_md      [4*26*DQ_MAP[12*n+8 +: 4] + 26*DQ_MAP[12*n+4 +: 4] + 2*DQ_MAP[12*n +: 4] +: 2]  ),
    .ts_md            ( oe_md      [4*26*DQ_MAP[12*n+8 +: 4] + 26*DQ_MAP[12*n+4 +: 4] + 2*DQ_MAP[12*n +: 4] +: 2]  ),

    .pdr_dq           ( pdr_dq     [4*DQ_MAP[12*n+8 +: 4] + DQ_MAP[12*n+4 +: 4]]  ),
    .pdr_dqs          ( pdr_dqs    [4*DQ_MAP[12*n+8 +: 4] + DQ_MAP[12*n+4 +: 4]]  ),
    .pdr_dqsn         ( pdr_dqsn   [4*DQ_MAP[12*n+8 +: 4] + DQ_MAP[12*n+4 +: 4]]  ),
    .ts_dq            ( oe_dq      [4*DQ_MAP[12*n+8 +: 4] + DQ_MAP[12*n+4 +: 4]]  ),
    .ts_dqs           ( oe_dqs     [4*DQ_MAP[12*n+8 +: 4] + DQ_MAP[12*n+4 +: 4]]  ),
    .ts_dqsn          ( oe_dqsn    [4*DQ_MAP[12*n+8 +: 4] + DQ_MAP[12*n+4 +: 4]]  ),
    .te_dq            ( te_dq      [4*DQ_MAP[12*n+8 +: 4] + DQ_MAP[12*n+4 +: 4]]  ),
    .te_dqs           ( te_dqs     [4*DQ_MAP[12*n+8 +: 4] + DQ_MAP[12*n+4 +: 4]]  ),
    .te_dqsn          ( te_dqsn    [4*DQ_MAP[12*n+8 +: 4] + DQ_MAP[12*n+4 +: 4]]  ),

    .pad              ( ddr_dq[n] )

);
end
endgenerate

generate
if ((WDM == "ENABLE") || (WDBI == "ENABLE") || (RDBI == "ENABLE")) begin : dm_en
for (n = 0; n < DM_WIDTH; n = n+1) begin : ddrio_dm
ph1_ddrphy_pad # (
    .TYPE        ( "DDRDQ"     ),
    .MAP_INFO    ( DM_MAP[12*n +: 12] ),
    .LOOPBACK_EN ( LOOPBACK_EN )
) u_ddrio (

    .ctl_phy_clk      ( phy_clk    [4*DM_MAP[12*n+8 +: 4] + DM_MAP[12*n+4 +: 4]]   ),
    .ctl_clk_ac       ( ctlclk_ac  [4*DM_MAP[12*n+8 +: 4] + DM_MAP[12*n+4 +: 4]]   ),
    .ctl_clk_wdq      ( ctlclk_wdq [4*DM_MAP[12*n+8 +: 4] + DM_MAP[12*n+4 +: 4]]   ),
    .ctl_clk_dqs      ( ctlclk_dqs [4*DM_MAP[12*n+8 +: 4] + DM_MAP[12*n+4 +: 4]]   ),
    .ddr_clk_ac       ( ddrclk_ac  [4*DM_MAP[12*n+8 +: 4] + DM_MAP[12*n+4 +: 4]]   ),
    .ddr_clk_wdq      ( ddrclk_wdq [4*DM_MAP[12*n+8 +: 4] + DM_MAP[12*n+4 +: 4]]   ),
    .ddr_clk_dqs      ( ddrclk_dqs [4*DM_MAP[12*n+8 +: 4] + DM_MAP[12*n+4 +: 4]]   ),

    .ac_wr_rst_n      ( ac_wr_rst_n[4*DM_MAP[12*n+8 +: 4] + DM_MAP[12*n+4 +: 4]]  ),
    .dx_wr_rst_n      ( dx_wr_rst_n[4*DM_MAP[12*n+8 +: 4] + DM_MAP[12*n+4 +: 4]]  ),
    .ac_rd_rst_n      ( ac_rd_rst_n[4*DM_MAP[12*n+8 +: 4] + DM_MAP[12*n+4 +: 4]]  ),
    .dx_rd_rst_n      ( dx_rd_rst_n[4*DM_MAP[12*n+8 +: 4] + DM_MAP[12*n+4 +: 4]]  ),

    .wr_bdl_byp       ( wr_bdl_byp [4*13*DM_MAP[12*n+8 +: 4] + 13*DM_MAP[12*n+4 +: 4] +   DM_MAP[12*n +: 4]]       ),
    .rd_bdl_byp       ( rd_bdl_byp [4*13*DM_MAP[12*n+8 +: 4] + 13*DM_MAP[12*n+4 +: 4] +   DM_MAP[12*n +: 4]]       ),
    .wr_bdl_dly       ( wr_bdl_dly [4*78*DM_MAP[12*n+8 +: 4] + 78*DM_MAP[12*n+4 +: 4] + 6*DM_MAP[12*n +: 4] +: 6]  ),
    .rd_bdl_dly       ( rd_bdl_dly [4*78*DM_MAP[12*n+8 +: 4] + 78*DM_MAP[12*n+4 +: 4] + 6*DM_MAP[12*n +: 4] +: 6]  ),

    .doq              ( wdata      [4*104*DM_MAP[12*n+8 +: 4] + 104*DM_MAP[12*n+4 +: 4] + 8*DM_MAP[12*n +: 4] +: 8]  ),
    .diq              ( rdata      [4*104*DM_MAP[12*n+8 +: 4] + 104*DM_MAP[12*n+4 +: 4] + 8*DM_MAP[12*n +: 4] +: 8]  ),
    .indd             ( indd       [4* 13*DM_MAP[12*n+8 +: 4] +  13*DM_MAP[12*n+4 +: 4] +   DM_MAP[12*n +: 4]]       ),

    .rdqs_p           ( rdqs_r     [4*DM_MAP[12*n+8 +: 4] + DM_MAP[12*n+4 +: 4]]  ),
    .rdqs_n           ( rdqs_f     [4*DM_MAP[12*n+8 +: 4] + DM_MAP[12*n+4 +: 4]]  ),

    .pdr_md           ( pdr_md     [4*26*DM_MAP[12*n+8 +: 4] + 26*DM_MAP[12*n+4 +: 4] + 2*DM_MAP[12*n +: 4] +: 2]  ),
    .te_md            ( te_md      [4*26*DM_MAP[12*n+8 +: 4] + 26*DM_MAP[12*n+4 +: 4] + 2*DM_MAP[12*n +: 4] +: 2]  ),
    .ts_md            ( oe_md      [4*26*DM_MAP[12*n+8 +: 4] + 26*DM_MAP[12*n+4 +: 4] + 2*DM_MAP[12*n +: 4] +: 2]  ),

    .pdr_dq           ( pdr_dq     [4*DM_MAP[12*n+8 +: 4] + DM_MAP[12*n+4 +: 4]]  ),
    .pdr_dqs          ( pdr_dqs    [4*DM_MAP[12*n+8 +: 4] + DM_MAP[12*n+4 +: 4]]  ),
    .pdr_dqsn         ( pdr_dqsn   [4*DM_MAP[12*n+8 +: 4] + DM_MAP[12*n+4 +: 4]]  ),
    .ts_dq            ( oe_dq      [4*DM_MAP[12*n+8 +: 4] + DM_MAP[12*n+4 +: 4]]  ),
    .ts_dqs           ( oe_dqs     [4*DM_MAP[12*n+8 +: 4] + DM_MAP[12*n+4 +: 4]]  ),
    .ts_dqsn          ( oe_dqsn    [4*DM_MAP[12*n+8 +: 4] + DM_MAP[12*n+4 +: 4]]  ),
    .te_dq            ( te_dq      [4*DM_MAP[12*n+8 +: 4] + DM_MAP[12*n+4 +: 4]]  ),
    .te_dqs           ( te_dqs     [4*DM_MAP[12*n+8 +: 4] + DM_MAP[12*n+4 +: 4]]  ),
    .te_dqsn          ( te_dqsn    [4*DM_MAP[12*n+8 +: 4] + DM_MAP[12*n+4 +: 4]]  ),

    .pad              ( ddr_dm[n] )

);
end
end
endgenerate

endmodule

`timescale 1ps / 1ps

module ph1_ddrphy_pad # (
    parameter TYPE        = "DDRAC",
    parameter MAP_INFO    = 12'h000,
    parameter LOOPBACK_EN = "DISABLE"
)(

    input         ctl_phy_clk      ,
    input         ctl_clk_ac       ,
    input         ctl_clk_wdq      ,
    input         ctl_clk_dqs      ,
    input         ddr_clk_ac       ,
    input         ddr_clk_wdq      ,
    input         ddr_clk_dqs      ,

    input         ac_wr_rst_n      ,
    input         dx_wr_rst_n      ,
    input         ac_rd_rst_n      ,
    input         dx_rd_rst_n      ,

    input         wr_bdl_byp       ,
    input         rd_bdl_byp       ,
    input  [5:0]  wr_bdl_dly       ,
    input  [5:0]  rd_bdl_dly       ,

    input  [7:0]  doq              ,
    output [7:0]  diq              ,
    output        indd             ,

    output        rdqs_o           ,
    input         rdqs_p           ,
    input         rdqs_n           ,

    input  [1:0]  pdr_md           ,
    input  [1:0]  te_md            ,
    input  [1:0]  ts_md            ,
    input         pdr_dq           ,
    input         pdr_dqs          ,
    input         pdr_dqsn         ,
    input         ts_dq            ,
    input         ts_dqs           ,
    input         ts_dqsn          ,
    input         te_dq            ,
    input         te_dqs           ,
    input         te_dqsn          ,

    inout         pad

);

localparam MODE       = (TYPE == "DDRAC") ? "OUT" : "BI";
localparam DDRIO_TYPE = (TYPE == "DDRAC") ? "AC"  : "DX";

localparam OSCLK_SEL  = (TYPE == "DDRAC") ? "DDR_CLK_IO" : (TYPE == "DDRDQ") ? "DDR_CLK_WDQ" : "DDR_CLK_WL";
localparam OPCLK_SEL  = (TYPE == "DDRAC") ? "CTL_CLK_IO" : (TYPE == "DDRDQ") ? "CTL_CLK_WDQ" : "CTL_CLK_WL";

localparam PDR_SEL    = (TYPE == "DDRDQSP") ? "DQS" : (TYPE == "DDRDQSN") ? "DQSN" : "DQAC";
localparam TS_SEL     = (TYPE == "DDRDQSP") ? "DQS" : (TYPE == "DDRDQSN") ? "DQSN" : "DQAC";
localparam ODT_SEL    = (TYPE == "DDRDQSP") ? "DQS" : (TYPE == "DDRDQSN") ? "DQSN" : "DQAC";

localparam DQS_PUPD   = (TYPE == "DDRDQSP") ? "PD" : "PU";

PH1_PHY_DDR_PAD #(
    .APPS                    ( "DDR_DRAM"      ),
    .DATA_WIDTH              ( "X8"            ),
    .MODE                    (  MODE           ),
    .SIGTYPE                 (  DDRIO_TYPE     ),
    .DDR_SIGNAL_TYPE         (  DDRIO_TYPE     ),
    .OSCLK_SEL               (  OSCLK_SEL      ),
    .OPCLK_SEL               (  OPCLK_SEL      ),

    .PDR_MODE_SEL            (  PDR_SEL        ),
    .ODT_SRC_SEL             (  ODT_SEL        ),
    .TS_SEL                  (  TS_SEL         ),

    .DQS_PUPD                (  DQS_PUPD       ),
    .DQS_PUPD_STRENGTH       ( "MED"           ),

    .LOOPBACK_EN             (  LOOPBACK_EN    ),
    .DDR_RST_TYPE            ( "ASYNC"         ),
    .DATA_OUT_SYNC           ( "SYNC_DISABLE"  ),
    .DLY_TEST_EN             ( "DISABLE"       ),
    .VREF_EXT_IN             ( "DISABLE"       ),
    .DISABLE_GSR             ( "ENABLE"        ),

    .IOCLK0D2S               ( "DISABLE"       ),
    .IOCLK1D2S               ( "DISABLE"       ),
    .IOCLK2D2S               ( "DISABLE"       ),
    .IOCLK3D2S               ( "DISABLE"       ),

    .OUTPUT_IMP              (  60             ),
    .ODT                     (  120            ),

    .OUTDEL                  (  0              ),
    .INDEL                   (  0              ),
    .OUTDELMUX               ( "DDR_DRAM"      ),
    .INDELMUX                ( "DDR_DRAM"      )
) u_ddrphy_pad (

    .ctl_phy_clk             ( ctl_phy_clk       ),

    .ctl_clk_ac              ( ctl_clk_ac        ),
    .ctl_clk_dqs             ( ctl_clk_dqs       ),
    .ctl_clk_wdq             ( ctl_clk_wdq       ),
    .ddr_clk_ac              ( ddr_clk_ac        ),
    .ddr_clk_dqs             ( ddr_clk_dqs       ),
    .ddr_clk_wdq             ( ddr_clk_wdq       ),
    .qs_n_div                (                   ),

    .wr_path_rstn_low        ( ac_wr_rst_n       ),
    .wr_path_rstn_upp        ( dx_wr_rst_n       ),
    .rd_path_rstn_low        ( ac_rd_rst_n       ),
    .rd_path_rstn_upp        ( dx_rd_rst_n       ),

    .in_bdl_byp              ( wr_bdl_byp        ),
    .out_bdl_byp             ( rd_bdl_byp        ),
    .in_bdl_dly              ( wr_bdl_dly        ),
    .out_bdl_dly             ( rd_bdl_dly        ),

    .doq                     ( doq               ),
    .diq                     ( diq               ),
    .indd                    ( indd              ),
    .indqs                   ( rdqs_o            ),

    .rdqs                    ( rdqs_p            ),
    .rdqs_n_gated            ( rdqs_n            ),

    .pdr_md                  ( pdr_md            ),
    .ts_md                   ( ts_md             ),
    .te_md                   ( te_md             ),

    .pdr                     ( pdr_dq            ),
    .pdr_dqs                 ( pdr_dqs           ),
    .pdr_dqsn                ( pdr_dqsn          ),

    .ts_dq                   ( ts_dq             ),
    .ts_dqs                  ( ts_dqs            ),
    .ts_dqsn                 ( ts_dqsn           ),

    .te                      ( te_dq             ),
    .te_dqs                  ( te_dqs            ),
    .te_dqsn                 ( te_dqsn           ),

    .pad                     ( pad               )

);

endmodule

`timescale 1ps/1ps

module ph1_ddrphy_mcu_wrapper #(
`ifdef PH1_DDRPHY_SIM
    parameter DDRPHY_CFG_ROM = `MC0_DDRPHY_CFG_ROM,
    parameter DDRPHY_MCU_ROM = `MC0_DDRPHY_MCU_ROM,
`else
    parameter DDRPHY_CFG_ROM = "ui_ddr_cfg_rom.txt",
    parameter DDRPHY_MCU_ROM = "ui_ddr_mcu_rom.txt",
`endif
    parameter CLK_FREQ       = 50_000_000
)(
    input           i_clk           ,
    input           i_rst           ,

    output          o_apb_psel      ,
    output          o_apb_penable   ,
    output          o_apb_pwrite    ,
    output  [31:0]  o_apb_paddr     ,
    output  [31:0]  o_apb_pwdata    ,
    input   [31:0]  i_apb_prdata    ,
    input           i_apb_pready    ,

    output          o_uart_txd      ,
    input           i_uart_rxd      ,

    input           dfx_apb_psel    ,
    input           dfx_apb_penable ,
    input           dfx_apb_pwrite  ,
    input   [15:0]  dfx_apb_paddr   ,
    input   [31:0]  dfx_apb_pwdata  ,
    output  [31:0]  dfx_apb_prdata  ,
    output          dfx_apb_pready  ,

    input           uram_en         ,
    output          uram_clr        ,
    input   [ 7:0]  uram_addr       ,
    output  [31:0]  uram_rdata      ,

    input   [31:0]  ddrphy_cr       ,
    output  [31:0]  ddrphy_sr
);

wire          dfx_apb_write   ;
wire  [31:0]  dfx_apb_addr    ;

wire          mcu_apb_psel    ;
wire          mcu_apb_penable ;
wire          mcu_apb_pwrite  ;
wire  [31:0]  mcu_apb_paddr   ;
wire  [31:0]  mcu_apb_pwdata  ;
wire  [31:0]  mcu_apb_prdata  ;
wire          mcu_apb_pready  ;

wire          mst_apb_psel    ;
wire          mst_apb_penable ;
wire          mst_apb_pwrite  ;
wire  [31:0]  mst_apb_paddr   ;
wire  [31:0]  mst_apb_pwdata  ;
wire  [31:0]  mst_apb_prdata  ;
wire          mst_apb_pready  ;

wire  [ 7:0]  slv_apb_psel    ;
wire          slv_apb_penable ;
wire          slv_apb_pwrite  ;
wire  [31:0]  slv_apb_paddr   ;
wire  [31:0]  slv_apb_pwdata  ;
wire  [31:0]  slv_apb_prdata0 ;
wire  [31:0]  slv_apb_prdata1 ;
wire  [31:0]  slv_apb_prdata2 ;
wire  [31:0]  slv_apb_prdata3 ;
wire  [31:0]  slv_apb_prdata4 ;
wire  [31:0]  slv_apb_prdata5 ;
wire  [31:0]  slv_apb_prdata6 ;
wire  [31:0]  slv_apb_prdata7 ;
wire  [ 7:0]  slv_apb_pready  ;

ph1_ddrphy_mcu_core #(
    .MCU_TCM_INIT  ( DDRPHY_MCU_ROM )
)u_mcu_core (
    .i_clk         ( i_clk           ),
    .i_rst         ( i_rst           ),

    .o_apb_psel    ( mcu_apb_psel    ),
    .o_apb_penable ( mcu_apb_penable ),
    .o_apb_pwrite  ( mcu_apb_pwrite  ),
    .o_apb_paddr   ( mcu_apb_paddr   ),
    .o_apb_pwdata  ( mcu_apb_pwdata  ),
    .i_apb_prdata  ( mcu_apb_prdata  ),
    .i_apb_pready  ( mcu_apb_pready  )
);

ph1_ddrphy_apb_2to1 u_mcu_apb_2to1 (  
    .clk           ( i_clk           ), 
    .rst_n         (~i_rst           ),

    .i_p0_psel     ( mcu_apb_psel    ), 
    .i_p0_pen      ( mcu_apb_penable ), 
    .i_p0_pwrite   ( mcu_apb_pwrite  ), 
    .i_p0_paddr    ( mcu_apb_paddr   ), 
    .i_p0_pwdata   ( mcu_apb_pwdata  ), 
    .o_p0_prdata   ( mcu_apb_prdata  ), 
    .o_p0_pready   ( mcu_apb_pready  ), 

    .i_p1_psel     ( dfx_apb_psel    ), 
    .i_p1_pen      ( dfx_apb_penable ), 
    .i_p1_pwrite   ( dfx_apb_write   ), 
    .i_p1_paddr    ( dfx_apb_addr    ), 
    .i_p1_pwdata   ( dfx_apb_pwdata  ), 
    .o_p1_prdata   ( dfx_apb_prdata  ),
    .o_p1_pready   ( dfx_apb_pready  ), 

    .o_apb_psel    ( mst_apb_psel    ),
    .o_apb_pen     ( mst_apb_penable ),
    .o_apb_pwrite  ( mst_apb_pwrite  ),
    .o_apb_paddr   ( mst_apb_paddr   ),
    .o_apb_pwdata  ( mst_apb_pwdata  ),
    .i_apb_prdata  ( mst_apb_prdata  ),
    .i_apb_pready  ( mst_apb_pready  )
); 

assign dfx_apb_addr[31:0] = (dfx_apb_paddr[15] == 1'b0) ? {16'hE000, 4'h0, dfx_apb_paddr[11:0]} : {16'hF000, 1'b0, dfx_apb_paddr[14:0]};

assign dfx_apb_write = (dfx_apb_paddr[15:2] == 14'h03) ? dfx_apb_pwrite :
                       (dfx_apb_paddr[15:2] == 14'h04) ? dfx_apb_pwrite :
                       (dfx_apb_paddr[15:2] == 14'h08) ? dfx_apb_pwrite :
                       (dfx_apb_paddr[15:2] == 14'h09) ? dfx_apb_pwrite :
                      ((dfx_apb_paddr[15:2] >= 14'h40) && (dfx_apb_paddr[15:2] <= 14'h46)) ? dfx_apb_pwrite :
                      ((dfx_apb_paddr[15:2] >= 14'h80) && (dfx_apb_paddr[15:2] <= 14'h89)) ? dfx_apb_pwrite : 1'b0;

ph1_ddrphy_mcu_apb_decoder u_mcu_apb_decoder (
    .i_slv_apb_psel    ( mst_apb_psel     ), 
    .i_slv_apb_penable ( mst_apb_penable  ), 
    .i_slv_apb_pwrite  ( mst_apb_pwrite   ), 
    .i_slv_apb_paddr   ( mst_apb_paddr    ), 
    .i_slv_apb_pwdata  ( mst_apb_pwdata   ), 
    .o_slv_apb_prdata  ( mst_apb_prdata   ), 
    .o_slv_apb_pready  ( mst_apb_pready   ), 
    .o_slv_apb_pslverr (                  ), 

    .o_mst_apb_psel    ( slv_apb_psel     ), 
    .o_mst_apb_penable ( slv_apb_penable  ), 
    .o_mst_apb_pwrite  ( slv_apb_pwrite   ), 
    .o_mst_apb_paddr   ( slv_apb_paddr    ), 
    .o_mst_apb_pwdata  ( slv_apb_pwdata   ), 
    .i_mst_apb_prdata0 ( slv_apb_prdata0  ), 
    .i_mst_apb_prdata1 ( slv_apb_prdata1  ), 
    .i_mst_apb_prdata2 ( slv_apb_prdata2  ), 
    .i_mst_apb_prdata3 ( slv_apb_prdata3  ), 
    .i_mst_apb_prdata4 ( slv_apb_prdata4  ), 
    .i_mst_apb_prdata5 ( slv_apb_prdata5  ), 
    .i_mst_apb_prdata6 ( slv_apb_prdata6  ), 
    .i_mst_apb_prdata7 ( slv_apb_prdata7  ), 
    .i_mst_apb_pready  ( slv_apb_pready   ), 
    .i_mst_apb_pslverr ( 8'h00            )
);

assign slv_apb_pready[0] = 1'b1;
assign slv_apb_prdata0   = 32'h0;

assign slv_apb_pready[1] = 1'b1;
assign slv_apb_prdata1   = 32'h0;

ph1_ddrphy_mcu_apb_uart #(
    .CLK_FREQ    ( CLK_FREQ )
) u_mcu_apb_uart (
    .i_clk         ( i_clk               ), 
    .i_rst         ( i_rst               ), 
    .i_apb_psel    ( slv_apb_psel  [2]   ), 
    .i_apb_penable ( slv_apb_penable     ), 
    .i_apb_pwrite  ( slv_apb_pwrite      ), 
    .i_apb_paddr   ( slv_apb_paddr [7:0] ), 
    .i_apb_pwdata  ( slv_apb_pwdata      ), 
    .o_apb_prdata  ( slv_apb_prdata2     ), 
    .o_apb_pready  ( slv_apb_pready[2]   ), 

    .i_uart_rxd    ( i_uart_rxd          ), 
    .o_uart_txd    ( o_uart_txd          )  
);

ph1_ddrphy_mcu_apb_gpio u_mcu_apb_gpio (
    .i_clk          ( i_clk              ),
    .i_rst          ( i_rst              ),

    .i_apb_psel     ( slv_apb_psel  [3]  ), 
    .i_apb_penable  ( slv_apb_penable    ), 
    .i_apb_pwrite   ( slv_apb_pwrite     ), 
    .i_apb_paddr    ( slv_apb_paddr [7:0]), 
    .i_apb_pwdata   ( slv_apb_pwdata     ), 
    .o_apb_prdata   ( slv_apb_prdata3    ), 
    .o_apb_pready   ( slv_apb_pready[3]  ), 

    .o_uram_clr     ( uram_clr           ),

    .o_reg_w_00     ( ddrphy_sr          ),

    .i_reg_r_10     ( ddrphy_cr          ),
    .i_reg_r_14     ({31'h0, uram_en}    )

);

assign slv_apb_pready[4] = 1'b1;
assign slv_apb_prdata4   = 32'h0;

assign slv_apb_pready[5] = 1'b1;
assign slv_apb_prdata5   = 32'h0;

ph1_ddrphy_cfg_rom #(
    .DDRPHY_CFG_ROM ( DDRPHY_CFG_ROM )
) u_ddrphy_cfg_rom  (
    .clk            ( i_clk             ),
    .rst            ( i_rst             ),
    .apb_psel       ( slv_apb_psel  [6] ),
    .apb_penable    ( slv_apb_penable   ),
    .apb_pwrite     ( slv_apb_pwrite    ),
    .apb_paddr      ( slv_apb_paddr     ),
    .apb_pwdata     ( slv_apb_pwdata    ),
    .apb_prdata     ( slv_apb_prdata6   ),
    .apb_pready     ( slv_apb_pready[6] ),

    .uram_addr      ( uram_addr         ),
    .uram_rdata     ( uram_rdata        )
);

assign  o_apb_psel    = slv_apb_psel  [7];
assign  o_apb_penable = slv_apb_penable  ;
assign  o_apb_pwrite  = slv_apb_pwrite   ;
assign  o_apb_paddr   = slv_apb_paddr    ;
assign  o_apb_pwdata  = slv_apb_pwdata   ;

assign  slv_apb_prdata7   = i_apb_prdata ;
assign  slv_apb_pready[7] = i_apb_pready ;

endmodule

`timescale 1ps / 1ps

module ph1_ddrphy_mcu_core #(
    parameter  MCU_TCM_INIT = ""
)(
    input         i_clk         ,
    input         i_rst         ,

    output        o_apb_psel    ,
    output        o_apb_penable ,
    output        o_apb_pwrite  ,
    output [31:0] o_apb_paddr   ,
    output [31:0] o_apb_pwdata  ,
    input  [31:0] i_apb_prdata  ,
    input         i_apb_pready
);

localparam [31:0] RESET_VECTOR = 32'h0000_0000;

wire         rst_done;
reg   [ 1:0] rst_r   ;
wire         rst_int ;

wire         pc_vld;
wire  [31:0] PC;

wire  [31:0] pc_jump;
wire         pc_jump_vld;

wire         instr_vld     ;
wire  [31:0] instr_code    ;

wire  [ 4:0] instr_rs1_idx ;
wire  [ 4:0] instr_rs2_idx ;
wire  [11:0] instr_csr_idx ;
wire  [31:0] instr_rs1     ;
wire  [31:0] instr_rs2     ;
wire  [ 4:0] instr_rd_idx  ;
wire  [31:0] instr_rd_data ;
wire         instr_rd_vld  ;

wire  [ 4:0] instr_shamt   ;
wire  [31:0] instr_imm     ;

wire         instr_rvc_en   ;

wire         instr_op_system;
wire         instr_op_load  ;
wire         instr_op_store ;

wire         instr_lui    ;
wire         instr_auipc  ;
wire         instr_jal    ;
wire         instr_jalr   ;
wire         instr_beq    ;
wire         instr_bne    ;
wire         instr_blt    ;
wire         instr_bge    ;
wire         instr_bltu   ;
wire         instr_bgeu   ;
wire         instr_lb     ;
wire         instr_lh     ;
wire         instr_lw     ;
wire         instr_lbu    ;
wire         instr_lhu    ;
wire         instr_sb     ;
wire         instr_sh     ;
wire         instr_sw     ;
wire         instr_addi   ;
wire         instr_slti   ;
wire         instr_sltiu  ;
wire         instr_xori   ;
wire         instr_ori    ;
wire         instr_andi   ;
wire         instr_slli   ;
wire         instr_srli   ;
wire         instr_srai   ;
wire         instr_add    ;
wire         instr_sub    ;
wire         instr_sll    ;
wire         instr_slt    ;
wire         instr_sltu   ;
wire         instr_xor    ;
wire         instr_srl    ;
wire         instr_sra    ;
wire         instr_or     ;
wire         instr_and    ;
wire         instr_fence  ;
wire         instr_ecall  ;
wire         instr_ebreak ;

wire         instr_csrrw  ;
wire         instr_csrrc  ;
wire         instr_csrrs  ;
wire         instr_csrrwi ;
wire         instr_csrrci ;
wire         instr_csrrsi ;

wire         csr_rd_vld   ;
wire  [31:0] csr_rd_data  ;

wire         mem_wr_done  ;
wire         mem_rd_vld   ;
wire  [31:0] mem_rd_data  ;

wire         mem_wen      ;
wire  [31:0] mem_waddr    ;
wire  [31:0] mem_wdata    ;
wire  [ 3:0] mem_wmask    ;
wire         mem_wresp    ;
wire         mem_ren      ;
wire  [31:0] mem_raddr    ;
wire  [31:0] mem_rdata    ;
wire         mem_rvld     ;

wire         tcm_wen      ;
wire  [31:0] tcm_waddr    ;
wire  [31:0] tcm_wdata    ;
wire  [ 3:0] tcm_wmask    ;
wire         tcm_ren      ;
wire  [31:0] tcm_raddr    ;
wire  [31:0] tcm_rdata    ;
wire         tcm_rvld     ;

wire         pc2tcm_ren   ;
reg          pc2tcm_ren_r ;
wire  [31:0] pc2tcm_raddr ;
reg   [31:0] pc2tcm_rdata ;
reg          pc2tcm_rvld  ;

wire         mem2tcm_wen  ;
wire  [31:0] mem2tcm_waddr;
wire  [31:0] mem2tcm_wdata;
wire  [ 3:0] mem2tcm_wmask;
wire         mem2tcm_ren  ;
reg          mem2tcm_ren_r;
wire  [31:0] mem2tcm_raddr;
reg   [31:0] mem2tcm_rdata;
reg          mem2tcm_rvld ;

always @ (posedge i_clk or posedge i_rst)
begin
    if (i_rst == 1'b1)
        rst_r <= 2'b11;
    else if (rst_done)
        rst_r <= {rst_r[0], 1'b0};
end

assign rst_int = rst_r[1];

ph1_ddrphy_mcu_core_pc #(
    .RESET_VECTOR ( RESET_VECTOR   )
) u_mcu_core_pc (
    .i_clk        ( i_clk          ),
    .i_rst        ( rst_int        ),

    .i_rvc_en     ( instr_rvc_en   ),

    .i_op_load    ( instr_op_load  ),
    .i_op_store   ( instr_op_store ),

    .i_load_done  ( mem_rd_vld     ),
    .i_store_done ( mem_wr_done    ),

    .i_jump_vld   ( pc_jump_vld    ),
    .i_jump       ( pc_jump        ),

    .o_tcm_ren    ( pc2tcm_ren     ),
    .o_tcm_raddr  ( pc2tcm_raddr   ),
    .i_tcm_rdata  ( pc2tcm_rdata   ),
    .i_tcm_rvld   ( pc2tcm_rvld    ),

    .o_instr_vld  ( instr_vld      ),
    .o_instr      ( instr_code     ),

    .o_pc_vld     ( pc_vld         ),
    .o_pc         ( PC             )
);

ph1_ddrphy_mcu_core_tcm #(
    .MCU_TCM_INIT ( MCU_TCM_INIT )
) u_mcu_core_tcm (
    .i_clk       ( i_clk      ),
    .i_rst       ( rst_int    ),

    .i_tcm_wen   ( tcm_wen    ),
    .i_tcm_waddr ( tcm_waddr  ), 
    .i_tcm_wdata ( tcm_wdata  ),
    .i_tcm_wmask ( tcm_wmask  ),

    .i_tcm_ren   ( tcm_ren    ),
    .i_tcm_raddr ( tcm_raddr  ), 
    .o_tcm_rvld  ( tcm_rvld   ),
    .o_tcm_rdata ( tcm_rdata  )
);

assign tcm_wen   = mem2tcm_wen  ;
assign tcm_waddr = mem2tcm_waddr;
assign tcm_wdata = mem2tcm_wdata;
assign tcm_wmask = mem2tcm_wmask;

assign tcm_ren   = pc2tcm_ren | mem2tcm_ren;
assign tcm_raddr = pc2tcm_ren ? pc2tcm_raddr : mem2tcm_ren ? mem2tcm_raddr : pc2tcm_raddr;

always @ (posedge i_clk) begin
    if (rst_int == 1'b1) begin
       mem2tcm_ren_r <= 1'b0;
        pc2tcm_ren_r <= 1'b0;
    end else begin
       mem2tcm_ren_r <= mem2tcm_ren;
        pc2tcm_ren_r <=  pc2tcm_ren;
    end
end

always @ (posedge i_clk) begin
    if (rst_int == 1'b1) begin
       pc2tcm_rvld  <=  1'b0;
       pc2tcm_rdata <= 32'h0;
    end else if (pc2tcm_ren_r) begin
       pc2tcm_rvld  <= tcm_rvld;
       pc2tcm_rdata <= tcm_rdata;
    end else begin
       pc2tcm_rvld  <= 1'b0;
    end
end

always @ (posedge i_clk) begin
    if (rst_int == 1'b1) begin
       mem2tcm_rvld  <=  1'b0;
       mem2tcm_rdata <= 32'h0;
    end else if (mem2tcm_ren_r) begin
       mem2tcm_rvld  <= 1'b1;
       mem2tcm_rdata <= tcm_rdata;
    end else begin
       mem2tcm_rvld  <= 1'b0;
    end
end

ph1_ddrphy_mcu_core_decoder u_mcu_core_decoder (
    .i_instr     ( instr_code      ),

    .o_rd        ( instr_rd_idx    ),
    .o_rs1       ( instr_rs1_idx   ),
    .o_rs2       ( instr_rs2_idx   ),
    .o_csr       ( instr_csr_idx   ),
    .o_shamt     ( instr_shamt     ),
    .o_imm       ( instr_imm       ),

    .o_rvc_en    ( instr_rvc_en    ),

    .o_op_system ( instr_op_system ),
    .o_op_load   ( instr_op_load   ),
    .o_op_store  ( instr_op_store  ),

    .o_lui       ( instr_lui       ),
    .o_auipc     ( instr_auipc     ),
    .o_jal       ( instr_jal       ),
    .o_jalr      ( instr_jalr      ),
    .o_beq       ( instr_beq       ),
    .o_bne       ( instr_bne       ),
    .o_blt       ( instr_blt       ),
    .o_bge       ( instr_bge       ),
    .o_bltu      ( instr_bltu      ),
    .o_bgeu      ( instr_bgeu      ),
    .o_lb        ( instr_lb        ),
    .o_lh        ( instr_lh        ),
    .o_lw        ( instr_lw        ),
    .o_lbu       ( instr_lbu       ),
    .o_lhu       ( instr_lhu       ),
    .o_sb        ( instr_sb        ),
    .o_sh        ( instr_sh        ),
    .o_sw        ( instr_sw        ),
    .o_addi      ( instr_addi      ),
    .o_slti      ( instr_slti      ),
    .o_sltiu     ( instr_sltiu     ),
    .o_xori      ( instr_xori      ),
    .o_ori       ( instr_ori       ),
    .o_andi      ( instr_andi      ),
    .o_slli      ( instr_slli      ),
    .o_srli      ( instr_srli      ),
    .o_srai      ( instr_srai      ),
    .o_add       ( instr_add       ),
    .o_sub       ( instr_sub       ),
    .o_sll       ( instr_sll       ),
    .o_slt       ( instr_slt       ),
    .o_sltu      ( instr_sltu      ),
    .o_xor       ( instr_xor       ),
    .o_srl       ( instr_srl       ),
    .o_sra       ( instr_sra       ),
    .o_or        ( instr_or        ),
    .o_and       ( instr_and       ),
    .o_fence     ( instr_fence     ),
    .o_ecall     ( instr_ecall     ),
    .o_ebreak    ( instr_ebreak    ),

    .o_csrrw     ( instr_csrrw     ),
    .o_csrrs     ( instr_csrrs     ),
    .o_csrrc     ( instr_csrrc     ),
    .o_csrrwi    ( instr_csrrwi    ),
    .o_csrrsi    ( instr_csrrsi    ),
    .o_csrrci    ( instr_csrrci    )
);

ph1_ddrphy_mcu_core_csr u_mcu_core_csr (
    .i_clk       ( i_clk         ),
    .i_rst       ( rst_int       ),

    .i_op_system ( instr_vld & instr_op_system ),
    .i_csrrw     ( instr_csrrw   ),
    .i_csrrs     ( instr_csrrs   ),
    .i_csrrc     ( instr_csrrc   ),
    .i_csrrwi    ( instr_csrrwi  ),
    .i_csrrsi    ( instr_csrrsi  ),
    .i_csrrci    ( instr_csrrci  ),

    .i_csr       ( instr_csr_idx ),
    .i_rs1_data  ( instr_rs1     ),

    .o_rd_vld    ( csr_rd_vld    ),
    .o_rd_data   ( csr_rd_data   )
);

ph1_ddrphy_mcu_core_regfile u_mcu_core_regfile (
    .i_clk       ( i_clk         ),
    .i_rst       ( i_rst         ),
    .i_rs1       ( instr_rs1_idx ),
    .i_rs2       ( instr_rs2_idx ),
    .i_rd        ( instr_rd_idx  ),
    .i_rd_data   ( instr_rd_data ),
    .i_rd_vld    ( instr_rd_vld  ),
    .o_rs1_data  ( instr_rs1     ),
    .o_rs2_data  ( instr_rs2     ),
    .i_csr_rvld  ( csr_rd_vld    ),
    .i_csr_rdata ( csr_rd_data   ),
    .i_mem_rvld  ( mem_rd_vld    ),
    .i_mem_rdata ( mem_rd_data   ),
    .o_rst_done  ( rst_done      )
);

ph1_ddrphy_mcu_core_alu u_mcu_core_alu (
    .i_clk        ( i_clk          ),
    .i_rst        ( rst_int        ),

    .i_instr_vld  ( instr_vld      ),
    .i_rvc_en     ( instr_rvc_en   ),

    .i_pc         ( PC             ),
    .o_pc         ( pc_jump        ),
    .o_pc_vld     ( pc_jump_vld    ),

    .i_rs1        ( instr_rs1      ),
    .i_rs2        ( instr_rs2      ),

    .o_rd_vld     ( instr_rd_vld   ),
    .o_rd_data    ( instr_rd_data  ),

    .i_shamt      ( instr_shamt    ),
    .i_imm        ( instr_imm      ),

    .i_lui        ( instr_lui      ),
    .i_auipc      ( instr_auipc    ),
    .i_jal        ( instr_jal      ),
    .i_jalr       ( instr_jalr     ),
    .i_beq        ( instr_beq      ),
    .i_bne        ( instr_bne      ),
    .i_blt        ( instr_blt      ),
    .i_bge        ( instr_bge      ),
    .i_bltu       ( instr_bltu     ),
    .i_bgeu       ( instr_bgeu     ),
    .i_lb         ( instr_lb       ),
    .i_lh         ( instr_lh       ),
    .i_lw         ( instr_lw       ),
    .i_lbu        ( instr_lbu      ),
    .i_lhu        ( instr_lhu      ),
    .i_sb         ( instr_sb       ),
    .i_sh         ( instr_sh       ),
    .i_sw         ( instr_sw       ),
    .i_addi       ( instr_addi     ),
    .i_slti       ( instr_slti     ),
    .i_sltiu      ( instr_sltiu    ),
    .i_xori       ( instr_xori     ),
    .i_ori        ( instr_ori      ),
    .i_andi       ( instr_andi     ),
    .i_slli       ( instr_slli     ),
    .i_srli       ( instr_srli     ),
    .i_srai       ( instr_srai     ),
    .i_add        ( instr_add      ),
    .i_sub        ( instr_sub      ),
    .i_sll        ( instr_sll      ),
    .i_slt        ( instr_slt      ),
    .i_sltu       ( instr_sltu     ),
    .i_xor        ( instr_xor      ),
    .i_srl        ( instr_srl      ),
    .i_sra        ( instr_sra      ),
    .i_or         ( instr_or       ),
    .i_and        ( instr_and      ),
    .i_fence      ( instr_fence    ),
    .i_ecall      ( instr_ecall    ),
    .i_ebreak     ( instr_ebreak   )
);

ph1_ddrphy_mcu_core_reg2mem u_mcu_core_reg2mem (
    .i_clk         ( i_clk          ),
    .i_rst         ( rst_int        ),

    .i_instr_vld   ( instr_vld      ),
    .i_op_load     ( instr_op_load  ),
    .i_op_store    ( instr_op_store ),
    .i_lw          ( instr_lw       ),
    .i_lh          ( instr_lh       ),
    .i_lb          ( instr_lb       ),
    .i_lhu         ( instr_lhu      ),
    .i_lbu         ( instr_lbu      ),
    .i_sw          ( instr_sw       ),
    .i_sh          ( instr_sh       ),
    .i_sb          ( instr_sb       ),

    .i_imm         ( instr_imm      ),
    .i_rs1         ( instr_rs1      ),
    .i_rs2         ( instr_rs2      ),

    .o_mem_wen     ( mem_wen        ),
    .o_mem_waddr   ( mem_waddr      ),
    .o_mem_wdata   ( mem_wdata      ),
    .o_mem_wmask   ( mem_wmask      ),
    .i_mem_wresp   ( mem_wresp      ),

    .o_mem_ren     ( mem_ren        ),
    .o_mem_raddr   ( mem_raddr      ),
    .i_mem_rdata   ( mem_rdata      ),
    .i_mem_rvld    ( mem_rvld       ),

    .o_wr_done     ( mem_wr_done    ),
    .o_rd_vld      ( mem_rd_vld     ),
    .o_rd_data     ( mem_rd_data    )
);

ph1_ddrphy_mcu_core_mem2apb u_mcu_core_mem2apb (
    .i_clk         ( i_clk         ),
    .i_rst         ( rst_int       ),

    .i_mem_wen     ( mem_wen       ),
    .i_mem_waddr   ( mem_waddr     ),
    .i_mem_wdata   ( mem_wdata     ),
    .i_mem_wmask   ( mem_wmask     ),
    .o_mem_wresp   ( mem_wresp     ),

    .i_mem_ren     ( mem_ren       ),
    .i_mem_raddr   ( mem_raddr     ),
    .o_mem_rdata   ( mem_rdata     ),
    .o_mem_rvld    ( mem_rvld      ),

    .o_tcm_wen     ( mem2tcm_wen   ),
    .o_tcm_waddr   ( mem2tcm_waddr ),
    .o_tcm_wdata   ( mem2tcm_wdata ),
    .o_tcm_wmask   ( mem2tcm_wmask ),

    .o_tcm_ren     ( mem2tcm_ren   ),
    .o_tcm_raddr   ( mem2tcm_raddr ),
    .i_tcm_rdata   ( mem2tcm_rdata ),
    .i_tcm_rvld    ( mem2tcm_rvld  ),

    .o_apb_psel    ( o_apb_psel    ),
    .o_apb_penable ( o_apb_penable ),
    .o_apb_pwrite  ( o_apb_pwrite  ),
    .o_apb_paddr   ( o_apb_paddr   ),
    .o_apb_pwdata  ( o_apb_pwdata  ),
    .i_apb_prdata  ( i_apb_prdata  ),
    .i_apb_pready  ( i_apb_pready  )
);

endmodule

`timescale 1ps/1ps

`define PH1_DDRPHY_MCU_TCM_OREG
`define PH1_DDRPHY_MCU_TCM_16KB

module ph1_ddrphy_mcu_core_tcm #(
    parameter MCU_TCM_INIT = ""
)(
    input           i_clk       ,
    input           i_rst       ,

    input           i_tcm_wen   ,
    input   [31:0]  i_tcm_waddr , 
    input   [31:0]  i_tcm_wdata ,
    input   [ 3:0]  i_tcm_wmask ,

    input           i_tcm_ren   ,
    input   [31:0]  i_tcm_raddr , 
    output          o_tcm_rvld  ,
    output  [31:0]  o_tcm_rdata
);

`ifdef PH1_DDRPHY_MCU_TCM_8KB
localparam AW = 11;
`elsif PH1_DDRPHY_MCU_TCM_16KB
localparam AW = 12;
`elsif PH1_DDRPHY_MCU_TCM_32KB
localparam AW = 13;
`elsif PH1_DDRPHY_MCU_TCM_64KB
localparam AW = 14;
`elsif PH1_DDRPHY_MCU_TCM_128KB
localparam AW = 15;
`endif

localparam DEPTH = 2**AW;

reg  [  31:0] tcm_mem[DEPTH-1:0]; 

wire [AW-1:0] mem_raddr;
reg  [32-1:0] mem_rdata;
reg           mem_rvld ;

wire [AW-1:0] mem_waddr;
wire [32-1:0] mem_wdata;

initial begin
    $readmemh(MCU_TCM_INIT, tcm_mem);
end

assign mem_raddr = i_tcm_raddr[2 +: AW];

`ifdef PH1_DDRPHY_MCU_TCM_OREG
always @ (posedge i_clk or posedge i_rst) begin
    if (i_rst == 1'b1) begin
        mem_rvld  <=  1'b0;
        mem_rdata <= 32'h0;
    end else if (i_tcm_ren) begin
        mem_rvld  <= 1'b1;
        mem_rdata <= tcm_mem[mem_raddr];
    end else begin
        mem_rvld  <= 1'b0;
    end
end
`else
always @ (posedge i_clk) begin
    if (i_rst == 1'b1) begin
        mem_rvld  <=  1'b0;
    end else if (i_tcm_ren) begin
        mem_rvld  <= 1'b1;
    end else begin
        mem_rvld  <= 1'b0;
    end
end

always @ (*) begin
    mem_rdata <= tcm_mem[mem_raddr];
end
`endif

assign o_tcm_rvld  = mem_rvld ;
assign o_tcm_rdata = mem_rdata;

assign mem_waddr = i_tcm_waddr[2 +: AW];

genvar n;
generate
    for (n = 0; n <= 3; n = n+1) begin : tcm_wbyte
        always @ (posedge i_clk) begin
            if (i_tcm_wen && i_tcm_wmask[n]) begin 
                tcm_mem[mem_waddr][8*n +: 8] <= i_tcm_wdata[8*n +: 8];
            end
        end
    end
endgenerate

endmodule

`timescale 1ps/1ps

module ph1_ddrphy_mcu_core_pc (
    input           i_clk        ,
    input           i_rst        ,

    input           i_rvc_en     ,

    input           i_op_load    ,
    input           i_op_store   ,

    input           i_load_done  ,
    input           i_store_done ,

    input           i_jump_vld   ,
    input   [31:0]  i_jump       ,

    output          o_tcm_ren    ,
    output  [31:0]  o_tcm_raddr  ,
    input   [31:0]  i_tcm_rdata  ,
    input           i_tcm_rvld   ,

    output          o_instr_vld  ,
    output  [31:0]  o_instr      ,

    output          o_pc_vld     ,
    output  [31:0]  o_pc
);

parameter [31:0] RESET_VECTOR = 32'h0000_0000;

reg   [ 1:0]  pc_start_r;
wire          pc_start  ;
reg           pc_update ; 

reg           pc_vld; 
reg   [31:0]  pc    ; 

reg           instr_vld;
reg   [31:0]  instr_code;

reg           tcm_ren;
reg   [31:0]  tcm_raddr;

always @ (posedge i_clk) begin
    if (i_rst == 1'b1)
        pc_start_r <= 2'b00;
    else
        pc_start_r <= {pc_start_r[0], 1'b1};
end

assign pc_start = (pc_start_r[0] == 1'b1) & (pc_start_r[1] == 1'b0);

always @ (posedge i_clk) begin
    if (i_rst == 1'b1)
        pc_update <= 1'b0;
    else if (i_op_load)
        pc_update <= i_load_done;
    else if (i_op_store)
        pc_update <= i_store_done;
    else
        pc_update <= instr_vld;
end

always @ (posedge i_clk) begin
    if (i_rst == 1'b1)
        pc <= RESET_VECTOR;
    else if (pc_update == 1'b1)
        pc <= (i_jump_vld == 1'b1) ? i_jump : i_rvc_en ? pc + 4'h2 : pc + 4'h4;
end

always @ (posedge i_clk) begin
    if (i_rst == 1'b1)
        pc_vld <= 1'b0;
    else
        pc_vld <= pc_start | pc_update;
end

localparam [1:0] TCM_IDLE = 2'b00;
localparam [1:0] TCM_RDC  = 2'b01; 
localparam [1:0] TCM_RDN  = 2'b10; 

reg [1:0] tcm_state;

always @ (posedge i_clk) begin
    if (i_rst == 1'b1) begin
        tcm_state <= 1'b0;
    end else begin
        case (tcm_state)
            TCM_IDLE : tcm_state <= pc_vld ? TCM_RDC : TCM_IDLE;
            TCM_RDC  : tcm_state <= (pc[1:0] == 2'h2) ? TCM_RDN : TCM_IDLE;
            TCM_RDN  : tcm_state <= TCM_IDLE;
            default  : tcm_state <= TCM_IDLE;
        endcase
    end
end

always @ (posedge i_clk) begin
    if (i_rst == 1'b1) begin
        tcm_ren   <= 1'b0;
        tcm_raddr <= 32'h0;
    end else begin
        if (tcm_state == TCM_IDLE) begin
            tcm_ren   <= 1'b0;
        end else if (tcm_state == TCM_RDC) begin
            tcm_ren   <= 1'b1;
            tcm_raddr <= pc;
        end else if (tcm_state == TCM_RDN) begin
            tcm_ren   <= 1'b1;
            tcm_raddr <= pc + 4'h2;
        end else begin
            tcm_ren   <= 1'b0;
        end
    end
end

reg        tcm_rvld;
reg [31:0] tcm_rdata;

always @ (posedge i_clk) begin
    if (i_rst == 1'b1) begin
        tcm_rvld  <= 1'b0;
        tcm_rdata <= 32'h0;
    end else begin
        tcm_rvld  <= i_tcm_rvld;
        tcm_rdata <= i_tcm_rdata;
    end
end

always @ (posedge i_clk) begin
    if (i_rst == 1'b1) begin
        instr_vld  <= 1'b0;
        instr_code <= 32'h0;
    end else if (pc[1:0] == 2'h0) begin
        instr_vld  <= i_tcm_rvld;
        instr_code <= i_tcm_rdata;
    end else if (pc[1:0] == 2'h2) begin
        instr_vld  <= i_tcm_rvld & tcm_rvld;
        instr_code <= (i_tcm_rvld & tcm_rvld) ? {i_tcm_rdata[15:0], tcm_rdata[31:16]} : instr_code;
    end else begin
        instr_vld  <= 1'b0;
    end
end

assign o_pc_vld    = pc_vld;
assign o_pc        = pc;

assign o_instr_vld = instr_vld;
assign o_instr     = instr_code;

assign o_tcm_ren   = tcm_ren;
assign o_tcm_raddr = tcm_raddr;

endmodule

`timescale 1ps/1ps

module ph1_ddrphy_mcu_core_decoder (
    input   [31:0] i_instr     ,

    output  [ 4:0] o_rd        ,
    output  [ 4:0] o_rs1       ,
    output  [ 4:0] o_rs2       ,
    output  [ 4:0] o_shamt     ,
    output  [31:0] o_imm       ,
    output  [11:0] o_csr       ,
    output  [ 4:0] o_uimm      ,

    output         o_rvc_en    ,

    output         o_op_system ,
    output         o_op_load   ,
    output         o_op_store  ,

    output         o_lui    ,
    output         o_auipc  ,
    output         o_jal    ,
    output         o_jalr   ,
    output         o_beq    ,
    output         o_bne    ,
    output         o_blt    ,
    output         o_bge    ,
    output         o_bltu   ,
    output         o_bgeu   ,
    output         o_lb     ,
    output         o_lh     ,
    output         o_lw     ,
    output         o_lbu    ,
    output         o_lhu    ,
    output         o_sb     ,
    output         o_sh     ,
    output         o_sw     ,
    output         o_addi   ,
    output         o_slti   ,
    output         o_sltiu  ,
    output         o_xori   ,
    output         o_ori    ,
    output         o_andi   ,
    output         o_slli   ,
    output         o_srli   ,
    output         o_srai   ,
    output         o_add    ,
    output         o_sub    ,
    output         o_sll    ,
    output         o_slt    ,
    output         o_sltu   ,
    output         o_xor    ,
    output         o_srl    ,
    output         o_sra    ,
    output         o_or     ,
    output         o_and    ,
    output         o_fence  ,
    output         o_ecall  ,
    output         o_ebreak ,

    output         o_csrrw  ,
    output         o_csrrs  ,
    output         o_csrrc  ,
    output         o_csrrwi ,
    output         o_csrrsi ,
    output         o_csrrci

);

localparam  [6:0]  OPCODE_MAP_LOAD     = 7'b00_000_11;
localparam  [6:0]  OPCODE_MAP_LOAD_LP  = 7'b00_001_11;
localparam  [6:0]  OPCODE_MAP_CUST0    = 7'b00_010_11; 
localparam  [6:0]  OPCODE_MAP_MISC_MEM = 7'b00_011_11;
localparam  [6:0]  OPCODE_MAP_OP_IMM   = 7'b00_100_11;
localparam  [6:0]  OPCODE_MAP_AUIPC    = 7'b00_101_11;
localparam  [6:0]  OPCODE_MAP_OP_IMM32 = 7'b00_110_11;

localparam  [6:0]  OPCODE_MAP_STORE    = 7'b01_000_11;
localparam  [6:0]  OPCODE_MAP_STORE_FP = 7'b01_001_11;
localparam  [6:0]  OPCODE_MAP_CUST1    = 7'b01_010_11; 
localparam  [6:0]  OPCODE_MAP_AMO      = 7'b01_011_11;
localparam  [6:0]  OPCODE_MAP_OP       = 7'b01_100_11;
localparam  [6:0]  OPCODE_MAP_LUI      = 7'b01_101_11;
localparam  [6:0]  OPCODE_MAP_OP32     = 7'b01_110_11;

localparam  [6:0]  OPCODE_MAP_MADD     = 7'b10_000_11;
localparam  [6:0]  OPCODE_MAP_MSUB     = 7'b10_001_11;
localparam  [6:0]  OPCODE_MAP_NMSUB    = 7'b10_010_11;
localparam  [6:0]  OPCODE_MAP_NMADD    = 7'b10_011_11;
localparam  [6:0]  OPCODE_MAP_OP_FP    = 7'b10_100_11;
localparam  [6:0]  OPCODE_MAP_RSVD0    = 7'b10_101_11; 
localparam  [6:0]  OPCODE_MAP_CUST2    = 7'b10_110_11; 

localparam  [6:0]  OPCODE_MAP_BRANCH   = 7'b11_000_11;
localparam  [6:0]  OPCODE_MAP_JALR     = 7'b11_001_11;
localparam  [6:0]  OPCODE_MAP_RSVD1    = 7'b11_010_11; 
localparam  [6:0]  OPCODE_MAP_JAL      = 7'b11_011_11;
localparam  [6:0]  OPCODE_MAP_SYSTEM   = 7'b11_100_11;
localparam  [6:0]  OPCODE_MAP_RSVD2    = 7'b11_101_11; 
localparam  [6:0]  OPCODE_MAP_CUST3    = 7'b11_110_11; 

localparam  [2:0] FUNCT3_JALR    = 3'b000;

localparam  [2:0] FUNCT3_BEQ     = 3'b000;
localparam  [2:0] FUNCT3_BNE     = 3'b001;
localparam  [2:0] FUNCT3_BLT     = 3'b100;
localparam  [2:0] FUNCT3_BGE     = 3'b101;
localparam  [2:0] FUNCT3_BLTU    = 3'b110;
localparam  [2:0] FUNCT3_BGEU    = 3'b111;

localparam  [2:0] FUNCT3_LB      = 3'b000;
localparam  [2:0] FUNCT3_LH      = 3'b001;
localparam  [2:0] FUNCT3_LW      = 3'b010;
localparam  [2:0] FUNCT3_LBU     = 3'b100;
localparam  [2:0] FUNCT3_LHU     = 3'b101;

localparam  [2:0] FUNCT3_SB      = 3'b000;
localparam  [2:0] FUNCT3_SH      = 3'b001;
localparam  [2:0] FUNCT3_SW      = 3'b010;

localparam  [2:0] FUNCT3_ADDI    = 3'b000;
localparam  [2:0] FUNCT3_SLTI    = 3'b010;
localparam  [2:0] FUNCT3_SLTIU   = 3'b011;
localparam  [2:0] FUNCT3_XORI    = 3'b100;
localparam  [2:0] FUNCT3_ORI     = 3'b110;
localparam  [2:0] FUNCT3_ANDI    = 3'b111;
localparam  [2:0] FUNCT3_SLLI    = 3'b001;
localparam  [2:0] FUNCT3_SRLI    = 3'b101;
localparam  [2:0] FUNCT3_SRAI    = 3'b101;

localparam  [2:0] FUNCT3_ADD     = 3'b000;
localparam  [2:0] FUNCT3_SUB     = 3'b000;
localparam  [2:0] FUNCT3_SLL     = 3'b001;
localparam  [2:0] FUNCT3_SLT     = 3'b010;
localparam  [2:0] FUNCT3_SLTU    = 3'b011;
localparam  [2:0] FUNCT3_LTU     = 3'b011;
localparam  [2:0] FUNCT3_XOR     = 3'b100;
localparam  [2:0] FUNCT3_SRL     = 3'b101;
localparam  [2:0] FUNCT3_SRA     = 3'b101;
localparam  [2:0] FUNCT3_OR      = 3'b110;
localparam  [2:0] FUNCT3_AND     = 3'b111;

localparam  [2:0] FUNCT3_FENCE   = 3'b000;
localparam  [2:0] FUNCT3_FENCE_I = 3'b001;

localparam  [2:0] FUNCT3_PRIV    = 3'b000;
localparam  [2:0] FUNCT3_CSRRW   = 3'b001;
localparam  [2:0] FUNCT3_CSRRS   = 3'b010;
localparam  [2:0] FUNCT3_CSRRC   = 3'b011;
localparam  [2:0] FUNCT3_CSRRWI  = 3'b101;
localparam  [2:0] FUNCT3_CSRRSI  = 3'b110;
localparam  [2:0] FUNCT3_CSRRCI  = 3'b111;
localparam  [2:0] FUNCT12_ECALL  = 12'b0000_0000_0000;
localparam  [2:0] FUNCT12_EBREAK = 12'b0000_0000_0001;

localparam  [31:0] ISA_ECALL     = 32'b0000000_00000_00000_000_00000_1110011;
localparam  [31:0] ISA_EBREAK    = 32'b0000000_00001_00000_000_00000_1110011;
localparam  [31:0] ISA_URET      = 32'b0000000_00010_00000_000_00000_1110011;
localparam  [31:0] ISA_SRET      = 32'b0001000_00010_00000_000_00000_1110011;
localparam  [31:0] ISA_MRET      = 32'b0011000_00010_00000_000_00000_1110011;
localparam  [31:0] ISA_WFI       = 32'b0001000_00101_00000_000_00000_1110011;

wire  [ 6:0] opcode = i_instr[ 6: 0];
wire  [ 4:0] rd     = i_instr[11: 7];
wire  [ 2:0] funct3 = i_instr[14:12];
wire  [ 4:0] rs1    = i_instr[19:15];
wire  [ 4:0] rs2    = i_instr[24:20];
wire  [ 4:0] shamt  = i_instr[24:20];
wire  [ 6:0] funct7 = i_instr[31:25];
wire  [11:0] csr    = i_instr[31:20];

wire  [ 4:0] uimm   = i_instr[19:15];

wire  [31:0] imm_i  = {{20{i_instr[31]}}, i_instr[31:20]};
wire  [31:0] imm_s  = {{20{i_instr[31]}}, i_instr[31:25], i_instr[11:7]};
wire  [31:0] imm_u  = {i_instr[31:12], 12'h0};

wire  [31:0] imm_b  = {{19{i_instr[31]}}, i_instr[31], i_instr[7], i_instr[30:25], i_instr[11: 8], 1'b0};
wire  [31:0] imm_j  = {{12{i_instr[31]}}, i_instr[31], i_instr[19:12], i_instr[20], i_instr[30:21], 1'b0};

wire         rvc_c0_en  = (i_instr[1:0] == 2'b00);
wire         rvc_c1_en0 = (i_instr[1:0] == 2'b01) && (i_instr[15] == 1'b0);
wire         rvc_c1_en1 = (i_instr[1:0] == 2'b01) && (i_instr[15] == 1'b1);
wire         rvc_c2_en  = (i_instr[1:0] == 2'b10);

wire  [31:0] c0_nzuimm = {22'h0, i_instr[10:7], i_instr[12:11], i_instr[5], i_instr[6], 2'b00};
wire  [31:0] c0_uimm   = {25'h0, i_instr[5],    i_instr[12:10], i_instr[6], 2'b00};

wire  [31:0] c1_nzimm0 = {{26{i_instr[12]}}, i_instr[12], i_instr[6:2]};
wire  [31:0] c1_nzimm3a= {{22{i_instr[12]}}, i_instr[12], i_instr[4],  i_instr[3], i_instr[5], i_instr[2], i_instr[6], 4'h0};
wire  [31:0] c1_nzimm3b= {{14{i_instr[12]}}, i_instr[12], i_instr[6:2], 12'h0};
wire  [31:0] c1_nzuimm = { 26'h0,            i_instr[12], i_instr[6:2]};
wire  [31:0] c1_imm_i  = {{26{i_instr[12]}}, i_instr[12], i_instr[6:2]};
wire  [31:0] c1_imm_j  = {{20{i_instr[12]}}, i_instr[12], i_instr[8], i_instr[10:9], i_instr[6], i_instr[7], i_instr[2], i_instr[11], i_instr[5:3], 1'b0};
wire  [31:0] c1_imm_b  = {{23{i_instr[12]}}, i_instr[12], i_instr[6:5], i_instr[2], i_instr[11:10], i_instr[4:3], 1'b0};

wire  [31:0] c2_nzuimm = {26'h0, i_instr[12],  i_instr[6:2]};
wire  [31:0] c2_uimm_l = {24'h0, i_instr[3:2], i_instr[12], i_instr[6:4], 2'b00};
wire  [31:0] c2_uimm_s = {24'h0, i_instr[8:7], i_instr[12:9], 2'b00};

wire  [ 4:0] c0_rd_3b  = {2'b01, i_instr[4:2]};
wire  [ 4:0] c0_rs1_3b = (i_instr[15:13] == 3'b000) ? 5'h2 : {2'b01, i_instr[9:7]};
wire  [ 4:0] c0_rs2_3b = {2'b01, i_instr[4:2]};

wire  [ 4:0] c1_rd     = (i_instr[15:13] == 3'b001) ? 5'h01 : i_instr[11:7];
wire  [ 4:0] c1_rs1    = (i_instr[15:13] == 3'b010) ? 5'h00 : i_instr[11:7];
wire  [ 4:0] c1_rs2    = i_instr[ 6:2];
wire  [ 4:0] c1_rd_3b  = (i_instr[15:13] == 3'b101) ? 5'h00 : {2'b01, i_instr[9:7]};
wire  [ 4:0] c1_rs1_3b = {2'b01, i_instr[9:7]};
wire  [ 4:0] c1_rs2_3b = ((i_instr[15:13] == 3'b110) || (i_instr[15:13] == 3'b111)) ? 5'h0 : {2'b01, i_instr[4:2]};

wire  [ 4:0] c2_rd     = i_instr[11:7];
wire  [ 4:0] c2_rs1    = ((i_instr[15:13] == 3'b010) || (i_instr[15:13] == 3'b110)) ? 5'h2 :
                         ((i_instr[15:13] == 3'b100) && (i_instr[12] == 1'b0) && (i_instr[6:2] != 5'h0)) ? 5'h0 : i_instr[11:7];
wire  [ 4:0] c2_rs2    = i_instr[ 6:2];

wire instr_ecall   = (i_instr[31:0] == ISA_ECALL ) ? 1'b1 : 1'b0;
wire instr_ebreak  = (i_instr[31:0] == ISA_EBREAK) ? 1'b1 : 1'b0;
wire instr_uret    = (i_instr[31:0] == ISA_URET  ) ? 1'b1 : 1'b0;
wire instr_sret    = (i_instr[31:0] == ISA_SRET  ) ? 1'b1 : 1'b0;
wire instr_mret    = (i_instr[31:0] == ISA_MRET  ) ? 1'b1 : 1'b0;
wire instr_wfi     = (i_instr[31:0] == ISA_WFI   ) ? 1'b1 : 1'b0;

wire instr_op_load     = (opcode == OPCODE_MAP_LOAD    ) ? 1'b1 : 1'b0 ;
wire instr_op_load_lp  = (opcode == OPCODE_MAP_LOAD_LP ) ? 1'b1 : 1'b0 ;
wire instr_op_misc_mem = (opcode == OPCODE_MAP_MISC_MEM) ? 1'b1 : 1'b0 ;
wire instr_op_imm      = (opcode == OPCODE_MAP_OP_IMM  ) ? 1'b1 : 1'b0 ;
wire instr_op_auipc    = (opcode == OPCODE_MAP_AUIPC   ) ? 1'b1 : 1'b0 ;
wire instr_op_imm32    = (opcode == OPCODE_MAP_OP_IMM32) ? 1'b1 : 1'b0 ;
wire instr_op_store    = (opcode == OPCODE_MAP_STORE   ) ? 1'b1 : 1'b0 ;
wire instr_op_store_fp = (opcode == OPCODE_MAP_STORE_FP) ? 1'b1 : 1'b0 ;
wire instr_op_amo      = (opcode == OPCODE_MAP_AMO     ) ? 1'b1 : 1'b0 ;
wire instr_op_op       = (opcode == OPCODE_MAP_OP      ) ? 1'b1 : 1'b0 ;
wire instr_op_lui      = (opcode == OPCODE_MAP_LUI     ) ? 1'b1 : 1'b0 ;
wire instr_op_op32     = (opcode == OPCODE_MAP_OP32    ) ? 1'b1 : 1'b0 ;
wire instr_op_madd     = (opcode == OPCODE_MAP_MADD    ) ? 1'b1 : 1'b0 ;
wire instr_op_msub     = (opcode == OPCODE_MAP_MSUB    ) ? 1'b1 : 1'b0 ;
wire instr_op_nmsub    = (opcode == OPCODE_MAP_NMSUB   ) ? 1'b1 : 1'b0 ;
wire instr_op_nmadd    = (opcode == OPCODE_MAP_NMADD   ) ? 1'b1 : 1'b0 ;
wire instr_op_fp       = (opcode == OPCODE_MAP_OP_FP   ) ? 1'b1 : 1'b0 ;
wire instr_op_branch   = (opcode == OPCODE_MAP_BRANCH  ) ? 1'b1 : 1'b0 ;
wire instr_op_jalr     = (opcode == OPCODE_MAP_JALR    ) ? 1'b1 : 1'b0 ;
wire instr_op_jal      = (opcode == OPCODE_MAP_JAL     ) ? 1'b1 : 1'b0 ;
wire instr_op_system   = (opcode == OPCODE_MAP_SYSTEM  ) ? 1'b1 : 1'b0 ;

wire instr_beq  = instr_op_branch && (funct3 == FUNCT3_BEQ );
wire instr_bne  = instr_op_branch && (funct3 == FUNCT3_BNE );
wire instr_blt  = instr_op_branch && (funct3 == FUNCT3_BLT );
wire instr_bge  = instr_op_branch && (funct3 == FUNCT3_BGE );
wire instr_bltu = instr_op_branch && (funct3 == FUNCT3_BLTU);
wire instr_bgeu = instr_op_branch && (funct3 == FUNCT3_BGEU);

wire instr_lb  = instr_op_load && (funct3 == FUNCT3_LB );
wire instr_lh  = instr_op_load && (funct3 == FUNCT3_LH );
wire instr_lw  = instr_op_load && (funct3 == FUNCT3_LW );
wire instr_lbu = instr_op_load && (funct3 == FUNCT3_LBU);
wire instr_lhu = instr_op_load && (funct3 == FUNCT3_LHU);

wire instr_sb = instr_op_store && (funct3 == FUNCT3_SB);
wire instr_sh = instr_op_store && (funct3 == FUNCT3_SH);
wire instr_sw = instr_op_store && (funct3 == FUNCT3_SW);

wire instr_addi  = instr_op_imm && (funct3 == FUNCT3_ADDI );
wire instr_slti  = instr_op_imm && (funct3 == FUNCT3_SLTI );
wire instr_sltiu = instr_op_imm && (funct3 == FUNCT3_SLTIU);
wire instr_xori  = instr_op_imm && (funct3 == FUNCT3_XORI );
wire instr_ori   = instr_op_imm && (funct3 == FUNCT3_ORI  );
wire instr_andi  = instr_op_imm && (funct3 == FUNCT3_ANDI );

wire instr_slli  = instr_op_imm && (funct3 == FUNCT3_SLLI) && (funct7 == 7'b000_0000);
wire instr_srli  = instr_op_imm && (funct3 == FUNCT3_SRLI) && (funct7 == 7'b000_0000);
wire instr_srai  = instr_op_imm && (funct3 == FUNCT3_SRAI) && (funct7 == 7'b010_0000);

wire instr_add  = instr_op_op && (funct3 == FUNCT3_ADD ) && (funct7 == 7'b000_0000);
wire instr_sub  = instr_op_op && (funct3 == FUNCT3_SUB ) && (funct7 == 7'b010_0000);
wire instr_sll  = instr_op_op && (funct3 == FUNCT3_SLL ) && (funct7 == 7'b000_0000);
wire instr_slt  = instr_op_op && (funct3 == FUNCT3_SLT ) && (funct7 == 7'b000_0000);
wire instr_sltu = instr_op_op && (funct3 == FUNCT3_SLTU) && (funct7 == 7'b000_0000);
wire instr_ltu  = instr_op_op && (funct3 == FUNCT3_LTU ) && (funct7 == 7'b000_0000);
wire instr_xor  = instr_op_op && (funct3 == FUNCT3_XOR ) && (funct7 == 7'b000_0000);
wire instr_srl  = instr_op_op && (funct3 == FUNCT3_SRL ) && (funct7 == 7'b000_0000);
wire instr_sra  = instr_op_op && (funct3 == FUNCT3_SRA ) && (funct7 == 7'b010_0000);
wire instr_or   = instr_op_op && (funct3 == FUNCT3_OR  ) && (funct7 == 7'b000_0000);
wire instr_and  = instr_op_op && (funct3 == FUNCT3_AND ) && (funct7 == 7'b000_0000);

wire instr_fence = instr_op_misc_mem && (funct3 == FUNCT3_FENCE);

wire instr_nop = instr_addi && (rs1 == 5'h0) && (imm_i == 12'h0) && (rd == 5'h0);

wire instr_csrrw  = instr_op_system && (funct3 == FUNCT3_CSRRW ); 
wire instr_csrrs  = instr_op_system && (funct3 == FUNCT3_CSRRS ); 
wire instr_csrrc  = instr_op_system && (funct3 == FUNCT3_CSRRC ); 
wire instr_csrrwi = instr_op_system && (funct3 == FUNCT3_CSRRWI); 
wire instr_csrrsi = instr_op_system && (funct3 == FUNCT3_CSRRSI); 
wire instr_csrrci = instr_op_system && (funct3 == FUNCT3_CSRRCI); 

wire instr_c0_addi4spn = rvc_c0_en  && (i_instr[15:13] == 3'b000) && (c0_nzuimm[9:0] != 10'h0); 
wire instr_c0_lw       = rvc_c0_en  && (i_instr[15:13] == 3'b010);
wire instr_c0_sw       = rvc_c0_en  && (i_instr[15:13] == 3'b110);

wire instr_c1_nop      = rvc_c1_en0 && (i_instr[15:13] == 3'b000) && (c1_nzimm0[5:0] == 6'h0) && (c1_rd == 5'h0);
wire instr_c1_addi     = rvc_c1_en0 && (i_instr[15:13] == 3'b000) && (c1_nzimm0[5:0] != 6'h0) && (c1_rd != 5'h0);
wire instr_c1_jal      = rvc_c1_en0 && (i_instr[15:13] == 3'b001);
wire instr_c1_li       = rvc_c1_en0 && (i_instr[15:13] == 3'b010) && (c1_rd != 5'h0);
wire instr_c1_addi16sp = rvc_c1_en0 && (i_instr[15:13] == 3'b011) && (c1_nzimm3a[ 9:0] != 10'h0) && (c1_rd == 5'h2);
wire instr_c1_lui      = rvc_c1_en0 && (i_instr[15:13] == 3'b011) && (c1_nzimm3b[17:0] != 18'h0) && (c1_rd != 5'h0) && (c1_rd != 5'h2);
wire instr_c1_srli     = rvc_c1_en1 && (i_instr[15:13] == 3'b100) && (i_instr[11:10] == 2'b00) && (c1_nzuimm[5] == 1'b0);
wire instr_c1_srai     = rvc_c1_en1 && (i_instr[15:13] == 3'b100) && (i_instr[11:10] == 2'b01) && (c1_nzuimm[5] == 1'b0);
wire instr_c1_andi     = rvc_c1_en1 && (i_instr[15:13] == 3'b100) && (i_instr[11:10] == 2'b10);
wire instr_c1_sub      = rvc_c1_en1 && (i_instr[15:13] == 3'b100) && (i_instr[11:10] == 2'b11) && (i_instr[6:5] == 2'b00);
wire instr_c1_xor      = rvc_c1_en1 && (i_instr[15:13] == 3'b100) && (i_instr[11:10] == 2'b11) && (i_instr[6:5] == 2'b01);
wire instr_c1_or       = rvc_c1_en1 && (i_instr[15:13] == 3'b100) && (i_instr[11:10] == 2'b11) && (i_instr[6:5] == 2'b10);
wire instr_c1_and      = rvc_c1_en1 && (i_instr[15:13] == 3'b100) && (i_instr[11:10] == 2'b11) && (i_instr[6:5] == 2'b11);
wire instr_c1_j        = rvc_c1_en1 && (i_instr[15:13] == 3'b101);
wire instr_c1_beqz     = rvc_c1_en1 && (i_instr[15:13] == 3'b110);
wire instr_c1_bnez     = rvc_c1_en1 && (i_instr[15:13] == 3'b111);

wire instr_c2_slli     = rvc_c2_en  && (i_instr[15:13] == 3'b000) && (i_instr[12] == 1'b0) && (i_instr[11:7] != 5'h0);
wire instr_c2_jr       = rvc_c2_en  && (i_instr[15:13] == 3'b100) && (i_instr[12] == 1'b0) && (i_instr[11:7] != 5'h0) && (i_instr[6:2] == 5'h0);
wire instr_c2_mv       = rvc_c2_en  && (i_instr[15:13] == 3'b100) && (i_instr[12] == 1'b0) && (i_instr[11:7] != 5'h0) && (i_instr[6:2] != 5'h0);
wire instr_c2_ebreak   = rvc_c2_en  && (i_instr[15:13] == 3'b100) && (i_instr[12] == 1'b1) && (i_instr[11:2] == 10'h0);
wire instr_c2_jalr     = rvc_c2_en  && (i_instr[15:13] == 3'b100) && (i_instr[12] == 1'b1) && (i_instr[11:7] != 5'h0) && (i_instr[6:2] == 5'h0);
wire instr_c2_add      = rvc_c2_en  && (i_instr[15:13] == 3'b100) && (i_instr[12] == 1'b1) && (i_instr[11:7] != 5'h0) && (i_instr[6:2] != 5'h0);
wire instr_c2_lwsp     = rvc_c2_en  && (i_instr[15:13] == 3'b010) && (i_instr[11:7] != 5'h0);
wire instr_c2_swsp     = rvc_c2_en  && (i_instr[15:13] == 3'b110);

assign o_lui    = instr_op_lui  | instr_c1_lui;
assign o_auipc  = instr_op_auipc;
assign o_jal    = instr_op_jal  | instr_c1_jal  | instr_c1_j;
assign o_jalr   = instr_op_jalr | instr_c2_jalr | instr_c2_jr;
assign o_beq    = instr_beq     | instr_c1_beqz;
assign o_bne    = instr_bne     | instr_c1_bnez;
assign o_blt    = instr_blt;
assign o_bge    = instr_bge;
assign o_bltu   = instr_bltu;
assign o_bgeu   = instr_bgeu;
assign o_lb     = instr_lb;
assign o_lh     = instr_lh;
assign o_lw     = instr_lw      | instr_c0_lw | instr_c2_lwsp;
assign o_lbu    = instr_lbu;
assign o_lhu    = instr_lhu;
assign o_sb     = instr_sb;
assign o_sh     = instr_sh;
assign o_sw     = instr_sw      | instr_c0_sw | instr_c2_swsp;
assign o_addi   = instr_addi    | instr_c0_addi4spn | instr_c1_addi | instr_c1_addi16sp | instr_c1_li;
assign o_slti   = instr_slti;
assign o_sltiu  = instr_sltiu;
assign o_xori   = instr_xori;
assign o_ori    = instr_ori;
assign o_andi   = instr_andi    | instr_c1_andi;
assign o_slli   = instr_slli    | instr_c2_slli;
assign o_srli   = instr_srli    | instr_c1_srli;
assign o_srai   = instr_srai    | instr_c1_srai;
assign o_add    = instr_add     | instr_c2_add | instr_c2_mv;
assign o_sub    = instr_sub     | instr_c1_sub;
assign o_sll    = instr_sll;
assign o_slt    = instr_slt;
assign o_sltu   = instr_sltu;
assign o_xor    = instr_xor     | instr_c1_xor;
assign o_srl    = instr_srl;
assign o_sra    = instr_sra;
assign o_or     = instr_or      | instr_c1_or;
assign o_and    = instr_and     | instr_c1_and;
assign o_fence  = instr_fence;
assign o_ecall  = instr_ecall;
assign o_ebreak = instr_ebreak  | instr_c2_ebreak;

assign o_csrrw  = instr_csrrw ;
assign o_csrrs  = instr_csrrs ;
assign o_csrrc  = instr_csrrc ;
assign o_csrrwi = instr_csrrwi;
assign o_csrrsi = instr_csrrsi;
assign o_csrrci = instr_csrrci;

assign o_rvc_en    = rvc_c0_en | rvc_c1_en0 | rvc_c1_en1 | rvc_c2_en;

assign o_op_system = instr_op_system;
assign o_op_load   = instr_op_load || instr_c0_lw || instr_c2_lwsp;
assign o_op_store  = instr_op_store;

assign o_csr    = csr;
assign o_uimm   = uimm;

assign o_rd     = rvc_c0_en ? c0_rd_3b  : rvc_c1_en0 ? c1_rd  : rvc_c1_en1 ? c1_rd_3b  : rvc_c2_en ? c2_rd  : rd ;
assign o_rs1    = rvc_c0_en ? c0_rs1_3b : rvc_c1_en0 ? c1_rs1 : rvc_c1_en1 ? c1_rs1_3b : rvc_c2_en ? c2_rs1 : rs1;
assign o_rs2    = rvc_c0_en ? c0_rs2_3b : rvc_c1_en0 ? c1_rs2 : rvc_c1_en1 ? c1_rs2_3b : rvc_c2_en ? c2_rs2 : rs2;
assign o_shamt  = instr_c1_srli ? c1_nzuimm[4:0] :
                  instr_c1_srai ? c1_nzuimm[4:0] :
                  instr_c2_slli ? c2_nzuimm[4:0] : shamt;
assign o_imm    = instr_op_lui      ? imm_u :
                  instr_op_auipc    ? imm_u :
                  instr_op_imm      ? imm_i :
                  instr_op_jalr     ? imm_i :
                  instr_op_load     ? imm_i :
                  instr_op_store    ? imm_s :
                  instr_op_branch   ? imm_b :
                  instr_op_jal      ? imm_j :
                  instr_c0_addi4spn ? c0_nzuimm :
                 (instr_c0_lw   || instr_c0_sw)   ? c0_uimm   :
                  instr_c1_addi     ? c1_nzimm0  :
                  instr_c1_addi16sp ? c1_nzimm3a :
                  instr_c1_lui      ? c1_nzimm3b :

                 (instr_c1_li   || instr_c1_andi) ? c1_imm_i   :
                 (instr_c1_jal  || instr_c1_j)    ? c1_imm_j   :
                 (instr_c1_beqz || instr_c1_bnez) ? c1_imm_b   :

                  instr_c2_lwsp     ? c2_uimm_l  :
                  instr_c2_swsp     ? c2_uimm_s  : 32'h0;

endmodule

`timescale 1ps/1ps

module ph1_ddrphy_mcu_core_alu (
    input          i_clk      ,
    input          i_rst      ,

    input          i_instr_vld,
    input          i_rvc_en   ,

    input   [31:0] i_pc       ,
    output  [31:0] o_pc       ,
    output         o_pc_vld   ,

    input   [31:0] i_rs1      ,
    input   [31:0] i_rs2      ,

    output         o_rd_vld   ,
    output  [31:0] o_rd_data  ,

    input   [ 4:0] i_shamt    ,
    input   [31:0] i_imm      ,

    input          i_lui      ,
    input          i_auipc    ,
    input          i_jal      ,
    input          i_jalr     ,
    input          i_beq      ,
    input          i_bne      ,
    input          i_blt      ,
    input          i_bge      ,
    input          i_bltu     ,
    input          i_bgeu     ,
    input          i_lb       ,
    input          i_lh       ,
    input          i_lw       ,
    input          i_lbu      ,
    input          i_lhu      ,
    input          i_sb       ,
    input          i_sh       ,
    input          i_sw       ,
    input          i_addi     ,
    input          i_slti     ,
    input          i_sltiu    ,
    input          i_xori     ,
    input          i_ori      ,
    input          i_andi     ,
    input          i_slli     ,
    input          i_srli     ,
    input          i_srai     ,
    input          i_add      ,
    input          i_sub      ,
    input          i_sll      ,
    input          i_slt      ,
    input          i_sltu     ,
    input          i_xor      ,
    input          i_srl      ,
    input          i_sra      ,
    input          i_or       ,
    input          i_and      ,
    input          i_fence    ,
    input          i_ecall    ,
    input          i_ebreak
);

reg         rd_vld;
reg         pc_vld;
reg  [31:0] rd;
reg  [31:0] pc;

always @ (posedge i_clk) begin
    if (i_rst == 1'b1) begin
        rd_vld <= 1'b0;
        rd     <= 32'h0;
    end else if (i_instr_vld == 1'b0) begin
        rd_vld <= 1'b0;
    end else if (i_lui == 1'b1) begin
        rd_vld <= 1'b1;
        rd     <= {i_imm[31:12], 12'h0};
    end else if (i_auipc == 1'b1) begin
        rd_vld <= 1'b1;
        rd     <= {i_imm[31:12], 12'h0} + i_pc;
    end else if (i_jal == 1'b1) begin
        rd_vld <= 1'b1;
        rd     <= (i_rvc_en) ? i_pc + 32'h2 : i_pc + 32'h4;
    end else if (i_jalr == 1'b1) begin
        rd_vld <= 1'b1;
        rd     <= (i_rvc_en) ? i_pc + 32'h2 : i_pc + 32'h4;

    end else if (i_addi == 1'b1) begin
        rd_vld <= 1'b1;
        rd     <= i_rs1 + i_imm; 
    end else if (i_slti == 1'b1) begin
        rd_vld <= 1'b1;
        rd     <= ($signed(i_rs1) < $signed(i_imm)) ? 32'h1 : 32'h0;
    end else if (i_sltiu == 1'b1) begin
        rd_vld <= 1'b1;
        rd     <= (i_rs1 < i_imm) ? 32'h1 : 32'h0;
    end else if (i_xori == 1'b1) begin
        rd_vld <= 1'b1;
        rd     <= i_rs1 ^ i_imm; 
    end else if (i_ori == 1'b1) begin
        rd_vld <= 1'b1;
        rd     <= i_rs1 | i_imm; 
    end else if (i_andi == 1'b1) begin
        rd_vld <= 1'b1;
        rd     <= i_rs1 & i_imm; 
    end else if (i_slli == 1'b1) begin
        rd_vld <= 1'b1;
        rd     <= i_rs1 << i_shamt; 
    end else if (i_srli == 1'b1) begin
        rd_vld <= 1'b1;
        rd     <= i_rs1 >> i_shamt; 
    end else if (i_srai == 1'b1) begin
        rd_vld <= 1'b1;
        rd     <= {{32{i_rs1[31]}}, i_rs1} >> i_shamt; 
    end else if (i_add == 1'b1) begin
        rd_vld <= 1'b1;
        rd     <= i_rs1 + i_rs2;
    end else if (i_sub == 1'b1) begin
        rd_vld <= 1'b1;
        rd     <= i_rs1 - i_rs2;
    end else if (i_slt == 1'b1) begin
        rd_vld <= 1'b1;
        rd     <= ($signed(i_rs1) < $signed(i_rs2)) ? 1'b1 : 1'b0;
    end else if (i_sltu == 1'b1) begin
        rd_vld <= 1'b1;
        rd     <= (i_rs1 < i_rs2) ? 1'b1 : 1'b0;
    end else if (i_sll == 1'b1) begin
        rd_vld <= 1'b1;
        rd     <= i_rs1 << i_rs2[4:0]; 
    end else if (i_srl == 1'b1) begin
        rd_vld <= 1'b1;
        rd     <= i_rs1 >> i_rs2[4:0]; 
    end else if (i_sra == 1'b1) begin
        rd_vld <= 1'b1;
        rd     <= {{32{i_rs1[31]}}, i_rs1} >> i_rs2[4:0]; 
    end else if (i_xor == 1'b1) begin
        rd_vld <= 1'b1;
        rd     <= i_rs1 ^ i_rs2;
    end else if (i_or == 1'b1) begin
        rd_vld <= 1'b1;
        rd     <= i_rs1 | i_rs2;
    end else if (i_and == 1'b1) begin
        rd_vld <= 1'b1;
        rd     <= i_rs1 & i_rs2;

    end else begin
        rd_vld <= 1'b0;
    end
end

always @ (posedge i_clk) begin
    if (i_rst == 1'b1) begin
        pc_vld <=  1'b0;
        pc     <= 32'h0;
    end else if (i_instr_vld == 1'b0) begin
        pc_vld <= 1'b0;
    end else if (i_jal == 1'b1) begin
        pc_vld <=  1'b1;
        pc     <= i_pc + i_imm;
    end else if (i_jalr == 1'b1) begin
        pc_vld <=  1'b1;
        pc     <= i_rs1 + i_imm;
    end else if (i_beq == 1'b1) begin
        pc_vld <= (i_rs1 == i_rs2) ? 1'b1  : 1'b0;
        pc     <= (i_rs1 == i_rs2) ? i_pc + i_imm : i_pc;
    end else if (i_bne == 1'b1) begin
        pc_vld <= (i_rs1 != i_rs2) ? 1'b1  : 1'b0;
        pc     <= (i_rs1 != i_rs2) ? i_pc + i_imm : i_pc;
    end else if (i_blt == 1'b1) begin
        pc_vld <= ($signed(i_rs1) <  $signed(i_rs2)) ? 1'b1  : 1'b0;
        pc     <= ($signed(i_rs1) <  $signed(i_rs2)) ? i_pc + i_imm : i_pc;
    end else if (i_bge == 1'b1) begin
        pc_vld <= ($signed(i_rs1) >= $signed(i_rs2)) ? 1'b1  : 1'b0;
        pc     <= ($signed(i_rs1) >= $signed(i_rs2)) ? i_pc + i_imm : i_pc;
    end else if (i_bltu == 1'b1) begin
        pc_vld <= (i_rs1 <  i_rs2) ? 1'b1  : 1'b0;
        pc     <= (i_rs1 <  i_rs2) ? i_pc + i_imm : i_pc;
    end else if (i_bgeu == 1'b1) begin
        pc_vld <= (i_rs1 >= i_rs2) ? 1'b1  : 1'b0;
        pc     <= (i_rs1 >= i_rs2) ? i_pc + i_imm : i_pc;
    end else begin
        pc_vld <= 1'b0;
    end
end

assign o_rd_vld  = rd_vld;
assign o_rd_data = rd;

assign o_pc_vld  = pc_vld;
assign o_pc      = pc;

endmodule

`timescale 1ps/1ps

module ph1_ddrphy_mcu_core_csr (
    input          i_clk       ,
    input          i_rst       ,

    input          i_op_system ,
    input          i_csrrw     ,
    input          i_csrrs     ,
    input          i_csrrc     ,
    input          i_csrrwi    ,
    input          i_csrrsi    ,
    input          i_csrrci    ,

    input  [11:0]  i_csr       ,
    input  [31:0]  i_rs1_data  ,

    output         o_rd_vld    ,
    output [31:0]  o_rd_data
);

localparam  [11:0]  ADDR_CSR_FFLAGS     =  12'h001;
localparam  [11:0]  ADDR_CSR_FRM        =  12'h002;
localparam  [11:0]  ADDR_CSR_FCSR       =  12'h003;
localparam  [11:0]  ADDR_CSR_MSTATUS    =  12'h300;
localparam  [11:0]  ADDR_CSR_MISA       =  12'h301;
localparam  [11:0]  ADDR_CSR_MIE        =  12'h304;
localparam  [11:0]  ADDR_CSR_MTVEC      =  12'h305;
localparam  [11:0]  ADDR_CSR_MSCRATCH   =  12'h340;
localparam  [11:0]  ADDR_CSR_MEPC       =  12'h341;
localparam  [11:0]  ADDR_CSR_MCAUSE     =  12'h342;
localparam  [11:0]  ADDR_CSR_MTVAL      =  12'h343;
localparam  [11:0]  ADDR_CSR_MIP        =  12'h344;
localparam  [11:0]  ADDR_CSR_MCYCLE     =  12'hB00;
localparam  [11:0]  ADDR_CSR_MCYCLEH    =  12'hB80;
localparam  [11:0]  ADDR_CSR_MINSTRET   =  12'hB02;
localparam  [11:0]  ADDR_CSR_MINSTRETH  =  12'hB82;
localparam  [11:0]  ADDR_CSR_MVENDORID  =  12'hF11;
localparam  [11:0]  ADDR_CSR_MARCHID    =  12'hF12;
localparam  [11:0]  ADDR_CSR_MIMPID     =  12'hF13;
localparam  [11:0]  ADDR_CSR_MHARTID    =  12'hF14;

reg  [31:0]  CSR_MSTATUS  ; 

reg  [31:0]  CSR_MIE      ; 

reg  [31:0]  CSR_MVENDORID; 
reg  [31:0]  CSR_MARCHID  ; 
reg  [31:0]  CSR_MIMPID   ; 
reg  [31:0]  CSR_MHARTID  ; 

reg          csr_rvld ;
reg  [31:0]  csr_rdata;

always @ (posedge i_clk) begin
    if (i_rst == 1'b1) begin
        CSR_MIE <= 32'h0;
    end else if (i_op_system == 1'b1) begin
        CSR_MIE <= (i_csrrw == 1'b1) && (i_csr == ADDR_CSR_MIE) ? i_rs1_data : CSR_MIE;
    end
end

always @ (posedge i_clk) begin
    if (i_rst == 1'b1) begin
        CSR_MSTATUS <= 32'h0;
    end else if (i_op_system == 1'b1) begin
        CSR_MSTATUS <= (i_csrrw == 1'b1) && (i_csr == ADDR_CSR_MSTATUS) ? i_rs1_data : CSR_MSTATUS;
    end
end

always @ (posedge i_clk) begin
    if (i_rst == 1'b1) begin
        CSR_MVENDORID <= 32'h0688_1070;
        CSR_MARCHID   <= 32'h2004_0722;
        CSR_MIMPID    <= 32'h2004_0722;
        CSR_MHARTID   <= 32'h0000_0000;
    end else begin
    end
end

always @ (posedge i_clk) begin
    if (i_rst == 1'b1) begin
        csr_rvld  <=  1'b0;
        csr_rdata <= 32'h0;
    end else if (i_op_system == 1'b0) begin
        csr_rvld  <=  1'b0;
        csr_rdata <= 32'h0;
    end else if (i_op_system == 1'b1) begin
        csr_rvld  <= 1'b1;
        case (i_csr[11:0])

            ADDR_CSR_MSTATUS   : csr_rdata <= CSR_MSTATUS  ;

            ADDR_CSR_MIE       : csr_rdata <= CSR_MIE      ;

            ADDR_CSR_MVENDORID : csr_rdata <= CSR_MVENDORID;
            ADDR_CSR_MARCHID   : csr_rdata <= CSR_MARCHID  ;
            ADDR_CSR_MIMPID    : csr_rdata <= CSR_MIMPID   ;
            ADDR_CSR_MHARTID   : csr_rdata <= CSR_MHARTID  ;
            default            : csr_rdata <= 32'hdeadbeef ;
        endcase
    end
end

assign o_rd_vld  = csr_rvld ;
assign o_rd_data = csr_rdata;

endmodule

`timescale 1ps/1ps

module ph1_ddrphy_mcu_core_regfile (
    input         i_clk      ,
    input         i_rst      ,

    input  [ 4:0] i_rs1      ,
    input  [ 4:0] i_rs2      ,
    input  [ 4:0] i_rd       ,

    input         i_rd_vld   ,
    input  [31:0] i_rd_data  ,
    input         i_csr_rvld ,
    input  [31:0] i_csr_rdata,
    input         i_mem_rvld ,
    input  [31:0] i_mem_rdata,

    output [31:0] o_rs1_data ,
    output [31:0] o_rs2_data ,

    output        o_rst_done

);

reg  [31:0] regfile[31:0]; 

wire [31:0] reg_data;
wire [ 4:0] reg_addr;
reg         rst_done; 

reg  [ 4:0] init_addr;

assign o_rs1_data = regfile[i_rs1[4:0]];
assign o_rs2_data = regfile[i_rs2[4:0]];

always @ (posedge i_clk or posedge i_rst)
begin
    if (i_rst == 1'b1)
        init_addr <= 5'h0;
    else if (init_addr == 5'h1f)
        init_addr <= 5'h1f;
    else
        init_addr <= init_addr + 1'b1;
end

always @ (posedge i_clk or posedge i_rst)
begin
    if (i_rst == 1'b1)
        rst_done <= 1'b0;
    else if (init_addr == 5'h1f)
        rst_done <= 1'b1;
    else
        rst_done <= 1'b0; 
end

assign reg_addr = rst_done ? i_rd : init_addr;

assign reg_data = (rst_done  == 1'b0) ? 32'h0 :
                  (i_rd[4:0] == 5'h0) ? 32'h0 :
                  i_rd_vld   ? i_rd_data   : 
                  i_csr_rvld ? i_csr_rdata :
                  i_mem_rvld ? i_mem_rdata : 32'h0;

always @ (posedge i_clk) begin
    if ((rst_done == 1'b0) || i_rd_vld || i_csr_rvld || i_mem_rvld) begin
        regfile[reg_addr] <= reg_data; 
    end
end

assign o_rst_done = rst_done;

`ifdef PH1_DDRPHY_MCU_SIM
wire [31:0] x00_zero  = regfile[5'h00]; 
wire [31:0] x01_ra    = regfile[5'h01];
wire [31:0] x02_sp    = regfile[5'h02];
wire [31:0] x03_gp    = regfile[5'h03];
wire [31:0] x04_tp    = regfile[5'h04];
wire [31:0] x05_t0    = regfile[5'h05];
wire [31:0] x06_t1    = regfile[5'h06];
wire [31:0] x07_t2    = regfile[5'h07];
wire [31:0] x08_s0_fp = regfile[5'h08];
wire [31:0] x09_s1    = regfile[5'h09];
wire [31:0] x10_a0    = regfile[5'h0A];
wire [31:0] x11_a1    = regfile[5'h0B];
wire [31:0] x12_a2    = regfile[5'h0C];
wire [31:0] x13_a3    = regfile[5'h0D];
wire [31:0] x14_a4    = regfile[5'h0E];
wire [31:0] x15_a5    = regfile[5'h0F];
wire [31:0] x16_a6    = regfile[5'h10];
wire [31:0] x17_a7    = regfile[5'h11];
wire [31:0] x18_s2    = regfile[5'h12];
wire [31:0] x19_s3    = regfile[5'h13];
wire [31:0] x20_s4    = regfile[5'h14];
wire [31:0] x21_s5    = regfile[5'h15];
wire [31:0] x22_s6    = regfile[5'h16];
wire [31:0] x23_s7    = regfile[5'h17];
wire [31:0] x24_s8    = regfile[5'h18];
wire [31:0] x25_s9    = regfile[5'h19];
wire [31:0] x26_s10   = regfile[5'h1A];
wire [31:0] x27_s11   = regfile[5'h1B];
wire [31:0] x28_t3    = regfile[5'h1C];
wire [31:0] x29_t4    = regfile[5'h1D];
wire [31:0] x30_t5    = regfile[5'h1E];
wire [31:0] x31_t6    = regfile[5'h1F];
`endif

endmodule

`timescale 1ps/1ps

module ph1_ddrphy_mcu_core_reg2mem (
    input          i_clk         ,
    input          i_rst         ,

    input          i_instr_vld   ,
    input          i_op_load     ,
    input          i_op_store    ,
    input          i_lw          ,
    input          i_lh          ,
    input          i_lb          ,
    input          i_lhu         ,
    input          i_lbu         ,
    input          i_sw          ,
    input          i_sh          ,
    input          i_sb          ,

    input  [31:0]  i_imm         ,
    input  [31:0]  i_rs1         ,
    input  [31:0]  i_rs2         ,

    output         o_mem_wen     ,
    output [31:0]  o_mem_waddr   ,
    output [31:0]  o_mem_wdata   ,
    output [ 3:0]  o_mem_wmask   ,
    input          i_mem_wresp   ,

    output         o_mem_ren     ,
    output [31:0]  o_mem_raddr   ,
    input  [31:0]  i_mem_rdata   ,
    input          i_mem_rvld    ,

    output         o_wr_done     ,
    output         o_rd_vld      ,
    output [31:0]  o_rd_data
);

reg           ren  ;
reg           rvld ;
reg   [31:0]  rdata;
reg   [31:0]  raddr;
reg           wen  ;
reg   [31:0]  wdata;
reg   [31:0]  waddr;
wire  [ 3:0]  wmask;

wire  [ 1:0]  rbyte;
wire  [ 1:0]  wbyte;

always @ (posedge i_clk) begin
    if (i_rst == 1'b1) begin
        wen   <=  1'b0;
        waddr <= 32'h0;
        wdata <= 32'h0;
    end else if (i_instr_vld && i_sw) begin
        wen   <= 1'b1;
        waddr <= i_rs1 + i_imm;
        wdata <= i_rs2;
    end else if (i_instr_vld && i_sh) begin
        wen   <= 1'b1;
        waddr <= i_rs1 + i_imm;
        wdata <= {16'h0, i_rs2[15:0]};
    end else if (i_instr_vld && i_sb) begin
        wen   <= 1'b1;
        waddr <= i_rs1 + i_imm;
        wdata <= {24'h0, i_rs2[ 7:0]};
    end else begin
        wen   <= 1'b0;
    end
end

assign wbyte = waddr[1:0];
assign wmask = i_sw ?  4'b1111 :
               i_sh ? (4'b0011 << wbyte) :
               i_sb ? (4'b0001 << wbyte) : 4'b1111; 

always @ (posedge i_clk) begin
    if (i_rst == 1'b1) begin
        ren   <=  1'b0;
        raddr <= 32'h0;
    end else if (i_instr_vld && i_op_load) begin
        ren   <= 1'b1;
        raddr <= i_rs1 + i_imm;
    end else begin
        ren   <= 1'b0;
    end
end

assign rbyte = raddr[1:0];

always @ (posedge i_clk) begin
    if (i_rst == 1'b1) begin
        rvld  <= 1'b0;
    end else begin
        rvld  <= i_mem_rvld ? 1'b1 : 1'b0;
    end
end

always @ (posedge i_clk) begin
    if (i_rst == 1'b1) begin
        rdata <= 32'h0;
    end else if (i_lw  == 1'b1) begin
        rdata <= i_mem_rvld ? i_mem_rdata : rdata;
    end else if (i_lh  == 1'b1) begin
        rdata <= i_mem_rvld  ? {{16{i_mem_rdata[rbyte*8+15]}}, i_mem_rdata[rbyte*8 +: 16]} : rdata;
    end else if (i_lb  == 1'b1) begin
        rdata <= i_mem_rvld  ? {{24{i_mem_rdata[rbyte*8+ 7]}}, i_mem_rdata[rbyte*8 +:  8]} : rdata;
    end else if (i_lhu == 1'b1) begin
        rdata <= i_mem_rvld  ? {16'h0, i_mem_rdata[rbyte*8 +: 16]} : rdata;
    end else if (i_lbu == 1'b1) begin
        rdata <= i_mem_rvld  ? {24'h0, i_mem_rdata[rbyte*8 +:  8]} : rdata;
    end
end

assign o_wr_done = i_mem_wresp;
assign o_rd_vld  = rvld ;
assign o_rd_data = rdata;

assign o_mem_wen     = wen; 
assign o_mem_waddr   ={waddr[31:2], 2'b00};
assign o_mem_wdata   =(wdata << (wbyte*8));
assign o_mem_wmask   = wmask;

assign o_mem_ren     = ren; 
assign o_mem_raddr   ={raddr[31:2], 2'b00};

endmodule

`timescale 1ps/1ps

module ph1_ddrphy_mcu_core_mem2apb (
    input          i_clk         ,
    input          i_rst         ,

    input          i_mem_wen     ,
    input  [31:0]  i_mem_waddr   ,
    input  [31:0]  i_mem_wdata   ,
    input  [ 3:0]  i_mem_wmask   ,
    output         o_mem_wresp   ,

    input          i_mem_ren     ,
    input  [31:0]  i_mem_raddr   ,
    output [31:0]  o_mem_rdata   ,
    output         o_mem_rvld    ,

    output         o_tcm_wen     ,
    output [31:0]  o_tcm_waddr   ,
    output [31:0]  o_tcm_wdata   ,
    output [ 3:0]  o_tcm_wmask   ,

    output         o_tcm_ren     ,
    output [31:0]  o_tcm_raddr   ,
    input  [31:0]  i_tcm_rdata   ,
    input          i_tcm_rvld    ,

    output         o_apb_psel    ,
    output         o_apb_penable ,
    output         o_apb_pwrite  ,
    output [31:0]  o_apb_paddr   ,
    output [31:0]  o_apb_pwdata  ,
    input  [31:0]  i_apb_prdata  ,
    input          i_apb_pready
);

localparam [1:0]  S_IDLE   = 2'b00;
localparam [1:0]  S_SETUP  = 2'b01; 
localparam [1:0]  S_ACCESS = 2'b10;
localparam [1:0]  S_WAIT   = 2'b11;

localparam [31:0] TCM_BASEADDR = 32'h0000_0000;
localparam [31:0] APB_BASEADDR = 32'h8000_0000;

reg           mem_wresp;
reg           mem_rvld ;
reg   [31:0]  mem_rdata;

wire          tcm_wen  ;
wire          tcm_ren  ;
reg           tcm_wen_r;
reg   [31:0]  tcm_waddr;
reg   [31:0]  tcm_wdata;
reg   [ 3:0]  tcm_wmask;
reg           tcm_ren_r;
reg   [31:0]  tcm_raddr;
wire  [31:0]  tcm_rdata;
wire          tcm_rvld ;

wire          apb_wen;
wire          apb_ren;
reg   [ 1:0]  apb_state  ; 
reg           apb_psel   ; 
reg           apb_penable; 
reg           apb_pwrite ; 
reg   [31:0]  apb_paddr  ; 
reg   [31:0]  apb_pwdata ; 
reg   [ 3:0]  apb_pwmask ; 
reg   [31:0]  apb_prdata ; 
wire          apb_pready ; 
reg           apb_wdone  ; 
reg           apb_rdone  ; 
wire          apb_done   ; 

assign tcm_wen = (i_mem_waddr[31] == 1'b0) ? i_mem_wen : 1'b0; 
assign tcm_ren = (i_mem_raddr[31] == 1'b0) ? i_mem_ren : 1'b0; 

assign apb_wen = (i_mem_waddr[31] == 1'b1) ? i_mem_wen : 1'b0; 
assign apb_ren = (i_mem_raddr[31] == 1'b1) ? i_mem_ren : 1'b0; 

always @ (posedge i_clk) begin
    if (i_rst == 1'b1) begin
        tcm_wen_r <=  1'b0;
        tcm_waddr <= 32'h0;
        tcm_wdata <= 32'h0;
        tcm_wmask <=  4'h0;
    end else if (tcm_wen) begin
        tcm_wen_r <= 1'b1;
        tcm_waddr <= i_mem_waddr;
        tcm_wdata <= i_mem_wdata;
        tcm_wmask <= i_mem_wmask;
    end else begin
        tcm_wen_r <= 1'b0;
    end
end

always @ (posedge i_clk) begin
    if (i_rst == 1'b1) begin
        tcm_ren_r <=  1'b0;
        tcm_raddr <= 32'h0;
    end else if (tcm_ren) begin
        tcm_ren_r <= 1'b1;
        tcm_raddr <= i_mem_raddr;
    end else begin
        tcm_ren_r <= 1'b0;
    end
end

always @ (posedge i_clk) begin
    if (i_rst == 1'b1)
        apb_state <= S_IDLE;
    else begin
        case (apb_state)
            S_IDLE   : apb_state <= (apb_wen || apb_ren) ? S_SETUP : S_IDLE;
            S_SETUP  : apb_state <= S_ACCESS;
            S_ACCESS : apb_state <= S_WAIT;
            S_WAIT   : apb_state <= apb_done ? ((apb_wen || apb_ren) ? S_SETUP : S_IDLE) : S_WAIT;
            default  : apb_state <= S_IDLE;
        endcase
    end
end

always @ (posedge i_clk) begin
    if (i_rst == 1'b1)
        apb_psel <= 1'b0;
    else
        apb_psel <= (apb_state == S_SETUP) ? 1'b1 : apb_done ? 1'b0 : apb_psel;
end

always @ (posedge i_clk) begin
    if (i_rst == 1'b1)
        apb_penable <= 1'b0;
    else
        apb_penable <= (apb_state == S_ACCESS) ? 1'b1 : apb_done ? 1'b0 : apb_penable;
end

always @ (posedge i_clk) begin
    if (i_rst == 1'b1)
        apb_pwrite <= 1'b0;
    else if (apb_wen == 1'b1)
        apb_pwrite <= 1'b1;
    else if (apb_ren == 1'b1)
        apb_pwrite <= 1'b0;
end

always @ (posedge i_clk) begin
    if (i_rst == 1'b1)
        apb_paddr <= 32'h0;
    else if (apb_wen == 1'b1)
        apb_paddr <= i_mem_waddr;
    else if (apb_ren == 1'b1)
        apb_paddr <= i_mem_raddr;
end

always @ (posedge i_clk) begin
    if (i_rst == 1'b1) begin
        apb_pwdata <= 32'h0;
        apb_pwmask <= 4'b1111;
    end else if (apb_wen == 1'b1) begin
        apb_pwdata <= i_mem_wdata;
        apb_pwmask <= i_mem_wmask;
    end
end

assign apb_done = apb_psel & apb_penable & apb_pready;

always @ (posedge i_clk) begin
    if (i_rst == 1'b1) begin
        apb_wdone <= 1'b0;
        apb_rdone <= 1'b0;
    end else begin
        apb_wdone <= apb_done & (apb_pwrite == 1'b1);
        apb_rdone <= apb_done & (apb_pwrite == 1'b0);
    end
end

always @ (posedge i_clk) begin
    if (i_rst == 1'b1) begin
        apb_prdata <= 32'h0;
    end else if (apb_done & (apb_pwrite == 1'b0)) begin
        apb_prdata <= i_apb_prdata;
    end
end

always @ (posedge i_clk) begin
    if (i_rst == 1'b1)
        mem_wresp <= 1'b0;
    else
        mem_wresp <= apb_wdone | tcm_wen_r;
end

always @ (posedge i_clk) begin
    if (i_rst == 1'b1) begin
        mem_rvld  <=  1'b0;
        mem_rdata <= 32'h0;
    end else begin
        mem_rvld  <= apb_rdone ? 1'b1       : tcm_rvld ? 1'b1      : 1'b0;
        mem_rdata <= apb_rdone ? apb_prdata : tcm_rvld ? tcm_rdata : mem_rdata;
    end
end

assign apb_pready    = i_apb_pready;

assign o_apb_psel    = apb_psel   ; 
assign o_apb_penable = apb_penable; 
assign o_apb_pwrite  = apb_pwrite ;
assign o_apb_paddr   ={apb_paddr[31:2], 2'b00};
assign o_apb_pwdata  = apb_pwdata ;

assign tcm_rvld      = i_tcm_rvld;
assign tcm_rdata     = i_tcm_rdata;

assign o_tcm_wen     = tcm_wen_r; 
assign o_tcm_waddr   ={tcm_waddr[31:2], 2'b00};
assign o_tcm_wdata   = tcm_wdata;
assign o_tcm_wmask   = tcm_wmask;

assign o_tcm_ren     = tcm_ren_r; 
assign o_tcm_raddr   ={tcm_raddr[31:2], 2'b00};

assign o_mem_wresp   = mem_wresp;
assign o_mem_rvld    = mem_rvld ;
assign o_mem_rdata   = mem_rdata;

endmodule

`timescale 1ps / 1ps

module ph1_ddrphy_mcu_apb_decoder (
    input               i_slv_apb_psel    , 
    input               i_slv_apb_penable , 
    input               i_slv_apb_pwrite  , 
    input      [31:0]   i_slv_apb_paddr   , 
    input      [31:0]   i_slv_apb_pwdata  , 
    output reg [31:0]   o_slv_apb_prdata  , 
    output reg          o_slv_apb_pready  , 
    output reg          o_slv_apb_pslverr , 

    output reg [ 7:0]   o_mst_apb_psel    , 
    output              o_mst_apb_penable , 
    output              o_mst_apb_pwrite  , 
    output     [31:0]   o_mst_apb_paddr   , 
    output     [31:0]   o_mst_apb_pwdata  , 
    input      [31:0]   i_mst_apb_prdata0 , 
    input      [31:0]   i_mst_apb_prdata1 , 
    input      [31:0]   i_mst_apb_prdata2 , 
    input      [31:0]   i_mst_apb_prdata3 , 
    input      [31:0]   i_mst_apb_prdata4 , 
    input      [31:0]   i_mst_apb_prdata5 , 
    input      [31:0]   i_mst_apb_prdata6 , 
    input      [31:0]   i_mst_apb_prdata7 , 
    input      [ 7:0]   i_mst_apb_pready  , 
    input      [ 7:0]   i_mst_apb_pslverr 
);

assign o_mst_apb_paddr   = i_slv_apb_paddr;
assign o_mst_apb_penable = i_slv_apb_penable;
assign o_mst_apb_pwrite  = i_slv_apb_pwrite;
assign o_mst_apb_pwdata  = i_slv_apb_pwdata;

always @ (*) begin
    o_mst_apb_psel[0] = ((i_slv_apb_paddr & 32'hf000_0000) == 32'h8000_0000) ? i_slv_apb_psel : 1'b0;
    o_mst_apb_psel[1] = ((i_slv_apb_paddr & 32'hf000_0000) == 32'h9000_0000) ? i_slv_apb_psel : 1'b0;    
    o_mst_apb_psel[2] = ((i_slv_apb_paddr & 32'hf000_0000) == 32'ha000_0000) ? i_slv_apb_psel : 1'b0;
    o_mst_apb_psel[3] = ((i_slv_apb_paddr & 32'hf000_0000) == 32'hb000_0000) ? i_slv_apb_psel : 1'b0;
    o_mst_apb_psel[4] = ((i_slv_apb_paddr & 32'hf000_0000) == 32'hc000_0000) ? i_slv_apb_psel : 1'b0;
    o_mst_apb_psel[5] = ((i_slv_apb_paddr & 32'hf000_0000) == 32'hd000_0000) ? i_slv_apb_psel : 1'b0;
    o_mst_apb_psel[6] = ((i_slv_apb_paddr & 32'hf000_0000) == 32'he000_0000) ? i_slv_apb_psel : 1'b0;
    o_mst_apb_psel[7] = ((i_slv_apb_paddr & 32'hf000_0000) == 32'hf000_0000) ? i_slv_apb_psel : 1'b0;
end

always @ (*) begin
    case (o_mst_apb_psel[7:0])
    8'b0000_0001 : o_slv_apb_prdata  = i_mst_apb_prdata0;
    8'b0000_0010 : o_slv_apb_prdata  = i_mst_apb_prdata1;
    8'b0000_0100 : o_slv_apb_prdata  = i_mst_apb_prdata2;
    8'b0000_1000 : o_slv_apb_prdata  = i_mst_apb_prdata3;
    8'b0001_0000 : o_slv_apb_prdata  = i_mst_apb_prdata4;
    8'b0010_0000 : o_slv_apb_prdata  = i_mst_apb_prdata5;
    8'b0100_0000 : o_slv_apb_prdata  = i_mst_apb_prdata6;
    8'b1000_0000 : o_slv_apb_prdata  = i_mst_apb_prdata7;
    default      : o_slv_apb_prdata  = 32'hdeadbeaf;
    endcase
end

always @ (*) begin
    case (o_mst_apb_psel[7:0])
    8'b0000_0001 : o_slv_apb_pready  = i_mst_apb_pready[0];
    8'b0000_0010 : o_slv_apb_pready  = i_mst_apb_pready[1];
    8'b0000_0100 : o_slv_apb_pready  = i_mst_apb_pready[2];
    8'b0000_1000 : o_slv_apb_pready  = i_mst_apb_pready[3];
    8'b0001_0000 : o_slv_apb_pready  = i_mst_apb_pready[4];
    8'b0010_0000 : o_slv_apb_pready  = i_mst_apb_pready[5];
    8'b0100_0000 : o_slv_apb_pready  = i_mst_apb_pready[6];
    8'b1000_0000 : o_slv_apb_pready  = i_mst_apb_pready[7];
    default      : o_slv_apb_pready  = 1'b1;
    endcase
end

always @ (*) begin
    case (o_mst_apb_psel[7:0])
    8'b0000_0001 : o_slv_apb_pslverr  = i_mst_apb_pslverr[0];
    8'b0000_0010 : o_slv_apb_pslverr  = i_mst_apb_pslverr[1];
    8'b0000_0100 : o_slv_apb_pslverr  = i_mst_apb_pslverr[2];
    8'b0000_1000 : o_slv_apb_pslverr  = i_mst_apb_pslverr[3];
    8'b0001_0000 : o_slv_apb_pslverr  = i_mst_apb_pslverr[4];
    8'b0010_0000 : o_slv_apb_pslverr  = i_mst_apb_pslverr[5];
    8'b0100_0000 : o_slv_apb_pslverr  = i_mst_apb_pslverr[6];
    8'b1000_0000 : o_slv_apb_pslverr  = i_mst_apb_pslverr[7];
    default      : o_slv_apb_pslverr  = 1'b0;
    endcase
end

endmodule

`timescale 1ps/1ps

module ph1_ddrphy_mcu_apb_gpio (
    input               i_clk         ,
    input               i_rst         ,

    input      [ 7:0]   i_apb_paddr   , 
    input               i_apb_psel    , 
    input               i_apb_penable , 
    input               i_apb_pwrite  , 
    input      [31:0]   i_apb_pwdata  , 
    output     [31:0]   o_apb_prdata  , 
    output              o_apb_pready  , 
    output              o_apb_pslverr , 

    output     [31:0]   o_reg_w_00    ,

    input      [31:0]   i_reg_r_10    ,
    input      [31:0]   i_reg_r_14    ,

    output              o_uram_clr
);

wire apb_pclk   =  i_clk;
wire apb_prst_n = ~i_rst;

reg           apb_pready  ; 
wire          apb_psel    ; 
wire          apb_penable ; 
wire  [ 7:0]  apb_paddr   ; 
wire          apb_pwrite  ; 
wire  [31:0]  apb_pwdata  ; 
reg   [31:0]  apb_prdata  ; 
wire          apb_wr_en   ; 
wire          apb_rd_en   ; 

  reg   [31:0]  wdata_00  ; 

  reg   [31:0]  rdata_10  ; 
  reg   [31:0]  rdata_14  ; 

assign apb_wr_en = apb_psel & apb_penable & (apb_pwrite == 1'b1) & apb_pready;
assign apb_rd_en = apb_psel & apb_penable & (apb_pwrite == 1'b0);

always @ (posedge apb_pclk or negedge apb_prst_n)
begin
    if (apb_prst_n == 1'b0)
        apb_pready <= 1'b0;
    else if (apb_psel & (apb_penable == 1'b0))
        apb_pready <= 1'b0;
    else if (apb_psel & apb_penable & (apb_pwrite == 1'b1))
        apb_pready <= 1'b1;
    else if (apb_psel & apb_penable & (apb_pwrite == 1'b0))
        apb_pready <= apb_rd_en ;
    else
        apb_pready <= 1'b1;
end

always @ (posedge apb_pclk or negedge apb_prst_n)
begin
    if (apb_prst_n == 1'b0) begin
        wdata_00 <= 32'h0;

    end else if (apb_wr_en) begin
        case (apb_paddr[7:0])
            8'h00  : wdata_00 <= apb_pwdata;

            default: begin
            end
        endcase
    end
end

assign o_reg_w_00 = wdata_00;

always @ (*) begin
    rdata_10 <= i_reg_r_10;
    rdata_14 <= i_reg_r_14;

end

always @ (posedge apb_pclk or negedge apb_prst_n)
begin
    if (apb_prst_n == 1'b0) begin
        apb_prdata <= 32'h0;
    end else if (apb_rd_en) begin
        case (apb_paddr[7:0])
            8'h00  : apb_prdata <= wdata_00;

            8'h10  : apb_prdata <= rdata_10;
            8'h14  : apb_prdata <= rdata_14;

            default: apb_prdata <= 32'hdeadbeef;
        endcase
    end else begin
        apb_prdata <= 32'h0;
    end
end

assign apb_paddr    = i_apb_paddr  ;
assign apb_psel     = i_apb_psel   ;
assign apb_penable  = i_apb_penable;
assign apb_pwrite   = i_apb_pwrite ;
assign apb_pwdata   = i_apb_pwdata ;

assign o_apb_pready  = apb_pready ;
assign o_apb_prdata  = apb_prdata ;
assign o_apb_pslverr = 1'b0;

assign o_uram_clr    = apb_wr_en & (apb_paddr[7:0] == 8'h04);

endmodule

`timescale 1ps / 1ps

module ph1_ddrphy_mcu_apb_uart #(
    parameter CLK_FREQ = 100_000_000
)(
    input         i_clk        ,
    input         i_rst        ,

    input         i_apb_psel   ,
    input         i_apb_penable,
    input         i_apb_pwrite ,
    input  [ 7:0] i_apb_paddr  ,
    input  [31:0] i_apb_pwdata ,
    output [31:0] o_apb_prdata ,
    output        o_apb_pready ,

    input         i_uart_rxd   ,
    output        o_uart_txd
);

localparam BAUD_RATE = 115_200;

reg  [31:0] reg_00;
reg  [31:0] reg_04;
reg  [31:0] reg_08;
wire [31:0] reg_0c;

reg         apb_pready;
reg  [31:0] apb_prdata;
wire        apb_wen;
wire        apb_ren;
wire        apb_rld;

reg         tx_en;
reg         rx_en;

wire        tx_fifo_rst  ;
wire        tx_fifo_empty;
wire        tx_fifo_full ;
reg         tx_fifo_wen  ;
reg  [ 7:0] tx_fifo_wdata;
wire        tx_fifo_ren  ;
wire [ 7:0] tx_fifo_rdata;

wire        rx_fifo_rst  ;
wire        rx_fifo_empty;
wire        rx_fifo_full ;
wire        rx_fifo_wen  ;
wire [ 7:0] rx_fifo_wdata;
wire        rx_fifo_ren  ;
wire [ 7:0] rx_fifo_rdata;

always @ (posedge i_clk or posedge i_rst)
begin
    if (i_rst == 1'b1)
        apb_pready <= 1'b0;
    else if (i_apb_psel && (i_apb_penable == 1'b0))
        apb_pready <= 1'b0;

    else if (i_apb_psel && i_apb_penable)
        apb_pready <= 1'b1;

    else
        apb_pready <= 1'b1;
end

assign apb_wen = i_apb_psel & i_apb_penable & (i_apb_pwrite == 1'b1) & apb_pready;
assign apb_ren = i_apb_psel & i_apb_penable & (i_apb_pwrite == 1'b0) & apb_pready;

assign apb_rld = i_apb_psel & i_apb_penable & (i_apb_pwrite == 1'b0) & (apb_pready == 1'b0);

always @ (posedge i_clk or posedge i_rst)
begin
    if (i_rst == 1'b1) begin
        reg_00 <= 32'h0;
        reg_08 <= 32'h0;
    end else if (apb_wen) begin
        case (i_apb_paddr[7:0])
            8'h00   : reg_00 <= i_apb_pwdata;
            8'h08   : reg_08 <= i_apb_pwdata;
            default : begin
                reg_00 <= reg_00;
                reg_08 <= reg_08;
            end
        endcase
    end
end

always @ (posedge i_clk or posedge i_rst)
begin
    if (i_rst == 1'b1) begin
        apb_prdata <= 32'h0;
    end else if (apb_rld) begin
        case (i_apb_paddr[7:0])
            8'h00   : apb_prdata <= reg_00;
            8'h04   : apb_prdata <= reg_04;
            8'h08   : apb_prdata <= reg_08;
            8'h0c   : apb_prdata <= reg_0c;
            default : apb_prdata <= 32'hdeadbeef;
        endcase
    end
end

assign o_apb_pready = apb_pready;
assign o_apb_prdata = apb_prdata;

assign tx_fifo_rst = reg_00[0];
assign rx_fifo_rst = reg_00[1];

always @ (posedge i_clk or posedge i_rst)
begin
    if (i_rst == 1'b1) begin
        tx_en <= 1'b0;
        rx_en <= 1'b0;
    end else begin
        tx_en <= apb_wen && (i_apb_paddr[7:0] == 8'h08);
        rx_en <= apb_ren && (i_apb_paddr[7:0] == 8'h0c);
    end
end

always @ (posedge i_clk or posedge i_rst)
begin
    if (i_rst == 1'b1) begin
        tx_fifo_wen   <= 1'b0;
        tx_fifo_wdata <= 8'h0;
    end else if (tx_en) begin
        tx_fifo_wen   <= 1'b1;
        tx_fifo_wdata <= reg_08[7:0];
    end else begin
        tx_fifo_wen   <= 1'b0;
    end
end

assign rx_fifo_ren = rx_en;

always @ (posedge i_clk or posedge i_rst)
begin
    if (i_rst == 1'b1) begin
        reg_04 <= 32'h0;

    end else begin
        reg_04 <= {28'h0, rx_fifo_full, rx_fifo_empty, tx_fifo_full, tx_fifo_empty};

    end
end

assign reg_0c = {24'h0, rx_fifo_rdata};

`ifdef PH1_DDRPHY_SIM
assign tx_fifo_empty =  1'b1;
assign tx_fifo_full  =  1'b0;
assign tx_fifo_rdata = 32'h0;

always @ (posedge i_clk) begin
    if (tx_fifo_wen) begin
        $write("%s", tx_fifo_wdata);
    end
end
`else
ph1_ddrphy_mcu_uart_fifo u_tx_fifo (
    .clk          ( i_clk               ),
    .rst          ( i_rst | tx_fifo_rst ),
    .fifo_empty   ( tx_fifo_empty       ),
    .fifo_full    ( tx_fifo_full        ),
    .fifo_wr_en   ( tx_fifo_wen         ),
    .fifo_wr_data ( tx_fifo_wdata       ),
    .fifo_rd_en   ( tx_fifo_ren         ),
    .fifo_rd_data ( tx_fifo_rdata       )
);
`endif

ph1_ddrphy_mcu_uart_fifo u_rx_fifo (
    .clk          ( i_clk               ),
    .rst          ( i_rst | rx_fifo_rst ),
    .fifo_empty   ( rx_fifo_empty       ),
    .fifo_full    ( rx_fifo_full        ),
    .fifo_wr_en   ( rx_fifo_wen         ),
    .fifo_wr_data ( rx_fifo_wdata       ),
    .fifo_rd_en   ( rx_fifo_ren         ),
    .fifo_rd_data ( rx_fifo_rdata       )
);

ph1_ddrphy_mcu_uart_tx #(
    .BAUD_RATE ( BAUD_RATE ),
    .CLK_FREQ  ( CLK_FREQ  )
) u_uart_tx (
    .i_clk     ( i_clk         ),
    .i_rst     ( i_rst         ),
    .i_tx_req  (~tx_fifo_empty ),
    .i_tx_data ( tx_fifo_rdata ),
    .o_tx_ack  ( tx_fifo_ren   ),
    .o_txd     ( o_uart_txd    )
);

ph1_ddrphy_mcu_uart_rx #(
    .BAUD_RATE ( BAUD_RATE ),
    .CLK_FREQ  ( CLK_FREQ  )
) u_uart_rx (
    .i_clk     ( i_clk         ),
    .i_rst     ( i_rst         ),
    .i_rxd     ( i_uart_rxd    ),
    .o_rx_vld  ( rx_fifo_wen   ),
    .o_rx_data ( rx_fifo_wdata ),
    .o_err     (               )
);

endmodule

module ph1_ddrphy_mcu_uart_fifo (
    input        clk         ,
    input        rst         ,

    output       fifo_empty  ,
    output       fifo_full   ,

    input        fifo_wr_en  ,
    input  [7:0] fifo_wr_data,

    input        fifo_rd_en  ,
    output [7:0] fifo_rd_data
);

reg  [7:0] fifo_data[0:15]; 

reg  [3:0] fifo_wr_addr;
reg  [3:0] fifo_rd_addr;

wire [4:0] fifo_gap;

assign fifo_empty = (fifo_gap == 5'h0) ? 1'b1 : 1'b0 ;
assign fifo_full  = (fifo_gap == 5'hF) ? 1'b1 : 1'b0 ;

always @ (posedge clk)
begin
    if (fifo_wr_en) begin
        fifo_data[fifo_wr_addr] <= fifo_wr_data;
    end
end

always @ (posedge clk or posedge rst)
begin
    if (rst == 1'b1) begin
        fifo_wr_addr <= 4'h0 ;
    end else if (fifo_wr_en) begin
        if (fifo_gap == 5'h0F)
            fifo_wr_addr <= fifo_wr_addr ;
        else if (fifo_wr_addr == 4'hF) begin
            fifo_wr_addr <= 4'h0 ;
        end else begin
            fifo_wr_addr <= fifo_wr_addr + 1'b1 ;
        end
    end else begin
        fifo_wr_addr <= fifo_wr_addr ;
    end
end

always @ (posedge clk or posedge rst)
begin
    if (rst == 1'b1) begin
        fifo_rd_addr <= 4'h0 ;
    end else if (fifo_rd_en) begin
        if (fifo_gap == 5'h00) begin
            fifo_rd_addr <= fifo_rd_addr ;
        end else if (fifo_rd_addr == 4'hF) begin
            fifo_rd_addr <= 4'h0 ;
        end else begin
            fifo_rd_addr <= fifo_rd_addr + 1'b1 ;
        end
    end
end

assign fifo_rd_data = fifo_data[fifo_rd_addr[3:0]] ;

assign fifo_gap = (fifo_wr_addr >= fifo_rd_addr) ? (fifo_wr_addr - fifo_rd_addr) : ({1'b1, fifo_wr_addr} - fifo_rd_addr);

endmodule

module ph1_ddrphy_mcu_uart_tx #(
    parameter BAUD_RATE = 115_200,
    parameter CLK_FREQ  = 100_000_000
)(
    input        i_clk    ,
    input        i_rst    ,
    input        i_tx_req ,
    input  [7:0] i_tx_data,
    output       o_tx_ack ,
    output       o_txd
);

wire  baud_x16_en;

ph1_ddrphy_mcu_uart_baud_gen #(
    .CLK_FREQ   ( CLK_FREQ   ),
    .BAUD_RATE  ( BAUD_RATE  )
) u_baud_gen    (
    .i_clk      ( i_clk       ),
    .i_rst      ( i_rst       ),
    .o_x16_en   ( baud_x16_en )
);

ph1_ddrphy_mcu_uart_tx_ctl u_tx_ctl (
    .i_clk      ( i_clk       ),
    .i_rst      ( i_rst       ),
    .i_x16_en   ( baud_x16_en ),
    .i_tx_req   ( i_tx_req    ),
    .i_tx_data  ( i_tx_data   ),
    .o_tx_ack   ( o_tx_ack    ),
    .o_txd      ( o_txd       )
);

endmodule

module ph1_ddrphy_mcu_uart_rx #(
    parameter CLK_FREQ  = 100_000_000,
    parameter BAUD_RATE = 115_200
)(
    input          i_clk    ,
    input          i_rst    ,

    input          i_rxd    ,

    output  [7:0]  o_rx_data,
    output         o_rx_vld ,
    output         o_err
);

reg        rxd_sync;
wire       baud_x16_en;
wire       rx_vld   ;

always @ (posedge i_clk or posedge i_rst)
begin
    if (i_rst == 1'b1)
        rxd_sync <= 1'b1;
    else
        rxd_sync <= i_rxd;
end

ph1_ddrphy_mcu_uart_baud_gen #(
    .BAUD_RATE  ( BAUD_RATE   ),
    .CLK_FREQ   ( CLK_FREQ    )
) u_baud_gen    (
    .i_clk      ( i_clk       ),
    .i_rst      ( i_rst       ),
    .o_x16_en   ( baud_x16_en )
);

ph1_ddrphy_mcu_uart_rx_ctl u_rx_ctl (
    .i_clk      ( i_clk       ),
    .i_rst      ( i_rst       ),

    .i_x16_en   ( baud_x16_en ),
    .i_rxd      ( rxd_sync    ),

    .o_rx_vld   ( o_rx_vld    ),
    .o_rx_data  ( o_rx_data   ),
    .o_err      ( o_err       )
);

endmodule

module ph1_ddrphy_mcu_uart_tx_ctl (
    input          i_clk     ,
    input          i_rst     ,

    input          i_x16_en  ,

    input          i_tx_req  ,
    input   [7:0]  i_tx_data ,
    output         o_tx_ack  ,

    output         o_txd
);

localparam IDLE  = 2'b00;
localparam START = 2'b01;
localparam DATA  = 2'b10;
localparam STOP  = 2'b11;

reg  [1:0]  state;

reg  [3:0]  sample_cnt;
wire        sample_done;

reg  [2:0]  bit_cnt;
wire        bit_done;

reg  [7:0]  tx_data;
reg         txd_r;

always @ (posedge i_clk or posedge i_rst)
begin
    if (i_rst == 1'b1) begin
        state         <= IDLE;
    end else if (i_x16_en) begin
        case (state)
            IDLE : state <= (i_tx_req == 1'b1)                  ? START : IDLE ;
            START: state <= (sample_done == 1'b1)               ? DATA  : START; 
            DATA : state <= (sample_done && bit_done)           ? STOP  : DATA ;
            STOP : state <= (sample_done && (i_tx_req == 1'b0)) ? IDLE  :
                            (sample_done && (i_tx_req == 1'b1)) ? START : STOP ;
        endcase
    end
end

assign o_tx_ack = i_x16_en & sample_done & (state == START);

always @ (posedge i_clk or posedge i_rst)
begin
    if (i_rst == 1'b1) begin
        sample_cnt <= 4'h0;
    end else if (i_x16_en) begin
        if ((state == IDLE) && (i_tx_req == 1'b1))
            sample_cnt <= 4'h0;
        else
            sample_cnt <= sample_cnt + 1'b1;
    end
end

assign sample_done = (sample_cnt == 4'hf);

always @ (posedge i_clk or posedge i_rst)
begin
    if (i_rst == 1'b1) begin
        bit_cnt <= 3'b0;
    end else if (i_x16_en && sample_done) begin
        bit_cnt <= (state == START) ? 3'h0 :
                   (state == DATA ) ? bit_cnt + 1'b1 : bit_cnt;
    end
end

assign bit_done = (bit_cnt == 3'd7);

always @ (posedge i_clk or posedge i_rst)
begin
    if (i_rst == 1'b1) begin
        tx_data <= 8'h0;
    end else if (o_tx_ack) begin
        tx_data <= i_tx_data;
    end
end

always @ (posedge i_clk or posedge i_rst)
begin
    if (i_rst == 1'b1) begin
        txd_r <= 1'b1;
    end else if (i_x16_en) begin
        case (state)
            IDLE : txd_r <= 1'b1;
            START: txd_r <= 1'b0;
            DATA : txd_r <= tx_data[bit_cnt];
            STOP : txd_r <= 1'b1;
        endcase
    end
end

assign o_txd = txd_r;

endmodule

module ph1_ddrphy_mcu_uart_rx_ctl (
    input             i_clk   ,
    input             i_rst   ,

    input             i_x16_en,  
    input             i_rxd   ,

    output  reg [7:0] o_rx_data,
    output  reg       o_rx_vld ,
    output            o_err
);

localparam  IDLE  = 2'b00;
localparam  START = 2'b01;
localparam  DATA  = 2'b10;
localparam  STOP  = 2'b11;

reg          rx_vld ;
reg [7:0]    rx_data;
reg          frm_err;

reg [1:0]    state;

reg [3:0]    sample_cnt;
wire         sample_done;

reg [2:0]    bit_cnt;
wire         bit_done;

always @ (posedge i_clk or posedge i_rst)
begin
    if (i_rst == 1'b1) begin
        state <= IDLE;
    end else if (i_x16_en) begin
        case (state)
            IDLE : state <= (i_rxd == 1'b0) ? START : IDLE;
            START: state <= (sample_done && (i_rxd == 1'b0)) ? DATA :
                            (sample_done && (i_rxd == 1'b1)) ? IDLE : START;
            DATA : state <= (sample_done && bit_done) ? STOP : DATA;
            STOP : state <= sample_done ? IDLE : STOP;
        endcase
    end
end

always @ (posedge i_clk or posedge i_rst)
begin
    if (i_rst == 1'b1) begin
        sample_cnt <= 4'd0;
    end else if (i_x16_en) begin
        sample_cnt <= ((state == IDLE ) && (i_rxd == 1'b0)) ? 4'h8 :
                      (sample_done && (state == START) && (i_rxd == 1'b0)) ? 4'h0 :
                      (sample_done && (state == DATA ))                    ? 4'h0 : sample_cnt + 1'b1;
    end
end

assign sample_done = (sample_cnt == 4'hf);

always @ (posedge i_clk or posedge i_rst)
begin
    if (i_rst == 1'b1) begin
        bit_cnt    <= 3'b0;
    end else begin
        bit_cnt <= (i_x16_en && sample_done && (state == START)) ? 3'h0 :
                   (i_x16_en && sample_done && (state == DATA )) ? bit_cnt + 1'b1 : bit_cnt;
    end
end

assign bit_done = (bit_cnt == 3'h7);

always @ (posedge i_clk or posedge i_rst)
begin
    if (i_rst == 1'b1) begin
        rx_vld  <= 1'b0;
        rx_data <= 8'b0000_0000;
    end else begin
        if (i_x16_en && sample_done) begin
            if (state == DATA) begin
                rx_vld           <= bit_done;
                rx_data[bit_cnt] <= i_rxd;
            end else begin
                rx_vld <= 1'b0;
            end
        end
    end
end

always @ (posedge i_clk or posedge i_rst)
begin
    if (i_rst == 1'b1) begin
        frm_err <= 1'b0;
    end else if (i_x16_en) begin
        if ((state == STOP) && sample_done && (i_rxd == 1'b0)) begin
            frm_err <= 1'b1;
        end else begin
            frm_err <= 1'b0;
        end
    end
end

always @ (posedge i_clk or posedge i_rst)
begin
    if (i_rst == 1'b1) begin
        o_rx_vld  <= 1'b0;
        o_rx_data <= 8'h0;
    end else if (i_x16_en && sample_done && rx_vld) begin
        o_rx_vld  <= rx_vld ;
        o_rx_data <= rx_data;
    end else begin
        o_rx_vld  <= 1'b0;
    end
end

assign o_err = frm_err;

endmodule

module ph1_ddrphy_mcu_uart_baud_gen #(
    CLK_FREQ  = 100_000_000,
    BAUD_RATE = 115_200
)(
    input   i_clk,
    input   i_rst,
    output  o_x16_en
);

localparam integer MAX_CNT = CLK_FREQ/(BAUD_RATE*16);

reg  [31:0] cnt_r;
reg         baud_x16_en;

always @ (posedge i_clk or posedge i_rst)
begin
    if (i_rst == 1'b1) begin
        cnt_r <= 32'h0;
    end else if (cnt_r == MAX_CNT) begin
        cnt_r <= 32'h0;
    end else begin
        cnt_r <= cnt_r + 1'b1;
    end
end

always @ (posedge i_clk or posedge i_rst)
begin
    if (i_rst == 1'b1) begin
        baud_x16_en <= 1'b0;
    end else begin
        baud_x16_en <= (cnt_r == MAX_CNT-1) ? 1'b1 : 1'b0;
    end
end

assign o_x16_en = baud_x16_en;

endmodule

`timescale 1ps/1ps

module ph1_ddrphy_apb_2to1 (

    input                   clk           ,
    input                   rst_n         ,

    input  wire             i_p0_psel     ,
    input  wire             i_p0_pen      ,
    input  wire             i_p0_pwrite   ,
    input  wire [32-1:0]    i_p0_paddr    ,
    input  wire [32-1:0]    i_p0_pwdata   ,
    output reg              o_p0_pready   ,
    output reg  [32-1:0]    o_p0_prdata   ,

    input  wire             i_p1_psel     ,
    input  wire             i_p1_pen      ,
    input  wire             i_p1_pwrite   ,
    input  wire [32-1:0]    i_p1_paddr    ,
    input  wire [32-1:0]    i_p1_pwdata   ,
    output reg              o_p1_pready   ,
    output reg  [32-1:0]    o_p1_prdata   ,

    output wire             o_apb_psel    ,
    output wire             o_apb_pen     ,
    output wire             o_apb_pwrite  ,
    output wire [32-1:0]    o_apb_paddr   ,
    output wire [32-1:0]    o_apb_pwdata  ,
    input  wire             i_apb_pready  ,
    input  wire [32-1:0]    i_apb_prdata
);

localparam TCQ             = 0; 

localparam REG_IDLE        = 4'b0001;
localparam REG_APB0_ACCESS = 4'b0010;
localparam REG_APB1_ACCESS = 4'b0100;
localparam REG_ACCESS_EXIT = 4'b1000;

reg  [32-1:0]  arb_paddr;
reg            arb_psel;
reg            arb_penable;
reg            arb_pwrite;
reg  [32-1:0]  arb_pwdata;
wire           arb_pready;
wire [32-1:0]  arb_prdata;

reg  [3   :0]  state_cur;
reg  [3   :0]  state_nxt;

wire       rra_rst;
wire [1:0] rra_req;
wire [1:0] rra_ack;

assign rra_req = {i_p1_psel, i_p0_psel};
assign rra_rst = 1'b0;

ph1_ddrphy_apb_arb u_apb_arb (
    .clk      ( clk      ),
    .rst_n    ( rst_n    ),
    .rra_rst  ( rra_rst  ),
    .rra_req  ( rra_req  ),
    .rra_ack  ( rra_ack  )
);

always @ (posedge clk or negedge rst_n)
begin
    if (rst_n == 1'b0)
        state_cur <= #TCQ REG_IDLE;
    else
        state_cur <= #TCQ state_nxt;
end

always @ (*) begin
    state_nxt = state_cur;
    case (state_cur)
        REG_IDLE: begin
            if (rra_ack[0])
                state_nxt = REG_APB0_ACCESS;
            else if (rra_ack[1])
                state_nxt = REG_APB1_ACCESS;
            else
                state_nxt = REG_IDLE;
        end
        REG_APB0_ACCESS: begin
            if (arb_pready)
                state_nxt = REG_ACCESS_EXIT;
            else
                state_nxt = REG_APB0_ACCESS;
        end
        REG_APB1_ACCESS: begin
            if (arb_pready)
                state_nxt = REG_ACCESS_EXIT;
            else
                state_nxt = REG_APB1_ACCESS;
        end
        REG_ACCESS_EXIT: begin
            state_nxt = REG_IDLE;
        end
        default:  begin
            state_nxt = REG_IDLE;
        end
    endcase
end

always @ (posedge clk or negedge rst_n)
begin
    if (rst_n == 1'b0) begin
        arb_psel     <= #TCQ 1'b0;
        arb_penable  <= #TCQ 1'b0;
    end else if  ((state_cur == REG_IDLE) && ((state_nxt == REG_APB0_ACCESS) || (state_nxt == REG_APB1_ACCESS))) begin
        arb_psel     <= #TCQ 1'b1;
        arb_penable  <= #TCQ 1'b0;
    end else if (((state_cur == REG_APB0_ACCESS) && (state_nxt == REG_APB0_ACCESS)) || ((state_cur == REG_APB1_ACCESS) && (state_nxt == REG_APB1_ACCESS))) begin
        arb_psel     <= #TCQ 1'b1;
        arb_penable  <= #TCQ 1'b1;
    end else if (((state_cur == REG_APB0_ACCESS) || (state_cur == REG_APB1_ACCESS)) && (state_nxt == REG_ACCESS_EXIT)) begin
        arb_psel     <= #TCQ 1'b0;
        arb_penable  <= #TCQ 1'b0;
    end
end

always @ (posedge clk or negedge rst_n)
begin
    if (rst_n == 1'b0) begin
        arb_pwrite   <= #TCQ  1'b1;
        arb_paddr    <= #TCQ 32'h0;
        arb_pwdata   <= #TCQ 32'h0;
    end else if ((state_cur == REG_IDLE) && (state_nxt == REG_APB0_ACCESS)) begin
        arb_pwrite   <= #TCQ i_p0_pwrite;
        arb_paddr    <= #TCQ i_p0_paddr;
        arb_pwdata   <= #TCQ i_p0_pwdata;
    end else if ((state_cur == REG_IDLE) && (state_nxt == REG_APB1_ACCESS)) begin
        arb_pwrite   <= #TCQ i_p1_pwrite;
        arb_paddr    <= #TCQ i_p1_paddr;
        arb_pwdata   <= #TCQ i_p1_pwdata;
    end
end

always @ (posedge clk or negedge rst_n)
begin
    if (rst_n == 1'b0) begin
        o_p0_pready <= #TCQ 1'b1;
    end else if ((i_p0_pen == 1'b0) && (i_p0_psel == 1'b1)) begin
        o_p0_pready <= #TCQ 1'b0;
    end else if ((state_cur == REG_APB0_ACCESS) && (state_nxt == REG_ACCESS_EXIT)) begin
        o_p0_pready <= #TCQ 1'b1;
    end
end

always @ (posedge clk or negedge rst_n)
begin
    if (rst_n == 1'b0)  begin
        o_p1_pready <= #TCQ 1'b1;
    end else if ((i_p1_pen == 1'b0) && (i_p1_psel == 1'b1)) begin
        o_p1_pready <= #TCQ 1'b0;
    end else if ((state_cur == REG_APB1_ACCESS) && (state_nxt == REG_ACCESS_EXIT)) begin
        o_p1_pready <= #TCQ 1'b1;
    end
end

always @ (posedge clk or negedge rst_n)
begin
    if (rst_n == 1'b0) begin
        o_p0_prdata <= #TCQ 32'h0;
        o_p1_prdata <= #TCQ 32'h0;
    end else if ((state_cur == REG_APB0_ACCESS) && (state_nxt == REG_ACCESS_EXIT)) begin
        o_p0_prdata <= #TCQ arb_prdata;
    end else if ((state_cur == REG_APB1_ACCESS) && (state_nxt == REG_ACCESS_EXIT)) begin
        o_p1_prdata <= #TCQ arb_prdata;
    end
end

assign  o_apb_psel    =  arb_psel;
assign  o_apb_pen     =  arb_psel & arb_penable;
assign  o_apb_pwrite  =  arb_psel & arb_pwrite ;
assign  o_apb_paddr   =  arb_paddr  ;
assign  o_apb_pwdata  =  arb_pwdata ;

assign  arb_pready    =  (arb_psel & arb_penable) ? i_apb_pready : arb_penable;
assign  arb_prdata    =  i_apb_prdata;

endmodule

`timescale 1ps/1ps

module ph1_ddrphy_apb_arb (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       rra_rst,
    input  wire [1:0] rra_req,
    output wire [1:0] rra_ack
);

localparam TCQ                   = 0;

localparam ARB_RESET             = 2'b00;
localparam IDLE                  = 2'b01;
localparam WAIT_FOR_REQ_DEASSERT = 2'b10;

reg  [1:0] index_cur;
reg  [1:0] index_cur_r;

reg  [1:0] state_cur;
reg  [1:0] state_nxt;

always @ (posedge clk or negedge rst_n)
begin
    if (rst_n == 1'b0) begin
        state_cur   <= #TCQ ARB_RESET;
        index_cur_r <= #TCQ 2'b00;
    end else begin
        state_cur   <= #TCQ state_nxt;
        index_cur_r <= #TCQ index_cur;
    end
end

always @ (*) begin

    index_cur = index_cur_r;
    state_nxt = state_cur;

    case (state_nxt)

        ARB_RESET : begin
            index_cur = 2'b01;
            if (rra_rst == 1'b0) begin
                state_nxt = IDLE;
            end
        end

        

        
        IDLE : begin
            if (rra_rst) begin
                index_cur = 2'b01;
                state_nxt = ARB_RESET;
            end else if (rra_req != 2'b00) begin
                state_nxt = WAIT_FOR_REQ_DEASSERT;

                if ((rra_req & index_cur_r) == 2'b00) begin
                    if ((rra_req & {index_cur_r[0], index_cur_r[1]}) != 2'b00)
                        index_cur = {index_cur_r[0], index_cur_r[1]};
                end
            end
        end

        
        WAIT_FOR_REQ_DEASSERT : begin
            if (rra_rst) begin
                index_cur = 2'b01;
                state_nxt = ARB_RESET;
            end

            
            else if ((rra_req & index_cur_r) == 2'b00) begin
                if (rra_req != 2'b00) begin
                    if ((rra_req & {index_cur_r[0], index_cur_r[1]}) != 2'b00)
                        index_cur = {index_cur_r[0], index_cur_r[1]};
                end

                
                else begin
                    index_cur = {index_cur_r[0], index_cur_r[1]};
                    state_nxt = IDLE;
                end
            end
        end

        default : begin
            state_nxt = ARB_RESET;
            index_cur = 2'b01;
        end
    endcase
end

assign rra_ack = (rra_req != 2'b00) ? index_cur : 2'b00;

endmodule

`timescale 1ps/1ps

module ph1_ddrphy_cfg_rom #(
    parameter DDRPHY_CFG_ROM = ""
)(

    input              clk         ,
    input              rst         ,

    input              apb_psel    ,
    input              apb_penable ,
    input              apb_pwrite  ,
    input      [31:0]  apb_paddr   ,
    input      [31:0]  apb_pwdata  ,
    output reg [31:0]  apb_prdata  ,
    output reg         apb_pready  ,

    input      [ 7:0]  uram_addr   ,
    output     [31:0]  uram_rdata

);

localparam  AW    = 8;
localparam  DW    = 32;
localparam  DEPTH = 2**AW;

reg  [DW-1:0] mem[DEPTH-1:0]; 

reg  [AW-1:0] mem_addr;
wire [DW-1:0] mem_rdata;

reg           mem_wen;
reg  [DW-1:0] mem_wdata;

wire          apb_wen;
wire          apb_ren;

assign apb_wen = apb_psel & apb_penable & (apb_pwrite == 1'b1) & apb_pready;
assign apb_ren = apb_psel & apb_penable & (apb_pwrite == 1'b0);

always @ (posedge clk or posedge rst)
begin
    if (rst == 1'b1)
        apb_pready <= 1'b0;
    else if (apb_psel && (apb_penable == 1'b0))
        apb_pready <= 1'b0;
    else if (apb_psel && (apb_penable == 1'b1) && (apb_pwrite == 1'b1))
        apb_pready <= 1'b1;
    else if (apb_psel && (apb_penable == 1'b1) && (apb_pwrite == 1'b1))
        apb_pready <= apb_ren;
    else
        apb_pready <= 1'b1;
end

always @ (posedge clk or posedge rst)
begin
    if (rst == 1'b1)
        apb_prdata <= 32'h0;
    else if (apb_ren)
        apb_prdata <= mem_rdata;
end

initial begin
    $readmemh(DDRPHY_CFG_ROM, mem);
end

always @ (posedge clk or posedge rst)
begin
    if (rst == 1'b1) begin
        mem_addr <= {AW{1'b0}};
    end else begin
        mem_addr = apb_paddr[2+:AW];
    end
end

always @ (posedge clk or posedge rst)
begin
    if (rst == 1'b1) begin
        mem_wen   <= 1'b0;
        mem_wdata <= 32'h0;
    end else begin
        mem_wen   <= apb_wen ? 1'b1 : 1'b0;
        mem_wdata <= apb_wen ? apb_pwdata : mem_wdata;
    end
end

always @ (posedge clk) begin
    if (mem_wen)
        mem[mem_addr] <= mem_wdata;
end

assign mem_rdata  = mem[mem_addr];

assign uram_rdata = mem[uram_addr];

endmodule

