#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""roi_stats.py —— 在**任意一张图**（真实抓帧或合成图）上量各 ROI 的统计量。

现场为什么要它
--------------
LED/颜色/汉字的阈值都要"看着真实画面调"。这个工具不猜、也不取流：
把图喂进来，它就把配置里每个 ROI 的**原始统计量**打出来，于是

* LED/颜色：`V 均值 / HSV 均值 / 色域命中率 / 与基线的 score / 判定结果` 一眼看到，
  阈值该往哪调有依据；
* 汉字：`灰度均值/标准差 / Otsu 阈值 / 前景占比 / 连通域个数`，
  能立刻判断"字是不是太小/太淡/被反光吃掉"；
* 示波器：波形掩膜的像素占比、有效列占比、ROI 内 HSV 分布。

用法
----
    # 先抓一帧（图上哪都可以），再量
    python3 tools/roi_stats.py --config config/example_config.json --image /tmp/f.png
    # 只量 LED / 只量 OCR
    python3 tools/roi_stats.py -c config/example_config.json -i /tmp/f.png --only led
    # 顺便把每个 ROI 抠出来存图（现场对位置最直观）
    python3 tools/roi_stats.py -c config/example_config.json -i /tmp/f.png --crop-dir /tmp/rois
    # 带全灭基线 JSON（LedDetector 的格式）就能直接给 score/ON-OFF
    python3 tools/roi_stats.py -c config/cfg.json -i /tmp/f.png --baseline config/led_baseline.json
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

from soc_vision.config import load_config                            
from soc_vision.led_detect import LedBaseline, LedDetector           

def _roi_of(img: np.ndarray, roi) -> np.ndarray:
    x, y, w, h = [int(v) for v in roi]
    H, W = img.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + w), min(H, y + h)
    return img[y0:y1, x0:x1]

def _hsv_stats(patch: np.ndarray) -> dict:
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    return {
        "bgr_mean": tuple(round(float(v), 1) for v in patch.reshape(-1, 3).mean(axis=0)),
        "gray_mean": round(float(gray.mean()), 1),
        "gray_std": round(float(gray.std()), 1),
        "gray_min": int(gray.min()), "gray_max": int(gray.max()),
        "h_mean": round(float(hsv[:, :, 0].mean()), 1),
        "s_mean": round(float(hsv[:, :, 1].mean()), 1),
        "v_mean": round(float(hsv[:, :, 2].mean()), 1),
        "v_std": round(float(hsv[:, :, 2].std()), 1),
    }

def _color_hit(patch: np.ndarray, lo, hi) -> float:
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, np.array(lo, np.uint8), np.array(hi, np.uint8))
    return round(float(np.count_nonzero(m)) / max(1, m.size) * 100.0, 2)

