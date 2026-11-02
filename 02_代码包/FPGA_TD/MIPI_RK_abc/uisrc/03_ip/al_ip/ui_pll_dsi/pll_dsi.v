

`timescale 1 ns / 100 fs

module pll_dsi (
  refclk,
  reset,
  lock,
  clk0_out,
  clk1_out,
  clk2_out,
  clk3_out,
  clk4_out,
  clk5_out 
);

  input refclk;
  input reset;
  output lock;
  output clk0_out;
  output clk1_out;
  output clk2_out;
  output clk3_out;
  output clk4_out;
  output clk5_out;

  wire clk0_buf;

  PH1_LOGIC_BUFG bufg_feedback (
    .i(clk0_buf),
    .o(clk0_out) 
  );

  PH1_PHY_PLL #(
    .DYN_PHASE_PATH_SEL("DISABLE"),
    .DYN_FPHASE_EN("DISABLE"),
    .MPHASE_ENABLE("DISABLE"),
    .FIN("25.000000"),
    .FEEDBK_MODE("NORMAL"),
    .FBKCLK("CLKC0_EXT"),
    .PLL_FEED_TYPE("EXTERNAL"),
    .PLL_USR_RST("ENABLE"),
    .GMC_GAIN(1),
    .ICP_CUR(11),
    .LPF_CAP(2),
    .LPF_RES(3),
    .REFCLK_DIV(1),
    .FBCLK_DIV(1),
    .CLKC0_ENABLE("ENABLE"),
    .CLKC0_DIV(40),
    .CLKC0_CPHASE(39),
    .CLKC0_FPHASE(0),
    .CLKC0_FPHASE_RSTSEL(0),
    .CLKC0_DUTY_INT(20),
    .CLKC0_DUTY50("ENABLE"),
    .CLKC1_ENABLE("ENABLE"),
    .CLKC1_DIV(8),
    .CLKC1_CPHASE(7),
    .CLKC1_FPHASE(0),
    .CLKC1_FPHASE_RSTSEL(0),
    .CLKC1_DUTY_INT(4),
    .CLKC1_DUTY50("ENABLE"),
    .CLKC2_ENABLE("ENABLE"),
    .CLKC2_DIV(4),
    .CLKC2_CPHASE(3),
    .CLKC2_FPHASE(0),
    .CLKC2_FPHASE_RSTSEL(0),
    .CLKC2_DUTY_INT(2),
    .CLKC2_DUTY50("ENABLE"),
    .CLKC3_ENABLE("ENABLE"),
    .CLKC3_DIV(2),
    .CLKC3_CPHASE(1),
    .CLKC3_FPHASE(0),
    .CLKC3_FPHASE_RSTSEL(0),
    .CLKC3_DUTY_INT(1),
    .CLKC3_DUTY50("ENABLE"),
    .CLKC4_ENABLE("ENABLE"),
    .CLKC4_DIV(2),
    .CLKC4_CPHASE(1),
    .CLKC4_FPHASE(4),
    .CLKC4_FPHASE_RSTSEL(1),
    .CLKC4_DUTY_INT(1),
    .CLKC4_DUTY50("ENABLE"),
    .CLKC5_ENABLE("ENABLE"),
    .CLKC5_DIV(100),
    .CLKC5_CPHASE(99),
    .CLKC5_FPHASE(0),
    .CLKC5_FPHASE_RSTSEL(0),
    .CLKC5_DUTY_INT(50),
    .CLKC5_DUTY50("ENABLE"),
    .INTPI(0),
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
    .psdone(pll_dsi_open0),
    .cps_step(2'b00),
    .drp_clk(1'b0),
    .drp_rstn(1'b1),
    .drp_sel(1'b0),
    .drp_rd(1'b0),
    .drp_wr(1'b0),
    .drp_addr(8'b00000000),
    .drp_wdata(8'b00000000),
    .drp_err(pll_dsi_open1),
    .drp_rdy(pll_dsi_open2),
    .drp_rdata({pll_dsi_open10, pll_dsi_open9, pll_dsi_open8, pll_dsi_open7, pll_dsi_open6, pll_dsi_open5, pll_dsi_open4, pll_dsi_open3}),
    .fbclk(clk0_out),
    .clkc({pll_dsi_open19, pll_dsi_open17, clk5_out, clk4_out, clk3_out, clk2_out, clk1_out, clk0_buf}),
    .clkcb({pll_dsi_open20, pll_dsi_open18, pll_dsi_open16, pll_dsi_open15, pll_dsi_open14, pll_dsi_open13, pll_dsi_open12, pll_dsi_open11}),
    .clkc_en({8'b00111111}),
    .clkc_rst(2'b00),
    .ext_freq_mod_clk(1'b0),
    .ext_freq_mod_en(1'b0),
    .ext_freq_mod_val(17'b00000000000000000),
    .ssc_en(1'b0) 
  );

endmodule

