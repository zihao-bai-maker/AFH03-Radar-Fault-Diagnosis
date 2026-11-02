

module ui_dbuf#(
parameter  integer                      AXI_DATA_WIDTH = 128	, 
parameter  integer                      AXI_ADDR_WIDTH = 32		, 

parameter  integer                      ENABLE_VSYNC   = 1		,

parameter  integer                      W_BUFDEPTH     = 2048	, 
parameter  integer                      W_DATAWIDTH    = 32		, 
parameter  [AXI_ADDR_WIDTH -1'b1: 0]    W_BASEADDR     = 0		, 
parameter  integer                      W_DSIZEBITS    = 24		, 
parameter  integer                      W_XSIZE        = 1920	, 
parameter  integer                      W_XSTRIDE      = 1920	, 
parameter  integer                      W_YSIZE        = 1080	, 
parameter  integer                      W_XDIV         = 2		, 
parameter  integer                      W_BUFSIZE      = 3		, 

parameter  integer                      R_BUFDEPTH     = 2048	, 
parameter  integer                      R_DATAWIDTH    = 32		, 
parameter  [AXI_ADDR_WIDTH -1'b1: 0]    R_BASEADDR     = 0		, 
parameter  integer                      R_DSIZEBITS    = 24		, 
parameter  integer                      R_XSIZE        = 1920	, 
parameter  integer                      R_XSTRIDE      = 1920	, 
parameter  integer                      R_YSIZE        = 1080	, 
parameter  integer                      R_XDIV         = 2		, 
parameter  integer                      R_BUFSIZE      = 3 		  
) 
(
input   wire                            I_ui_clk		,
input   wire                            I_ui_rstn		,

input   wire                            I_W_en			,
input   wire                            I_W_wclk		, 
input   wire                            I_W_tuser		,  
input   wire                            I_W_tvalid		,
input   wire [W_DATAWIDTH -1 : 0]       I_W_tdata		,
input   wire                            I_W_tlast		,
output  wire                            O_W_tready		,
output  reg  [7 : 0]                    O_W_sync_cnt	,
input   wire [7 : 0]                    I_W_buf			,

output  wire [AXI_ADDR_WIDTH- 1:0]      O_fdma_waddr	,
output  wire                            O_fdma_wareq	,
output  wire [15  :0]                   O_fdma_wsize	,
input   wire                            I_fdma_wbusy	,
output  wire [AXI_DATA_WIDTH - 1:0]     O_fdma_wdata	,
input   wire                            I_fdma_wvalid	,
output  wire                            O_fdma_wready	,
output  reg [7 : 0]                     O_fdma_wbuf		,
output  wire                            O_fdma_wirq		,

input   wire                            I_R_en			, 
input   wire                            I_Rsync_en		,
input   wire                            I_R_rclk		,  
input   wire                            I_R_tready		,  
output  wire                            O_R_tuser		,
output  wire                            O_R_tvalid		,
output  wire [R_DATAWIDTH- 1 : 0]       O_R_tdata		,
output  wire                            O_R_vrst		,
output  wire                            O_R_tlast		,  
output  reg  [7 : 0] 					O_R_sync_cnt 	,
input   wire [7 : 0] 					I_R_buf			,

output  wire [AXI_ADDR_WIDTH-1'b1: 0]   O_fdma_raddr	, 
output  wire                            O_fdma_rareq	, 
output  wire [15: 0]                    O_fdma_rsize	, 
input   wire                            I_fdma_rbusy	, 
input   wire [AXI_DATA_WIDTH-1'b1:0]    I_fdma_rdata	, 
input   wire                            I_fdma_rvalid	, 
output  wire                            O_fdma_rready	, 
output  reg  [7  :0]                    O_fdma_rbuf 	, 
output  wire                            O_fdma_rirq 	  
);

function integer clog2;
    input integer value;
    begin
      for (clog2 = 0; value > 0; clog2 = clog2 + 1) value = value >> 1;
    end
endfunction

localparam    S_IDLE  = 2'd0;
localparam    S_RST   = 2'd1;
localparam    S_DATA1 = 2'd2;
localparam    S_DATA2 = 2'd3;

localparam    WFIFO_DEPTH           = W_BUFDEPTH;  
localparam    W_WR_DATA_COUNT_WIDTH = clog2(WFIFO_DEPTH);  
localparam    W_RD_DATA_COUNT_WIDTH = clog2(
      WFIFO_DEPTH * W_DATAWIDTH / AXI_DATA_WIDTH
);  

localparam    WYBUF_SIZE = (W_BUFSIZE - 1'b1);  
localparam    WY_BURST_TIMES       = (W_YSIZE*W_XDIV);
localparam    FDMA_WX_BURST        = (W_XSIZE*W_DATAWIDTH/AXI_DATA_WIDTH)/W_XDIV; 
localparam    WX_BURST_ADDR_INC    = (W_XSIZE*(W_DATAWIDTH/8))/W_XDIV; 
localparam    WX_LAST_ADDR_INC     = (W_XSTRIDE-W_XSIZE)*(W_DATAWIDTH/8) + WX_BURST_ADDR_INC; 

wire                              W_empty;

wire[W_RD_DATA_COUNT_WIDTH-1 : 0] W_rcnt;
reg [W_RD_DATA_COUNT_WIDTH-1 : 0] W_rcnt_r1,W_rcnt_r2;
reg [8  : 0]                      wrst_cnt;
reg                               wfifo_rst_done;
reg                               wfifo_rst_lock;

reg                               W_tuser_r3,W_tuser_r2, W_tuser_r1;
reg                               W_tvalid_r1;
reg                               W_tlast_r1,W_tlast_r2;
reg [W_DATAWIDTH -1 : 0]          W_tdata_r1;
always @(posedge I_W_wclk) begin
              W_tuser_r1        <= I_W_tuser;
              W_tuser_r2        <= W_tuser_r1;
              W_tlast_r1        <= I_W_tlast;
              W_tlast_r2        <= W_tlast_r1;
              W_tvalid_r1       <= I_W_tvalid;
              W_tdata_r1        <= I_W_tdata;          
              W_tuser_r3        <= W_tuser_r2|W_tuser_r1|I_W_tuser;
end  

always @(posedge I_W_wclk or negedge I_ui_rstn) begin
  if (~I_ui_rstn) begin
              wrst_cnt          <= 0;
              wfifo_rst_done    <= 0;
              wfifo_rst_lock    <= 0;
  end
  else if(I_W_tuser & (W_empty == 1'b0)) begin 
              wfifo_rst_lock    <= 1;
              wfifo_rst_done    <= 0;
              wrst_cnt          <= 0;
  end 
  else if(wfifo_rst_lock & (wrst_cnt[8] == 0))  
              wrst_cnt          <= wrst_cnt + 1'b1;
  else if(W_MS == S_IDLE & I_W_tuser)begin      
              wrst_cnt          <= 0;
              wfifo_rst_done    <= 1;
              wfifo_rst_lock    <= 0;
  end
end

wire   wfifo_rst  = (wrst_cnt >10) & (wrst_cnt <80) ;

reg [1:0]     W_MS_r = 0;
always @(posedge I_ui_clk) W_MS_r <= W_MS;

always @(posedge I_ui_clk) begin
    if (I_ui_rstn == 1'b0) begin
              wirq_dly_cnt      <= 6'd0;
              O_fdma_wbuf       <= 0;
    end else if ((W_MS_r == S_DATA2) && (W_MS == S_IDLE)) begin
              wirq_dly_cnt      <= 60;
              O_fdma_wbuf       <= O_fdma_wbufn;
    end else if (wirq_dly_cnt > 0)
              wirq_dly_cnt      <= wirq_dly_cnt - 1'b1;
end

assign O_fdma_wareq = O_fdma_wareq_r;

reg           wfifo_rst_done_r1 = 1'b0, wfifo_rst_done_r2 = 1'b0, wfifo_rst_done_r3 = 1'b0;
always @(posedge I_ui_clk) begin
              wfifo_rst_done_r1 <= wfifo_rst_done;
              wfifo_rst_done_r2 <= wfifo_rst_done_r1;
end

reg           wfs_r1,wfs_r2,wfs_r3,wfs_r4;
always @(posedge I_ui_clk) begin
              wfs_r1            <= W_tuser_r3;
              wfs_r2            <= wfs_r1;
              wfs_r3            <= wfs_r2;
              wfs_r4            <= wfs_r3;
end

wire            w_fs;
assign          w_fs              = {wfs_r4,wfs_r3} == 2'b10 ? 1 : 0;

always @(posedge I_ui_clk)begin
              W_rcnt_r1           <= W_rcnt;
              W_rcnt_r2           <= W_rcnt_r1;
end

always @(posedge I_ui_clk) W_REQ <= (W_rcnt_r2 > FDMA_WX_BURST - 1);

assign        O_fdma_wready = 1'b1;

reg [1 : 0]   W_MS                = 0;
reg [W_DSIZEBITS-1'b1:0] W_addr   = 0;
reg [15:0]    W_bcnt              = 0;
reg           W_REQ               = 0;
reg [5 : 0]   wirq_dly_cnt        = 0;
reg [3 : 0]   wdiv_cnt            = 0;

assign        O_fdma_wsize        = FDMA_WX_BURST;
assign        O_fdma_wirq         = (wirq_dly_cnt > 0);
assign        O_fdma_waddr        = W_BASEADDR + {O_fdma_wbufn,W_addr};
reg           O_fdma_wareq_r      = 1'b0; 
reg           W_FIFO_Rst          = 0;
reg [7 : 0]   O_fdma_wbufn;

always @(posedge I_ui_clk) begin
  if (!I_ui_rstn) begin
              W_MS              <= S_IDLE;
              W_FIFO_Rst        <= 0;
              W_addr            <= 0;
              O_W_sync_cnt      <= 0;
              W_bcnt            <= 0;
              wdiv_cnt          <= 0;
              O_fdma_wbufn      <= 0;
    end else begin
      case (W_MS)
        S_IDLE: begin
              W_addr            <= 0;
              W_bcnt            <= 0;
              wdiv_cnt          <= 0;
          if((I_W_en & (wfifo_rst_done_r2 & w_fs) )) begin 
		    W_MS              <= S_RST;
            if((O_W_sync_cnt == WYBUF_SIZE && O_fdma_rbufn == 0) ||(O_W_sync_cnt + 1 == O_fdma_rbufn))
              O_W_sync_cnt  <=  O_W_sync_cnt;
            else  if (O_W_sync_cnt < WYBUF_SIZE)  
              O_W_sync_cnt <= O_W_sync_cnt + 1'b1;
            else O_W_sync_cnt <= 0;
          end
        end
        S_RST:begin
              O_fdma_wbufn      <= I_W_buf;
              W_MS              <= S_DATA1;
        end
        S_DATA1: begin  
          if (wfifo_rst_done_r2 == 1'b0) 
              W_MS              <= S_IDLE;
          else if (I_fdma_wbusy == 1'b1) begin
              W_MS              <= S_DATA2;
          end
        end
        S_DATA2: begin  
          if (I_fdma_wbusy == 1'b0) begin
            if (W_bcnt == WY_BURST_TIMES - 1'b1)  
              W_MS              <= S_IDLE;
            else begin
              if(wdiv_cnt < W_XDIV - 1'b1)begin
                W_addr          <= W_addr + WX_BURST_ADDR_INC;  
                wdiv_cnt        <= wdiv_cnt + 1'b1;
              end else begin
                W_addr          <= W_addr + WX_LAST_ADDR_INC; 
                wdiv_cnt        <= 0;
              end
                W_bcnt          <= W_bcnt + 1'b1;
                W_MS            <= S_DATA1;
            end
          end
        end
        default: W_MS           <= S_IDLE;
      endcase
    end
end

wire          W_full_pro;
wire          O_W_full;
assign        O_W_tready = 1'b1;

wire   wfifo_wen  = W_tvalid_r1 & wfifo_rst_done;

sfifo #( 
.DATA_WIDTH_W(W_DATAWIDTH), 
.DATA_WIDTH_R(AXI_DATA_WIDTH), 
.ADDR_WIDTH_W(W_WR_DATA_COUNT_WIDTH), 
.ADDR_WIDTH_R(W_RD_DATA_COUNT_WIDTH), 
.AL_FULL_NUM(WFIFO_DEPTH-2), 
.AL_EMPTY_NUM(2), 
.SHOW_AHEAD_EN(1'b1) , 
.OUTREG_EN ("NOREG")
) wdbuf_fifo (
.rst          ((I_ui_rstn == 1'b0) | wfifo_rst  ),
.clkw         (I_W_wclk                         ),
.we           (wfifo_wen                        ),
.di           (W_tdata_r1                       ),
.full_flag    (O_W_full                         ),
.afull        (W_full_pro                       ),
.clkr         (I_ui_clk                         ),
.re           (I_fdma_wvalid                    ),
.dout         (O_fdma_wdata                     ),
.empty_flag   (W_empty                          ),
.rdusedw      (W_rcnt                           )
);

localparam RYBUF_SIZE = (R_BUFSIZE - 1'b1);  
localparam RY_BURST_TIMES             = (R_YSIZE*R_XDIV); 
localparam FDMA_RX_BURST              = (R_XSIZE*R_DATAWIDTH/AXI_DATA_WIDTH)/R_XDIV; 
localparam RX_BURST_ADDR_INC          = (R_XSIZE*(R_DATAWIDTH/8))/R_XDIV; 
localparam RX_LAST_ADDR_INC           = (R_XSTRIDE-R_XSIZE)*(R_DATAWIDTH/8) + RX_BURST_ADDR_INC; 

localparam RFIFO_DEPTH                = R_BUFDEPTH*R_DATAWIDTH/AXI_DATA_WIDTH;
localparam R_WR_DATA_COUNT_WIDTH      = clog2(RFIFO_DEPTH);  
localparam R_RD_DATA_COUNT_WIDTH      = clog2(R_BUFDEPTH);  

assign O_fdma_rready = 1'b1;
reg                                     O_fdma_rareq_r = 1'b0;
reg  [                         1 : 0]   R_MS = 0;
reg  [            R_DSIZEBITS-1'b1:0]   R_addr = 0;
reg  [                          15:0]   R_bcnt = 0;
wire [R_WR_DATA_COUNT_WIDTH-1'b1 : 0]   R_wcnt;
reg  [R_WR_DATA_COUNT_WIDTH-1'b1 : 0]   R_wcnt_r1,R_wcnt_r2;
reg                                     R_REQ = 0;
reg  [                         5 : 0]   rirq_dly_cnt = 0;
reg  [                         3 : 0]   rdiv_cnt = 0;
reg  [                         7 : 0]   rrst_cnt = 0;
reg  [                         7 : 0]   O_fdma_rbufn;
assign    O_fdma_rsize                 = FDMA_RX_BURST;
assign    O_fdma_rirq                  = (rirq_dly_cnt > 0);

assign    O_fdma_raddr                 = R_BASEADDR + {O_fdma_rbufn,R_addr};

reg  [1 :0] R_MS_r = 0;

always @(posedge I_ui_clk)      R_MS_r <= R_MS;

always @(posedge I_ui_clk) begin
  if (I_ui_rstn == 1'b0) begin
              rirq_dly_cnt        <= 6'd0;
              O_fdma_rbuf         <= 0;
  end else if ((R_MS_r == S_DATA2) && (R_MS == S_IDLE)) begin
              rirq_dly_cnt        <= 60;
              O_fdma_rbuf         <= O_fdma_rbufn;
  end else if (rirq_dly_cnt > 0) 
              rirq_dly_cnt        <= rirq_dly_cnt - 1'b1;
end

assign        O_fdma_rareq         = O_fdma_rareq_r;

reg rfifo_rst;
reg rfs_r1,rfs_r2,rfs_r3,rfs_r4;

always @(posedge I_ui_clk) begin
              rfs_r1            <= I_R_en;
              rfs_r2            <= rfs_r1;
              rfs_r3            <= rfs_r2;
              rfs_r4            <= rfs_r3;
end

always @(posedge I_ui_clk) begin
  if (!I_ui_rstn) begin
              R_MS              <= S_IDLE;
              R_addr            <= 0;
              O_R_sync_cnt      <= 0;
              R_bcnt            <= 0;
              rrst_cnt          <= 0;
              rdiv_cnt          <= 0;
              O_fdma_rbufn      <= 0;
  end else begin
    case (R_MS) 
    S_IDLE: begin
              R_addr          <= 0;
              R_bcnt          <= 0;
              rrst_cnt        <= 0;
              rdiv_cnt        <= 0;
      if({rfs_r4,rfs_r3} == 2'b10 | (ENABLE_VSYNC == 0)) begin
              R_MS <= S_RST;
        if(O_R_sync_cnt < RYBUF_SIZE) 
              O_R_sync_cnt    <= O_R_sync_cnt + 1'b1;
        else  O_R_sync_cnt    <= 0;
      end

    end
    S_RST: begin  
 		          O_fdma_rbufn    <= I_R_buf;
              R_MS            <= S_DATA1;
    end
    S_DATA1: begin
      if (I_fdma_rbusy == 1'b1) begin
              R_MS            <= S_DATA2;
      end
    end
    S_DATA2: begin  
      if (I_fdma_rbusy == 1'b0) begin
        if (R_bcnt == RY_BURST_TIMES - 1'b1)  
              R_MS            <= S_IDLE;
        else begin
          if(rdiv_cnt < R_XDIV - 1'b1)begin
              R_addr          <= R_addr + RX_BURST_ADDR_INC;  
              rdiv_cnt        <= rdiv_cnt + 1'b1;
          end else begin
              R_addr          <= R_addr + RX_LAST_ADDR_INC; 
              rdiv_cnt        <= 0;
          end
              R_bcnt          <= R_bcnt + 1'b1;
              R_MS            <= S_DATA1;
        end
      end
    end
    default:  R_MS            <= S_IDLE;
    endcase
  end
end

wire          R_empty;  
wire          R_tvalid;  
assign        R_tvalid        = ~R_empty;

always @(posedge I_ui_clk) begin
              R_wcnt_r1       <= R_wcnt;
              R_wcnt_r2       <= R_wcnt_r1;
end
always @(posedge I_ui_clk) R_REQ <= (R_wcnt_r2 < FDMA_RX_BURST - 1 );

assign        O_R_tvalid      = ~R_empty &(I_R_tready);

reg           r_tuser_lock;  

reg           r_tlast;  
reg [15:0]    r_xcnt;  
reg           fram_end;  
reg [15:0]    r_ycnt;  

assign        O_R_tuser = r_tuser_lock & O_R_tvalid;
assign        O_R_tlast = (r_xcnt == R_XSIZE - 1) & O_R_tvalid;

always @(posedge I_R_rclk or negedge I_ui_rstn) begin
  if (~I_ui_rstn) 
              r_xcnt          <= 0;
  else if (O_R_tvalid) begin
    if (r_xcnt == R_XSIZE - 1) 
              r_xcnt          <= 0;
    else      
              r_xcnt          <= r_xcnt + 1'b1;
  end
end

always @(posedge I_R_rclk or negedge I_ui_rstn) begin
  if (~I_ui_rstn) begin
              r_tuser_lock    <= 1'b1;
              r_ycnt          <= 0;
  end else begin
    if (O_R_tlast) begin
      if (r_ycnt == R_YSIZE - 1) begin
              r_tuser_lock    <= 1'b1;
              r_ycnt          <= 0;
      end 
      else 
              r_ycnt          <= r_ycnt + 1'b1;
    end 
    else if (O_R_tuser)
              r_tuser_lock    <= 1'b0;
  end
end

reg [20:0]    dl_cnt;
assign        O_R_vrst        = ~dl_cnt[20];
always @(posedge I_R_rclk or negedge I_ui_rstn) begin
  if(~I_ui_rstn)
              dl_cnt          <= 0;
  else if(~dl_cnt[20])
               dl_cnt         <= dl_cnt + 1'b1;
end

sfifo #( 
.DATA_WIDTH_W(AXI_DATA_WIDTH), 
.DATA_WIDTH_R(R_DATAWIDTH), 
.ADDR_WIDTH_W(R_WR_DATA_COUNT_WIDTH), 
.ADDR_WIDTH_R(R_RD_DATA_COUNT_WIDTH), 
.AL_FULL_NUM(RFIFO_DEPTH-2), 
.AL_EMPTY_NUM(2), 
.SHOW_AHEAD_EN(1'b1) , 
.OUTREG_EN ("NOREG")
) rdbuf_fifo (
.rst       (I_ui_rstn == 1'b0             ),
.clkw      (I_ui_clk                      ),
.we        (I_fdma_rvalid                 ),
.di        (I_fdma_rdata                  ),
.wrusedw   (R_wcnt                        ),
.clkr      (I_R_rclk                      ),
.re        (O_R_tvalid                    ),
.dout      (O_R_tdata                     ),
.empty_flag(R_empty                       )
);

reg [1:0]WR_S;

always @(posedge I_ui_clk) begin
  if(!I_ui_rstn)begin
              WR_S            <= 2'd0;
              O_fdma_wareq_r  <= 1'd0;
              O_fdma_rareq_r  <= 1'd0;
  end
  else begin
    case(WR_S)
    0:begin
      if(I_fdma_wbusy == 1'b0 && W_REQ && W_MS == S_DATA1)begin 
              O_fdma_wareq_r  <= 1'b1;
              WR_S            <= 2'd1;
      end  
      else if(I_fdma_rbusy == 1'b0 && R_REQ  && R_MS == S_DATA1)begin
              O_fdma_rareq_r  <= 1'b1;  
              WR_S            <= 2'd2;
      end
    end
    1:begin
      if(I_fdma_wbusy == 1'b1) begin 
              O_fdma_wareq_r  <= 1'b0;
              WR_S            <= 3;
      end
    end          
    2:begin
      if(I_fdma_rbusy == 1'b1) begin 
              O_fdma_rareq_r  <= 1'b0;
              WR_S            <= 3;
      end            
    end
    3:begin
      if(I_fdma_wbusy==0&&I_fdma_rbusy==0)
              WR_S            <= 0;
      end
    default:  WR_S            <= 0;
    endcase
    end
end  

endmodule

