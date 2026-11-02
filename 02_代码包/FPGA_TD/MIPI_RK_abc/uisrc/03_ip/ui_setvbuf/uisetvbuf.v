

`timescale 1ns / 1ps

module ui_setvbuf#(
parameter  integer                  BUF_DELAY     = 1,
parameter  integer                  BUF_LENTH     = 3
)
(

input      [7   :0]                 I_bufn,
output     [7   :0]                 O_bufn
);   

assign O_bufn = I_bufn < BUF_DELAY?  (BUF_LENTH - BUF_DELAY + I_bufn) : (I_bufn - BUF_DELAY) ;

endmodule

