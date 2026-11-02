

module ui_gamma #(
    parameter [4:0] GAMMA_10x = 22 
)
(
    input                   I_clk  		, 
    input                   I_rst_n		, 

    input                   I_tlast     , 
    input                   I_tuser     , 
    input [95:0]            I_tdata     , 
    input                   I_tvalid    , 
    output                  I_tready    , 

    output                  O_tlast     , 
    output                  O_tuser     , 
    output [95:0]           O_tdata     , 
    output                  O_tvalid    , 
    input                   O_tready      
);

    wire [23:0] I_tdata_r1 = I_tdata[23:0] ;     
    wire [23:0] I_tdata_r2 = I_tdata[47:24];     
    wire [23:0] I_tdata_r3 = I_tdata[71:48];     
    wire [23:0] I_tdata_r4 = I_tdata[95:72];     

    wire [7:0]  rgb888_r[3:0];                   
    wire [7:0]  rgb888_g[3:0];                   
    wire [7:0]  rgb888_b[3:0];                   

    assign   rgb888_r[0] = I_tdata_r1[16+:8];    
    assign   rgb888_g[0] = I_tdata_r1[8+:8] ;    
    assign   rgb888_b[0] = I_tdata_r1[0+:8] ;    

    assign   rgb888_r[1] = I_tdata_r2[16+:8];
    assign   rgb888_g[1] = I_tdata_r2[8+:8] ;
    assign   rgb888_b[1] = I_tdata_r2[0+:8] ;

    assign   rgb888_r[2] = I_tdata_r3[16+:8];
    assign   rgb888_g[2] = I_tdata_r3[8+:8] ;
    assign   rgb888_b[2] = I_tdata_r3[0+:8] ;

    assign   rgb888_r[3] = I_tdata_r4[16+:8];
    assign   rgb888_g[3] = I_tdata_r4[8+:8] ;
    assign   rgb888_b[3] = I_tdata_r4[0+:8] ;

    wire [11:0] O_LUT_2_6_data_r[3:0];
    wire [11:0] O_LUT_2_6_data_g[3:0];
    wire [11:0] O_LUT_2_6_data_b[3:0];

    wire [11:0] O_LUT_2_4_data_r[3:0];
    wire [11:0] O_LUT_2_4_data_g[3:0];
    wire [11:0] O_LUT_2_4_data_b[3:0];

    wire [11:0] O_LUT_2_2_data_r[3:0];
    wire [11:0] O_LUT_2_2_data_g[3:0];
    wire [11:0] O_LUT_2_2_data_b[3:0];

    wire [11:0] O_LUT_2_0_data_r[3:0];
    wire [11:0] O_LUT_2_0_data_g[3:0];
    wire [11:0] O_LUT_2_0_data_b[3:0];

    wire [11:0] O_LUT_1_8_data_r[3:0];
    wire [11:0] O_LUT_1_8_data_g[3:0];
    wire [11:0] O_LUT_1_8_data_b[3:0];

    wire [11:0] O_LUT_1_6_data_r[3:0];
    wire [11:0] O_LUT_1_6_data_g[3:0];
    wire [11:0] O_LUT_1_6_data_b[3:0];

    wire [11:0] O_LUT_1_4_data_r[3:0];
    wire [11:0] O_LUT_1_4_data_g[3:0];
    wire [11:0] O_LUT_1_4_data_b[3:0];

    wire [11:0] O_LUT_1_2_data_r[3:0];
    wire [11:0] O_LUT_1_2_data_g[3:0];
    wire [11:0] O_LUT_1_2_data_b[3:0];

    wire [11:0] O_LUT_0_8_data_r[3:0];
    wire [11:0] O_LUT_0_8_data_g[3:0];
    wire [11:0] O_LUT_0_8_data_b[3:0];

    wire  [7:0]  R_new [3:0];
    wire  [7:0]  G_new [3:0];
    wire  [7:0]  B_new [3:0];

    reg   [11:0]  acc_rgb888_r[3:0];
    reg   [11:0]  acc_rgb888_g[3:0];
    reg   [11:0]  acc_rgb888_b[3:0];

    reg   [3:0]   I_tlast_r ;
    reg   [3:0]   I_tuser_r ;
    reg   [3:0]   I_tvalid_r;

    reg   [20:0] acc_rgb888_r_x0[3:0];
    reg   [20:0] acc_rgb888_g_x0[3:0];
    reg   [20:0] acc_rgb888_b_x0[3:0];

    reg   [20:0] acc_rgb888_r_x1[3:0];
    reg   [20:0] acc_rgb888_g_x1[3:0];
    reg   [20:0] acc_rgb888_b_x1[3:0];

    reg   [7:0]  acc_rgb888_r_x2[3:0];
    reg   [7:0]  acc_rgb888_g_x2[3:0];
    reg   [7:0]  acc_rgb888_b_x2[3:0];

    genvar i;
    generate
        for(i = 0; i < 4; i = i + 1)
        begin: LUT

            ui_lut_2_6 X_ui_lut_2_6_R(
                .I_clk         (I_clk     ),
                .I_rst_n       (I_rst_n   ),
                .I_LUT_2_6_data(rgb888_r[i]),
                .O_LUT_2_6_data(O_LUT_2_6_data_r[i])
            );

            ui_lut_2_6 X_ui_lut_2_6_G(
                .I_clk         (I_clk     ),
                .I_rst_n       (I_rst_n   ),
                .I_LUT_2_6_data(rgb888_g[i]),
                .O_LUT_2_6_data(O_LUT_2_6_data_g[i])
            );

            ui_lut_2_6 X_ui_lut_2_6_B(
                .I_clk         (I_clk     ),
                .I_rst_n       (I_rst_n   ),
                .I_LUT_2_6_data(rgb888_b[i]),
                .O_LUT_2_6_data(O_LUT_2_6_data_b[i])
            );

            ui_lut_2_4 X_ui_lut_2_4_R(
                .I_clk         (I_clk     ),
                .I_rst_n       (I_rst_n   ),
                .I_LUT_2_4_data(rgb888_r[i]),
                .O_LUT_2_4_data(O_LUT_2_4_data_r[i])
            );

            ui_lut_2_4 X_ui_lut_2_4_G(
                .I_clk         (I_clk     ),
                .I_rst_n       (I_rst_n   ),
                .I_LUT_2_4_data(rgb888_g[i]),
                .O_LUT_2_4_data(O_LUT_2_4_data_g[i])
            );

            ui_lut_2_4 X_ui_lut_2_4_B(
                .I_clk         (I_clk     ),
                .I_rst_n       (I_rst_n   ),
                .I_LUT_2_4_data(rgb888_b[i]),
                .O_LUT_2_4_data(O_LUT_2_4_data_b[i])
            );

            ui_lut_2_2 X_ui_lut_2_2_R(
                .I_clk         (I_clk     ),
                .I_rst_n       (I_rst_n   ),
                .I_LUT_2_2_data(rgb888_r[i]),
                .O_LUT_2_2_data(O_LUT_2_2_data_r[i])
            );

            ui_lut_2_2 X_ui_lut_2_2_G(
                .I_clk         (I_clk     ),
                .I_rst_n       (I_rst_n   ),
                .I_LUT_2_2_data(rgb888_g[i]),
                .O_LUT_2_2_data(O_LUT_2_2_data_g[i])
            );

            ui_lut_2_2 X_ui_lut_2_2_B(
                .I_clk         (I_clk     ),
                .I_rst_n       (I_rst_n   ),
                .I_LUT_2_2_data(rgb888_b[i]),
                .O_LUT_2_2_data(O_LUT_2_2_data_b[i])
            );

            ui_lut_2_0 X_ui_lut_2_0_R(
                .I_clk         (I_clk     ),
                .I_rst_n       (I_rst_n   ),
                .I_LUT_2_0_data(rgb888_r[i]),
                .O_LUT_2_0_data(O_LUT_2_0_data_r[i])
            );

            ui_lut_2_0 X_ui_lut_2_0_G(
                .I_clk         (I_clk     ),
                .I_rst_n       (I_rst_n   ),
                .I_LUT_2_0_data(rgb888_g[i]),
                .O_LUT_2_0_data(O_LUT_2_0_data_g[i])
            );

            ui_lut_2_0 X_ui_lut_2_0_B(
                .I_clk         (I_clk     ),
                .I_rst_n       (I_rst_n   ),
                .I_LUT_2_0_data(rgb888_b[i]),
                .O_LUT_2_0_data(O_LUT_2_0_data_b[i])
            );

            ui_lut_1_8 X_ui_lut_1_8_R(
                .I_clk         (I_clk     ),
                .I_rst_n       (I_rst_n   ),
                .I_LUT_1_8_data(rgb888_r[i]),
                .O_LUT_1_8_data(O_LUT_1_8_data_r[i])
            );

            ui_lut_1_8 X_ui_lut_1_8_G(
                .I_clk         (I_clk     ),
                .I_rst_n       (I_rst_n   ),
                .I_LUT_1_8_data(rgb888_g[i]),
                .O_LUT_1_8_data(O_LUT_1_8_data_g[i])
            );

            ui_lut_1_8 X_ui_lut_1_8_B(
                .I_clk         (I_clk     ),
                .I_rst_n       (I_rst_n   ),
                .I_LUT_1_8_data(rgb888_b[i]),
                .O_LUT_1_8_data(O_LUT_1_8_data_b[i])
            );

            ui_lut_1_6 X_ui_lut_1_6_R(
                .I_clk         (I_clk     ),
                .I_rst_n       (I_rst_n   ),
                .I_LUT_1_6_data(rgb888_r[i]),
                .O_LUT_1_6_data(O_LUT_1_6_data_r[i])
            );

            ui_lut_1_6 X_ui_lut_1_6_G(
                .I_clk         (I_clk     ),
                .I_rst_n       (I_rst_n   ),
                .I_LUT_1_6_data(rgb888_g[i]),
                .O_LUT_1_6_data(O_LUT_1_6_data_g[i])
            );

            ui_lut_1_6 X_ui_lut_1_6_B(
                .I_clk         (I_clk     ),
                .I_rst_n       (I_rst_n   ),
                .I_LUT_1_6_data(rgb888_b[i]),
                .O_LUT_1_6_data(O_LUT_1_6_data_b[i])
            );

            ui_lut_1_4 X_ui_lut_1_4_R(
                .I_clk         (I_clk     ),
                .I_rst_n       (I_rst_n   ),
                .I_LUT_1_4_data(rgb888_r[i]),
                .O_LUT_1_4_data(O_LUT_1_4_data_r[i])
            );

            ui_lut_1_4 X_ui_lut_1_4_G(
                .I_clk         (I_clk     ),
                .I_rst_n       (I_rst_n   ),
                .I_LUT_1_4_data(rgb888_g[i]),
                .O_LUT_1_4_data(O_LUT_1_4_data_g[i])
            );

            ui_lut_1_4 X_ui_lut_1_4_B(
                .I_clk         (I_clk     ),
                .I_rst_n       (I_rst_n   ),
                .I_LUT_1_4_data(rgb888_b[i]),
                .O_LUT_1_4_data(O_LUT_1_4_data_b[i])
            );

            ui_lut_1_2 X_ui_lut_1_2_R(
                .I_clk         (I_clk     ),
                .I_rst_n       (I_rst_n   ),
                .I_LUT_1_2_data(rgb888_r[i]),
                .O_LUT_1_2_data(O_LUT_1_2_data_r[i])
            );

            ui_lut_1_2 X_ui_lut_1_2_G(
                .I_clk         (I_clk     ),
                .I_rst_n       (I_rst_n   ),
                .I_LUT_1_2_data(rgb888_g[i]),
                .O_LUT_1_2_data(O_LUT_1_2_data_g[i])
            );

            ui_lut_1_2 X_ui_lut_1_2_B(
                .I_clk         (I_clk     ),
                .I_rst_n       (I_rst_n   ),
                .I_LUT_1_2_data(rgb888_b[i]),
                .O_LUT_1_2_data(O_LUT_1_2_data_b[i])
            );

            ui_lut_0_8 X_ui_lut_0_8_R(
                .I_clk         (I_clk     ),
                .I_rst_n       (I_rst_n   ),
                .I_LUT_0_8_data(rgb888_r[i]),
                .O_LUT_0_8_data(O_LUT_0_8_data_r[i])
            );

            ui_lut_0_8 X_ui_lut_0_8_G(
                .I_clk         (I_clk     ),
                .I_rst_n       (I_rst_n   ),
                .I_LUT_0_8_data(rgb888_g[i]),
                .O_LUT_0_8_data(O_LUT_0_8_data_g[i])
            );

            ui_lut_0_8 X_ui_lut_0_8_B(
                .I_clk         (I_clk     ),
                .I_rst_n       (I_rst_n   ),
                .I_LUT_0_8_data(rgb888_b[i]),
                .O_LUT_0_8_data(O_LUT_0_8_data_b[i])
            );

            always @(posedge I_clk or negedge I_rst_n)begin 
                if(!I_rst_n)begin
                    acc_rgb888_r[i] <= 12'd0;
                    acc_rgb888_g[i] <= 12'd0;
                    acc_rgb888_b[i] <= 12'd0;
                end
                else begin
                    case (GAMMA_10x)
                        5'd26:begin 
                           acc_rgb888_r[i] <= O_LUT_2_6_data_r[i];
                           acc_rgb888_g[i] <= O_LUT_2_6_data_g[i];
                           acc_rgb888_b[i] <= O_LUT_2_6_data_b[i];
                        end
                        5'd24:begin 
                           acc_rgb888_r[i] <= O_LUT_2_4_data_r[i];
                           acc_rgb888_g[i] <= O_LUT_2_4_data_g[i];
                           acc_rgb888_b[i] <= O_LUT_2_4_data_b[i];
                        end
                        5'd22:begin 
                           acc_rgb888_r[i] <= O_LUT_2_2_data_r[i];
                           acc_rgb888_g[i] <= O_LUT_2_2_data_g[i];
                           acc_rgb888_b[i] <= O_LUT_2_2_data_b[i];
                        end
                        5'd20:begin
                           acc_rgb888_r[i] <= O_LUT_2_0_data_r[i];
                           acc_rgb888_g[i] <= O_LUT_2_0_data_g[i];
                           acc_rgb888_b[i] <= O_LUT_2_0_data_b[i];
                        end
                        5'd18:begin
                           acc_rgb888_r[i] <= O_LUT_1_8_data_r[i];
                           acc_rgb888_g[i] <= O_LUT_1_8_data_g[i];
                           acc_rgb888_b[i] <= O_LUT_1_8_data_b[i];
                        end
                        5'd16:begin
                           acc_rgb888_r[i] <= O_LUT_1_6_data_r[i];
                           acc_rgb888_g[i] <= O_LUT_1_6_data_g[i];
                           acc_rgb888_b[i] <= O_LUT_1_6_data_b[i];
                        end
                        5'd14:begin
                           acc_rgb888_r[i] <= O_LUT_1_4_data_r[i];
                           acc_rgb888_g[i] <= O_LUT_1_4_data_g[i];
                           acc_rgb888_b[i] <= O_LUT_1_4_data_b[i];
                        end
                        5'd12:begin
                           acc_rgb888_r[i] <= O_LUT_1_2_data_r[i];
                           acc_rgb888_g[i] <= O_LUT_1_2_data_g[i];
                           acc_rgb888_b[i] <= O_LUT_1_2_data_b[i];
                        end
                        5'd8 :begin
                           acc_rgb888_r[i] <= O_LUT_0_8_data_r[i];
                           acc_rgb888_g[i] <= O_LUT_0_8_data_g[i];
                           acc_rgb888_b[i] <= O_LUT_0_8_data_b[i];
                        end
                        default:begin 
                           acc_rgb888_r[i] <= O_LUT_2_2_data_r[i];
                           acc_rgb888_g[i] <= O_LUT_2_2_data_g[i];
                           acc_rgb888_b[i] <= O_LUT_2_2_data_b[i];
                        end
                    endcase
                end
            end

            always @(posedge I_clk or negedge I_rst_n)begin 
                if(!I_rst_n)begin
                    acc_rgb888_r_x0[i] <= 0;
                    acc_rgb888_g_x0[i] <= 0;
                    acc_rgb888_b_x0[i] <= 0;
                end
                else if(I_tvalid_r[0])begin
                    acc_rgb888_r_x0[i] <= acc_rgb888_r[i] << 8;
                    acc_rgb888_g_x0[i] <= acc_rgb888_g[i] << 8;
                    acc_rgb888_b_x0[i] <= acc_rgb888_b[i] << 8;
                end
                else begin
                    acc_rgb888_r_x0[i] <= acc_rgb888_r_x0[i] ;
                    acc_rgb888_g_x0[i] <= acc_rgb888_g_x0[i] ;
                    acc_rgb888_b_x0[i] <= acc_rgb888_b_x0[i] ;
                end
            end

            
            always @(posedge I_clk or negedge I_rst_n)begin 
                if(!I_rst_n)begin
                    acc_rgb888_r_x1[i] <= 0;
                    acc_rgb888_g_x1[i] <= 0;
                    acc_rgb888_b_x1[i] <= 0;
                end
                else if(I_tvalid_r[1])begin
                    acc_rgb888_r_x1[i] <= acc_rgb888_r_x0[i] - 2048;
                    acc_rgb888_g_x1[i] <= acc_rgb888_g_x0[i] - 2048;
                    acc_rgb888_b_x1[i] <= acc_rgb888_b_x0[i] - 2048;
                end
                else begin
                    acc_rgb888_r_x1[i] <= acc_rgb888_r_x1[i];
                    acc_rgb888_g_x1[i] <= acc_rgb888_g_x1[i];
                    acc_rgb888_b_x1[i] <= acc_rgb888_b_x1[i];
                end
            end

            
            always @(posedge I_clk or negedge I_rst_n)begin 
                if(!I_rst_n)begin
                    acc_rgb888_r_x2[i] <= 0;
                    acc_rgb888_g_x2[i] <= 0;
                    acc_rgb888_b_x2[i] <= 0;
                end
                else if(I_tvalid_r[2])begin
                    acc_rgb888_r_x2[i] <= (acc_rgb888_r_x1[i][20]) ? 8'd255 : (acc_rgb888_r_x1[i][19:12]);
                    acc_rgb888_g_x2[i] <= (acc_rgb888_g_x1[i][20]) ? 8'd255 : (acc_rgb888_g_x1[i][19:12]);
                    acc_rgb888_b_x2[i] <= (acc_rgb888_b_x1[i][20]) ? 8'd255 : (acc_rgb888_b_x1[i][19:12]);
                end
                else begin
                    acc_rgb888_r_x2[i] <= acc_rgb888_r_x2[i];
                    acc_rgb888_g_x2[i] <= acc_rgb888_g_x2[i];
                    acc_rgb888_b_x2[i] <= acc_rgb888_b_x2[i];
                end
            end

            assign R_new[i] = acc_rgb888_r_x2[i];
            assign G_new[i] = acc_rgb888_g_x2[i];
            assign B_new[i] = acc_rgb888_b_x2[i];

        end
    endgenerate

    always @(posedge I_clk or negedge I_rst_n) begin
        if(!I_rst_n)
            {I_tlast_r,I_tuser_r,I_tvalid_r} <= 0;
        else begin
            I_tlast_r <= {I_tlast_r[2:0],I_tlast};
            I_tuser_r <= {I_tuser_r[2:0],I_tuser};
            I_tvalid_r <= {I_tvalid_r[2:0],I_tvalid};
        end
    end

    assign  O_tlast  = I_tlast_r[3];   
    assign  O_tuser  = I_tuser_r[3];   
    assign  O_tvalid = I_tvalid_r[3];

    assign O_tdata = {R_new[3],G_new[3],B_new[3],
                      R_new[2],G_new[2],B_new[2],
                      R_new[1],G_new[1],B_new[1],
                      R_new[0],G_new[0],B_new[0]};

    assign  I_tready = O_tready;

endmodule
