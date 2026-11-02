#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""frame_forensics.py —— 对**已经抓到的帧文件**做一次性离线取证（不碰任何设备）。

用途
----
现场把"抓帧"和"分析"分开：抓帧的人只负责产出文件（PNG + 原始 YUYV），
本工具对文件做全部判据与分析，**零设备风险**（不开 `/dev/video22`、不触发任何 ioctl）。

它对三类文件给出结论：
  1) **原始 YUYV**（`--raw`，期望 1920×1080×2 = 4,147,200 B）
     * 0xFF 占比 / 不同字节值 / `[REAL]`|`[DUMMY]`
     * FPGA 魔数 `0xA5C35A00` 小端/大端出现次数 → 判"ROI 版位流 / 厂家版位流"
     * 若命中魔数，调用 `soc_vision.fpga_status.scan_raw_yuyv` 解出 8 路 ROI 判决
  2) **PNG 帧**（`--png`，可再给 `--png2`）
     * 灰度 min/max/均值/标准差/灰阶数/纯白占比
     * 给了两张图就做**帧间差**（`|差|>4` 像素占比）→ 判画面是否"活的"
  3) **ROI 统计**（`--config`，默认 `config/example_config.json`）
     * LED/颜色：每个 ROI 的 BGR/灰度/HSV 均值与色域命中率
     * 汉字：ROI 的灰度统计、Otsu 前景占比、连通域个数与最大面积
     * 示波器：波形色域命中率与标定值回显

用法
----
    python3 tools/frame_forensics.py --raw /tmp/f.raw --png /tmp/f.png --png2 /tmp/f2.png
    python3 tools/frame_forensics.py --png /tmp/f.png --config config/example_config.json
    python3 tools/frame_forensics.py --raw /tmp/f.raw --json-out /tmp/forensics.json

退出码：0 正常（含判为 DUMMY 的情况，结论写在输出里）/ 1 参数或文件读取失败
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys

try:
    import numpy as np
except Exception as _e:                                           
    np = None                                                     
    _NP_ERR = _e
else:
    _NP_ERR = None

try:
    import cv2
except Exception as _e2:                                          
    cv2 = None                                                    
    _CV2_ERR = _e2
else:
    _CV2_ERR = None

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

MAGIC = 0xA5C35A00
W, H = 1920, 1080
EXPECT_RAW = W * H * 2

def sec(t: str) -> None:
    print("\n== %s ==" % t)

def analyze_raw(path: str, out: dict) -> None:
    sec("1) 原始 YUYV 判据：%s" % path)
    if not os.path.isfile(path):
        print("  [ERR] 文件不存在")
        out["raw"] = {"error": "not found"}
        return
    d = open(path, "rb").read()
    n = len(d) or 1
    ff = d.count(0xff)
    uniq = len(set(d))
    ffp = ff * 100.0 / n
    print("  大小 = %d B（期望 %d，%s）" % (len(d), EXPECT_RAW,
                                          "一致" if len(d) == EXPECT_RAW else "不一致"))
    print("  0xFF 占比 = %.2f%%   不同字节值 = %d" % (ffp, uniq))
    verdict = "DUMMY" if ffp > 95 else "REAL"
    print("  -> [%s] %s" % (verdict, "几乎全 0xFF：FPGA 未配置（rkcif dummy buffer）"
                           if verdict == "DUMMY" else "有分布，像真实图像数据"))
    le = MAGIC.to_bytes(4, "little")
    be = MAGIC.to_bytes(4, "big")
    c_le, c_be = d.count(le), d.count(be)
    print("  魔数 0x%08X：小端=%d 大端=%d -> %s"
          % (MAGIC, c_le, c_be,
             "**ROI 版位流（带状态字）**" if (c_le or c_be) else "厂家版位流（无状态字）"))
    rec = {"size": len(d), "expect": EXPECT_RAW, "ff_pct": round(ffp, 4),
           "distinct": uniq, "verdict": verdict,
           "magic_le": c_le, "magic_be": c_be,
           "bitstream": "roi" if (c_le or c_be) else "factory",
           "first32_hex": d[:32].hex()}
    print("  首 32 字节 = %s" % d[:32].hex())
    if c_le or c_be:
        try:
            from soc_vision.fpga_status import scan_raw_yuyv
            st = scan_raw_yuyv(d)
            print("  scan_raw_yuyv: present=%s layout=%s frame_cnt=%s n_lit=%s lit=%s"
                  % (st.present, st.layout, st.frame_cnt, st.n_lit, st.lit_bits()))
            print("                 ready=%s any_lit=%s note=%s"
                  % (getattr(st, "ready", None), getattr(st, "any_lit", None), st.note))
            rec["fpga_status"] = {"present": st.present, "layout": st.layout,
                                  "frame_cnt": st.frame_cnt, "n_lit": st.n_lit,
                                  "lit": st.lit_bits(), "note": st.note}
        except Exception as e:                                    
            print("  [warn] scan_raw_yuyv 失败: %s" % e)
    out["raw"] = rec

