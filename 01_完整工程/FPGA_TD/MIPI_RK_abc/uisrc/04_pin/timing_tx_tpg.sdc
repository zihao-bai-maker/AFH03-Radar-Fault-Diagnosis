
create_clock -name {sys_clk} -period 40.000 -waveform {0.000 20.000} [get_ports {I_sysclk_25m}]

derive_clocks

rename_clock -name {S_dsi_25m}     [get_clocks {u_ui_pll_dsi/pll_inst.clkc[0]}]
rename_clock -name {S_dsi_byte}    [get_clocks {u_ui_pll_dsi/pll_inst.clkc[1]}]
rename_clock -name {S_dsi_hs_x2}   [get_clocks {u_ui_pll_dsi/pll_inst.clkc[2]}]
rename_clock -name {S_dsi_hs_x4}   [get_clocks {u_ui_pll_dsi/pll_inst.clkc[3]}]
rename_clock -name {S_dsi_hs_x4_q} [get_clocks {u_ui_pll_dsi/pll_inst.clkc[4]}]
rename_clock -name {S_dsi_lp}      [get_clocks {u_ui_pll_dsi/pll_inst.clkc[5]}]

set_clock_groups -asynchronous \
    -group [get_clocks {sys_clk}] \
    -group [get_clocks {S_dsi_byte S_dsi_hs_x2 S_dsi_hs_x4 S_dsi_hs_x4_q S_dsi_lp}]
