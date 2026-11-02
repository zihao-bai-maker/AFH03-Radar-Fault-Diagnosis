`timescale 1ns/1ps

module rgb_to_yuv422_quad (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         i_de,
    input  wire         i_user_sof,
    input  wire         i_last,
    input  wire [127:0] i_data,        
    output reg          o_de,
    output reg          o_user_sof,
    output reg          o_last,
    output reg  [63:0]  o_data         
);

    localparam [9:0] C_Y_R  = 10'd47;   
    localparam [9:0] C_Y_G  = 10'd157;  
    localparam [9:0] C_Y_B  = 10'd16;   
    localparam [9:0] C_CB_R = 10'd26;   
    localparam [9:0] C_CB_G = 10'd86;   
    localparam [9:0] C_CB_B = 10'd112;  
    localparam [9:0] C_CR_R = 10'd112;  
    localparam [9:0] C_CR_G = 10'd102;  
    localparam [9:0] C_CR_B = 10'd10;   
    localparam [17:0] OFF_Y   = 18'd4096;   
    localparam [17:0] OFF_UV  = 18'd32768;  

    reg [3:0] de_d, sof_d, last_d;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            de_d   <= 4'd0;
            sof_d  <= 4'd0;
            last_d <= 4'd0;
        end else begin
            de_d   <= {de_d[2:0],   i_de       };
            sof_d  <= {sof_d[2:0],  i_user_sof };
            last_d <= {last_d[2:0], i_last     };
        end
    end

    
    wire [7:0] pr [0:3];
    wire [7:0] pg [0:3];
    wire [7:0] pb [0:3];
    assign pr[0] = i_data[ 23:16]; assign pg[0] = i_data[ 15: 8]; assign pb[0] = i_data[  7: 0];
    assign pr[1] = i_data[ 55:48]; assign pg[1] = i_data[ 47:40]; assign pb[1] = i_data[ 39:32];
    assign pr[2] = i_data[ 87:80]; assign pg[2] = i_data[ 79:72]; assign pb[2] = i_data[ 71:64];
    assign pr[3] = i_data[119:112];assign pg[3] = i_data[111:104];assign pb[3] = i_data[103:96];

    reg [17:0] m_yr [0:3], m_yg [0:3], m_yb [0:3];
    reg [17:0] m_ur [0:3], m_ug [0:3], m_ub [0:3];
    reg [17:0] m_vr [0:3], m_vg [0:3], m_vb [0:3];
    integer    k;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (k=0;k<4;k=k+1) begin
                m_yr[k]<=0; m_yg[k]<=0; m_yb[k]<=0;
                m_ur[k]<=0; m_ug[k]<=0; m_ub[k]<=0;
                m_vr[k]<=0; m_vg[k]<=0; m_vb[k]<=0;
            end
        end else begin
            for (k=0;k<4;k=k+1) begin
                m_yr[k] <= pr[k] * C_Y_R;
                m_yg[k] <= pg[k] * C_Y_G;
                m_yb[k] <= pb[k] * C_Y_B;
                m_ur[k] <= pr[k] * C_CB_R;
                m_ug[k] <= pg[k] * C_CB_G;
                m_ub[k] <= pb[k] * C_CB_B;
                m_vr[k] <= pr[k] * C_CR_R;
                m_vg[k] <= pg[k] * C_CR_G;
                m_vb[k] <= pb[k] * C_CR_B;
            end
        end
    end

    reg [17:0] s_y_pos [0:3];
    reg [17:0] s_u_pos [0:3], s_u_neg [0:3];
    reg [17:0] s_v_pos [0:3], s_v_neg [0:3];
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (k=0;k<4;k=k+1) begin
                s_y_pos[k]<=0;
                s_u_pos[k]<=0; s_u_neg[k]<=0;
                s_v_pos[k]<=0; s_v_neg[k]<=0;
            end
        end else begin
            for (k=0;k<4;k=k+1) begin
                s_y_pos[k] <= m_yr[k] + m_yg[k] + m_yb[k] + OFF_Y;

                s_u_pos[k] <= m_ub[k] + OFF_UV;
                s_u_neg[k] <= m_ur[k] + m_ug[k];

                s_v_pos[k] <= m_vr[k] + OFF_UV;
                s_v_neg[k] <= m_vg[k] + m_vb[k];
            end
        end
    end

    reg [7:0] yv [0:3], cb [0:3], cr [0:3];
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (k=0;k<4;k=k+1) begin yv[k]<=0; cb[k]<=0; cr[k]<=0; end
        end else begin
            for (k=0;k<4;k=k+1) begin
                yv[k] <= (s_y_pos[k][17:16]!=2'b00) ? 8'hff : s_y_pos[k][15:8];
                cb[k] <= (s_u_pos[k] >= s_u_neg[k]) ? (((s_u_pos[k]-s_u_neg[k])>>8 > 18'd255) ? 8'hff : (s_u_pos[k]-s_u_neg[k])>>8) : 8'd0;
                cr[k] <= (s_v_pos[k] >= s_v_neg[k]) ? (((s_v_pos[k]-s_v_neg[k])>>8 > 18'd255) ? 8'hff : (s_v_pos[k]-s_v_neg[k])>>8) : 8'd0;
            end
        end
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            o_data     <= 64'd0;
            o_de       <= 1'b0;
            o_user_sof <= 1'b0;
            o_last     <= 1'b0;
        end else begin
            o_data     <= { cr[3], yv[3], cb[2], yv[2],
                            cr[1], yv[1], cb[0], yv[0] };
            o_de       <= de_d[3];
            o_user_sof <= sof_d[3];
            o_last     <= last_d[3];
        end
    end

endmodule
