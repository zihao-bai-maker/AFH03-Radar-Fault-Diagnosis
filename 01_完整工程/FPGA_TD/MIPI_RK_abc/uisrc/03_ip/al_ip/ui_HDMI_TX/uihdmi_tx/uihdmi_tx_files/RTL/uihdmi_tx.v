

`timescale 1ns / 1ns 

module uihdmi_tx#(
    parameter DEVICE            = "DR1"
)
(

    input wire       I_pixel_clk, 
    input wire       I_serial_clk,
    input wire       I_rst, 
    input wire[23:0] I_video_in_data,   
    input wire       I_video_in_de,     
    input wire       I_video_in_vs,     
    input wire       I_video_in_hs,     
    output           O_hdmi_clk_p, 
    output    [2:0]  O_hdmi_tx_p  

);
reg [23:0] r_video_in_data;
always @(posedge I_pixel_clk) r_video_in_data <= I_video_in_data;

  
    wire[9:0]   S_ch0_tmds_code_data;               
    wire[9:0]   S_ch1_tmds_code_data;               
    wire[9:0]   S_ch2_tmds_code_data;               
    wire[9:0]   S_clk_tmds_code_data;

    hdmi_tx_controller_wrapper u_hdmi_tx_controller_wrapper(
        .I_pixel_clk          (I_pixel_clk          ),
        .I_rst                (I_rst                ),
        .I_video_in_data      (r_video_in_data      ),
        .I_video_in_vs        (I_video_in_vs        ),
        .I_video_in_hs        (I_video_in_hs        ),
        .I_video_in_de        (I_video_in_de        ),
        .O_ch0_tmds_code_data ( S_ch0_tmds_code_data ),
        .O_ch1_tmds_code_data ( S_ch1_tmds_code_data ),
        .O_ch2_tmds_code_data ( S_ch2_tmds_code_data ),
        .O_clk_tmds_code_data ( S_clk_tmds_code_data )
    );

    hdmi_tx_phy_wrapper  #(
        .DEVICE ( "DR1" )  
    )u_hdmi_tx_phy_wrapper(
        .I_pixel_clk        ( I_pixel_clk          ),
        .I_serial_clk       ( I_serial_clk         ),
        .I_rst              ( I_rst                ),

        .I_tmds_channel_0   ( S_ch0_tmds_code_data ),
        .I_tmds_channel_1   ( S_ch1_tmds_code_data ),
        .I_tmds_channel_2   ( S_ch2_tmds_code_data ),
        .I_tmds_channel_clk ( S_clk_tmds_code_data ),

        .O_tmds_ch0_p       ( O_hdmi_tx_p[0]       ),
        .O_tmds_ch1_p       ( O_hdmi_tx_p[1]       ),
        .O_tmds_ch2_p       ( O_hdmi_tx_p[2]       ),
        .O_tmds_clk_p       ( O_hdmi_clk_p         )
    );

endmodule