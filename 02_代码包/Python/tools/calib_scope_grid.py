#!/usr/bin/env python3
"""示波器屏幕网格标定：从一张截图里量出"每格多少像素"，并把标定写进 JSON。

为什么要这个工具
----------------
频率换算只需要两个量：
    f = 1 / (period_px * dt_per_px)     dt_per_px = (time/div) / (px per div)
`time/div` 从示波器面板读（RIGOL DS2302A 屏幕右下角显示，例如 "1.000ms/div"），
`px per div` 必须从图像里量。本工具负责量后者，并支持用**已知频率信号**
（示波器自带的 1 kHz 探头补偿输出）反解、验证整条链路。

用法
----
1) 只看网格：
     python3 tools/calib_scope_grid.py --image shot.png --roi 40,60,700,360

2) 用示波器自带 1kHz 校准方波反解并验证（推荐）：
     # 探头挂到示波器前面板的探头补偿端子，time/div=0.5ms，V/div=1V，探头 x10
     python3 tools/calib_scope_grid.py --image cal.png --roi 40,60,700,360 \
             --time-per-div 0.0005 --volt-per-div 1 --probe 10 --expect-hz 1000 \
             --write-config config/scope_calib.json

3) 只有已知频率、想反推 px/div：
     python3 tools/calib_scope_grid.py --image shot.png --roi ... \
             --time-per-div 0.001 --expect-hz 1000 --solve-px-per-div

输出里会打印：检出的网格线位置、候选 px/div（跨度法/线距法/FFT 法）、
以及用各候选值算出来的频率。哪个候选能把频率算对，就用哪个。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import cv2
except Exception as e:                                      
    print("需要 cv2：%s" % e)
    raise SystemExit(1)

from soc_vision.scope_wave import (analyze_scope_frame, detect_grid_lines,      
                                   estimate_grid_pitch)
from soc_vision.config import ScopeCfg                                          

def main() -> int:
    ap = argparse.ArgumentParser(description="示波器网格标定 / 频率链路验证")
    ap.add_argument("--image", required=True, help="示波器截图（png/jpg）")
    ap.add_argument("--roi", default="", help="波形显示区 x,y,w,h（不填=整图）")
    ap.add_argument("--time-per-div", type=float, required=True, help="时基 s/div")
    ap.add_argument("--volt-per-div", type=float, default=1.0, help="垂直 V/div")
    ap.add_argument("--probe", type=float, default=1.0, help="探头衰减 x1/x10/x100")
    ap.add_argument("--h-div", type=float, default=14.0, help="水平大格数（现场数，DS2000A 常见 14）")
    ap.add_argument("--v-div", type=float, default=8.0, help="垂直大格数")
    ap.add_argument("--subdiv", type=int, default=5, help="每大格的小格数（RIGOL 通常 5）")
    ap.add_argument("--expect-hz", type=float, default=0.0, help="已知信号的频率（验证用）")
    ap.add_argument("--px-per-div-x", type=float, default=0.0, help="直接给定则跳过测量")
    ap.add_argument("--solve-px-per-div", action="store_true",
                    help="用 --expect-hz 反解 px/div")
    ap.add_argument("--write-config", help="把标定写进这个 JSON（合并进 scope 段）")
    a = ap.parse_args()

    img = cv2.imread(a.image, cv2.IMREAD_COLOR)
    if img is None:
        print("读不到图: %s" % a.image)
        return 1
    print("图像: %s  %dx%d" % (a.image, img.shape[1], img.shape[0]))

    if a.roi:
        x, y, w, h = (int(v) for v in a.roi.split(","))
    else:
        x, y, w, h = 0, 0, img.shape[1], img.shape[0]
        print("未给 --roi，按整图处理。**强烈建议先用 capture_probe.sh 抓帧，"
              "标出真正的波形显示区**（RIGOL 屏幕右侧有菜单栏、底部有状态栏）")
    roi = img[y:y + h, x:x + w]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

    print("\n== 网格线检测 ==")
    lines_x = detect_grid_lines(gray, axis=1)
    lines_y = detect_grid_lines(gray, axis=0)
    print("  竖线 x（%d 条）: %s" % (len(lines_x), lines_x[:20]))
    print("  横线 y（%d 条）: %s" % (len(lines_y), lines_y[:20]))

    cands = {}
    if len(lines_x) >= 2:
        span = lines_x[-1] - lines_x[0]
        diffs = np.diff(np.asarray(lines_x, dtype=float))
        diffs = diffs[diffs >= 3]
        if diffs.size:
            cands["线距法 x subdiv=%d" % a.subdiv] = float(np.median(diffs)) * a.subdiv
            cands["线距法 x 原始(不乘 subdiv)"] = float(np.median(diffs))
        cands["跨度法 x /h_div=%.1f" % a.h_div] = span / a.h_div
        print("  竖线跨度 = %d px，跨度法 px/div = %.2f" % (span, span / a.h_div))
    if len(lines_y) >= 2:
        span_y = lines_y[-1] - lines_y[0]
        cands["跨度法 y /v_div=%.1f" % a.v_div] = span_y / a.v_div
        diffs_y = np.diff(np.asarray(lines_y, dtype=float))
        diffs_y = diffs_y[diffs_y >= 3]
        if diffs_y.size:
            cands["线距法 y subdiv=%d" % a.subdiv] = float(np.median(diffs_y)) * a.subdiv
        print("  横线跨度 = %d px，跨度法 px/div = %.2f" % (span_y, span_y / a.v_div))
    fft_p = estimate_grid_pitch(gray, axis=1)
    if fft_p:
        cands["图案自相关(最可信)"] = float(fft_p)

    print("\n== px/div 候选 ==")
    for k, v in cands.items():
        print("  %-28s %.2f px/div" % (k, v))

    if len(lines_x) >= 2:
        diffs = np.diff(np.asarray(lines_x, dtype=float))
        diffs = diffs[diffs >= 3]
        if diffs.size:
            gap = float(np.median(diffs))
            print("\n== 相邻网格线中位间距 = %.2f px；若按不同 subdiv 解释，px/div 与频率如下 =="
                  % gap)
            print("  %-8s %-12s %-16s %s" % ("subdiv", "px/div", "频率(Hz)", "与已知值的偏差"))
            for sd in (1, 2, 4, 5, 10):
                ppd = gap * sd
                sc_try = ScopeCfg(roi=(0, 0, w, h), time_per_div_s=a.time_per_div,
                                  volt_per_div_v=a.volt_per_div, probe_atten=a.probe,
                                  h_div=a.h_div, v_div=a.v_div, grid_subdiv=1,
                                  px_per_div_x=ppd, px_per_div_y=ppd)
                r_try = analyze_scope_frame(roi, sc_try)
                f = r_try.freq_hz if r_try.ok else 0.0
                note = ""
                if a.expect_hz > 0 and f > 0:
                    d = (f - a.expect_hz) / a.expect_hz * 100.0
                    note = "%+.2f%%" % d
                    if abs(d) <= 3.0:
                        note += "   <-- 这一行能和已知信号对上"
                print("  %-8d %-12.2f %-16.6g %s" % (sd, ppd, f, note))
            print("  提示：数一下示波器屏幕上'一大格'里有几条虚线，就能确定用哪一行。")

    if a.px_per_div_x > 0:
        chosen = a.px_per_div_x
        print("\n使用 --px-per-div-x = %.2f" % chosen)
    elif a.solve_px_per_div and a.expect_hz > 0:

        sc0 = ScopeCfg(roi=(0, 0, w, h), time_per_div_s=a.time_per_div,
                       volt_per_div_v=a.volt_per_div, probe_atten=a.probe,
                       h_div=a.h_div, v_div=a.v_div, grid_subdiv=a.subdiv,
                       px_per_div_x=100.0, px_per_div_y=100.0)
        r0 = analyze_scope_frame(roi, sc0)
        if not r0.ok:
            print("单帧分析失败：%s" % r0.message)
            return 2

        chosen = a.expect_hz * r0.period_px * a.time_per_div
        print("\n反解: period_px=%.3f, time/div=%.6gs -> px/div = %.3f"
              % (r0.period_px, a.time_per_div, chosen))
        print("     （注意：反解把算法误差也算进去了，建议再用别的频率复核一次）")
    else:
        order = ["图案自相关(最可信)", "跨度法 x /h_div=%.1f" % a.h_div,
                 "线距法 x subdiv=%d" % a.subdiv]
        chosen = next((cands[k] for k in order if k in cands), 0.0)
        if chosen <= 0:
            print("没量出 px/div，请检查 ROI/截图质量")
            return 2

    print("\n== 用 px/div=%.3f 跑一遍算法 ==" % chosen)
    sc = ScopeCfg(roi=(0, 0, w, h), time_per_div_s=a.time_per_div,
                  volt_per_div_v=a.volt_per_div, probe_atten=a.probe,
                  h_div=a.h_div, v_div=a.v_div, grid_subdiv=a.subdiv,
                  px_per_div_x=chosen, px_per_div_y=cands.get("跨度法 y /v_div=%.1f" % a.v_div, chosen),
                  expect_hz=(a.expect_hz or None))
    res = analyze_scope_frame(roi, sc)
    print(json.dumps({k: v for k, v in res.to_dict().items()
                      if k in ("ok", "freq_hz", "vpp_v", "period_px", "confidence",
                               "estimators_agree", "aliasing_suspect", "verdict",
                               "freq_dev_pct", "message")},
                     ensure_ascii=False, indent=2))
    if a.expect_hz > 0:
        dev = (res.freq_hz - a.expect_hz) / a.expect_hz * 100.0
        print("\n已知信号 %.6g Hz，实测 %.6g Hz，偏差 %+.2f%%  -> %s"
              % (a.expect_hz, res.freq_hz, dev,
                 "标定可用" if abs(dev) <= 3.0 else "偏差偏大：检查 ROI 是否含菜单栏/是否含整周期"))

    if a.write_config:
        block = {
            "model": "RIGOL DS2302A",
            "roi": [x, y, w, h],
            "time_per_div_s": a.time_per_div,
            "volt_per_div_v": a.volt_per_div,
            "probe_atten": a.probe,
            "h_div": a.h_div,
            "v_div": a.v_div,
            "grid_h_div_hint": a.h_div,
            "grid_subdiv": a.subdiv,
            "px_per_div_x": round(float(chosen), 4),
            "px_per_div_y": round(float(cands.get("跨度法 y /v_div=%.1f" % a.v_div, chosen)), 4),
        }
        old = {}
        if os.path.isfile(a.write_config):
            try:
                old = json.load(open(a.write_config, encoding="utf-8"))
            except Exception:
                old = {}
        cfg = old.get("scope", {}) if isinstance(old.get("scope"), dict) else {}
        cfg.update(block)
        old["scope"] = cfg
        os.makedirs(os.path.dirname(os.path.abspath(a.write_config)) or ".", exist_ok=True)
        with open(a.write_config, "w", encoding="utf-8") as f:
            json.dump(old, f, ensure_ascii=False, indent=2)
        print("\n标定已写入 %s（scope 段）" % a.write_config)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
