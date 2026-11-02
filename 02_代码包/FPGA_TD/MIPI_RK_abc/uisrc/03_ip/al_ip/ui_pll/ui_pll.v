

`timescale 1 ns / 100 fs

module ui_pll (
  refclk,
  reset,
  lock,
  clk0_out,
  clk1_out,
  clk2_out,
  clk3_out 
);

  input refclk;
  input reset;
  output lock;
  output clk0_out;
  output clk1_out;
  output clk2_out;
  output clk3_out;

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
    .CLKC0_DIV(59),
    .CLKC0_CPHASE(58),
    .CLKC0_FPHASE(0),
    .CLKC0_FPHASE_RSTSEL(0),
    .CLKC0_DUTY_INT(30),
    .CLKC0_DUTY50("ENABLE"),
    .CLKC1_ENABLE("ENABLE"),
    .CLKC1_DIV(10),
    .CLKC1_CPHASE(9),
    .CLKC1_FPHASE(0),
    .CLKC1_FPHASE_RSTSEL(0),
    .CLKC1_DUTY_INT(5),
    .CLKC1_DUTY50("ENABLE"),
    .CLKC2_ENABLE("ENABLE"),
    .CLKC2_DIV(2),
    .CLKC2_CPHASE(1),
    .CLKC2_FPHASE(0),
    .CLKC2_FPHASE_RSTSEL(0),
    .CLKC2_DUTY_INT(1),
    .CLKC2_DUTY50("ENABLE"),
    .CLKC3_ENABLE("ENABLE"),
    .CLKC3_DIV(21),
    .CLKC3_CPHASE(20),
    .CLKC3_FPHASE(0),
    .CLKC3_FPHASE_RSTSEL(0),
    .CLKC3_DUTY_INT(11),
    .CLKC3_DUTY50("ENABLE"),
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
    .psdone(ui_pll_open0),
    .cps_step(2'b00),
    .drp_clk(1'b0),
    .drp_rstn(1'b1),
    .drp_sel(1'b0),
    .drp_rd(1'b0),
    .drp_wr(1'b0),
    .drp_addr(8'b00000000),
    .drp_wdata(8'b00000000),
    .drp_err(ui_pll_open1),
    .drp_rdy(ui_pll_open2),
    .drp_rdata({ui_pll_open10, ui_pll_open9, ui_pll_open8, ui_pll_open7, ui_pll_open6, ui_pll_open5, ui_pll_open4, ui_pll_open3}),
    .fbclk(clk0_out),
    .clkc({ui_pll_open21, ui_pll_open19, ui_pll_open17, ui_pll_open15, clk3_out, clk2_out, clk1_out, clk0_buf}),
    .clkcb({ui_pll_open22, ui_pll_open20, ui_pll_open18, ui_pll_open16, ui_pll_open14, ui_pll_open13, ui_pll_open12, ui_pll_open11}),
    .clkc_en({8'b00001111}),
    .clkc_rst(2'b00),
    .ext_freq_mod_clk(1'b0),
    .ext_freq_mod_en(1'b0),
    .ext_freq_mod_val(17'b00000000000000000),
    .ssc_en(1'b0) 
  );

endmodule

