

module ui_awb #(
    parameter IMG_HEIGHT = 1080,
    parameter IMG_WIDTH  = 1920
)(
    input                   I_clk,
    input                   I_rst_n,

    input  wire [12:0]      I_img_width,
    input  wire [12:0]      I_img_height,

    input                   I_tlast,
    input                   I_tuser,
    input      [95:0]       I_tdata,
    input                   I_tvalid,
    output                  I_tready,

    output                  O_tlast,
    output                  O_tuser,
    output     [95:0]       O_tdata,
    output                  O_tvalid,
    input                   O_tready
);

    reg         I_tvalid_r0, I_tvalid_r1;
    reg  [95:0] I_tdata_d0, I_tdata_d1, I_tdata_d2;

    reg  [31:0] sum_r;
    reg  [31:0] sum_g;
    reg  [31:0] sum_b;

    wire [95:0] data_d0;
    wire        valid_d0;
    wire        I_tuser_r0;

    reg         I_tuser_r1;
    reg  [95:0] data_d1;
    reg         valid_d1;
    reg  [9:0]  rgb_sum;

    always @(posedge I_clk or negedge I_rst_n) begin
        if (!I_rst_n) begin
            I_tdata_d0  <= 96'd0;
            I_tdata_d1  <= 96'd0;
            I_tdata_d2  <= 96'd0;
            I_tvalid_r0 <= 1'b0;
            I_tvalid_r1 <= 1'b0;
        end else begin
            I_tdata_d0  <= I_tdata;
            I_tdata_d1  <= I_tdata_d0;
            I_tdata_d2  <= I_tdata_d1;
            I_tvalid_r0 <= I_tvalid;
            I_tvalid_r1 <= I_tvalid_r0;
        end
    end

    wire [7:0] rgb888_r_d  = I_tdata[16+:8];
    wire [7:0] rgb888_g_d  = I_tdata[8+:8];
    wire [7:0] rgb888_b_d  = I_tdata[0+:8];

    wire [7:0] rgb888_r_d0 = I_tdata_d0[16+:8];
    wire [7:0] rgb888_g_d0 = I_tdata_d0[8+:8];
    wire [7:0] rgb888_b_d0 = I_tdata_d0[0+:8];

    always @(posedge I_clk or negedge I_rst_n) begin
        if (!I_rst_n)
            rgb_sum <= 10'd0;
        else if (I_tvalid)
            rgb_sum <= rgb888_r_d + rgb888_g_d + rgb888_b_d;
    end

    wire        flag_frame_r;
    reg [31:0] sum_r_d;
    reg [31:0] sum_g_d;
    reg [31:0] sum_b_d;

    always @(posedge I_clk or negedge I_rst_n) begin
        if (!I_rst_n) begin
            sum_r <= 32'd1;
            sum_g <= 32'd1;
            sum_b <= 32'd1;
        end else if (flag_frame_r) begin
            sum_r <= sum_r_d;
            sum_g <= sum_g_d;
            sum_b <= sum_b_d;
        end else if (I_tvalid_r0 && (rgb_sum < 10'd700)) begin
            sum_r <= sum_r + rgb888_r_d0;
            sum_g <= sum_g + rgb888_g_d0;
            sum_b <= sum_b + rgb888_b_d0;
        end
    end

    reg [3:0] frame_cnt;

    always @(posedge I_clk or negedge I_rst_n) begin
        if (!I_rst_n) begin
            sum_r_d <= 32'd1;
            sum_g_d <= 32'd1;
            sum_b_d <= 32'd1;
        end else if (frame_cnt == 4'd4) begin
            sum_r_d <= 32'd1;
            sum_g_d <= 32'd1;
            sum_b_d <= 32'd1;
        end else if (I_tvalid_r0 && (rgb_sum < 10'd700)) begin
            sum_r_d <= sum_r_d + rgb888_r_d0;
            sum_g_d <= sum_g_d + rgb888_g_d0;
            sum_b_d <= sum_b_d + rgb888_b_d0;
        end
    end

    always @(posedge I_clk or negedge I_rst_n) begin
        if (!I_rst_n)
            frame_cnt <= 4'd0;
        else if (frame_cnt == 4'd4)
            frame_cnt <= 4'd0;
        else if (I_tuser)
            frame_cnt <= frame_cnt + 1'b1;
    end

    reg flag_frame;
    always @(posedge I_clk or negedge I_rst_n) begin
        if (!I_rst_n)
            flag_frame <= 1'b0;
        else if (frame_cnt == 4'd1)
            flag_frame <= 1'b1;
        else
            flag_frame <= 1'b0;
    end

    reg flag_frame_d;
    always @(posedge I_clk or negedge I_rst_n) begin
        if (!I_rst_n)
            flag_frame_d <= 1'b0;
        else
            flag_frame_d <= flag_frame;
    end

    assign flag_frame_r = flag_frame & ~flag_frame_d;

    wire [47:0] dout_R;
    wire [47:0] dout_B;
    wire        done;

    wire [47:0] in_r_x1 = dout_R[47:0];
    wire [47:0] in_b_x1 = dout_B[47:0];

    divider div_gen_G_R_r1 (
        .clk        (I_clk),
        .rst        (!I_rst_n),
        .start      (I_tvalid_r1),
        .denominator(sum_r),
        .numerator  ({sum_g, 16'd0}),
        .quotient   (dout_R),
        .done       (done)
    );

    divider divide_G_B_r1 (
        .clk        (I_clk),
        .rst        (!I_rst_n),
        .start      (I_tvalid_r1),
        .denominator(sum_b),
        .numerator  ({sum_g, 16'd0}),
        .quotient   (dout_B),
        .done       ()
    );

    ui_signal_delay #(
        .IMG_HEIGHT (IMG_HEIGHT),
        .IMG_WIDTH  (IMG_WIDTH),
        .DATA_WIDTH (96),
        .DELAY_CYCLE(50)
    ) X_ui_signal_delay (
        .I_clk       (I_clk),
        .I_rst_n     (I_rst_n),
        .I_img_width (I_img_width),
        .I_img_height(I_img_height),
        .I_tuser     (I_tuser),
        .I_valid     (I_tvalid_r1),
        .I_data      (I_tdata_d1),
        .O_valid     (valid_d0),
        .O_data      (data_d0),
        .O_tuser     (I_tuser_r0)
    );

    reg [19:0] in_r_r1;
    reg [19:0] in_b_r1;

    always @(posedge I_clk or negedge I_rst_n) begin
        if (!I_rst_n) begin
            in_r_r1 <= 20'h10000;
            in_b_r1 <= 20'h10000;
        end else if (done) begin
            in_r_r1 <= (|in_r_x1[47:20]) ? 20'hfffff : in_r_x1[19:0];
            in_b_r1 <= (|in_b_x1[47:20]) ? 20'hfffff : in_b_x1[19:0];
        end
    end

    always @(posedge I_clk or negedge I_rst_n) begin
        if (!I_rst_n) begin
            valid_d1   <= 1'b0;
            data_d1    <= 96'd0;
            I_tuser_r1 <= 1'b0;
        end else begin
            valid_d1   <= valid_d0;
            data_d1    <= data_d0;
            I_tuser_r1 <= I_tuser_r0;
        end
    end

    reg [27:0] R_new_r1, G_new_r1, B_new_r1;
    reg [27:0] R_new_r2, G_new_r2, B_new_r2;
    reg [27:0] R_new_r3, G_new_r3, B_new_r3;
    reg [27:0] R_new_r4, G_new_r4, B_new_r4;

    wire [7:0] rgb888_r_d1[0:3];
    wire [7:0] rgb888_g_d1[0:3];
    wire [7:0] rgb888_b_d1[0:3];

    assign rgb888_r_d1[0] = data_d1[16+:8];
    assign rgb888_g_d1[0] = data_d1[8+:8];
    assign rgb888_b_d1[0] = data_d1[0+:8];

    assign rgb888_r_d1[1] = data_d1[40+:8];
    assign rgb888_g_d1[1] = data_d1[32+:8];
    assign rgb888_b_d1[1] = data_d1[24+:8];

    assign rgb888_r_d1[2] = data_d1[64+:8];
    assign rgb888_g_d1[2] = data_d1[56+:8];
    assign rgb888_b_d1[2] = data_d1[48+:8];

    assign rgb888_r_d1[3] = data_d1[88+:8];
    assign rgb888_g_d1[3] = data_d1[80+:8];
    assign rgb888_b_d1[3] = data_d1[72+:8];

    always @(posedge I_clk or negedge I_rst_n) begin
        if (!I_rst_n) begin
            R_new_r1 <= 28'd0; G_new_r1 <= 28'd0; B_new_r1 <= 28'd0;
            R_new_r2 <= 28'd0; G_new_r2 <= 28'd0; B_new_r2 <= 28'd0;
            R_new_r3 <= 28'd0; G_new_r3 <= 28'd0; B_new_r3 <= 28'd0;
            R_new_r4 <= 28'd0; G_new_r4 <= 28'd0; B_new_r4 <= 28'd0;
        end else if (valid_d1) begin
            R_new_r1 <= in_r_r1 * rgb888_r_d1[0];
            G_new_r1 <=           rgb888_g_d1[0];
            B_new_r1 <= in_b_r1 * rgb888_b_d1[0];

            R_new_r2 <= in_r_r1 * rgb888_r_d1[1];
            G_new_r2 <=           rgb888_g_d1[1];
            B_new_r2 <= in_b_r1 * rgb888_b_d1[1];

            R_new_r3 <= in_r_r1 * rgb888_r_d1[2];
            G_new_r3 <=           rgb888_g_d1[2];
            B_new_r3 <= in_b_r1 * rgb888_b_d1[2];

            R_new_r4 <= in_r_r1 * rgb888_r_d1[3];
            G_new_r4 <=           rgb888_g_d1[3];
            B_new_r4 <= in_b_r1 * rgb888_b_d1[3];
        end
    end

    wire [7:0] R_new_x1 = (R_new_r1[27:24]) ? 8'd255 : R_new_r1[23:16];
    wire [7:0] G_new_x1 = G_new_r1[7:0];
    wire [7:0] B_new_x1 = (B_new_r1[27:24]) ? 8'd255 : B_new_r1[23:16];

    wire [7:0] R_new_x2 = (R_new_r2[27:24]) ? 8'd255 : R_new_r2[23:16];
    wire [7:0] G_new_x2 = G_new_r2[7:0];
    wire [7:0] B_new_x2 = (B_new_r2[27:24]) ? 8'd255 : B_new_r2[23:16];

    wire [7:0] R_new_x3 = (R_new_r3[27:24]) ? 8'd255 : R_new_r3[23:16];
    wire [7:0] G_new_x3 = G_new_r3[7:0];
    wire [7:0] B_new_x3 = (B_new_r3[27:24]) ? 8'd255 : B_new_r3[23:16];

    wire [7:0] R_new_x4 = (R_new_r4[27:24]) ? 8'd255 : R_new_r4[23:16];
    wire [7:0] G_new_x4 = G_new_r4[7:0];
    wire [7:0] B_new_x4 = (B_new_r4[27:24]) ? 8'd255 : B_new_r4[23:16];

    reg valid_d2, I_tuser_r2;
    always @(posedge I_clk or negedge I_rst_n) begin
        if (!I_rst_n) begin
            valid_d2   <= 1'b0;
            I_tuser_r2 <= 1'b0;
        end else begin
            valid_d2   <= valid_d1;
            I_tuser_r2 <= I_tuser_r1;
        end
    end

    assign O_tlast  = (valid_d1 == 1'b0) && (valid_d2 == 1'b1);
    assign O_tuser  = I_tuser_r2;
    assign O_tvalid = valid_d2;

    assign O_tdata = O_tvalid ? {R_new_x4, G_new_x4, B_new_x4,
                                 R_new_x3, G_new_x3, B_new_x3,
                                 R_new_x2, G_new_x2, B_new_x2,
                                 R_new_x1, G_new_x1, B_new_x1} : 96'd0;

    assign I_tready = O_tready;

endmodule
