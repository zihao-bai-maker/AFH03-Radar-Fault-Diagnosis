

#include "Vtb_roi_wrap.h"
#include "verilated.h"

#include <cstdio>
#include <cstdint>
#include <cstring>
#include <vector>
#include <string>

static const int H_ACTIVE = 1920;
static const int V_ACTIVE = 1080;
static const int PPB      = 4;                 
static const int BEATS    = H_ACTIVE / PPB;    
static const int SAT_THR  = 250;

struct Roi { int x0, y0, x1, y1; };

static void pix_of(int cid, int x, int y, int &r, int &g, int &b)
{
    switch (cid) {
    case 0: r = 100; g = 100; b = 100; break;                 
    case 1: {                                                  

        r = ((x & 63) < 8 && (y & 63) < 8) ? 255 : 40;
        g = r; b = r; break;
    }
    case 2: r = 200; g = 50; b = 90; break;                    
    case 3: r = (x / 8 + y / 8) & 1 ? 250 : 5;                 
            g = r; b = r; break;
    case 4: r = (x % 256); g = (y % 256); b = ((x + y) % 256); break;  
    case 5: r = 0; g = 0; b = 0; break;                        
    case 6: r = 255; g = 255; b = 255; break;                  
    case 7: r = ((x & 31) < 4) ? 251 : 249;                    
            g = r; b = r; break;
    default: r = g = b = 0; break;
    }
}

struct Gold {
    uint64_t sr = 0, sg = 0, sb = 0, n = 0, sat = 0;
    int      mr = 0, mg = 0, mb = 0;
};

static void golden(int cid, const std::vector<Roi> &rois, std::vector<Gold> &out)
{
    out.assign(rois.size(), Gold());
    for (int y = 0; y < V_ACTIVE; y++) {
        for (int x = 0; x < H_ACTIVE; x++) {
            int r, g, b;
            pix_of(cid, x, y, r, g, b);
            for (size_t i = 0; i < rois.size(); i++) {
                const Roi &w = rois[i];
                if (x >= w.x0 && x < w.x1 && y >= w.y0 && y < w.y1) {
                    Gold &G = out[i];
                    G.sr += (uint64_t)r; G.sg += (uint64_t)g; G.sb += (uint64_t)b;
                    G.n  += 1;
                    if (r > G.mr) G.mr = r;
                    if (g > G.mg) G.mg = g;
                    if (b > G.mb) G.mb = b;
                    if (r > SAT_THR || g > SAT_THR || b > SAT_THR) G.sat++;
                }
            }
        }
    }
}

static int hw_mean(uint64_t sum) { return (int)((sum * 257ULL) >> 16); }

static inline uint64_t bits_at_bytes(const uint8_t *b, int bit, int width)
{
    uint64_t v = 0;
    for (int i = 0; i < width; i++) {
        int k = bit + i;
        uint64_t one = (b[k >> 3] >> (k & 7)) & 1u;
        v |= (one << i);
    }
    return v;
}

template <int N>
static inline uint64_t wide_bits(const VlWide<N> &w, int bit, int width)
{
    uint8_t buf[N * 4];
    for (int i = 0; i < N; i++) {
        uint32_t v = w[i];
        buf[i*4+0] = (uint8_t)(v      );
        buf[i*4+1] = (uint8_t)(v >>  8);
        buf[i*4+2] = (uint8_t)(v >> 16);
        buf[i*4+3] = (uint8_t)(v >> 24);
    }
    return bits_at_bytes(buf, bit, width);
}

static Vtb_roi_wrap *dut;
static uint64_t cyc = 0;

static void tick()
{
    dut->clk = 0; dut->eval();
    dut->clk = 1; dut->eval();
    cyc++;
}

struct Snap {
    std::vector<uint64_t> sr, sg, sb, n, sat;
    std::vector<int> mr, mg, mb, meanr, meang, meanb, max8;
    uint16_t frame_cnt;
    uint16_t line_beats; uint32_t frame_beats; uint16_t line_cnt;
    uint64_t mean_valid_cyc;
    bool ok = false;
};

