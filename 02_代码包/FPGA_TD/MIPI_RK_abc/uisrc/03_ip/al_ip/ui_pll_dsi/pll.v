

`timescale 1 ns / 100 fs

module pll (
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
    .MPHASE_ENABLE("ENABLE"),
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
    .CLKC0_DIV(36),
    .CLKC0_CPHASE(35),
    .CLKC0_FPHASE(0),
    .CLKC0_FPHASE_RSTSEL(0),
    .CLKC0_DUTY_INT(18),
    .CLKC0_DUTY50("ENABLE"),
    .CLKC1_ENABLE("ENABLE"),
    .CLKC1_DIV(12),
    .CLKC1_CPHASE(11),
    .CLKC1_FPHASE(0),
    .CLKC1_FPHASE_RSTSEL(0),
    .CLKC1_DUTY_INT(6),
    .CLKC1_DUTY50("ENABLE"),
    .CLKC2_ENABLE("ENABLE"),
    .CLKC2_DIV(6),
    .CLKC2_CPHASE(5),
    .CLKC2_FPHASE(0),
    .CLKC2_FPHASE_RSTSEL(0),
    .CLKC2_DUTY_INT(3),
    .CLKC2_DUTY50("ENABLE"),
    .CLKC3_ENABLE("ENABLE"),
    .CLKC3_DIV(3),
    .CLKC3_CPHASE(2),
    .CLKC3_FPHASE(0),
    .CLKC3_FPHASE_RSTSEL(0),
    .CLKC3_DUTY_INT(2),
    .CLKC3_DUTY50("ENABLE"),
    .CLKC4_ENABLE("ENABLE"),
    .CLKC4_DIV(3),
    .CLKC4_CPHASE(2),
    .CLKC4_FPHASE(6),
    .CLKC4_FPHASE_RSTSEL(1),
    .CLKC4_DUTY_INT(2),
    .CLKC4_DUTY50("ENABLE"),
    .CLKC5_ENABLE("ENABLE"),
    .CLKC5_DIV(90),
    .CLKC5_CPHASE(89),
    .CLKC5_FPHASE(0),
    .CLKC5_FPHASE_RSTSEL(0),
    .CLKC5_DUTY_INT(45),
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
    .psdone(pll_open252),
    .cps_step(2'b00),
    .drp_clk(1'b0),
    .drp_rstn(1'b1),
    .drp_sel(1'b0),
    .drp_rd(1'b0),
    .drp_wr(1'b0),
    .drp_addr(8'b00000000),
    .drp_wdata(8'b00000000),
    .drp_err(pll_open253),
    .drp_rdy(pll_open254),
    .drp_rdata({pll_open262, pll_open261, pll_open260, pll_open259, pll_open258, pll_open257, pll_open256, pll_open255}),
    .fbclk(clk0_out),
    .clkc({pll_open271, pll_open269, clk5_out, clk4_out, clk3_out, clk2_out, clk1_out, clk0_buf}),
    .clkcb({pll_open272, pll_open270, pll_open268, pll_open267, pll_open266, pll_open265, pll_open264, pll_open263}),
    .clkc_en({8'b00111111}),
    .clkc_rst(2'b00),
    .ext_freq_mod_clk(1'b0),
    .ext_freq_mod_en(1'b0),
    .ext_freq_mod_val(17'b00000000000000000),
    .ssc_en(1'b0) 
  );

endmodule

