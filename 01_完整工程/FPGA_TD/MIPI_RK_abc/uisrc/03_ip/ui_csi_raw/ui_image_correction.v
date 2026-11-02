

module ui_image_correction #(
    parameter DATA_WIDTH   = 40,
    parameter TDEST_WIDTH  = 10
)(
    input                          		I_clk   			,
    input                          		I_rst_n 			,

    input    [DATA_WIDTH - 1:0]       	I_raw_data			,       
    input                             	I_raw_valid 		,     
    input                             	I_raw_frame_start	,
    input                             	I_raw_frame_end  	,

    output     [DATA_WIDTH - 1:0]     	O_raw_tdata 		,
    output                            	O_raw_tlast 		,
    output reg [TDEST_WIDTH - 1:0]    	O_raw_tdest 		,
    output                            	O_raw_tvalid		,
    output                            	O_raw_tuser 		,
    input                             	O_raw_tready
);

    reg                        I_raw_tvalid_d; 
    reg    [DATA_WIDTH - 1:0]  I_raw_tdata_r;
    reg    [14:0]              h_cnt,v_cnt;
    wire                       V_valid,H_valid;
    wire                       tuser;

	assign H_valid 		= (h_cnt < 481) && (h_cnt > 0);

    assign tuser 		= (h_cnt == 1) && (v_cnt == 1) && I_raw_tvalid_d;

    assign O_raw_tdata  = V_valid && H_valid? I_raw_tdata_r:0;
    assign I_raw_tready = O_raw_tready;
    assign O_raw_tvalid = H_valid && V_valid && I_raw_tvalid_d;
    assign O_raw_tlast  = V_valid && (h_cnt == 480) && I_raw_tvalid_d;
    assign O_raw_tuser  = tuser;

    always @(posedge I_clk or negedge I_rst_n) begin
        if(!I_rst_n )begin
            I_raw_tvalid_d <= 0;
            I_raw_tdata_r  <= 0;
        end
        else begin
            I_raw_tvalid_d <= I_raw_valid;
            I_raw_tdata_r  <= I_raw_data;
        end
    end

    reg  [16:0] cnt;
    always @(posedge I_clk or negedge I_rst_n) begin
        if(!I_rst_n )begin
            cnt <= 0;
        end
        else if(I_raw_valid)
            cnt <= 0;
        else if(!I_raw_valid)begin
            cnt <= cnt + 1;
        end
    end

    wire last = (cnt == 10);

    always @(posedge I_clk or negedge I_rst_n) begin
        if(!I_rst_n || I_raw_frame_start)
            v_cnt <= 0;
        else if(last)
            v_cnt  <=  v_cnt + 1;
    end

    assign V_valid = (v_cnt > 0) && (v_cnt < 1081);

    always @(posedge I_clk or negedge I_rst_n) begin
        if(!I_rst_n || I_raw_frame_start) 
            h_cnt <= 0;
        else if(last)
            h_cnt <= 0;
        else if(I_raw_tvalid_d)
            h_cnt <=  h_cnt + 1;
    end

endmodule