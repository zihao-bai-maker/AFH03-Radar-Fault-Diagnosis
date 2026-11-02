import_device ph1_90.db -package PH1A90SEG324
set_param flow ooc_flow on
read_verilog -file "ChipWatcher_c350c0a21ae8_watcherInst.sv"
optimize_rtl
map_macro
map
pack
report_area -file ChipWatcher_c350c0a21ae8_gate.area
export_db -mode ooc "ChipWatcher_c350c0a21ae8_ooc.db"
