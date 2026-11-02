`timescale 1ns / 1ps

module rgb888_to_yuv422_pipeline(
    input               clk,
    input               rst_n,

    
    input               i_h_sync,
    input               i_v_sync,
    input               i_data_en,
    input       [31:0]  i_rgb_data,        

    
    output              o_h_sync,
    output              o_v_sync,
    output              o_data_en,
    output      [31:0]  o_yuv422_data      
);

parameter para_0183_10b = 10'd47;   
parameter para_0614_10b = 10'd157;  
parameter para_0062_10b = 10'd16;   
parameter para_0101_10b = 10'd26;   
parameter para_0338_10b = 10'd86;   
parameter para_0439_10b = 10'd112;  
parameter para_0399_10b = 10'd102;  
parameter para_0040_10b = 10'd10;   
parameter para_16_18b   = 18'd4096; 
parameter para_128_18b  = 18'd32768;

wire [7:0] rgb_r = i_rgb_data[23:16];
wire [7:0] rgb_g = i_rgb_data[15:8];
wire [7:0] rgb_b = i_rgb_data[7:0];

reg [17:0] mult_r_for_y_18b, mult_r_for_cb_18b, mult_r_for_cr_18b;
reg [17:0] mult_g_for_y_18b, mult_g_for_cb_18b, mult_g_for_cr_18b;
reg [17:0] mult_b_for_y_18b, mult_b_for_cb_18b, mult_b_for_cr_18b;

reg [17:0] add_y_0_18b, add_y_1_18b;
reg [17:0] add_cb_0_18b, add_cb_1_18b;
reg [17:0] add_cr_0_18b, add_cr_1_18b;

reg [17:0] result_y_18b, result_cb_18b, result_cr_18b;
reg [7:0]  y_final, cb_final, cr_final;

reg [4:0] h_sync_delay, v_sync_delay, data_en_delay;

reg yuv422_phase;  
reg [7:0] y_even, cb_even, y_odd, cr_odd;
reg phase_reset_flag;  

reg [31:0] yuv422_output;
reg output_valid;

always @(posedge clk) begin
    if (!rst_n) begin
        mult_r_for_y_18b  <= 18'd0;
        mult_r_for_cb_18b <= 18'd0;
        mult_r_for_cr_18b <= 18'd0;
        mult_g_for_y_18b  <= 18'd0;
        mult_g_for_cb_18b <= 18'd0;
        mult_g_for_cr_18b <= 18'd0;
        mult_b_for_y_18b  <= 18'd0;
        mult_b_for_cb_18b <= 18'd0;
        mult_b_for_cr_18b <= 18'd0;
    end else begin

        mult_r_for_y_18b  <= rgb_r * para_0183_10b;
        mult_r_for_cb_18b <= rgb_r * para_0101_10b;
        mult_r_for_cr_18b <= rgb_r * para_0439_10b;

        
        mult_g_for_y_18b  <= rgb_g * para_0614_10b;
        mult_g_for_cb_18b <= rgb_g * para_0338_10b;
        mult_g_for_cr_18b <= rgb_g * para_0399_10b;

        
        mult_b_for_y_18b  <= rgb_b * para_0062_10b;
        mult_b_for_cb_18b <= rgb_b * para_0439_10b;
        mult_b_for_cr_18b <= rgb_b * para_0040_10b;
    end
end

always @(posedge clk) begin
    if (!rst_n) begin
        add_y_0_18b  <= 18'd0;
        add_y_1_18b  <= 18'd0;
        add_cb_0_18b <= 18'd0;
        add_cb_1_18b <= 18'd0;
        add_cr_0_18b <= 18'd0;
        add_cr_1_18b <= 18'd0;
    end else begin

        add_y_0_18b <= mult_r_for_y_18b + mult_g_for_y_18b;
        add_y_1_18b <= mult_b_for_y_18b + para_16_18b;

        
        add_cb_0_18b <= mult_b_for_cb_18b + para_128_18b;
        add_cb_1_18b <= mult_r_for_cb_18b + mult_g_for_cb_18b;

        
        add_cr_0_18b <= mult_r_for_cr_18b + para_128_18b;
        add_cr_1_18b <= mult_g_for_cr_18b + mult_b_for_cr_18b;
    end
end

wire sign_cb = (add_cb_0_18b >= add_cb_1_18b);
wire sign_cr = (add_cr_0_18b >= add_cr_1_18b);

always @(posedge clk) begin
    if (!rst_n) begin
        result_y_18b  <= 18'd0;
        result_cb_18b <= 18'd0;
        result_cr_18b <= 18'd0;
        y_final       <= 8'd0;
        cb_final      <= 8'd0;
        cr_final      <= 8'd0;
    end else begin

        result_y_18b <= add_y_0_18b + add_y_1_18b;

        
        result_cb_18b <= sign_cb ? (add_cb_0_18b - add_cb_1_18b) : 18'd0;

        
        result_cr_18b <= sign_cr ? (add_cr_0_18b - add_cr_1_18b) : 18'd0;

        
        y_final  <= (result_y_18b[17:16] == 2'b00) ? result_y_18b[15:8] : 8'hFF;
        cb_final <= (result_cb_18b[17:16] == 2'b00) ? result_cb_18b[15:8] : 8'hFF;
        cr_final <= (result_cr_18b[17:16] == 2'b00) ? result_cr_18b[15:8] : 8'hFF;
    end
end

always @(posedge clk) begin
    if (!rst_n) begin
        h_sync_delay  <= 5'b00000;
        v_sync_delay  <= 5'b00000;
        data_en_delay <= 5'b00000;
        phase_reset_flag <= 1'b0;
    end else begin
        h_sync_delay  <= {h_sync_delay[3:0], i_h_sync};
        v_sync_delay  <= {v_sync_delay[3:0], i_v_sync};
        data_en_delay <= {data_en_delay[3:0], i_data_en};

        phase_reset_flag <= (h_sync_delay[1:0] == 2'b01); 
    end
end

always @(posedge clk) begin
    if (!rst_n) begin
        yuv422_phase <= 1'b0;
        y_even       <= 8'd0;
        cb_even      <= 8'd0;
        y_odd        <= 8'd0;
        cr_odd       <= 8'd0;
        yuv422_output<= 32'd0;
        output_valid <= 1'b0;
    end
    else if(phase_reset_flag) begin

            yuv422_phase <= 1'b0;
            output_valid <= 1'b0;

    end else if (data_en_delay[4]) begin
        yuv422_phase <= ~yuv422_phase;

        if (!yuv422_phase) begin

            y_even  <= y_final;
            cb_even <= cb_final;
            output_valid <= 1'b0;
        end else begin

            

            

            y_odd   <= y_final;
            cr_odd  <= cr_final;
            yuv422_output <= {cr_final, y_final, cb_even, y_even};
            output_valid  <= 1'b1;
        end
    end else begin
        output_valid <= 1'b0;
    end
end

assign o_h_sync      = h_sync_delay[4];
assign o_v_sync      = v_sync_delay[4];
assign o_data_en     = output_valid;
assign o_yuv422_data = yuv422_output;

endmodule
