source "D:/xuexishengshou/TD/cw/atpl/templa.tcl"
set fd [open "D:/xuexishengshou/TD/cw/atpl/vpi_ip.atpl" r]
set tmpl [read $fd]
close $fd
set parser [::tmpl_parser::tmpl_parser $tmpl]

set ComponentName     VPI_6a30bb3fd7b5
set input_bus_num     0
set output_bus_num    1
set bus_din_width     {}
set bus_dout_width    { 8 }
set bus_dout_init_val 8'b01010000
set fp [open "cw/VPI_6a30bb3fd7b5/VPI_6a30bb3fd7b5_vpiInst.sv" w+]
puts $fp [eval $parser]
close $fp