def analyze_png(path: str, tag: str, out: dict):
    sec("%s) PNG 帧判据：%s" % (tag, path))
    if cv2 is None:
        print("  [skip] 需要 cv2（%s）；--raw 判据不需要它" % _CV2_ERR)
        return None
    if not os.path.isfile(path):
        print("  [ERR] 文件不存在")
        return None
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        print("  [ERR] 读不到图")
        return None
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    white = float((g >= 250).mean() * 100.0)
    print("  尺寸 = %dx%d" % (img.shape[1], img.shape[0]))
    print("  灰度: min=%d max=%d 均值=%.1f 标准差=%.1f 灰阶数=%d 纯白占比=%.2f%%"
          % (g.min(), g.max(), g.mean(), g.std(), len(np.unique(g)), white))
    print("  BGR 均值 = %s" % (tuple(round(float(v), 1) for v in img.reshape(-1, 3).mean(axis=0)),))
    print("  -> %s" % ("[DUMMY?] 灰阶极少且几乎全白，像未配置的 dummy 帧"
                       if len(np.unique(g)) <= 20 and white > 90 else "[REAL] 灰阶丰富，像真实画面"))
    out.setdefault("png", {})[os.path.basename(path)] = {
        "shape": list(img.shape), "gray_min": int(g.min()), "gray_max": int(g.max()),
        "gray_mean": round(float(g.mean()), 2), "gray_std": round(float(g.std()), 2),
        "levels": int(len(np.unique(g))), "white_pct": round(white, 2)}
    return img

def frame_diff(a, b, out: dict) -> None:
    sec("帧间差（判画面是否 LIVE）")
    if np is None:
        print("  [skip] 需要 numpy（%s）" % _NP_ERR)
        return
    if a.shape != b.shape:
        print("  [跳过] 两张图尺寸不同: %s vs %s" % (a.shape, b.shape))
        return
    d = np.abs(a.astype(np.int16) - b.astype(np.int16))
    pct = float((d.max(axis=2) > 4).mean() * 100.0)
    print("  |差|>4 的像素占比 = %.2f%%   最大差=%d   平均差=%.2f"
          % (pct, d.max(), d.mean()))
    print("  -> %s" % ("[LIVE] 有帧间噪声/运动 → 真实传感器在出流"
                       if pct > 1.0 else "[STATIC?] 两帧几乎一样（静态场景或复用同一帧）"))
    out["frame_diff_pct"] = round(pct, 3)

