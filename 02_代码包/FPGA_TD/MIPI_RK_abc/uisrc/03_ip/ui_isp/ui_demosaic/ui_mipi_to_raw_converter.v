

module ui_mipi_to_raw_converter 
(
    input           	I_clk   	,
    input           	I_rst_n 	,

    input   [39:0]  	I_raw_tdata ,
    input   [ 9:0]  	I_raw_tdest ,
    input           	I_raw_tlast ,
    input           	I_raw_tvalid,
    input           	I_raw_tuser ,
    output          	I_raw_tready,

    
    output  [31:0]  	O_raw_tdata ,
    output          	O_raw_tlast ,
    output          	O_raw_tvalid,
    output          	O_raw_tuser ,
    input           	O_raw_tready
);
    reg            			I_tlast_r0;
    reg            			I_tuser_r0;

    reg            			I_tvalid_r0;
    reg    [31:0]  			raw_data_r0;

	assign  O_raw_tlast  = 	I_tlast_r0;   
    assign  O_raw_tuser  = 	I_tuser_r0;   
    assign  O_raw_tvalid = 	I_tvalid_r0;

    assign  O_raw_tdata  = 	raw_data_r0;

    assign  I_raw_tready = 	O_raw_tready;

    always @(posedge I_clk or negedge I_rst_n) begin
        if(!I_rst_n)
            raw_data_r0 <= 0;
        else if(I_raw_tvalid)begin
            raw_data_r0 <= {I_raw_tdata[9:2], I_raw_tdata[19:12], I_raw_tdata[29:22], I_raw_tdata[39:32]};
        end 
    end

    always @(posedge I_clk or negedge I_rst_n) begin
        if(!I_rst_n)begin
            {I_tlast_r0,I_tuser_r0,I_tvalid_r0} <= 0;
        end
        else begin
            I_tlast_r0  <= I_raw_tlast;
            I_tuser_r0  <= I_raw_tuser;
            I_tvalid_r0 <= I_raw_tvalid;
        end
    end

endmodule