static Snap run_case(int cid, const std::vector<Roi> &rois, int nframes, int sample_frame)
{
    Snap S;
    const int n = (int)rois.size();
    S.sr.assign(n,0); S.sg.assign(n,0); S.sb.assign(n,0); S.n.assign(n,0); S.sat.assign(n,0);
    S.mr.assign(n,0); S.mg.assign(n,0); S.mb.assign(n,0);
    S.meanr.assign(n,0); S.meang.assign(n,0); S.meanb.assign(n,0); S.max8.assign(n,0);
    S.frame_cnt = 0; S.line_beats = 0; S.frame_beats = 0; S.line_cnt = 0; S.mean_valid_cyc = 0;

    {
        uint8_t buf[64];
        for (int i = 0; i < 64; i++) buf[i] = 0;
        for (int i = 0; i < n; i++) {
            uint64_t geo = 0;
            geo |= (uint64_t)(rois[i].x0 & 0xFFF);
            geo |= (uint64_t)(rois[i].y0 & 0xFFF) << 12;
            geo |= (uint64_t)(rois[i].x1 & 0xFFF) << 24;
            geo |= (uint64_t)(rois[i].y1 & 0xFFF) << 36;
            for (int k = 0; k < 48; k++) {
                int bit = i*48 + k;
                uint8_t v = (geo >> k) & 1ULL;
                if (v) buf[bit >> 3] |=  (uint8_t)(1u << (bit & 7));
            }
        }
        for (int i = 0; i < 24; i++) {
            dut->i_geo[i] = (uint32_t)buf[i*4+0]
                          | ((uint32_t)buf[i*4+1] << 8)
                          | ((uint32_t)buf[i*4+2] << 16)
                          | ((uint32_t)buf[i*4+3] << 24);
        }
    }

    dut->i_de = 0; dut->i_sof = 0; dut->i_eol = 0;
    dut->i_px[0] = dut->i_px[1] = dut->i_px[2] = dut->i_px[3] = 0;

    for (int f = 0; f < nframes; f++) {

        for (int y = 0; y < V_ACTIVE; y++) {
            for (int bt = 0; bt < BEATS; bt++) {
                bool sof = (y == 0 && bt == 0);
                bool eol = (bt == BEATS - 1);

                int r0,g0,b0, r1,g1,b1, r2,g2,b2, r3,g3,b3;
                pix_of(cid, bt*4+0, y, r0,g0,b0);
                pix_of(cid, bt*4+1, y, r1,g1,b1);
                pix_of(cid, bt*4+2, y, r2,g2,b2);
                pix_of(cid, bt*4+3, y, r3,g3,b3);

                dut->i_px[0] = (uint32_t)((r0<<16)|(g0<<8)|b0);
                dut->i_px[1] = (uint32_t)((r1<<16)|(g1<<8)|b1);
                dut->i_px[2] = (uint32_t)((r2<<16)|(g2<<8)|b2);
                dut->i_px[3] = (uint32_t)((r3<<16)|(g3<<8)|b3);
                dut->i_de = 1; dut->i_sof = sof ? 1 : 0; dut->i_eol = eol ? 1 : 0;

                bool sample = (f == sample_frame - 1) && (y == V_ACTIVE-1) && eol;
                tick();

                if (sample) {

                    
                    tick();
                    S.frame_cnt = dut->o_frame_cnt;
                    S.line_beats = dut->o_line_beats;
                    S.frame_beats = dut->o_frame_beats;
                    S.line_cnt   = dut->o_line_cnt;
                    for (int i = 0; i < n; i++) {
                        S.sr[i]  = dut->a_rsum[i];
                        S.sg[i]  = dut->a_gsum[i];
                        S.sb[i]  = dut->a_bsum[i];
                        S.n[i]   = dut->a_cnt[i];
                        S.sat[i] = dut->a_satcnt[i];
                        uint32_t mx = dut->a_maxrgb[i];
                        S.mr[i] = (mx >> 16) & 0xFF;
                        S.mg[i] = (mx >>  8) & 0xFF;
                        S.mb[i] = (mx      ) & 0xFF;
                        S.max8[i] = (int)dut->a_max8[i];
                    }

                    int wait = 32*3*n + 128;
                    bool got = false;
                    for (int w = 0; w < wait; w++) {
                        if (dut->o_mean_valid) { got = true; break; }
                        tick();
                    }
                    if (got) {
                        S.mean_valid_cyc = cyc;
                        for (int i = 0; i < n; i++) {
                            uint32_t mv = dut->a_mean24[i];
                            S.meanr[i] = (mv >> 16) & 0xFF;
                            S.meang[i] = (mv >>  8) & 0xFF;
                            S.meanb[i] = (mv      ) & 0xFF;
                        }
                        S.ok = true;
                    }

                    dut->i_de = 0; dut->i_sof = 0; dut->i_eol = 0;
                    for (int z = 0; z < 10; z++) tick();
                }
            }
        }

        dut->i_de = 0; dut->i_sof = 0; dut->i_eol = 0;
        for (int z = 0; z < 200; z++) tick();
    }
    return S;
}

