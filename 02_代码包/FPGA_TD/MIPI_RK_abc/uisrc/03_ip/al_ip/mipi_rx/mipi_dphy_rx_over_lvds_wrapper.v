

module mipi_dphy_rx_over_lvds_wrapper #(
    parameter DEVICE       = "EG",
    parameter LANE_NUM     = 4
    )(
    input wire                    I_lp_clk,
    input wire                    I_rst,

    input wire                    I_mipi_clk_p,
    input wire[LANE_NUM-1 : 0]    I_mipi_data_hs_p,
    input wire[LANE_NUM-1 : 0]    I_mipi_data_lp_p,
    input wire[LANE_NUM-1 : 0]    I_mipi_data_lp_n,

	input wire[LANE_NUM-1 : 0]    I_lane_hs_invert,
    input wire[LANE_NUM-1 : 0]    I_lane_lp_invert,

    output wire                   O_hs_rx_clk,
    output wire                   O_hs_rx_valid,
    output wire[LANE_NUM*8-1 : 0] O_hs_rx_data,

    output wire                   O_lp_rx_lane0_p,
    output wire                   O_lp_rx_lane0_n,

	output wire[LANE_NUM-1 : 0]   O_lane_error
);

    wire                 S_rx_hs_clk;
    wire                 S_rx_hs_clk_x2;
    wire                 S_rx_hs_clk_x4;
    wire[LANE_NUM-1 : 0] S_data_lp_p;
    wire[LANE_NUM-1 : 0] S_data_lp_n;

    rx_clk_gen #(
        .DEVICE ( DEVICE )
    )u_rx_clk_gen(
        .I_mipi_clk_p ( I_mipi_clk_p  ),
        .I_rst        ( I_rst         ),
        .O_clk        ( S_hs_clk      ),
        .O_clk_x2     ( S_hs_clk_x2   ),
        .O_clk_x4     ( S_hs_clk_x4   )
    );

    assign O_hs_rx_clk = S_hs_clk;

    assign O_lp_rx_lane0_p = I_lane_lp_invert[0] ? I_mipi_data_lp_n[0] : I_mipi_data_lp_p[0];
    assign O_lp_rx_lane0_n = I_lane_lp_invert[0] ? I_mipi_data_lp_p[0] : I_mipi_data_lp_n[0];

    hs_rx_wrapper#(
        .LANE_NUM    ( LANE_NUM ),
        .DEVICE      ( DEVICE   )
    )u_hs_rx_wrapper(
        .I_hs_clk         ( S_hs_clk         ),
        .I_hs_clk_x2      ( S_hs_clk_x2      ),
        .I_hs_clk_x4      ( S_hs_clk_x4      ),
        .I_lp_clk         ( I_lp_clk         ),
        .I_rst            ( I_rst            ),

		.I_lane_hs_invert ( I_lane_hs_invert ),
        .I_lane_lp_invert ( I_lane_lp_invert ),

        .I_mipi_hs_p      ( I_mipi_data_hs_p ),
        .I_mipi_lp_p      ( I_mipi_data_lp_p ),
        .I_mipi_lp_n      ( I_mipi_data_lp_n ),

        .O_hs_valid       ( O_hs_rx_valid    ),
        .O_hs_data        ( O_hs_rx_data     ),        

		.O_lane_error     ( O_lane_error     )
    );

endmodule