def roi_report(img, cfg_path: str, out: dict) -> None:
    sec("ROI 统计（配置：%s）" % cfg_path)
    if cv2 is None:
        print("  [skip] 需要 cv2（%s）" % _CV2_ERR)
        return
    if not os.path.isfile(cfg_path):
        print("  [跳过] 找不到配置")
        return
    try:
        from soc_vision.config import load_config
    except Exception as e:                                        
        print("  [跳过] 无法导入 soc_vision.config: %s" % e)
        return
    cfg = load_config(cfg_path)
    rec = {}

    def roi_of(roi):
        x, y, w, h = [int(v) for v in roi]
        ih, iw = img.shape[:2]
        return img[max(0, y):min(ih, y + h), max(0, x):min(iw, x + w)]

    if cfg.led.items:
        print("  --- LED / 颜色 ROI ---")
        rec["led"] = {}
        for it in cfg.led.items:
            p = roi_of(it.roi)
            if p.size == 0:
                print("    %-6s ROI %s 越界" % (it.name, list(it.roi)))
                continue
            hsv = cv2.cvtColor(p, cv2.COLOR_BGR2HSV)
            gray = cv2.cvtColor(p, cv2.COLOR_BGR2GRAY)
            m = cv2.inRange(hsv, np.array(it.hsv_lo, np.uint8), np.array(it.hsv_hi, np.uint8))
            hit = float(np.count_nonzero(m)) / max(1, m.size) * 100.0
            print("    %-6s roi=%-20s mode=%-6s gray=%.1f±%.1f V=%.1f±%.1f 色域命中=%.2f%%"
                  % (it.name, str(list(it.roi)), it.mode, gray.mean(), gray.std(),
                     hsv[:, :, 2].mean(), hsv[:, :, 2].std(), hit))
            rec["led"][it.name] = {"gray_mean": round(float(gray.mean()), 1),
                                   "v_mean": round(float(hsv[:, :, 2].mean()), 1),
                                   "color_hit_pct": round(hit, 2)}
    else:
        print("  (配置里没有 led.items)")

    if cfg.ocr.items:
        print("  --- 汉字 ROI ---")
        rec["ocr"] = {}
        for it in cfg.ocr.items:
            p = roi_of(it.roi)
            if p.size == 0:
                print("    %-6s ROI %s 越界" % (it.name, list(it.roi)))
                continue
            g = cv2.cvtColor(p, cv2.COLOR_BGR2GRAY)
            _, bw = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            fg = float(np.count_nonzero(bw)) / bw.size * 100.0
            nn, _, stats, _ = cv2.connectedComponentsWithStats(bw, connectivity=8)
            areas = sorted([int(s) for s in stats[1:, cv2.CC_STAT_AREA]], reverse=True)[:5]
            print("    %-6s roi=%-20s engine=%-9s n_chars=%d gray=%.1f±%.1f 前景=%.1f%% 连通域=%d 前几大面积=%s"
                  % (it.name, str(list(it.roi)), it.engine, it.n_chars,
                     g.mean(), g.std(), fg, max(0, nn - 1), areas))
            rec["ocr"][it.name] = {"gray_mean": round(float(g.mean()), 1),
                                   "fg_pct": round(fg, 1), "components": int(max(0, nn - 1)),
                                   "top_areas": areas}
    else:
        print("  (配置里没有 ocr.items)")

    if getattr(cfg.scope, "enabled", False):
        print("  --- 示波器 ROI（图像法；SCPI 为主判据时仅作交叉参考）---")
        p = roi_of(cfg.scope.roi)
        if p.size:
            hsv = cv2.cvtColor(p, cv2.COLOR_BGR2HSV)
            m = cv2.inRange(hsv, np.array(cfg.scope.wave_hsv_lo, np.uint8),
                            np.array(cfg.scope.wave_hsv_hi, np.uint8))
            hit = float(np.count_nonzero(m)) / max(1, m.size) * 100.0
            print("    roi=%s 波形色域命中=%.2f%%  标定: t/div=%s V/div=%s 探头=×%s 白名单=%s"
                  % (list(cfg.scope.roi), hit, cfg.scope.time_per_div_s,
                     cfg.scope.volt_per_div_v, cfg.scope.probe_atten, cfg.scope.nominal_list()))
            rec["scope"] = {"color_hit_pct": round(hit, 2)}
    out["roi"] = rec

def main() -> int:
    ap = argparse.ArgumentParser(description="对已抓到的帧做一次性离线取证（不碰设备）")
    ap.add_argument("--raw", default="", help="原始 YUYV 文件（期望 4,147,200 B）")
    ap.add_argument("--png", default="", help="PNG 帧")
    ap.add_argument("--png2", default="", help="第二张 PNG（做帧间差，判是否 LIVE）")
    ap.add_argument("--config", default=os.path.join(os.path.dirname(HERE),
                                                     "config", "example_config.json"))
    ap.add_argument("--json-out", default="", help="把结论写成 JSON")
    a = ap.parse_args()
    if not (a.raw or a.png):
        ap.print_help()
        return 1

    out = {"note": "离线取证：未打开任何视频设备"}
    if a.raw:
        analyze_raw(a.raw, out)
    img1 = analyze_png(a.png, "2", out) if a.png else None
    img2 = analyze_png(a.png2, "3", out) if a.png2 else None
    if img1 is not None and img2 is not None:
        frame_diff(img1, img2, out)
    elif a.png2:
        print("\n[warn] 只有一张图能读，跳过帧间差")
    if img1 is not None:
        roi_report(img1, a.config, out)

    sec("结论速览")
    r = out.get("raw")
    if r:
        print("  原始帧：%s（0xFF %.2f%%，%s 版位流）"
              % (r["verdict"], r["ff_pct"], r["bitstream"]))
    if "frame_diff_pct" in out:
        print("  画面活性：帧间差 %.2f%% → %s"
              % (out["frame_diff_pct"], "LIVE" if out["frame_diff_pct"] > 1 else "静态/同帧"))

    if a.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(a.json_out)) or ".", exist_ok=True)
        with open(a.json_out, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print("  JSON -> %s" % a.json_out)
    print("\ndone（本工具未打开任何视频设备，零设备风险）")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
