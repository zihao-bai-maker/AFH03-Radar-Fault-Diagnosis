

#include "Vcam_stat_top.h"
#include "verilated.h"

#include <cstdio>
#include <cstdint>
#include <cstring>
#include <vector>

static const int H_ACTIVE = 1920;
static const int V_ACTIVE = 1080;
static const int PPB      = 4;
static const int BEATS    = H_ACTIVE / PPB;      
static const int WORDS_PL = H_ACTIVE / 2;        
static const int SAT_THR  = 250;

static int NROI = 16;
static int XBLK_WORDS = 3 + 3*16 + 3;
static int TOT_WORDS  = 15 + XBLK_WORDS;

struct Roi { int x0, y0, x1, y1; };

static void pix_of(int cid, int x, int y, int &r, int &g, int &b)
{
    switch (cid) {
    case 0: r = 100; g = 100; b = 100; break;
    case 1: r = ((x & 63) < 8 && (y & 63) < 8) ? 255 : 40; g = r; b = r; break;
    case 2: r = 200; g = 50; b = 90; break;
    case 3: r = (x / 8 + y / 8) & 1 ? 250 : 5; g = r; b = r; break;
    case 4: r = (x % 256); g = (y % 256); b = ((x + y) % 256); break;
    case 5: r = 0; g = 0; b = 0; break;
    case 6: r = 255; g = 255; b = 255; break;
    default: r = ((x & 31) < 4) ? 251 : 249; g = r; b = r; break;
    }
}

struct Gold { uint64_t sr=0,sg=0,sb=0,n=0,sat=0; int mr=0,mg=0,mb=0; };

static void golden(int cid, const std::vector<Roi> &rois, std::vector<Gold> &out)
{
    out.assign(rois.size(), Gold());
    for (int y = 0; y < V_ACTIVE; y++)
        for (int x = 0; x < H_ACTIVE; x++) {
            int r,g,b; pix_of(cid, x, y, r, g, b);
            for (size_t i = 0; i < rois.size(); i++) {
                const Roi &w = rois[i];
                if (x >= w.x0 && x < w.x1 && y >= w.y0 && y < w.y1) {
                    Gold &G = out[i];
                    G.sr += (uint64_t)r; G.sg += (uint64_t)g; G.sb += (uint64_t)b; G.n++;
                    if (r > G.mr) G.mr = r;
                    if (g > G.mg) G.mg = g;
                    if (b > G.mb) G.mb = b;
                    if (r > SAT_THR || g > SAT_THR || b > SAT_THR) G.sat++;
                }
            }
        }
}

static int hw_mean(uint64_t s) { return (int)((s * 257ULL) >> 16); }

static Vcam_stat_top *dut;

static void tick_pix()
{
    dut->I_pix_clk = 0; dut->eval();
    dut->I_pix_clk = 1; dut->eval();
}
static void tick_hs()
{
    dut->I_hs_clk = 0; dut->eval();
    dut->I_hs_clk = 1; dut->eval();
}

