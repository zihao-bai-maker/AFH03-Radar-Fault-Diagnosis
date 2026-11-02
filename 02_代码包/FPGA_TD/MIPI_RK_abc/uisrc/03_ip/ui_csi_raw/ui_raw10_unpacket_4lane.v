

module ui_raw10_unpacket_4lane (
    input wire        I_clk					,
    input wire        I_rst_n				,

    input wire        I_csi_frame_start		,
    input wire        I_csi_frame_end		,
    input wire        I_csi_valid			,
    input wire[31:0]  I_csi_data			,

    output reg        O_raw10_frame_start	,
    output reg        O_raw10_frame_end		,
    output reg        O_raw10_valid			,
    output reg[39:0]  O_raw10_data
);

    reg        S_csi_valid_1d;
    reg[31:0]  S_csi_data_1d;
    reg[2:0]   S_cnt;
    reg        S_raw10_wr_en;
    reg[39:0]  S_raw10_wr_data;

    always @(posedge I_clk) begin
        O_raw10_frame_start <= I_csi_frame_start;
        O_raw10_frame_end   <= I_csi_frame_end;
        S_csi_valid_1d      <= I_csi_valid;
        S_csi_data_1d       <= I_csi_data;
    end

    always @(posedge I_clk) begin
        if(S_csi_valid_1d)
            begin
                if(S_cnt == 'd4)
                    S_cnt <= 'd0;
                else
                    S_cnt <= S_cnt + 'd1;
            end
        else
            S_cnt <= 'd0;
    end

    always @(posedge I_clk) begin
        if(S_csi_valid_1d)
            begin
                case(S_cnt)
                    'd0:
                        begin
                            S_raw10_wr_en          <= 1'b1;
                            S_raw10_wr_data[39:30] <= {S_csi_data_1d[31:24],I_csi_data[25:24]}; 
                            S_raw10_wr_data[29:20] <= {S_csi_data_1d[23:16],I_csi_data[27:26]}; 
                            S_raw10_wr_data[19:10] <= {S_csi_data_1d[15:8], I_csi_data[29:28]}; 
                            S_raw10_wr_data[9:0]   <= {S_csi_data_1d[7:0],  I_csi_data[31:30]}; 
                        end
                    'd1:
                        begin
                            S_raw10_wr_en          <= 1'b1;
                            S_raw10_wr_data[39:30] <= {S_csi_data_1d[23:16],I_csi_data[17:16]}; 
                            S_raw10_wr_data[29:20] <= {S_csi_data_1d[15:8], I_csi_data[19:18]}; 
                            S_raw10_wr_data[19:10] <= {S_csi_data_1d[7:0],  I_csi_data[21:20]}; 
                            S_raw10_wr_data[9:0]   <= {I_csi_data[31:24],   I_csi_data[23:22]}; 
                        end
                    'd2:
                        begin
                            S_raw10_wr_en          <= 1'b1;
                            S_raw10_wr_data[39:30] <= {S_csi_data_1d[15:8],I_csi_data[9:8]};   
                            S_raw10_wr_data[29:20] <= {S_csi_data_1d[7:0], I_csi_data[11:10]}; 
                            S_raw10_wr_data[19:10] <= {I_csi_data[31:24],  I_csi_data[13:12]}; 
                            S_raw10_wr_data[9:0]   <= {I_csi_data[23:16],  I_csi_data[15:14]}; 
                        end
                    'd3:
                        begin
                            S_raw10_wr_en          <= 1'b1;
                            S_raw10_wr_data[39:30] <= {S_csi_data_1d[7:0],I_csi_data[1:0]}; 
                            S_raw10_wr_data[29:20] <= {I_csi_data[31:24], I_csi_data[3:2]}; 
                            S_raw10_wr_data[19:10] <= {I_csi_data[23:16], I_csi_data[5:4]}; 
                            S_raw10_wr_data[9:0]   <= {I_csi_data[15:8],  I_csi_data[7:6]}; 
                        end
                    'd4:
                        begin
                            S_raw10_wr_en          <= 1'b0;
                            S_raw10_wr_data[39:30] <= 'd0;
                            S_raw10_wr_data[29:20] <= 'd0;
                            S_raw10_wr_data[19:10] <= 'd0;
                            S_raw10_wr_data[9:0]   <= 'd0;
                        end
                endcase
            end
        else
            begin
                S_raw10_wr_en          <= 1'b0;
                S_raw10_wr_data[39:30] <= 'd0;
                S_raw10_wr_data[29:20] <= 'd0;
                S_raw10_wr_data[19:10] <= 'd0;
                S_raw10_wr_data[9:0]   <= 'd0;
            end
    end

  always @(posedge I_clk) begin
    O_raw10_data <= {
      S_raw10_wr_data[9:0], S_raw10_wr_data[19:10], S_raw10_wr_data[29:20], S_raw10_wr_data[39:30]
    };
    O_raw10_valid <= S_raw10_wr_en;
  end

endmodule

