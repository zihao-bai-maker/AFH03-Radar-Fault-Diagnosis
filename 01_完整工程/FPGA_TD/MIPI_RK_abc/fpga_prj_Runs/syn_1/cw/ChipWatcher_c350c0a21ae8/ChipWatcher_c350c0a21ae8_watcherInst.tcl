source "E:/Anlogic/TD_6.2.1_Release_6.2.175.876/cw/atpl/templa.tcl"
set fd [open "E:/Anlogic/TD_6.2.1_Release_6.2.175.876/cw/atpl/cwc_ip.atpl" r]
set tmpl [read $fd]
close $fd
set parser [::tmpl_parser::tmpl_parser $tmpl]

set ComponentName        ChipWatcher_c350c0a21ae8
set bus_num              12
set depth                4096
set ram_len              558
set input_pipe_num       0
set output_pipe_num      0
set capture_ctrl_exist   0
set trig_bus_num         12
set trig_bus_din_num     558
set trig_bus_ctrl_len    1704
set trig_ctrl_len        1724
set trig_bus_width       { 96,1,96,1,96,1,96,1,128,1,40,1 };
set trig_bus_din_pos     { 0,96,97,193,194,290,291,387,388,516,517,557 };
set trig_bus_ctrl_pos    { 0,292,296,588,592,884,888,1180,1184,1572,1576,1700 };
set bus_size             {  1 40 1 128 1 96 1 96 1 96 1 96 }
set data_enable          { probe0 probe1 probe2 probe3 probe4 probe5 probe6 probe7 probe8 probe9 probe10 probe11 }
set trig_enable          { probe0 probe1 probe2 probe3 probe4 probe5 probe6 probe7 probe8 probe9 probe10 probe11 }
set fp [open "cw/ChipWatcher_c350c0a21ae8/ChipWatcher_c350c0a21ae8_watcherInst.sv" w+]
puts $fp [eval $parser]
close $fp
