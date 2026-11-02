module hs_rx_wrapper #(
    parameter LANE_NUM = 4,
    parameter DEVICE = "EG"   
    )(
    input wire                  I_hs_clk,
    input wire                  I_hs_clk_x2,
    input wire                  I_hs_clk_x4,
    input wire                  I_lp_clk,
    input wire                  I_rst,

	input wire[LANE_NUM-1:0]    I_lane_hs_invert,
    input wire[LANE_NUM-1:0]    I_lane_lp_invert,

    input wire[LANE_NUM-1:0]    I_mipi_hs_p,
    input wire[LANE_NUM-1:0]    I_mipi_lp_p,
    input wire[LANE_NUM-1:0]    I_mipi_lp_n,

    output wire                 O_hs_valid,
    output wire[LANE_NUM*8-1:0] O_hs_data,    

	output wire[LANE_NUM-1:0]   O_lane_error
);

    wire[LANE_NUM-1:0] S_hs_valid;                   
    wire[7:0]          S_hs_data[LANE_NUM-1:0];      

    wire[LANE_NUM-1:0] S_ch_aligner_valid;
    wire[7:0]          S_ch_aligner_data[LANE_NUM-1:0];

    genvar i;
    generate
        for(i = 0; i < LANE_NUM; i = i+1) begin :   MIPI_DATA_LANE_GEN
            data_lane_rx_wrapper #(
                .DEVICE ( DEVICE )
            ) u_data_lane_rx_wrapper(
                .I_hs_clk_x4      ( I_hs_clk_x4         ),
                .I_hs_clk_x2      ( I_hs_clk_x2         ),
                .I_hs_clk         ( I_hs_clk            ),
                .I_lp_clk         ( I_lp_clk            ),
                .I_rst            ( I_rst               ),

				.I_lane_hs_invert ( I_lane_hs_invert[i] ),
                .I_lane_lp_invert ( I_lane_lp_invert[i] ),

                .I_mipi_hs_p      ( I_mipi_hs_p[i]      ),
                .I_mipi_lp_p      ( I_mipi_lp_p[i]      ),
                .I_mipi_lp_n      ( I_mipi_lp_n[i]      ),

                .O_hs_valid       ( S_hs_valid[i]       ),
                .O_hs_data        ( S_hs_data[i]        ),                

				.O_lane_error     ( O_lane_error[i]     )
            );
        end
    endgenerate

    channel_aligner_wrapper#(
        .CH_NUM             ( LANE_NUM ),
        .DATA_WIDTH         ( 8        )
    )u_channel_aligner_wrapper(
        .I_clk              ( I_hs_clk           ),
        .I_rst_n            ( ~I_rst             ),

        .I_ch_valid         ( S_hs_valid         ),
        .I_ch_data          ( S_hs_data          ),

        .O_ch_aligner_valid ( S_ch_aligner_valid ),
        .O_ch_aligner_data  ( S_ch_aligner_data  )
    );

    assign O_hs_valid = &S_ch_aligner_valid;

    generate
        for(i = 0; i < LANE_NUM; i = i+1) begin :   MIPI_DATA_MERGE
            assign O_hs_data[(i+1)*8-1 : i*8] = S_ch_aligner_data[LANE_NUM-1-i];
        end
    endgenerate

endmodule