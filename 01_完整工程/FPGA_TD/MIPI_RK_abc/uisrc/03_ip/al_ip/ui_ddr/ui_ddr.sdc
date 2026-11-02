derive_clocks

rename_clock -name ref_clk [get_clocks {u_ddrmc_top/u_ddr_phy/u_ddrphy_clk_gen/u_ddrphy_pll0/pll_inst.clkc[0]}]
rename_clock -name mcu_clk [get_clocks {u_ddrmc_top/u_ddr_phy/u_ddrphy_clk_gen/u_ddrphy_pll0/pll_inst.clkc[3]}]

rename_clock -name dfi_clk [get_clocks {u_ddrmc_top/u_ddr_phy/u_ddrphy_clk_gen/u_ddrphy_pll1/pll_inst.clkc[0]}]

set_clock_groups -asynchronous -group [get_clocks mcu_clk]
set_clock_uncertainty -setup 0.1 [get_clocks mcu_clk]

set_false_path -to [get_pins {u_ddrmc_top/u_ddr_phy/u_ddrphy_top/u_ddrphy_bank/bkIdx*bk_used$u_ddrbank_top/u_ddrbank.zqcal_clrcfg}]
set_false_path -to [get_pins {u_ddrmc_top/u_ddr_phy/u_ddrphy_top/u_ddrphy_bank/bkIdx*bk_used$u_ddrbank_top/u_ddrbank.zqcal_start}]
set_false_path -to [get_pins {u_ddrmc_top/u_ddr_phy/u_ddrphy_top/u_ddrphy_bank/bkIdx*bk_used$u_ddrbank_top/u_ddrbank.zqcal_update_en}]

set_false_path -to [get_pins {u_ddrmc_top/u_ddr_phy/u_ddrphy_top/u_ddrphy_bank/bkIdx*bk_used$u_ddrbank_top/u_ddrbank.*_dcc_clrcfg}]
set_false_path -to [get_pins {u_ddrmc_top/u_ddr_phy/u_ddrphy_top/u_ddrphy_bank/bkIdx*bk_used$u_ddrbank_top/u_ddrbank.*_dcc_start}]

set_false_path -to [get_pins {u_ddrmc_top/u_ddr_phy/u_ddrphy_top/u_ddrphy_bank/bkIdx*bk_used$u_ddrbank_top/u_ddrbank.*_delay_cal_mode}]
set_false_path -to [get_pins {u_ddrmc_top/u_ddr_phy/u_ddrphy_top/u_ddrphy_bank/bkIdx*bk_used$u_ddrbank_top/u_ddrbank.*_delay_cal_clk_en[*]}]
set_false_path -to [get_pins {u_ddrmc_top/u_ddr_phy/u_ddrphy_top/u_ddrphy_bank/bkIdx*bk_used$u_ddrbank_top/u_ddrbank.*_delay_cal_en_in[*]}]

set_false_path -to [get_pins {u_ddrmc_top/u_ddr_phy/u_ddrphy_top/u_ddrphy_bank/bkIdx*bk_used$u_ddrbank_top/u_ddrbank.*_dqs_pupd_en}]
set_false_path -to [get_pins {u_ddrmc_top/u_ddr_phy/u_ddrphy_top/u_ddrphy_bank/bkIdx*bk_used$u_ddrbank_top/u_ddrbank.*_wrlvl_mode}]

set_false_path -to [get_pins {u_ddrmc_top/u_ddr_phy/u_ddrphy_top/u_ddrphy_ppc/u_ddrppc.zqcal_done_bank[*]}]
set_false_path -to [get_pins {u_ddrmc_top/u_ddr_phy/u_ddrphy_top/u_ddrphy_ppc/u_ddrppc.dcc_done_bank[*]}]
set_false_path -to [get_pins {u_ddrmc_top/u_ddr_phy/u_ddrphy_top/u_ddrphy_ppc/u_ddrppc.delay_cal_en_in_upp[*]}]
set_false_path -to [get_pins {u_ddrmc_top/u_ddr_phy/u_ddrphy_top/u_ddrphy_ppc/u_ddrppc.delay_cal_in_upp[*]}]
set_false_path -to [get_pins {u_ddrmc_top/u_ddr_phy/u_ddrphy_top/u_ddrphy_ppc/u_ddrppc.wrlvl_qin[*]}]

