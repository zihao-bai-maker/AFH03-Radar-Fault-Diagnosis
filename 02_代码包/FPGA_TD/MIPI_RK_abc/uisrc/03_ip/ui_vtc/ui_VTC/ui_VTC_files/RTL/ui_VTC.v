

`timescale 1ns / 1ns  

module ui_VTC #(
    parameter integer H_ActiveSize  =   1920,               
    parameter integer H_FrameSize   =   1920+88+44+148,     
    parameter integer H_SyncStart   =   1920+88,            
    parameter integer H_SyncEnd     =   1920+88+44,         

    parameter integer V_ActiveSize  =   1080,               
    parameter integer V_FrameSize   =   1080+4+5+36,        
    parameter integer V_SyncStart   =   1080+4,             
    parameter integer V_SyncEnd     =   1080+4+5            
) (
    input  I_vtc_rstn,      
    input  I_vtc_clk,       
    output O_vtc_vs,        
    output O_vtc_hs,        
    output O_vtc_de_valid,  
    output O_vtc_user,      
    output O_vtc_last       
);

  reg [11:0] hcnt = 12'd0;  
  reg [11:0] vcnt = 12'd0;  
  reg [2 : 0] rst_cnt = 3'd0;  
  wire rst_sync = rst_cnt[2];  

  always @(posedge I_vtc_clk or negedge I_vtc_rstn) begin  
    if (I_vtc_rstn == 1'b0) rst_cnt <= 3'd0;
    else if (rst_cnt[2] == 1'b0) rst_cnt <= rst_cnt + 1'b1;
  end

  always @(posedge I_vtc_clk) begin
    if (rst_sync == 1'b0)  
      hcnt <= 12'd0;
    else if (hcnt < (H_FrameSize - 1'b1))  
      hcnt <= hcnt + 1'b1;
    else hcnt <= 12'd0;
  end

  always @(posedge I_vtc_clk) begin
    if (rst_sync == 1'b0) vcnt <= 12'd0;
    else if (hcnt == (H_ActiveSize - 1'b1)) begin  
      vcnt <= (vcnt == (V_FrameSize - 1'b1)) ? 12'd0 : vcnt + 1'b1;
    end
  end

  wire hs_valid = hcnt < H_ActiveSize;  
  wire vs_valid = vcnt < V_ActiveSize;  
  wire vtc_hs = (hcnt >= H_SyncStart && hcnt < H_SyncEnd);  
  wire vtc_vs = (vcnt > V_SyncStart && vcnt <= V_SyncEnd);  
  wire vtc_de    =  hs_valid && vs_valid;

  
  reg vtc_vs_r1;
  reg vtc_hs_r1;
  reg vtc_de_r1;
  reg vtc_user_r1, vtc_user_r2;
  reg vtc_valid_r1, vtc_valid_r2;
  reg vtc_last_r2;
  reg vs_start;

  always @(posedge I_vtc_clk) begin
    if (rst_sync == 1'b0)  
      vs_start <= 1'b0;
    else if (vtc_user_r1)  
      vs_start <= 1'b0;
    else if ({vtc_vs,vtc_vs_r1} == 2'b01)  
      vs_start <= 1'b1;
  end

  always @(posedge I_vtc_clk) begin
    vtc_vs_r1 <= vtc_vs;
    vtc_hs_r1 <= vtc_hs;
    vtc_user_r1 <= ~vtc_user_r1 & vs_start & vtc_de;  
    vtc_last_r2 <= ~vtc_de & vtc_valid_r1;  
    vtc_valid_r1 <= vtc_de;  
    vtc_valid_r2 <= vtc_valid_r1;
    vtc_user_r2  <= vtc_user_r1; 
  end

  assign O_vtc_vs       = vtc_vs_r1;
  assign O_vtc_hs       = vtc_hs_r1;
  assign O_vtc_de_valid = vtc_valid_r2;
  assign O_vtc_user     = vtc_user_r2;
  assign O_vtc_last     = vtc_last_r2;

endmodule

