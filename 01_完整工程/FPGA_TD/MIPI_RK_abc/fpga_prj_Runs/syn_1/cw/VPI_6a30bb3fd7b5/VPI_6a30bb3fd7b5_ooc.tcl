import_device ph1_90.db -package PH1A90SEG324
set_param flow ooc_flow on
read_verilog -file "VPI_6a30bb3fd7b5_vpiInst.sv"
optimize_rtl
map_macro
map
pack
report_area -file VPI_6a30bb3fd7b5_gate.area
export_db -mode ooc "VPI_6a30bb3fd7b5_ooc.db"
