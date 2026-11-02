#!/usr/bin/env python3
"""离线自测：不需要相机、不需要开发板外设，用合成图验证三个算法骨架。

    python3 tools/selftest_offline.py            # 全部测试
    python3 tools/selftest_offline.py --only scope
    python3 tools/selftest_offline.py --keep     # 把合成图/标注图存到 /tmp/afh03_selftest/

覆盖：
  1) scope   : 合成示波器屏幕 -> 频率(Hz) 与 Vpp(V) 是否在容差内；自相关/过零是否一致；
               网格间距自动估计是否正确
  2) led     : 合成 LED 面板 -> 全灭基线标定 -> 亮/灭判定是否符合期望（含时间去抖）
  3) fpga    : 伪造首行嵌入状态字 -> 小端/大端/两种布局能否解出
  4) ocr     : 用几何图元伪造 5 个"汉字" -> 建模板 -> 抖动后的图能否正确识别；
               投影切字能否把"川"这种会被切成 3 段的字正确合并
  5) scpi    : SCPI 主判据的纯逻辑（白名单 20/40 MHz 命中与容差边界、分位数、
               从回读方波本地解算频率/Vpp）。端到端模拟验收在 tools/scpi_sim_selftest.py

注意：这里用几何图元代替真汉字，是为了不依赖任何中文字体（板子上通常没有 CJK 字体）。
真汉字的模板请用 tools/make_templates.py 从现场标定图生成。
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import cv2
except Exception as e:                                      
    print("需要 cv2：%s" % e)
    raise SystemExit(1)

from soc_vision.config import LedCfg, OcrCfg, OcrItemCfg, ScopeCfg                
from soc_vision.fpga_status import (LAYOUT_CONDENSED, LAYOUT_REGISTER,           
                                    ID_VER_EXPECT, MAGIC_EMBED, decode_words,
                                    scan_raw_yuyv, words_from_bytes)
from soc_vision.led_detect import LedDetector                                     
from soc_vision.ocr_cn import CnRecognizer, split_fixed, split_projection         
from soc_vision.scope_wave import (analyze_scope_frame, estimate_grid_pitch,      
                                   period_autocorr, period_zerocross)
from soc_vision.video_source import make_test_led_image, make_test_scope_image    

OUT = os.path.join(tempfile.gettempdir(), "afh03_selftest")
KEEP = False
PASS = 0
FAIL = 0

def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %-46s %s" % (name, detail))
    else:
        FAIL += 1
        print("  [FAIL] %-46s %s" % (name, detail))

def close(name: str, got: float, want: float, tol_rel: float, unit: str = "") -> None:
    ok = want == 0 or abs(got - want) <= tol_rel * abs(want)
    check(name, ok, "got=%.4g%s want=%.4g%s (tol %.1f%%)"
          % (got, unit, want, unit, tol_rel * 100))

def _fmt(v) -> str:
    return "-" if v is None else "%.2f" % float(v)

def test_scope() -> None:
    print("\n== 1. 示波器波形：频率 / Vpp ==")
    W, H = 1000, 700
    ppd_x, ppd_y = 100.0, 80.0
    gnd = 350.0
    cases = [

        (2.5, 1e-3, 0.5, 1.0, 3.0),
        (5.0, 1e-3, 0.5, 1.0, 2.0),
        (3.0, 2e-3, 1.0, 10.0, 1.5),
        (7.5, 0.2e-3, 0.2, 1.0, 4.0),
    ]
    for i, (fdiv, tdiv, vdiv, probe, vppdiv) in enumerate(cases):
        img = make_test_scope_image(W, H, freq_div=fdiv, vpp_div=vppdiv,
                                    px_per_div_x=ppd_x, px_per_div_y=ppd_y,
                                    gnd_y=gnd, phase=0.31)
        cfg = ScopeCfg(roi=(0, 0, W, H), time_per_div_s=tdiv, volt_per_div_v=vdiv,
                       probe_atten=probe, h_div=10.0, v_div=8.0,
                       px_per_div_x=ppd_x, px_per_div_y=ppd_y, gnd_y_px=gnd)
        res = analyze_scope_frame(img, cfg)
        want_f = fdiv / (cfg.h_div * tdiv)
        want_vpp = vppdiv * vdiv * probe
        tag = "case%d(fdiv=%.2f)" % (i, fdiv)
        check(tag + " ok", res.ok, res.message)
        if res.ok:
            close(tag + " freq", res.freq_hz, want_f, 0.03, "Hz")
            close(tag + " vpp", res.vpp_v, want_vpp, 0.06, "V")
            check(tag + " 估计器一致", res.estimators_agree,
                  "fft=%s ac=%s zc=%s(px)" % (
                      _fmt(res.debug.get("period_fft_px")),
                      _fmt(res.debug.get("period_ac_px")),
                      _fmt(res.debug.get("period_zc_px"))))
            check(tag + " 置信度>0.5", res.confidence > 0.5, "conf=%.2f" % res.confidence)
            if KEEP:
                cv2.imwrite(os.path.join(OUT, "scope_%d.png" % i), img)

    img_few = make_test_scope_image(W, H, freq_div=1.0, vpp_div=3.0,
                                   px_per_div_x=ppd_x, px_per_div_y=ppd_y, gnd_y=gnd)
    cfg_few = ScopeCfg(roi=(0, 0, W, H), time_per_div_s=1e-3, volt_per_div_v=0.5,
                       h_div=10.0, v_div=8.0, px_per_div_x=ppd_x, px_per_div_y=ppd_y)
    r_few = analyze_scope_frame(img_few, cfg_few)
    check("周期数不足 -> 明确 fail", not r_few.ok, r_few.message[:60])

    img_ok = make_test_scope_image(W, H, freq_div=5.0, vpp_div=2.0,
                                  px_per_div_x=ppd_x, px_per_div_y=ppd_y, gnd_y=gnd)
    cfg_hit = ScopeCfg(roi=(0, 0, W, H), time_per_div_s=1e-3, volt_per_div_v=0.5,
                       h_div=10.0, v_div=8.0, px_per_div_x=ppd_x, px_per_div_y=ppd_y,
                       expect_hz=500.0, expect_hz_tol_pct=2.0)
    r_hit = analyze_scope_frame(img_ok, cfg_hit)
    check("标称 500Hz -> PASS", bool(r_hit.ok and r_hit.verdict == "PASS"),
          "f=%.2f dev=%+.2f%%" % (r_hit.freq_hz, r_hit.freq_dev_pct))
    cfg_miss = ScopeCfg(roi=(0, 0, W, H), time_per_div_s=1e-3, volt_per_div_v=0.5,
                        h_div=10.0, v_div=8.0, px_per_div_x=ppd_x, px_per_div_y=ppd_y,
                        expect_hz=1000.0, expect_hz_tol_pct=2.0)
    r_miss = analyze_scope_frame(img_ok, cfg_miss)
    check("标称 1kHz -> FAIL", bool(r_miss.ok and r_miss.verdict == "FAIL"),
          "f=%.2f dev=%+.2f%%" % (r_miss.freq_hz, r_miss.freq_dev_pct))

    

    print("  -- 白名单判定（20/40 MHz = NORMAL）--")
    NOM = [20e6, 40e6]
    SIMPLE = 10.0          
    for f_target, want in ((20e6, "PASS"), (40e6, "PASS"), (25e6, "FAIL"),
                           (12.5e6, "FAIL")):
        tdiv = 20e-9
        fdiv = f_target * SIMPLE * tdiv          
        imgw = make_test_scope_image(W, H, freq_div=fdiv, vpp_div=3.0,
                                     px_per_div_x=ppd_x, px_per_div_y=ppd_y, gnd_y=gnd)
        c = ScopeCfg(roi=(0, 0, W, H), time_per_div_s=tdiv, volt_per_div_v=0.5,
                     probe_atten=1.0, h_div=SIMPLE, v_div=8.0,
                     px_per_div_x=ppd_x, px_per_div_y=ppd_y, gnd_y_px=gnd,
                     expect_hz_list=NOM, expect_hz_tol_pct=1.0)
        rr = analyze_scope_frame(imgw, c)
        close("白名单 %s 实测频率" % ("%.6g" % f_target), rr.freq_hz, f_target, 0.012, "Hz")
        check("白名单 %.6g -> %s" % (f_target, want),
              rr.ok and rr.verdict == want and rr.label == ("NORMAL" if want == "PASS" else "ABNORMAL"),
              "%s/%s f=%.6g dev=%+.3f%%" % (rr.verdict, rr.label, rr.freq_hz, rr.freq_dev_pct))

    
    print("  -- 14 大格 + 20 ns/div（真实高频工况）--")
    W2, H2, PPDX2, PPDY2 = 1000, 480, 71.0, 60.0
    HDIV2 = 14.0
    for f_target in (20e6, 40e6):
        tdiv = 20e-9
        fdiv = f_target * HDIV2 * tdiv           
        img2 = make_test_scope_image(W2, H2, freq_div=fdiv, vpp_div=4.0,
                                     px_per_div_x=PPDX2, px_per_div_y=PPDY2, gnd_y=240.0)
        c2 = ScopeCfg(roi=(0, 0, W2, H2), time_per_div_s=tdiv, volt_per_div_v=0.5,
                      probe_atten=1.0, h_div=HDIV2, v_div=8.0,
                      px_per_div_x=PPDX2, px_per_div_y=PPDY2, gnd_y_px=240.0,
                      expect_hz_list=NOM, expect_hz_tol_pct=1.0)
        r2b = analyze_scope_frame(img2, c2)
        per_px = (PPDX2 / (tdiv * f_target))
        close("14格/20ns %.6g Hz" % f_target, r2b.freq_hz, f_target, 0.012, "Hz")
        check("14格/20ns %.6g 判定 %s" % (f_target, "PASS"),
              r2b.ok and r2b.verdict == "PASS" and r2b.label == "NORMAL",
              "周期 %.1f px  f=%.6g  dev=%+.3f%%  conf=%.2f"
              % (per_px, r2b.freq_hz, r2b.freq_dev_pct, r2b.confidence))

    img = make_test_scope_image(W, H, freq_div=2.5, vpp_div=3.0,
                                px_per_div_x=ppd_x, px_per_div_y=ppd_y, gnd_y=gnd)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    ex = estimate_grid_pitch(gray, axis=1)
    ey = estimate_grid_pitch(gray, axis=0)
    close("网格间距 x 自动估计", ex or 0.0, ppd_x, 0.03, "px/div")
    close("网格间距 y 自动估计", ey or 0.0, ppd_y, 0.03, "px/div")

    cfg2 = ScopeCfg(roi=(0, 0, W, H), time_per_div_s=1e-3, volt_per_div_v=0.5,
                    h_div=10.0, v_div=8.0)
    r2 = analyze_scope_frame(img, cfg2)
    check("不给 px_per_div 也能出结果", r2.ok, r2.message)
    if r2.ok:
        close("自动标定后 freq", r2.freq_hz, 2.5 / 0.01, 0.05, "Hz")

    noise = (np.random.RandomState(1).normal(60, 8, (H, W, 3))).astype(np.uint8)
    r3 = analyze_scope_frame(noise, cfg)
    check("纯噪声不会误报高置信度", (not r3.ok) or r3.confidence < 0.8,
          "ok=%s conf=%.2f" % (r3.ok, r3.confidence))

    x = np.arange(0, 2000)
    sig = np.sin(2 * np.pi * x / 137.0)
    p_ac, _, _ = period_autocorr(sig)
    p_zc, n_zc, zc_cv = period_zerocross(sig)
    close("period_autocorr", p_ac or 0.0, 137.0, 0.01, "px")
    close("period_zerocross", p_zc or 0.0, 137.0, 0.01, "px")
    check("过零间隔离散度 cv<0.02", zc_cv < 0.02, "cv=%.4f n=%d" % (zc_cv, n_zc))

def test_led() -> None:
    print("\n== 2. LED 亮灭判定 ==")
    rois = [(60, 80, 90, 90), (250, 80, 90, 90), (440, 80, 90, 90)]
    off = make_test_led_image((False, False, False), rois, 640, 240)
    on = make_test_led_image((True, False, True), rois, 640, 240)

    items = []
    for i, r in enumerate(rois):
        items.append({"name": "led%d" % i, "roi": list(r), "mode": "bright",
                      "on_thr": 45.0, "off_thr": 25.0})
    cfg = LedCfg.from_dict({"enabled": True, "items": items, "debounce_n": 3})

    det = LedDetector(cfg)
    det.calibrate([off] * 12)
    check("基线标定成功", len(det.baseline.v_mean) == 3,
          json.dumps({k: round(v, 1) for k, v in det.baseline.v_mean.items()}))
    check("基线噪声小", all(v < 12.0 for v in det.baseline.v_std.values()),
          json.dumps({k: round(v, 2) for k, v in det.baseline.v_std.items()}))

    st = None
    for _ in range(6):
        st = det.detect(off)
    check("全灭 -> 全 OFF", [s.on for s in st] == [False, False, False],
          str([round(s.score, 1) for s in st]))

    for _ in range(6):
        st = det.detect(on)
    got = [s.on for s in st]
    check("亮0/灭1/亮2 -> ON/OFF/ON", got == [True, False, True], str(got))
    check("分数区分明显", st[0].score > 100 and abs(st[1].score) < 25,
          "scores=%s" % [round(s.score, 1) for s in st])

    for _ in range(6):
        st = det.detect(on)
    one = off.copy()
    jitter = det.detect(one)
    check("单帧跳变不翻转（时间迟滞）", [s.on for s in jitter] == [True, False, True],
          str([s.on for s in jitter]))

    cfg2 = LedCfg.from_dict({"items": [{**items[0], "expect": True},
                                       {**items[1], "expect": False},
                                       {**items[2], "expect": True}]})
    det2 = LedDetector(cfg2)
    det2.set_baseline(det.baseline)
    for _ in range(6):
        st2 = det2.detect(on)
    check("check_expect 通过", det2.check_expect(st2) == [],
          str(det2.check_expect(st2)))

    if KEEP:
        cv2.imwrite(os.path.join(OUT, "led_off.png"), off)
        cv2.imwrite(os.path.join(OUT, "led_on.png"), on)

_PALETTE = {"off": (30, 26, 22), "red": (0, 0, 235), "green": (0, 235, 0),
            "blue": (235, 0, 0), "yellow": (0, 230, 240), "white": (238, 238, 238)}

_COLOR_HSV = {
    "red": ((0, 90, 80), (12, 255, 255)),
    "green": ((40, 90, 80), (85, 255, 255)),
    "blue": ((100, 90, 80), (135, 255, 255)),
    "yellow": ((20, 90, 80), (38, 255, 255)),
}

def _make_panel(colors, rois, w, h, rng, noise=7.0):
    """画一块"LED 面板"并加真实退化：随机增益 + 高斯噪声 + 偶发模糊。"""
    img = np.full((h, w, 3), 34.0, np.float32)
    for c, (x, y, rw, rh) in zip(colors, rois):
        img[y:y + rh, x:x + rw] = _PALETTE[c]
    img = img * float(rng.uniform(0.75, 1.25)) + rng.normal(0, noise, img.shape)
    out = np.clip(img, 0, 255).astype(np.uint8)
    if rng.uniform() < 0.4:
        out = cv2.GaussianBlur(out, (3, 3), 0)
    return out

def _rand_rng(seed):
    if hasattr(np.random, "default_rng"):
        return np.random.default_rng(seed)
    return np.random.RandomState(seed)

def test_led_rate(trials: int = 100) -> None:
    """LED 亮灭 / 颜色判定**正确率**（随机图案 + 噪声 + 增益 + 模糊，每组 6 帧走去抖）。"""
    print("\n== 2b. LED 亮灭 / 颜色判定 正确率（随机 %d 组，含噪声/增益/模糊）==" % trials)
    rois = [(60, 40, 90, 90), (250, 40, 90, 90), (440, 40, 90, 90)]
    W, H = 640, 200
    rng = _rand_rng(20260202)

    items = [{"name": "led%d" % i, "roi": list(r), "mode": "bright",
              "on_thr": 45.0, "off_thr": 25.0} for i, r in enumerate(rois)]
    cfg = LedCfg.from_dict({"enabled": True, "items": items, "debounce_n": 3})
    det = LedDetector(cfg)
    det.calibrate([_make_panel(("off",) * 3, rois, W, H, rng) for _ in range(12)])
    ok = tot = 0
    for _ in range(trials):
        pat = [bool(v) for v in (rng.random(3) < 0.5)]
        frame = _make_panel(["white" if p else "off" for p in pat], rois, W, H, rng)
        st = None
        for _ in range(6):                       
            st = det.detect(frame)
        got = [s.on for s in st]
        ok += sum(1 for a, b in zip(got, pat) if a == b)
        tot += len(pat)
    rate = ok / max(1, tot) * 100.0
    check("LED 亮灭正确率 >= 97%%（%d 次判定）" % tot, rate >= 97.0,
          "%.2f%% (%d/%d)" % (rate, ok, tot))

    targets = ["red", "green", "blue"]
    items2 = []
    for i, (r, tc) in enumerate(zip(rois, targets)):
        lo, hi = _COLOR_HSV[tc]
        items2.append({"name": "c%d" % i, "roi": list(r), "mode": "color",
                       "hsv_lo": list(lo), "hsv_hi": list(hi),
                       "on_thr": 100.0, "off_thr": 40.0, "min_color_ratio": 0.1})
    cfg2 = LedCfg.from_dict({"enabled": True, "items": items2, "debounce_n": 3})
    det2 = LedDetector(cfg2)
    det2.calibrate([_make_panel(("off",) * 3, rois, W, H, rng) for _ in range(12)])
    ok2 = tot2 = 0
    conf = {c: [0, 0] for c in ("red", "green", "blue")}   
    for _ in range(trials):

        cols = [rng.choice(targets + ["off", "yellow"]) for _ in targets]
        frame = _make_panel(cols, rois, W, H, rng)
        st = None
        for _ in range(6):
            st = det2.detect(frame)
        for i, s in enumerate(st):
            want = (cols[i] == targets[i])
            ok2 += int(s.on == want)
            tot2 += 1
            if cols[i] == targets[i]:
                conf[targets[i]][0] += int(s.on)
                conf[targets[i]][1] += 1
    rate2 = ok2 / max(1, tot2) * 100.0
    check("颜色判定正确率 >= 97%%（%d 次判定）" % tot2, rate2 >= 97.0,
          "%.2f%% (%d/%d)" % (rate2, ok2, tot2))
    for c in targets:
        hit, n = conf[c]
        check("颜色 %s 识别率 >= 95%%" % c, n == 0 or hit / n >= 0.95,
              "%d/%d = %.1f%%" % (hit, n, hit * 100.0 / max(1, n)))

    if KEEP:
        cv2.imwrite(os.path.join(OUT, "led_rate_panel.png"),
                    _make_panel(("red", "green", "blue"), rois, W, H, _rand_rng(1)))

def test_fpga() -> None:
    print("\n== 3. FPGA 首行嵌入状态字解码 ==")
    lit = [True, False, True, True, False, False, False, False]
    n_lit = sum(lit)
    frame = 0x1234
    status = (frame & 0xFF) | ((n_lit & 0xFF) << 8) | (1 << 16) | (1 << 17)

    words = [MAGIC_EMBED, frame, status]
    for b in lit:
        words.append((0x22 << 24) | (0xFF if b else 0x00))
    for endian in ("<", ">"):
        raw = struct.pack(endian + "%dI" % len(words), *words)
        raw = raw + bytes(4096 - len(raw))
        st = scan_raw_yuyv(raw)
        tag = "condensed %s" % ("小端" if endian == "<" else "大端")
        check(tag + " present", st.present, st.note)
        check(tag + " 布局", st.layout == LAYOUT_CONDENSED, st.layout)
        check(tag + " frame_cnt", st.frame_cnt == frame, str(st.frame_cnt))
        check(tag + " n_lit", st.n_lit == n_lit, str(st.n_lit))
        check(tag + " lit 位", st.lit_bits() == lit, str(st.lit_bits()))
        check(tag + " ready/any_lit", st.ready and st.any_lit,
              "ready=%s any=%s" % (st.ready, st.any_lit))

    rwords = [MAGIC_EMBED, ID_VER_EXPECT, frame, status, 0]
    for n in range(8):
        rwords += [1000 + n, 2000 + n, 3000 + n, 1600, (200 << 16) | (100 << 8) | 50,
                   (0x33 << 24) | (0xFF if lit[n] else 0)]
    raw = struct.pack("<%dI" % len(rwords), *rwords) + bytes(4096 - 4 * len(rwords))
    st = decode_words(words_from_bytes(raw, "<", 64), 0, LAYOUT_REGISTER)
    check("register 布局 present", st.present, st.note)
    check("register ID/VER", st.id_ver == ID_VER_EXPECT, "0x%08X" % st.id_ver)
    check("register lit 位", st.lit_bits() == lit, str(st.lit_bits()))
    check("register R_SUM", st.rois[3].r_sum == 1003, str(st.rois[3].r_sum))
    check("register MAX_RGB", (st.rois[0].max_r, st.rois[0].max_g, st.rois[0].max_b)
          == (200, 100, 50), str((st.rois[0].max_r, st.rois[0].max_g, st.rois[0].max_b)))

    raw = bytes(4096)
    st = scan_raw_yuyv(raw)
    check("全零帧 -> present=False", not st.present, st.note)

    bad_status = (frame & 0xFF) | (0x7F << 8)      
    awords = [MAGIC_EMBED, ID_VER_EXPECT, frame, bad_status, 0]
    for n in range(8):
        awords += [0, 0, 0, 0, 0, (0xFF if lit[n] else 0)]
    raw = struct.pack("<%dI" % len(awords), *awords) + bytes(4096 - 4 * len(awords))
    st = scan_raw_yuyv(raw)
    check("auto 回落 register", st.present and st.layout == LAYOUT_REGISTER,
          "layout=%s note=%s" % (st.layout, st.note))

GLYPHS = "日川口十三"

def _draw_glyphs(sheet: np.ndarray, boxes, kinds=None) -> None:
    kinds = kinds if kinds is not None else list(range(len(boxes)))
    for (x, y, w, h), k in zip(boxes, kinds):
        c, t = (255, 255, 255), 3
        if k == 0:      
            cv2.rectangle(sheet, (x + 6, y + 4), (x + w - 6, y + h - 4), c, t)
            cv2.line(sheet, (x + 6, y + h // 2), (x + w - 6, y + h // 2), c, t)
        elif k == 1:    
            for i in range(3):
                xx = x + 8 + i * (w - 16) // 2
                cv2.line(sheet, (xx, y + 4), (xx, y + h - 4), c, t)
        elif k == 2:    
            cv2.rectangle(sheet, (x + 8, y + 8), (x + w - 8, y + h - 8), c, t)
        elif k == 3:    
            cv2.line(sheet, (x + w // 2, y + 4), (x + w // 2, y + h - 4), c, t)
            cv2.line(sheet, (x + 6, y + h // 2), (x + w - 6, y + h // 2), c, t)
        else:           
            for j in range(3):
                yy = y + 8 + j * (h - 16) // 2
                cv2.line(sheet, (x + 6, yy), (x + w - 6, yy), c, t)

def test_ocr() -> None:
    print("\n== 4. 汉字识别（模板匹配 + 切字）==")
    BW, BH = 64, 64
    boxes = [(20 + i * 90, 30, BW, BH) for i in range(len(GLYPHS))]
    sheet = np.full((120, 20 + len(GLYPHS) * 90, 3), 22, np.uint8)
    _draw_glyphs(sheet, boxes)

    from soc_vision.ocr_cn import to_binary_char
    chars, imgs, grays = [], [], []
    for (x, y, w, h), ch in zip(boxes, GLYPHS):
        b = to_binary_char(sheet[y:y + h, x:x + w], (32, 32))
        chars.append(ch)
        imgs.append(b)
        grays.append(cv2.GaussianBlur(b, (3, 3), 0))
    os.makedirs(OUT, exist_ok=True)
    npz = os.path.join(OUT, "cn_templates_selftest.npz")
    np.savez_compressed(npz, chars=np.array(chars, dtype="<U8"),
                        imgs=np.stack(imgs), grays=np.stack(grays),
                        size=np.array([32, 32], dtype=np.int32))
    check("模板库生成", os.path.isfile(npz), npz)

    item = OcrItemCfg.from_dict({
        "name": "text0", "engine": "template", "split": "fixed",
        "roi": [0, 0, sheet.shape[1], sheet.shape[0]],
        "n_chars": len(GLYPHS), "fixed_boxes": [list(b) for b in boxes],
        "fixed_chars": GLYPHS, "char_size": [32, 32], "threshold": 0.5})
    ocr_cfg = OcrCfg.from_dict({})
    ocr_cfg.items = [item]
    ocr_cfg.template_npz = npz
    rec = CnRecognizer(ocr_cfg, base_dir=OUT)

    r = rec.recognize_item(sheet, item)
    check("原图识别正确", r.ok and r.text == GLYPHS, "text=%s conf=%.3f" % (r.text, r.conf))

    rng = np.random.RandomState(3)
    M = np.float32([[1.0, 0, 2.0], [0, 1.0, 1.0]])
    jit = cv2.warpAffine(sheet, M, (sheet.shape[1], sheet.shape[0]),
                         borderMode=cv2.BORDER_REPLICATE)
    jit = np.clip(jit.astype(np.float32) * 0.85 + 12 + rng.normal(0, 4, jit.shape),
                  0, 255).astype(np.uint8)
    r2 = rec.recognize_item(jit, item)
    check("抖动+噪声+变亮后仍正确", r2.ok and r2.text == GLYPHS,
          "text=%s conf=%.3f" % (r2.text, r2.conf))

    roi = sheet[0:120, 0:sheet.shape[1]]
    boxes_p = split_projection(roi, len(GLYPHS))
    check("投影切字合并到 5 段", len(boxes_p) == len(GLYPHS),
          "%d 段: %s" % (len(boxes_p), [b[0] for b in boxes_p]))
    if len(boxes_p) == len(GLYPHS):
        centers_p = [b[0] + b[2] / 2 for b in boxes_p]
        centers_t = [b[0] + b[2] / 2 for b in boxes]
        dev = max(abs(a - b) for a, b in zip(centers_p, centers_t))
        check("投影切字中心偏差 < 25px", dev < 25, "max dev=%.1fpx" % dev)

    bs = split_fixed(item)
    check("split_fixed 用标定框", len(bs) == len(GLYPHS) and bs[0] == boxes[0], str(bs[:1]))

    blank = np.full((sheet.shape[0], sheet.shape[1], 3), 22, np.uint8)
    item_blank = OcrItemCfg.from_dict({
        "name": "t2", "engine": "template", "split": "fixed",
        "roi": [0, 0, sheet.shape[1], sheet.shape[0]], "n_chars": len(GLYPHS),
        "fixed_boxes": [list(b) for b in boxes], "threshold": 0.5})
    ocr_cfg3 = OcrCfg.from_dict({})
    ocr_cfg3.items = [item_blank]
    ocr_cfg3.template_npz = npz
    r4 = CnRecognizer(ocr_cfg3, base_dir=OUT).recognize_item(blank, item_blank)
    check("空白 ROI -> 全部 '?'", r4.text == "?" * len(GLYPHS), "text=%s" % r4.text)

    if KEEP:
        cv2.imwrite(os.path.join(OUT, "ocr_sheet.png"), sheet)
        cv2.imwrite(os.path.join(OUT, "ocr_jitter.png"), jit)

def test_scpi_judge() -> None:
    """SCPI 主判据的**纯逻辑**部分（不起 socket；端到端在 tools/scpi_sim_selftest.py）。

    这里覆盖的是最容易写错、也最值钱的一段：白名单命中判定、容差边界、
    以及"从回读波形本地算频率/Vpp"的纯 Python 实现（踩过 _percentile 越界的坑）。
    """
    print("\n== 5. SCPI 判定逻辑（白名单 + 波形本地解算）==")
    from soc_vision.scpi_scope import (DEFAULT_NOMINAL_HZ, analyze_samples, fmt_hz,
                                      judge_freq, _percentile)

    for f, want in ((20e6, True), (40e6, True), (20.18e6, True), (40.3e6, True),
                    (20.24e6, False), (39.5e6, False), (13.5e6, False), (1e3, False)):
        hit, best, dev = judge_freq(f, DEFAULT_NOMINAL_HZ, 1.0)
        check("judge %.6g -> %s" % (f, "命中" if want else "不命中"), hit == want,
              "最近标称 %s 偏差 %+.3f%%" % (fmt_hz(best), dev))

    check("_percentile 百分数/比例 都可", abs(_percentile([1, 2, 3, 4], 0.5) - 2.5) < 1e-9
          and abs(_percentile([1, 2, 3, 4], 50) - 2.5) < 1e-9,
          "0.5->%.2f  50->%.2f" % (_percentile([1, 2, 3, 4], 0.5), _percentile([1, 2, 3, 4], 50)))
    check("_percentile 越界输入不崩", abs(_percentile([1, 2, 3], 5.0) - 1.1) < 1e-9
          and _percentile([1, 2, 3], -1.0) == 1.0
          and _percentile([1, 2, 3], 999.0) == 3.0,
          "q=5(->5%%)->%.1f q=-1->%.1f q=999->%.1f"
          % (_percentile([1, 2, 3], 5.0), _percentile([1, 2, 3], -1.0),
             _percentile([1, 2, 3], 999.0)))

    dt = 0.5e-9
    n = 1000
    f0 = 20e6
    samp = [1.65 if ((i * dt * f0) % 1.0) < 0.5 else -1.65 for i in range(n)]
    an = analyze_samples(samp, dt)
    close("方波回读频率", an["freq_hz"], f0, 0.002, "Hz")
    close("方波回读 Vpp", an["vpp_v"], 3.3, 0.02, "V")
    check("方波回读上升沿数 >= 8", an["n_edges"] >= 8,
          "n_edges=%d（0.5ns×1000 点 = 500ns = 10 个 20MHz 周期）" % an["n_edges"])

    check("回读数据过短 -> 安全返回 0", analyze_samples([1.0, 2.0], dt)["freq_hz"] == 0.0, "-")

def main() -> int:
    global KEEP
    ap = argparse.ArgumentParser(description="AFH03 SoC 侧算法离线自测")
    ap.add_argument("--only", choices=["scope", "led", "ledrate", "fpga", "ocr", "scpi"],
                    help="只跑某一组")
    ap.add_argument("--keep", action="store_true", help="保存合成图到 /tmp/afh03_selftest")
    a = ap.parse_args()
    KEEP = a.keep
    if KEEP:
        os.makedirs(OUT, exist_ok=True)

    print("AFH03 SoC 侧算法离线自测（numpy %s, opencv %s）"
          % (np.__version__, cv2.__version__))
    todo = {
        "scope": test_scope, "led": test_led, "ledrate": test_led_rate,
        "fpga": test_fpga, "ocr": test_ocr, "scpi": test_scpi_judge,
    }
    for name in (["scope", "led", "ledrate", "fpga", "ocr", "scpi"]
                 if not a.only else [a.only]):
        try:
            todo[name]()
        except Exception as e:
            import traceback
            traceback.print_exc()
            check("%s 不抛异常" % name, False, "%s: %s" % (type(e).__name__, e))

    print("\n" + "=" * 60)
    print("PASS=%d  FAIL=%d" % (PASS, FAIL))
    if KEEP:
        print("合成图/中间结果: %s" % OUT)
    print("=" * 60)
    return 0 if FAIL == 0 else 1

if __name__ == "__main__":
    raise SystemExit(main())
