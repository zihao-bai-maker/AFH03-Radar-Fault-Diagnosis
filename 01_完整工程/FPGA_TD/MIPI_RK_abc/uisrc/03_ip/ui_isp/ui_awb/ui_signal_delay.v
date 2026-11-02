

module ui_signal_delay #(
    parameter IMG_HEIGHT = 1080,
    parameter IMG_WIDTH  = 1920,
    parameter DATA_WIDTH = 96,
    parameter DELAY_CYCLE = 50
) (
    input                        I_clk,	   
    input                        I_rst_n,  
    input  wire [12:0]           I_img_width,
    input  wire [12:0]           I_img_height,
    input                        I_tuser,  
    input  wire                  I_valid,  
    input  wire [DATA_WIDTH-1:0] I_data,   
    output wire                  O_valid,  
    output wire [DATA_WIDTH-1:0] O_data ,  
    output wire                  O_tuser   
);

    wire        rd_en; 

    reg  [10:0] addra; 
    reg  [10:0] addrb; 

    reg  [13:0] h_cnt;
    reg  [13:0] v_cnt;
    reg  [13:0] rd_cnt;

    reg  [DATA_WIDTH-1:0] I_data_r;
    reg         rd_valid,I_valid_r;

    wire [12:0] img_width_4x  = I_img_width >> 2;
    wire [12:0] img_height_rt = I_img_height;
    always @(posedge I_clk or negedge I_rst_n) begin
        if (!I_rst_n ) begin
            I_valid_r <= 0;
            I_data_r  <= 0;
        end
        else begin
            I_valid_r <= I_valid;
            I_data_r  <= I_data;
        end
    end

	
    always @(posedge I_clk or negedge I_rst_n) begin
        if (!I_rst_n || I_tuser) begin
            h_cnt <= 0;
            v_cnt <= 0;
        end
        else begin
            h_cnt <= I_valid_r ? ((h_cnt == img_width_4x-1) ? 0 : h_cnt + 1) : h_cnt;
            v_cnt <= I_valid_r &&(h_cnt == img_width_4x-1) ? ((v_cnt == img_height_rt - 1) ? 0 : v_cnt + 1) : v_cnt;
        end
    end

	
    always @(posedge I_clk or negedge I_rst_n) begin
        if (!I_rst_n || I_tuser) begin
            rd_valid <= 0;
        end
        else if(h_cnt == DELAY_CYCLE - 3)begin
            rd_valid <= 1;
        end
        else if(rd_cnt == img_width_4x - 1) 
            rd_valid <= 0;
    end

	 
    always @(posedge I_clk or negedge I_rst_n) begin
        if (!I_rst_n || I_tuser) begin
            rd_cnt <= 0;
        end
        else if(rd_cnt == img_width_4x )
            rd_cnt <= 0;
        else if(rd_valid)begin
            rd_cnt <= rd_cnt + 1;
        end
    end

	
    always @(posedge I_clk or negedge I_rst_n) begin
        if (!I_rst_n || I_tuser) begin
            addra <= 0;
        end else if (I_valid_r) begin
            addra <= (addra == img_width_4x - 1) ? 'b0 : addra + 1'b1;
        end
    end

    always @(posedge I_clk or negedge I_rst_n) begin
      if (!I_rst_n || I_tuser) begin
        addrb <= 0;
      end else begin
                addrb <= rd_valid ? (addrb == img_width_4x - 1) ? 'b0 : addrb + 1'b1 : addrb;
      end
    end

	
    reg rd_valid_d;
    always @(posedge I_clk or negedge I_rst_n) begin
      if (!I_rst_n) begin
        rd_valid_d <= 0;
      end else begin
        rd_valid_d <= rd_valid;
      end
    end
    assign O_valid = rd_valid_d;
    assign O_tuser = (v_cnt == 0) && (rd_cnt == 1);

    ui_ram_awb_delay_signal X_ui_ram_awb_delay_signal (
      .clka (I_clk   ),  
      .wea  (I_valid_r),  
      .addra(addra   ),  
      .dia  (I_data_r ),  
      .clkb (I_clk   ),  
      .addrb(addrb   ),  
      .dob  (O_data  )   
    );

endmodule