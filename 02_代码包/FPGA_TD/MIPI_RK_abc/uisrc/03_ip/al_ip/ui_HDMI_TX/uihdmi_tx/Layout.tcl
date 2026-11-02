
set Tab_Tab_0 [add_tab -name {Tab_0} -col_count {1}]

set Line_Edit_DEVICE [add_param -parent {Tab_0} -name {DEVICE} -widget {Line Edit}]
set_widget_prop -widget_id $Line_Edit_DEVICE -prop {Display Name} -value {DEVICE}