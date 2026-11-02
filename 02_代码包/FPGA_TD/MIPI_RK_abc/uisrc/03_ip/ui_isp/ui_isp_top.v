

`timescale 1ns / 1ps

module ui_isp_top (
    input           I_clk,
    input           I_rst_n,
    input           I_tlast,
    input           I_tuser,
    input  [39:0]   I_tdata,
    input           I_tvalid,
    input  [9:0]    I_tdest,
    input           O_tready,
    output [127:0]  O_tdata,
    output          O_tlast,
    output          O_tuser,
    output          O_tvalid,
    output          I_tready
);

    wire            BLC_O_tlast;
    wire            BLC_O_tuser;
    wire [39:0]     BLC_O_tdata;
    wire            BLC_O_tvalid;
    wire [9:0]      BLC_O_tdest;
    wire            BLC_O_tready;

    wire            m_aixs_tvalid;
    wire [127:0]    m_aixs_tdata;
    wire            m_aixs_tuser;
    wire            m_aixs_tlast;
    wire            m_aixs_tready;
    wire [95:0]     m_aixs_tdata_96;

    wire            awb_O_tlast;
    wire            awb_O_tuser;
    wire [95:0]     awb_O_tdata;
    wire            awb_O_tvalid;
    wire            awb_O_tready;

    wire            gamma_O_tlast;
    wire            gamma_O_tuser;
    wire [95:0]     gamma_O_tdata;
    wire            gamma_O_tvalid;
    wire            gamma_O_tready;

    wire            cut_O_tlast;
    wire            cut_O_tuser;
    wire [95:0]     cut_O_tdata;
    wire            cut_O_tvalid;
    wire            cut_O_tready;

    wire            contrast_O_tlast;
    wire            contrast_O_tuser;
    wire [95:0]     contrast_O_tdata;
    wire            contrast_O_tvalid;
    wire            contrast_O_tready;

    wire            Brightness_O_tlast;
    wire            Brightness_O_tuser;
    wire [95:0]     Brightness_O_tdata;
    wire            Brightness_O_tvalid;
    wire            Brightness_O_tready;

    wire            Saturation_O_tlast;
    wire            Saturation_O_tuser;
    wire [95:0]     Saturation_O_tdata;
    wire            Saturation_O_tvalid;
    wire            Saturation_O_tready;

    assign Saturation_O_tready = O_tready;
    assign O_tdata = {
        8'h00, Saturation_O_tdata[95:72],
        8'h00, Saturation_O_tdata[71:48],
        8'h00, Saturation_O_tdata[47:24],
        8'h00, Saturation_O_tdata[23:0]
    };
    assign O_tlast  = Saturation_O_tlast;
    assign O_tuser  = Saturation_O_tuser;
    assign O_tvalid = Saturation_O_tvalid;

ui_BLC #(
    .Black_level_offset_r0 (50),
    .Black_level_offset_r1 (50),
    .Black_level_offset_r2 (50),
    .Black_level_offset_r3 (50)
) X_ui_BLC (
    .I_clk    (I_clk),
    .I_rst_n  (I_rst_n),
    .I_tlast  (I_tlast),
    .I_tuser  (I_tuser),
    .I_tdata  (I_tdata),
    .I_tvalid (I_tvalid),
    .I_tdest  (I_tdest),
    .I_tready (),

    .O_tlast  (BLC_O_tlast),
    .O_tuser  (BLC_O_tuser),
    .O_tdata  (BLC_O_tdata),
    .O_tvalid (BLC_O_tvalid),
    .O_tdest  (BLC_O_tdest),
    .O_tready (BLC_O_tready)
);

ui_top_demosaic #(
    .IMG_HEIGHT          (1080),
    .IMG_WIDTH           (1920),
    .data_complete_delay (50),
    .BAYER_MODE          ("RGGB")
) X_ui_top_demosaic (
    .I_clk        (I_clk),
    .I_rst_n      (I_rst_n),
    .I_axi4s_tdata(BLC_O_tdata),
    .I_axi4s_tdest(BLC_O_tdest),
    .I_axi4s_tlast(BLC_O_tlast),
    .I_axi4s_tvalid(BLC_O_tvalid),
    .I_axi4s_tuser(BLC_O_tuser),
    .I_axi4s_tready(BLC_O_tready),
    .O_tlast      (m_aixs_tlast),
    .O_tuser      (m_aixs_tuser),
    .O_tdata      (m_aixs_tdata),
    .O_tvalid     (m_aixs_tvalid),
    .O_tready     (m_aixs_tready)
);

ui_data128_96 X_ui_data128_96(
    .I_tdata(m_aixs_tdata),
    .O_tdata(m_aixs_tdata_96)
);

ui_awb #(
    .IMG_HEIGHT(1080),
    .IMG_WIDTH (1920)
) X_ui_awb (
    .I_clk  (I_clk),
    .I_rst_n(I_rst_n),
    .I_img_width (13'd1920),
    .I_img_height(13'd1080),
    .I_tlast(m_aixs_tlast),
    .I_tuser(m_aixs_tuser),
    .I_tdata(m_aixs_tdata_96),
    .I_tvalid(m_aixs_tvalid),
    .I_tready(m_aixs_tready),
    .O_tlast(awb_O_tlast),
    .O_tuser(awb_O_tuser),
    .O_tdata(awb_O_tdata),
    .O_tvalid(awb_O_tvalid),
    .O_tready(awb_O_tready)
);

ui_image_cut #(
    .IMG_WIDTH   (1920),
    .IMG_HEIGHT  (1080),
    .DATA_WIDTH  (96),
    .SKIP_ROWS_top  (0),
    .SKIP_ROWS_bottom(0),
    .SKIP_COLS_left (1),
    .SKIP_COLS_right(0)
) X_ui_image_cut (
    .I_clk  (I_clk),
    .I_rst_n(I_rst_n),
    .I_tlast(awb_O_tlast),
    .I_tuser(awb_O_tuser),
    .I_tdata(awb_O_tdata),
    .I_tvalid(awb_O_tvalid),
    .I_tready(awb_O_tready),
    .O_tlast(cut_O_tlast),
    .O_tuser(cut_O_tuser),
    .O_tdata(cut_O_tdata),
    .O_tvalid(cut_O_tvalid),
    .O_tready(cut_O_tready)
);

ui_gamma #(
    .GAMMA_10x(22)
) X_ui_gamma (
    .I_clk(I_clk),
    .I_rst_n(I_rst_n),
    .I_tlast(cut_O_tlast),
    .I_tuser(cut_O_tuser),
    .I_tdata(cut_O_tdata),
    .I_tvalid(cut_O_tvalid),
    .I_tready(cut_O_tready),
    .O_tlast(gamma_O_tlast),
    .O_tuser(gamma_O_tuser),
    .O_tdata(gamma_O_tdata),
    .O_tvalid(gamma_O_tvalid),
    .O_tready(gamma_O_tready)
);

ui_Contrast_adj #(
    .contrast_level(140)
) X_ui_Contrast_adj (
    .I_clk(I_clk),
    .I_rst_n(I_rst_n),
    .I_tlast(gamma_O_tlast),
    .I_tuser(gamma_O_tuser),
    .I_tdata(gamma_O_tdata),
    .I_tvalid(gamma_O_tvalid),
    .I_tready(gamma_O_tready),
    .O_tlast(contrast_O_tlast),
    .O_tuser(contrast_O_tuser),
    .O_tdata(contrast_O_tdata),
    .O_tvalid(contrast_O_tvalid),
    .O_tready(contrast_O_tready)
);

ui_Brightness_adj #(
    .BRIGHTNESS_ADD (5),
    .BRIGHTNESS_MINUS(0)
) X_ui_Brightness_adjustment (
    .I_clk(I_clk),
    .I_rst_n(I_rst_n),
    .I_tlast(contrast_O_tlast),
    .I_tuser(contrast_O_tuser),
    .I_tdata(contrast_O_tdata),
    .I_tvalid(contrast_O_tvalid),
    .I_tready(contrast_O_tready),
    .O_tlast(Brightness_O_tlast),
    .O_tuser(Brightness_O_tuser),
    .O_tdata(Brightness_O_tdata),
    .O_tvalid(Brightness_O_tvalid),
    .O_tready(Brightness_O_tready)
);

ui_Saturation_adj #(
    .ADJUST_VAL(130)
) X_ui_Saturation_adj (
    .I_clk(I_clk),
    .I_rst_n(I_rst_n),
    .I_tlast(Brightness_O_tlast),
    .I_tuser(Brightness_O_tuser),
    .I_tdata(Brightness_O_tdata),
    .I_tvalid(Brightness_O_tvalid),
    .I_tready(Brightness_O_tready),
    .O_tlast(Saturation_O_tlast),
    .O_tuser(Saturation_O_tuser),
    .O_tdata(Saturation_O_tdata),
    .O_tvalid(Saturation_O_tvalid),
    .O_tready(Saturation_O_tready)
);

endmodule