def main() -> int:
    ap = argparse.ArgumentParser(description="在图上量各 ROI 的统计量（标定辅助）")
    ap.add_argument("-c", "--config", required=True)
    ap.add_argument("-i", "--image", required=True)
    ap.add_argument("--only", choices=["led", "ocr", "scope", "all"], default="all")
    ap.add_argument("--crop-dir", default="", help="把每个 ROI 抠出来存这里")
    ap.add_argument("--baseline", default="", help="LED 全灭基线 JSON")
    a = ap.parse_args()

    cfg = load_config(a.config)
    img = cv2.imread(a.image, cv2.IMREAD_COLOR)
    if img is None:
        print("读不到图: %s" % a.image)
        return 1
    H, W = img.shape[:2]
    print("图: %s  %dx%d  BGR均值=%s" %
          (a.image, W, H, tuple(round(float(v), 1) for v in img.reshape(-1, 3).mean(axis=0))))

    crop = ""
    if a.crop_dir:
        os.makedirs(a.crop_dir, exist_ok=True)
        crop = a.crop_dir

    if a.only in ("all", "led"):
        print("\n== LED / 颜色 ROI（配置 led.items，顺序=FPGA ROI 编号）==")
        if not cfg.led.enabled:
            print("  (led.enabled=false，跳过)")
        det = None
        if a.baseline and os.path.isfile(a.baseline):
            with open(a.baseline, "r", encoding="utf-8") as f:
                det = LedDetector(cfg.led, LedBaseline.from_json(json.load(f)))
            print("  载入基线: %s" % a.baseline)
        for it in cfg.led.items:
            p = _roi_of(img, it.roi)
            if p.size == 0:
                print("  %-6s ROI %s 越界/为空" % (it.name, list(it.roi)))
                continue
            st = _hsv_stats(p)
            hit = _color_hit(p, it.hsv_lo, it.hsv_hi) if it.mode in ("mixed", "color") else None
            print("  %-6s roi=%-22s mode=%-6s BGR=(%s,%s,%s) gray=%.1f±%.1f H=%.1f S=%.1f V=%.1f±%.1f%s"
                  % (it.name, str(list(it.roi)), it.mode, st["bgr_mean"][0], st["bgr_mean"][1],
                     st["bgr_mean"][2], st["gray_mean"], st["gray_std"], st["h_mean"],
                     st["s_mean"], st["v_mean"], st["v_std"],
                     ("  色域命中=%.2f%%" % hit) if hit is not None else ""))
            if crop:
                cv2.imwrite(os.path.join(crop, "%s.png" % it.name),
                            cv2.resize(p, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST))
        if det is not None:
            states = det.detect(img)
            for s in states:
                print("  -> 判定 %-6s on=%-5s score=%+7.1f source=%s"
                      % (s.name, s.on, s.score, getattr(s, "source", "-")))
            bad = det.check_expect(states)
            print("  -> check_expect: %s" % (bad if bad else "全过"))

    if a.only in ("all", "ocr"):
        print("\n== 汉字 ROI（配置 ocr.items）==")
        if not cfg.ocr.enabled:
            print("  (ocr.enabled=false，跳过)")
        for it in cfg.ocr.items:
            p = _roi_of(img, it.roi)
            if p.size == 0:
                print("  %-6s ROI %s 越界/为空" % (it.name, list(it.roi)))
                continue
            g = cv2.cvtColor(p, cv2.COLOR_BGR2GRAY)
            _, bw = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            fg = float(np.count_nonzero(bw)) / bw.size * 100.0
            n, labels, stats, _ = cv2.connectedComponentsWithStats(bw, connectivity=8)
            areas = sorted([int(s) for s in stats[1:, cv2.CC_STAT_AREA]], reverse=True)[:6]
            print("  %-6s roi=%-20s engine=%-9s n_chars=%d split=%s"
                  % (it.name, str(list(it.roi)), it.engine, it.n_chars, it.split))
            print("         gray=%.1f±%.1f  前景(白)占比=%.1f%%  连通域=%d  最大几个面积=%s"
                  % (g.mean(), g.std(), fg, max(0, n - 1), areas))
            if crop:
                cv2.imwrite(os.path.join(crop, "%s.png" % it.name), p)

    if a.only in ("all", "scope"):
        print("\n== 示波器 ROI（图像法；SCPI 为主判据时这里只做交叉参考）==")
        x, y, w, h = [int(v) for v in cfg.scope.roi]
        p = _roi_of(img, cfg.scope.roi)
        if p.size == 0:
            print("  ROI %s 越界/为空" % str(list(cfg.scope.roi)))
        else:
            st = _hsv_stats(p)
            hit = _color_hit(p, cfg.scope.wave_hsv_lo, cfg.scope.wave_hsv_hi)
            gray = cv2.cvtColor(p, cv2.COLOR_BGR2GRAY)
            print("  roi=%s  BGR=(%s) H=%.1f S=%.1f V=%.1f  波形色域命中=%.2f%%"
                  % (str(list(cfg.scope.roi)), st["bgr_mean"], st["h_mean"],
                     st["s_mean"], st["v_mean"], hit))
            print("  标定: time/div=%s s  V/div=%s  探头=×%s  h_div=%s  grid_subdiv=%s  expect=%s"
                  % (cfg.scope.time_per_div_s, cfg.scope.volt_per_div_v, cfg.scope.probe_atten,
                     cfg.scope.h_div, cfg.scope.grid_subdiv, cfg.scope.nominal_list()))
            if crop:
                cv2.imwrite(os.path.join(crop, "scope.png"), p)
    if crop:
        print("\nROI 抠图(放大4x) -> %s" % crop)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
