

`timescale 1ns / 1ps
module ui_divider
(
  input                         aclk,
  input                         aresetn,
  input   [47:0]                s_axis_dividend_tdata,
  input                         s_axis_dividend_tvalid,
  input   [31:0]                s_axis_divisor_tdata,
  input                         s_axis_divisor_tvalid,
  output  [79:0]                m_axis_dout_tdata,
  output                        m_axis_dout_tvalid
);

  divider_top_ae263170b655
  #(
      .OPERAND_SIGN(0),
      .DIVIDEND_DW(48),
      .DIVISOR_DW(32),
      .DIVIDEND_CEIL_DW(48),
      .DIVISOR_CEIL_DW(32),
      .OUTPUT_DW(80),
      .FLOW_CONTROL(0),
      .LATENCY(50)
  )divider_top_ae263170b655_Inst
  (
      .aclk(aclk),
      .aresetn(aresetn),
      .s_axis_dividend_tdata(s_axis_dividend_tdata),
      .s_axis_dividend_tvalid(s_axis_dividend_tvalid),
      .s_axis_divisor_tdata(s_axis_divisor_tdata),
      .s_axis_divisor_tvalid(s_axis_divisor_tvalid),
      .m_axis_dout_tdata(m_axis_dout_tdata),
      .m_axis_dout_tvalid(m_axis_dout_tvalid)
  );
endmodule
