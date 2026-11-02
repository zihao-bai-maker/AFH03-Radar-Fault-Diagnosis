

module ui_Contrast_adj #(
    parameter  contrast_level   = 160 
)
(
    input                   I_clk  	 ,
    input                   I_rst_n	 ,

    input                   I_tlast  ,
    input                   I_tuser  ,
    input  [95:0]           I_tdata  ,
    input                   I_tvalid , 
    output                  I_tready ,

    output                  O_tlast  ,
    output                  O_tuser  ,
    output [95:0]           O_tdata  ,
    output                  O_tvalid ,
    input                   O_tready
);

    reg  [2:0]          I_tlast_r ;
    reg  [2:0]          I_tuser_r ;
    reg  [2:0]          I_tvalid_r;

    wire [23:0] I_tdata_r1 = I_tdata[23:0] ;
    wire [23:0] I_tdata_r2 = I_tdata[47:24];
    wire [23:0] I_tdata_r3 = I_tdata[71:48];
    wire [23:0] I_tdata_r4 = I_tdata[95:72];

    wire [7:0]  rgb888_r[3:0];
    wire [7:0]  rgb888_g[3:0];
    wire [7:0]  rgb888_b[3:0];

    reg  [9:0]  R_d[3:0];
    reg  [9:0]  G_d[3:0];
    reg  [9:0]  B_d[3:0];

    wire  [7:0]  R[3:0];
    wire  [7:0]  G[3:0];
    wire  [7:0]  B[3:0];

    reg  [15:0] pixel_shifted_R[3:0];
    reg  [15:0] pixel_shifted_G[3:0];
    reg  [15:0] pixel_shifted_B[3:0];

    reg  [15:0] temp_value_R[3:0];
    reg  [15:0] temp_value_G[3:0];
    reg  [15:0] temp_value_B[3:0];

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

    
    generate  
	genvar i ;
			for (i = 0;i<4 ;i=i+1 ) begin : top
    always @(posedge I_clk or negedge I_rst_n) begin
        if(!I_rst_n) begin
            pixel_shifted_R[i] <= 0;
            pixel_shifted_G[i] <= 0;
            pixel_shifted_B[i] <= 0;
        end
        else if(I_tvalid)begin
            pixel_shifted_R[i] <= {8'd0, rgb888_r[i]} - 16'd128;
            pixel_shifted_G[i] <= {8'd0, rgb888_g[i]} - 16'd128;
            pixel_shifted_B[i] <= {8'd0, rgb888_b[i]} - 16'd128;
        end
    end

    always @(posedge I_clk or negedge I_rst_n) begin
        if(!I_rst_n) begin
            temp_value_R[i] <= 0;
            temp_value_G[i] <= 0;
            temp_value_B[i] <= 0;
        end
        else if(I_tvalid_r[0])begin
            temp_value_R[i] <= (pixel_shifted_R[i] * contrast_level)>>7;
            temp_value_G[i] <= (pixel_shifted_G[i] * contrast_level)>>7;
            temp_value_B[i] <= (pixel_shifted_B[i] * contrast_level)>>7;
        end
    end

    always @(posedge I_clk or negedge I_rst_n) begin
        if(!I_rst_n) begin
            R_d[i] <= 0;
            G_d[i] <= 0;
            B_d[i] <= 0;
        end
        else if(I_tvalid_r[1])begin
            R_d[i] <= temp_value_R[i] + 16'd128;
            G_d[i] <= temp_value_G[i] + 16'd128;
            B_d[i] <= temp_value_B[i] + 16'd128;
        end
    end

    assign  R[i] = (R_d[i][9])?0:(R_d[i][8])?255:R_d[i][7:0];
    assign  G[i] = (G_d[i][9])?0:(G_d[i][8])?255:G_d[i][7:0];
    assign  B[i] = (B_d[i][9])?0:(B_d[i][8])?255:B_d[i][7:0];

       end
    endgenerate

    always @(posedge I_clk or negedge I_rst_n) begin
        if(!I_rst_n)
            {I_tlast_r,I_tuser_r,I_tvalid_r} <= 0;
        else begin
            I_tlast_r <= {I_tlast_r[1:0],I_tlast};
            I_tuser_r <= {I_tuser_r[1:0],I_tuser};
            I_tvalid_r <= {I_tvalid_r[1:0],I_tvalid};
        end
    end

    assign  O_tlast  = I_tlast_r[2];   
    assign  O_tuser  = I_tuser_r[2];   
    assign  O_tvalid = I_tvalid_r[2];

    assign O_tdata = {R[3],G[3],B[3],
                      R[2],G[2],B[2],
                      R[1],G[1],B[1],
                      R[0],G[0],B[0]};

    assign I_tready = O_tready;
endmodule

