

`timescale 1ns/1ps

module csi2_pack_yuv422_stream #(
    parameter integer H_ACTIVE = 1920,
    parameter integer V_ACTIVE = 1080
)(
    input  wire        src_clk,
    input  wire        src_rst_n,
    input  wire        s_tvalid,
    output wire        s_tready,
    input  wire [31:0] s_tdata,
    input  wire        s_tuser_sof,
    input  wire        s_tlast,

    input  wire        dst_clk,
    input  wire        dst_rst_n,
    input  wire        enable,
    output wire        m_tvalid,
    input  wire        m_tready,
    output wire [31:0] m_tdata,
    output wire        m_tuser_sof,
    output wire        m_tlast
);

    localparam integer WORDS_PAYLOAD = H_ACTIVE / 2;
    wire _unused_stlast = s_tlast;

    wire        a_full, a_empty;
    wire [32:0] a_dout;
    wire        a_rst_async = ~(src_rst_n & dst_rst_n);

    reg         src_armed;
    always @(posedge src_clk or negedge src_rst_n) begin
        if (!src_rst_n)                  src_armed <= 1'b0;
        else if (s_tvalid & s_tuser_sof) src_armed <= 1'b1;
    end
    wire        a_wr_en = s_tvalid & ~a_full & (src_armed | s_tuser_sof);
    assign      s_tready = ~a_full;
    reg         a_rd_en;

    wire [10:0] b_wr_data_count;    
    wire        b_near_full = (b_wr_data_count > 11'd1900);
    wire        a_can_read  = enable & ~a_empty & ~b_near_full;

    always @(posedge dst_clk or negedge dst_rst_n) begin
        if (!dst_rst_n) a_rd_en <= 1'b0;
        else            a_rd_en <= a_can_read;
    end

    fifo_32b_async_2 #(
        .DATA_WIDTH(33),
        .ADDR_WIDTH(11)
    ) u_async_fifo (
        .rst          (a_rst_async),
        .wr_clk       (src_clk    ),
        .rd_clk       (dst_clk    ),
        .din          ({s_tuser_sof, s_tdata}),
        .wr_en        (a_wr_en    ),
        .rd_en        (a_rd_en    ),
        .dout         (a_dout     ),
        .full         (a_full     ),
        .empty        (a_empty    ),
        .rd_data_count(           ),
        .wr_data_count(           ),
        .wr_rst_busy  (           ),
        .rd_rst_busy  (           )
    );

    reg        a_rd_en_d1;      
    always @(posedge dst_clk or negedge dst_rst_n) begin
        if (!dst_rst_n) a_rd_en_d1 <= 1'b0;
        else            a_rd_en_d1 <= a_rd_en;
    end

    reg        pipe_in_valid;
    reg [31:0] pipe_in_rgb;
    reg        pipe_in_sof;

    always @(posedge dst_clk or negedge dst_rst_n) begin
        if (!dst_rst_n) begin
            pipe_in_valid <= 1'b0;
            pipe_in_rgb   <= 32'd0;
            pipe_in_sof   <= 1'b0;
        end else begin
            pipe_in_valid <= a_rd_en_d1;                            
            pipe_in_rgb   <= a_dout[31:0];
            pipe_in_sof   <= a_rd_en_d1 ? a_dout[32] : 1'b0;
        end
    end

    reg        yuv_valid_r;
    reg [31:0] yuv_data_r;
    reg        yuv_sof_r;
    always @(posedge dst_clk or negedge dst_rst_n) begin
        if (!dst_rst_n) begin
            yuv_valid_r <= 1'b0;
            yuv_data_r  <= 32'd0;
            yuv_sof_r   <= 1'b0;
        end else begin
            yuv_valid_r <= pipe_in_valid;
            yuv_data_r  <= pipe_in_rgb;     
            yuv_sof_r   <= pipe_in_sof & pipe_in_valid;
        end
    end
    wire        yuv_valid = yuv_valid_r;
    wire [31:0] yuv_data  = yuv_data_r;
    wire        _unused_yuv_sof_r = yuv_sof_r;

    reg        frame_start_pending;
    reg [15:0] word_col;

    localparam integer FRAME_WORDS = V_ACTIVE * WORDS_PAYLOAD;
    reg        frame_window_open;
    reg [31:0] frame_word_cnt;

    wire yuv_valid_sig = yuv_valid;  
    wire yuv_sof  = yuv_valid_sig & frame_start_pending;
    wire yuv_last = yuv_valid_sig & (word_col == WORDS_PAYLOAD-1);

    always @(posedge dst_clk or negedge dst_rst_n) begin
        if (!dst_rst_n) begin
            frame_start_pending <= 1'b0;
            word_col            <= 16'd0;
        end else begin
            if (pipe_in_sof & pipe_in_valid)
                frame_start_pending <= 1'b1;
            if (yuv_valid) begin
                if (frame_start_pending) frame_start_pending <= 1'b0;
            end

            
            if (yuv_sof) begin
                word_col <= 16'd1;   
            end else if (frame_window_open & yuv_valid) begin
                word_col <= (word_col == WORDS_PAYLOAD-1) ? 16'd0 : (word_col + 1'b1);
            end
        end
    end

    always @(posedge dst_clk or negedge dst_rst_n) begin
        if (!dst_rst_n) begin
            frame_window_open <= 1'b0;
            frame_word_cnt    <= 32'd0;
        end else if (yuv_sof) begin

            frame_window_open <= 1'b1;
            frame_word_cnt    <= 32'd1;
        end else if (frame_window_open & yuv_valid) begin
            if (frame_word_cnt == FRAME_WORDS[31:0]-1) begin
                frame_window_open <= 1'b0;
                frame_word_cnt    <= 32'd0;
            end else begin
                frame_word_cnt    <= frame_word_cnt + 32'd1;
            end
        end
    end

    wire yuv_admit = yuv_valid & (frame_window_open | yuv_sof);

    wire        b_full, b_empty;
    wire [33:0] b_dout;
    wire [10:0] b_rd_data_count;    

    wire        b_wr_en = yuv_admit & ~b_full;
    reg         line_priming;        

                                     

                                     

    reg         line_active;
    reg         line_drain_done;     
    reg [15:0]  drain_cnt;           
    wire        line_ready = (b_rd_data_count >= WORDS_PAYLOAD[10:0]);

    
    wire        active_pop = m_tready & line_active & ~line_drain_done &
                            (drain_cnt != WORDS_PAYLOAD[15:0]);
    wire        b_rd_en    = ~b_empty & (line_priming | active_pop);

    always @(posedge dst_clk or negedge dst_rst_n) begin
        if (!dst_rst_n) begin
            line_priming    <= 1'b0;
            line_active     <= 1'b0;
            line_drain_done <= 1'b0;
            drain_cnt       <= 16'd0;
        end else if (!line_active && !line_priming) begin

            if (line_ready) begin
                line_priming    <= 1'b1;
                line_drain_done <= 1'b0;
                drain_cnt       <= 16'd0;
            end
        end else if (line_priming) begin

            line_priming <= 1'b0;
            line_active  <= 1'b1;
            drain_cnt    <= 16'd1;   
        end else begin
            if (line_drain_done) begin
                line_active     <= 1'b0;
                line_drain_done <= 1'b0;
                drain_cnt       <= 16'd0;
            end else if (m_tready) begin

                if (drain_cnt == WORDS_PAYLOAD[15:0])
                    line_drain_done <= 1'b1;   
                else
                    drain_cnt <= drain_cnt + 16'd1;
            end
        end
    end

    fifo_32b_async_2 #(
        .DATA_WIDTH(34),
        .ADDR_WIDTH(11)     
    ) u_out_fifo (
        .rst          (~dst_rst_n),
        .wr_clk       (dst_clk   ),
        .rd_clk       (dst_clk   ),
        .din          ({yuv_sof, yuv_last, yuv_data}),
        .wr_en        (b_wr_en   ),
        .rd_en        (b_rd_en   ),
        .dout         (b_dout    ),
        .full         (b_full    ),
        .empty        (b_empty   ),
        .rd_data_count(b_rd_data_count),
        .wr_data_count(b_wr_data_count),
        .wr_rst_busy  (          ),
        .rd_rst_busy  (          )
    );

    

    assign m_tvalid    = line_active;
    assign m_tdata     = b_dout[31:0];
    assign m_tlast     = b_dout[32];
    assign m_tuser_sof = b_dout[33];

endmodule
