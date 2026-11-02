

module ui_image_cut  #(   
    parameter [12:0] IMG_WIDTH  		= 640,
    parameter [12:0] IMG_HEIGHT 		= 480,
    parameter 	     DATA_WIDTH 		= 96,
	parameter	     SKIP_ROWS_top 		= 2, 
	parameter	     SKIP_ROWS_bottom 	= 2,
    parameter        SKIP_COLS_left  	= 2,
    parameter        SKIP_COLS_right 	= 2
) 
(
    input                       I_clk  ,
    input                       I_rst_n,

    input                       I_tlast  ,
    input                       I_tuser  ,
    input [DATA_WIDTH-1:0]      I_tdata  ,
    input                       I_tvalid , 
    output                      I_tready ,

    output                      O_tlast  ,
    output                      O_tuser  ,
    output reg [DATA_WIDTH-1:0] O_tdata  ,
    output                      O_tvalid ,
    input                       O_tready
);
reg 	[13:0]        h_cnt , v_cnt ; 

reg  [DATA_WIDTH-1:0] I_tdata_r;
reg                   I_tlast_r0 ,I_tuser_r0,I_tvalid_r0;
reg                   I_tlast_r1 ,I_tuser_r1,I_tvalid_r1;

localparam IMG_WIDTH_4x = (IMG_WIDTH >> 2);

wire  w_skip = (v_cnt < SKIP_ROWS_top) ||(h_cnt < SKIP_COLS_left) || (v_cnt >= IMG_HEIGHT - SKIP_ROWS_bottom) || (h_cnt >= IMG_WIDTH_4x - SKIP_COLS_right); 

    always @(posedge I_clk or negedge I_rst_n) begin
        if (!I_rst_n ) begin
            O_tdata <= 0;
        end
        else begin
            O_tdata <= w_skip ? {DATA_WIDTH{1'b0}} : I_tdata_r; 
        end
    end

    always @(posedge I_clk or negedge I_rst_n) begin
        if (!I_rst_n || I_tuser) begin
            h_cnt <= 0;
            v_cnt <= 0;
        end
        else begin
            h_cnt <= I_tvalid_r0 ? ((h_cnt == IMG_WIDTH_4x-1) ? 0 : h_cnt + 1) : h_cnt;
            v_cnt <= I_tvalid_r0 &&(h_cnt == IMG_WIDTH_4x-1) ? ((v_cnt == IMG_HEIGHT - 1) ? 0 : v_cnt + 1) : v_cnt;
        end
    end

    always @(posedge I_clk or negedge I_rst_n) begin
        if (!I_rst_n ) begin
            {I_tlast_r0 ,I_tlast_r1 } <= 0;
            {I_tuser_r0 ,I_tuser_r1 } <= 0;
            {I_tvalid_r0,I_tvalid_r1} <= 0;
            I_tdata_r  <= 0;
        end
        else begin
            I_tlast_r0  <= I_tlast ; 
            I_tuser_r0  <= I_tuser ;
            I_tvalid_r0 <= I_tvalid;
            I_tlast_r1  <= I_tlast_r0 ;
            I_tuser_r1  <= I_tuser_r0 ;
            I_tvalid_r1 <= I_tvalid_r0;
            I_tdata_r   <= I_tdata ;
        end
    end

    assign  O_tlast  = I_tlast_r1 ;   
    assign  O_tuser  = I_tuser_r1 ;   
    assign  O_tvalid = I_tvalid_r1;

    assign  I_tready = O_tready;

endmodule
