create_clock -name {sys_clk} -period 40.000 -waveform {0.000 20.000} [get_ports {I_sysclk_25m}]
create_clock -name {ddr_clk} -period 10.000 -waveform {0.000 5.000} [get_ports {I_ddr_clk}]

derive_clocks

rename_clock -name {S_clk_24m} [get_clocks {X_ui_pll/pll_inst.clkc[0]}]
rename_clock -name {S_pclkx1}  [get_clocks {X_ui_pll/pll_inst.clkc[1]}]
rename_clock -name {S_pclkx5}  [get_clocks {X_ui_pll/pll_inst.clkc[2]}]
rename_clock -name {S_clk_70m} [get_clocks {X_ui_pll/pll_inst.clkc[3]}]

rename_clock -name {S_dsi_25m}     [get_clocks {u_ui_pll_dsi/pll_inst.clkc[0]}]
rename_clock -name {S_dsi_byte}    [get_clocks {u_ui_pll_dsi/pll_inst.clkc[1]}]
rename_clock -name {S_dsi_hs_x2}   [get_clocks {u_ui_pll_dsi/pll_inst.clkc[2]}]
rename_clock -name {S_dsi_hs_x4}   [get_clocks {u_ui_pll_dsi/pll_inst.clkc[3]}]
rename_clock -name {S_dsi_hs_x4_q} [get_clocks {u_ui_pll_dsi/pll_inst.clkc[4]}]
rename_clock -name {S_dsi_lp}      [get_clocks {u_ui_pll_dsi/pll_inst.clkc[5]}]

set_clock_groups -exclusive -group [get_clocks {X_ui_ddr/dfi_clk}] -group [get_clocks {S_clk_24m}] -group [get_clocks {S_clk_70m}] -group [get_clocks {S_pclkx1}]

set_clock_groups -asynchronous \
    -group [get_clocks {sys_clk}] \
    -group [get_clocks {S_pclkx1}] \
    -group [get_clocks {S_dsi_byte S_dsi_hs_x2 S_dsi_hs_x4 S_dsi_hs_x4_q}]
