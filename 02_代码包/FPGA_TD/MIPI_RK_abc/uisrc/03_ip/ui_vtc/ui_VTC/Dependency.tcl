
set_param -param_id {H_ActiveSize} -data_type {Integer} -min {-2147483648} -max {2147483647}
set_param -param_id {H_FrameSize} -data_type {Integer} -min {-2147483648} -max {2147483647}
set_param -param_id {H_SyncStart} -data_type {Integer} -min {-2147483648} -max {2147483647}
set_param -param_id {H_SyncEnd} -data_type {Integer} -min {-2147483648} -max {2147483647}
set_param -param_id {V_ActiveSize} -data_type {Integer} -min {-2147483648} -max {2147483647}
set_param -param_id {V_FrameSize} -data_type {Integer} -min {-2147483648} -max {2147483647}
set_param -param_id {V_SyncStart} -data_type {Integer} -min {-2147483648} -max {2147483647}
set_param -param_id {V_SyncEnd} -data_type {Integer} -min {-2147483648} -max {2147483647}

proc updateRelValue { value } {
 set tmp $value
 return $tmp
}