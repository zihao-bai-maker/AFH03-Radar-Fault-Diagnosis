

`timescale 1ns / 1ps

module roi_mean_engine #(
    parameter integer N_ROI  = 16,
    parameter integer SUM_W  = 32,
    parameter integer MW     = 44,     
    parameter integer QW     = 40      
)(
    input  wire                     I_clk,
    input  wire                     I_rst_n,

    input  wire                     I_frame_end,
    input  wire [N_ROI*SUM_W-1:0]   I_rsum,
    input  wire [N_ROI*SUM_W-1:0]   I_gsum,
    input  wire [N_ROI*SUM_W-1:0]   I_bsum,

    output reg  [N_ROI*24-1:0]      O_mean,
    output reg                      O_mean_valid   
);

    localparam integer NJOB = 3 * N_ROI;

    localparam [1:0] IDLE = 2'd0, RUN = 2'd1, FLUSH = 2'd2;

    localparam [31:0] NJOB32 = 3 * N_ROI;
    localparam [31:0] SUMW32 = SUM_W;
    localparam [31:0] CYC_L  = SUM_W - 1;
    localparam [31:0] JOB_L  = 3 * N_ROI - 1;

    reg [1:0]      st;
    reg [15:0]     cyc;              
    reg [15:0]     job;              
    reg [1:0]      ch;               
    reg [QW-1:0]   q;                

    reg [MW-QW:0]  r;
    reg [SUM_W-1:0] cur_sum;         
    reg [MW-1:0]   num;              

    

    
    integer t;
    reg [SUM_W-1:0] sum_sel;
    wire [31:0] JOB_C0 = 32'd0, JOB_C1 = 32'd1, JOB_C2 = 32'd2;
    wire [31:0] job32 = {16'd0, job};
    always @(*) begin
        sum_sel = {SUM_W{1'b0}};
        for (t = 0; t < N_ROI; t = t + 1) begin
            if (job32 == (3*t + JOB_C0)) sum_sel = I_rsum[t*SUM_W +: SUM_W];
            if (job32 == (3*t + JOB_C1)) sum_sel = I_gsum[t*SUM_W +: SUM_W];
            if (job32 == (3*t + JOB_C2)) sum_sel = I_bsum[t*SUM_W +: SUM_W];
        end
    end

    

    
    wire [SUM_W+8:0] prod  = {1'b0, cur_sum} * 9'd257;      
    wire [MW-1:0]    num_c = prod[MW-QW-1:0] << QW;         

    wire [MW-1:0]    r_pad   = {{(MW-(MW-QW+1)){1'b0}}, r};
    wire [MW-1:0]    r_shift = r_pad << 1;
    wire             ge      = (r_shift >= num);
    wire [MW-QW:0]   r_sub   = r_shift[MW-QW:0] - num[MW-QW:0];
    wire [MW-QW:0]   r_next  = ge ? r_sub : r_shift[MW-QW:0];

    wire last_cyc = ({16'd0, cyc} == CYC_L);
    wire last_job = (job32 == JOB_L);

    

    reg [N_ROI*24-1:0] mean_acc;
    wire [15:0] q16 = q[QW-1:16];
    wire [7:0]  q8  = (q16 > 16'd255) ? 8'hFF : q16[7:0];

    integer u;
    reg [15:0] done_roi;
    always @(*) begin
        done_roi = 16'd0;
        for (u = 1; u <= N_ROI; u = u + 1)
            if (job32 == (3*u - 1)) done_roi = u[15:0];
    end

    always @(posedge I_clk or negedge I_rst_n) begin
        if (!I_rst_n) begin
            st           <= IDLE;
            cyc          <= 16'd0;
            job          <= 16'd0;
            ch           <= 2'd0;
            q            <= {QW{1'b0}};
            r            <= {(MW-QW+1){1'b0}};
            cur_sum      <= {SUM_W{1'b0}};
            num          <= {MW{1'b0}};
            mean_acc     <= {N_ROI*24{1'b0}};
            O_mean       <= {N_ROI*24{1'b0}};
            O_mean_valid <= 1'b0;
        end else begin
            O_mean_valid <= 1'b0;

            case (st)

            IDLE: begin
                if (I_frame_end) begin
                    job     <= 16'd0;
                    ch      <= 2'd0;
                    cyc     <= 16'd0;
                    q       <= {QW{1'b0}};
                    r       <= {(MW-QW+1){1'b0}};
                    cur_sum <= sum_sel;      
                    num     <= num_c;        
                    st      <= RUN;
                end
            end

            RUN: begin
                q <= {q[QW-2:0], ge};
                r <= r_next;

                if (last_cyc) begin

                    if (done_roi != 16'd0) begin
                        if      (ch == 2'd0)   
                            mean_acc[(done_roi-1)*24 + 16 +: 8] <= q8;
                        else if (ch == 2'd1)   
                            mean_acc[(done_roi-1)*24 +  8 +: 8] <= q8;
                        else                   
                            mean_acc[(done_roi-1)*24 +  0 +: 8] <= q8;
                    end

                    if (last_job) begin
                        st <= FLUSH;
                    end else begin
                        job     <= job + 16'd1;
                        cyc     <= 16'd0;
                        q       <= {QW{1'b0}};
                        r       <= {(MW-QW+1){1'b0}};
                        ch      <= (ch == 2'd2) ? 2'd0 : (ch + 2'd1);
                        cur_sum <= sum_sel;      
                        num     <= num_c;        
                    end
                end else begin
                    cyc <= cyc + 16'd1;
                end
            end

            FLUSH: begin
                O_mean       <= mean_acc;
                O_mean_valid <= 1'b1;
                st           <= IDLE;
            end
            default: st <= IDLE;
            endcase
        end
    end

endmodule