int main(int argc, char **argv)
{
    Verilated::commandArgs(argc, argv);
    dut = new Vtb_roi_wrap;

    dut->rst_n = 0;
    dut->clk = 0;
    for (int i = 0; i < 20; i++) tick();
    dut->rst_n = 1;
    for (int i = 0; i < 5; i++) tick();

    std::vector<Roi> rois16;
    for (int r = 0; r < 4; r++)
        for (int c = 0; c < 4; c++)
            rois16.push_back(Roi{160 + c*440, 140 + r*440, 160 + c*440 + 64, 140 + r*440 + 64});

    std::vector<Roi> rois8;
    for (int r = 0; r < 2; r++)
        for (int c = 0; c < 4; c++)
            rois8.push_back(Roi{160 + c*440, 140 + r*440, 160 + c*440 + 64, 140 + r*440 + 64});

    struct Case { int cid; const char *name; };
    Case cases[] = {
        {0, "uniform-gray-100"},
        {1, "hot-8x8-blocks-sat"},
        {2, "asym-rgb-200/50/90"},
        {3, "checker-8x8-250/5"},
        {4, "gradient-mod256"},
        {5, "all-black"},
        {6, "all-white"},
        {7, "sat-boundary-251/249"},
    };
    const int NC = (int)(sizeof(cases)/sizeof(cases[0]));

    int pass = 0, fail = 0;
    printf("=== ROI stat simulation (Verilator) : %dx%d, PPB=%d, SAT_THR=%d ===\n",
           H_ACTIVE, V_ACTIVE, PPB, SAT_THR);

    for (int ci = 0; ci < NC; ci++) {
        std::vector<Gold> G;
        golden(cases[ci].cid, rois16, G);
        Snap S = run_case(cases[ci].cid, rois16, 3, 3);

        if (!S.ok) { printf("[FAIL] %-24s : 均值引擎没给出 o_mean_valid\n", cases[ci].name); fail++; continue; }

        int field_fail = 0;
        int mean_diff_max = 0;
        int first_bad = -1;
        for (size_t i = 0; i < rois16.size(); i++) {
            bool bad = false;
            if (S.sr[i] != G[i].sr) bad = true;
            if (S.sg[i] != G[i].sg) bad = true;
            if (S.sb[i] != G[i].sb) bad = true;
            if (S.n[i]  != G[i].n ) bad = true;
            if (S.sat[i]!= G[i].sat) bad = true;
            if (S.mr[i] != G[i].mr) bad = true;
            if (S.mg[i] != G[i].mg) bad = true;
            if (S.mb[i] != G[i].mb) bad = true;
            if (bad && first_bad < 0) first_bad = (int)i;
            if (bad) field_fail++;

            int em = hw_mean(G[i].sr), eg = hw_mean(G[i].sg), eb = hw_mean(G[i].sb);
            if (S.meanr[i] != em || S.meang[i] != eg || S.meanb[i] != eb) {
                if (first_bad < 0) first_bad = (int)i;
                field_fail++;
            }

            if (G[i].n) {
                int d;
                d = S.meanr[i] - (int)(G[i].sr / G[i].n); if (d < 0) d = -d; if (d > mean_diff_max) mean_diff_max = d;
                d = S.meang[i] - (int)(G[i].sg / G[i].n); if (d < 0) d = -d; if (d > mean_diff_max) mean_diff_max = d;
                d = S.meanb[i] - (int)(G[i].sb / G[i].n); if (d < 0) d = -d; if (d > mean_diff_max) mean_diff_max = d;
            }
        }

        bool layout_ok = (S.frame_cnt == 3) && (S.line_beats == BEATS)
                      && (S.frame_beats == (uint32_t)(BEATS*V_ACTIVE)) && (S.line_cnt == V_ACTIVE);

        if (field_fail == 0 && layout_ok && mean_diff_max <= 1) {
            pass++;
            printf("[PASS] %-24s : 16 ROI x (sum,cnt,max,sat,mean) 全等; 帧几何 line_beats=%u frame_beats=%u line_cnt=%u; "
                   "mean 与 sum/cnt 最大偏差=%d\n",
                   cases[ci].name, S.line_beats, S.frame_beats, S.line_cnt, mean_diff_max);
        } else {
            fail++;
            printf("[FAIL] %-24s : 字段不符 %d 个, 首个 ROI=%d, 帧几何(line_beats=%u/%d frame_beats=%u/%u line_cnt=%u/%d) mean偏差max=%d\n",
                   cases[ci].name, field_fail, first_bad,
                   S.line_beats, BEATS, S.frame_beats, (unsigned)(BEATS*V_ACTIVE), S.line_cnt, V_ACTIVE, mean_diff_max);
            if (first_bad >= 0) {
                size_t i = (size_t)first_bad;
                printf("        ROI%zu exp sum=(%llu,%llu,%llu) cnt=%llu max=(%d,%d,%d) sat=%llu mean=(%d,%d,%d)\n",
                       i, (unsigned long long)G[i].sr, (unsigned long long)G[i].sg, (unsigned long long)G[i].sb,
                       (unsigned long long)G[i].n, G[i].mr, G[i].mg, G[i].mb, (unsigned long long)G[i].sat,
                       hw_mean(G[i].sr), hw_mean(G[i].sg), hw_mean(G[i].sb));
                printf("        ROI%zu got sum=(%llu,%llu,%llu) cnt=%llu max=(%d,%d,%d) sat=%llu mean=(%d,%d,%d)\n",
                       i, (unsigned long long)S.sr[i], (unsigned long long)S.sg[i], (unsigned long long)S.sb[i],
                       (unsigned long long)S.n[i], S.mr[i], S.mg[i], S.mb[i], (unsigned long long)S.sat[i],
                       S.meanr[i], S.meang[i], S.meanb[i]);
            }
        }
    }

    printf("\n=== 小计：%d/%d 通过 ===\n", pass, NC);
    delete dut;
    return (fail == 0) ? 0 : 1;
}
