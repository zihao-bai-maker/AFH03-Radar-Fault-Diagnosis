
set Tab_Tab_0 [add_tab -name {Tab_0} -col_count {1}]

set Spin_Box_H_ActiveSize [add_param -parent {Tab_0} -name {H_ActiveSize} -widget {Spin Box}]
set_widget_prop -widget_id $Spin_Box_H_ActiveSize -prop {Display Name} -value {H_ActiveSize}

set Spin_Box_H_FrameSize [add_param -parent {Tab_0} -name {H_FrameSize} -widget {Spin Box}]
set_widget_prop -widget_id $Spin_Box_H_FrameSize -prop {Display Name} -value {H_FrameSize}

set Spin_Box_H_SyncStart [add_param -parent {Tab_0} -name {H_SyncStart} -widget {Spin Box}]
set_widget_prop -widget_id $Spin_Box_H_SyncStart -prop {Display Name} -value {H_SyncStart}

set Spin_Box_H_SyncEnd [add_param -parent {Tab_0} -name {H_SyncEnd} -widget {Spin Box}]
set_widget_prop -widget_id $Spin_Box_H_SyncEnd -prop {Display Name} -value {H_SyncEnd}

set Spin_Box_V_ActiveSize [add_param -parent {Tab_0} -name {V_ActiveSize} -widget {Spin Box}]
set_widget_prop -widget_id $Spin_Box_V_ActiveSize -prop {Display Name} -value {V_ActiveSize}

set Spin_Box_V_FrameSize [add_param -parent {Tab_0} -name {V_FrameSize} -widget {Spin Box}]
set_widget_prop -widget_id $Spin_Box_V_FrameSize -prop {Display Name} -value {V_FrameSize}

set Spin_Box_V_SyncStart [add_param -parent {Tab_0} -name {V_SyncStart} -widget {Spin Box}]
set_widget_prop -widget_id $Spin_Box_V_SyncStart -prop {Display Name} -value {V_SyncStart}

set Spin_Box_V_SyncEnd [add_param -parent {Tab_0} -name {V_SyncEnd} -widget {Spin Box}]
set_widget_prop -widget_id $Spin_Box_V_SyncEnd -prop {Display Name} -value {V_SyncEnd}