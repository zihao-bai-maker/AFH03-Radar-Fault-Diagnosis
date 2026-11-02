import_device ph1_90.db -package PH1A90SEG324
set_param flow ooc_flow on
read_verilog -dir "D:/xuexishengshou/TD/ip/apm/apm_cwc" -global_include "debug_hub_define.v" -top top_debug_hub
optimize_rtl
map_macro
map
pack
report_area -file top_debug_hub_gate.area
export_db -mode ooc "top_debug_hub_ooc.db"