int main(int argc, char **argv)
{
    Verilated::commandArgs(argc, argv);
    if (argc > 1) NROI = atoi(argv[1]);
    XBLK_WORDS = 3 + 3*NROI + 3;
    TOT_WORDS  = 15 + XBLK_WORDS;

    dut = new Vcam_stat_top;

    dut->I_pix_clk = 0;
    dut->I_hs_clk  = 0;
    dut->I_pix_rst_n = 0;
    dut->I_hs_rst_n  = 0;
    dut->I_isp_de = 0; dut->I_isp_sof = 0; dut->I_isp_eol = 0;
    for (int i = 0; i < 4; i++) { dut->I_isp_px[i] = 0; }
    dut->I_pack_tvalid = 0; dut->I_pack_tuser_sof = 0; dut->I_pack_tlast = 0;
    dut->I_pack_tdata = 0;
    dut->O_tx_tready = 1;
    dut->I_cfg_we = 0; dut->I_cfg_addr = 0; dut->I_cfg_wdata = 0; dut->I_cfg_re = 0;

    for (int i = 0; i < 10; i++) { tick_pix(); tick_hs(); }
    dut->I_pix_rst_n = 1;
    dut->I_hs_rst_n  = 1;
    for (int i = 0; i < 4; i++) { tick_pix(); tick_hs(); }

    std::vector<Roi> rois;
    int rows = (NROI >= 16) ? 4 : 2;
    for (int r = 0; r < rows; r++)
        for (int c = 0; c < 4; c++)
            rois.push_back(Roi{160 + c*440, 140 + r*440, 160 + c*440 + 64, 140 + r*440 + 64});

    const int CID = 1;                    
    std::vector<Gold> G;
    golden(CID, rois, G);

    const int TARGET_FRAME = 3;           
    std::vector<uint32_t> cap;            
    bool captured = false;
    uint16_t cap_frame_cnt = 0;

    int hs_per_pix = 2;                   
    int pixel_line = 0;
    uint64_t pix_total = 0;

    for (int f = 1; f <= TARGET_FRAME; f++) {
        for (int y = 0; y < V_ACTIVE; y++) {
            for (int bt = 0; bt < BEATS; bt++) {
                int r0,g0,b0,r1,g1,b1,r2,g2,b2,r3,g3,b3;
                pix_of(CID, bt*4+0, y, r0,g0,b0);
                pix_of(CID, bt*4+1, y, r1,g1,b1);
                pix_of(CID, bt*4+2, y, r2,g2,b2);
                pix_of(CID, bt*4+3, y, r3,g3,b3);
                dut->I_isp_px[0] = (uint32_t)((r0<<16)|(g0<<8)|b0);
                dut->I_isp_px[1] = (uint32_t)((r1<<16)|(g1<<8)|b1);
                dut->I_isp_px[2] = (uint32_t)((r2<<16)|(g2<<8)|b2);
                dut->I_isp_px[3] = (uint32_t)((r3<<16)|(g3<<8)|b3);
                dut->I_isp_de  = 1;
                dut->I_isp_sof = (y == 0 && bt == 0);
                dut->I_isp_eol = (bt == BEATS-1);
                tick_pix();
                pix_total++;

                if (bt == BEATS-1) {
                    for (int w = 0; w < WORDS_PL; w++) {
                        dut->I_pack_tvalid    = 1;
                        dut->I_pack_tdata     = 0x11223344 + (uint32_t)w;
                        dut->I_pack_tuser_sof = (w == 0);
                        dut->I_pack_tlast     = (w == WORDS_PL-1);
                        tick_hs();

                        if (f == TARGET_FRAME && pixel_line == 0 && w < (uint32_t)TOT_WORDS) {
                            if (dut->O_tx_tvalid && dut->I_pack_tuser_sof) {
                                cap.clear();
                                cap_frame_cnt = dut->O_frame_cnt;
                            }
                            if (!cap.empty() && cap.size() < (size_t)TOT_WORDS) {
                                cap.push_back(dut->O_tx_tdata);
                            }
                        }
                    }
                    dut->I_pack_tvalid = 0; dut->I_pack_tuser_sof = 0; dut->I_pack_tlast = 0;
                    pixel_line++;
                }
            }
        }
    }
    for (int i = 0; i < 20; i++) { tick_pix(); tick_hs(); }

    printf("=== cam_stat_top 元数据块校验 : N_ROI=%d, XBLK_WORDS=%d, TOT_WORDS=%d, 抓帧=%d ===\n",
           NROI, XBLK_WORDS, TOT_WORDS, TARGET_FRAME);

    if (cap.size() < (size_t)TOT_WORDS) {
        printf("[FAIL] 只抓到 %zu 个注入字（期望 %d）——注入窗口没覆盖整块\n", cap.size(), TOT_WORDS);
        delete dut; return 1;
    }

    int fails = 0;

    printf("-- 老区段 W0..W14（必须逐位不变）--\n");
    printf("   W0  magic      = 0x%08X %s\n", cap[0], cap[0]==0xA5C35A00?"OK":"**FAIL**");
    if (cap[0] != 0xA5C35A00) fails++;
    printf("   W1  frame_cnt  = %u (O_frame_cnt=%u)\n", cap[1], cap_frame_cnt);
    if (cap[1] != cap_frame_cnt) { printf("   **FAIL** frame_cnt 不一致\n"); fails++; }
    printf("   W2  status     = 0x%08X  (n_lit=%u any_lit=%u ready=%u fcnt8=%u)\n",
           cap[2], (cap[2]>>8)&0xFF, (cap[2]>>17)&1, (cap[2]>>16)&1, cap[2]&0xFF);
    if (((cap[2]>>16)&1) != 1) { printf("   **FAIL** ready 位不是 1\n"); fails++; }
    int popcnt_lit = 0;
    for (int i = 3; i <= 10; i++) popcnt_lit += (cap[i] & 1);
    printf("   W3..W10 lit     : popcount=%d, W2.n_lit=%u %s\n",
           popcnt_lit, (cap[2]>>8)&0xFF, (popcnt_lit == (int)((cap[2]>>8)&0xFF))?"OK":"**FAIL**");
    if (popcnt_lit != (int)((cap[2]>>8)&0xFF)) fails++;
    printf("   W11 line_beats  = %u (期望 480) %s\n", cap[11], cap[11]==480?"OK":"**FAIL**");
    if (cap[11] != 480) fails++;
    printf("   W12 frame_beats = %u (期望 %d) %s\n", cap[12], BEATS*V_ACTIVE,
           cap[12]==(uint32_t)(BEATS*V_ACTIVE)?"OK":"**FAIL**");
    if (cap[12] != (uint32_t)(BEATS*V_ACTIVE)) fails++;
    printf("   W13 marker      = 0x%08X %s\n", cap[13], cap[13]==0x5A5AA5A5?"OK":"**FAIL**");
    if (cap[13] != 0x5A5AA5A5) fails++;
    printf("   W14 id/ver      = 0x%08X %s\n", cap[14], cap[14]==0xA5C30001?"OK":"**FAIL**");
    if (cap[14] != 0xA5C30001) fails++;

    printf("-- 扩展块头 --\n");
    printf("   W15 magic      = 0x%08X %s\n", cap[15], cap[15]==0xA5C3E100?"OK":"**FAIL**");
    if (cap[15] != 0xA5C3E100) fails++;
    uint32_t w16 = cap[16];
    int hdr_roi   = (w16 >> 16) & 0xFFFF;
    int hdr_wpr   = (w16 >>  8) & 0xFF;
    int hdr_words =  w16        & 0xFF;
    printf("   W16 {roi_n=%d, words_per_roi=%d, xblk_words=%d} %s\n", hdr_roi, hdr_wpr, hdr_words,
           (hdr_roi==NROI && hdr_wpr==3 && hdr_words==(XBLK_WORDS & 0xFF)) ? "OK":"**FAIL**");
    if (!(hdr_roi==NROI && hdr_wpr==3 && hdr_words==(XBLK_WORDS & 0xFF))) fails++;
    printf("   W17 {sat_thr=%u, mean_w=%u} %s\n", (cap[17]>>16)&0xFFFF, (cap[17]>>8)&0xFF,
           (((cap[17]>>16)&0xFFFF)==(uint32_t)SAT_THR && ((cap[17]>>8)&0xFF)==8) ? "OK":"**FAIL**");
    if (!(((cap[17]>>16)&0xFFFF)==(uint32_t)SAT_THR && ((cap[17]>>8)&0xFF)==8)) fails++;

    printf("-- 每 ROI MEAN/MAX/SAT (base=W18) --\n");
    int field_fail = 0, mean_diff_max = 0;
    for (int i = 0; i < NROI && i < (int)rois.size(); i++) {
        uint32_t wm = cap[18 + 3*i + 0];
        uint32_t wx = cap[18 + 3*i + 1];
        uint32_t ws = cap[18 + 3*i + 2];
        int mr = (wm>>16)&0xFF, mg = (wm>>8)&0xFF, mb = wm&0xFF;
        int xr = (wx>>16)&0xFF, xg = (wx>>8)&0xFF, xb = wx&0xFF;
        uint32_t sc = ws & 0xFFFFFF;
        if (wm>>24) { printf("   ROI%d MEAN 高位非0 (0x%08X)\n", i, wm); field_fail++; }
        if (wx>>24) { printf("   ROI%d MAX  高位非0 (0x%08X)\n", i, wx); field_fail++; }
        if (ws>>24) { printf("   ROI%d SAT  高位非0 (0x%08X)\n", i, ws); field_fail++; }
        if (mr!=hw_mean(G[i].sr) || mg!=hw_mean(G[i].sg) || mb!=hw_mean(G[i].sb)) {
            printf("   **ROI%d MEAN 不符 exp=(%d,%d,%d) got=(%d,%d,%d)\n", i,
                   hw_mean(G[i].sr), hw_mean(G[i].sg), hw_mean(G[i].sb), mr, mg, mb);
            field_fail++;
        }
        if (xr!=G[i].mr || xg!=G[i].mg || xb!=G[i].mb) {
            printf("   **ROI%d MAX 不符 exp=(%d,%d,%d) got=(%d,%d,%d)\n", i,
                   G[i].mr, G[i].mg, G[i].mb, xr, xg, xb);
            field_fail++;
        }
        if (sc != G[i].sat) {
            printf("   **ROI%d SAT 不符 exp=%llu got=%u\n", i, (unsigned long long)G[i].sat, sc);
            field_fail++;
        }
        if (G[i].n) {
            int d = mr - (int)(G[i].sr/G[i].n); if (d<0) d=-d; if (d>mean_diff_max) mean_diff_max=d;
            d = mg - (int)(G[i].sg/G[i].n); if (d<0) d=-d; if (d>mean_diff_max) mean_diff_max=d;
            d = mb - (int)(G[i].sb/G[i].n); if (d<0) d=-d; if (d>mean_diff_max) mean_diff_max=d;
        }
        if (i < 3 || i == NROI-1)
            printf("   ROI%-2d MEAN=(%3d,%3d,%3d) MAX=(%3d,%3d,%3d) SAT=%-6u (cnt=%llu)\n",
                   i, mr, mg, mb, xr, xg, xb, sc, (unsigned long long)G[i].n);
    }
    if (field_fail) { printf("   **每 ROI 字段不符 %d 处\n", field_fail); fails += field_fail; }
    else printf("   全部 %d 个 ROI 的 MEAN/MAX/SAT 与黄金模型一致 OK\n", NROI);
    if (mean_diff_max > 1) { printf("   **MEAN 与 sum/cnt 偏差 %d > 1\n", mean_diff_max); fails++; }
    else printf("   MEAN 与 sum/cnt 最大偏差 = %d (<=1 OK)\n", mean_diff_max);

    int iend = 18 + 3*NROI;
    printf("-- 尾字 --\n");
    printf("   W%-3d END      = 0x%08X %s\n", iend, cap[iend], cap[iend]==0xA5C3E1FF?"OK":"**FAIL**");
    if (cap[iend] != 0xA5C3E1FF) fails++;
    printf("   W%-3d VER      = 0x%08X (ver=%u gen=%u) %s\n", iend+1, cap[iend+1],
           cap[iend+1]&0xFF, (cap[iend+1]>>8)&0xFF, (cap[iend+1]&0xFF)==1?"OK":"**FAIL**");
    if ((cap[iend+1]&0xFF) != 1) fails++;
    uint32_t x = 0;
    for (int i = 15; i <= iend+1; i++) x ^= cap[i];
    printf("   W%-3d XOR      = 0x%08X, 本地重算 = 0x%08X %s\n", iend+2, cap[iend+2], x,
           cap[iend+2]==x?"OK":"**FAIL**");
    if (cap[iend+2] != x) fails++;
    printf("   （注入字数 %d，注入块结束后的字应回到占位数据 0x11223344+w）\n", TOT_WORDS);

    printf("\n=== 结论: %s (N_ROI=%d) ===\n", fails==0 ? "全部通过" : "有失败", NROI);
    delete dut;
    return fails == 0 ? 0 : 1;
}
