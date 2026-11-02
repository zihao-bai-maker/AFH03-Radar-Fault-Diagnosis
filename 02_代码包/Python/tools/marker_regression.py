#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""marker_regression.py —— 标记识别**正/负样本回归**（防"只优化假阳性、误杀正样本"）。

正样本：把 G1..G6 分别贴到**无标记的真实面板照片**上 → 必须识别出对应模块
负样本：3 张**无标记**的真实照片 → 必须 0 检出
用法：python3 tools/marker_regression.py [--json out/marker_regression.json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                                    
from PIL import Image                                                 

from soc_vision.marker_id import MarkerId                             

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEG = ["/data/local/tmp/led_all/IMG_20260923_150527.jpg",
       "/data/local/tmp/led_all/IMG_20260923_150326_1.jpg",
       "/data/local/tmp/led_all/IMG_20260923_151448.jpg"]

def compose(base_rgb, mk_rgb, frac=0.09, pos="tr"):
    h, w = base_rgb.shape[:2]
    s = max(24, int(min(h, w) * frac))
    m = np.asarray(Image.fromarray(mk_rgb).resize((s, s), Image.LANCZOS))
    out = base_rgb.copy()
    x = w - s - 30 if pos == "tr" else 30
    y = 30
    out[y:y + s, x:x + s] = m
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    ap.add_argument("--markers", default=os.path.join(HERE, "markers"))
    ap.add_argument("--modules", default=os.path.join(HERE, "markers_modules.json"))
    a = ap.parse_args()
    mi = MarkerId(a.modules, confirm_n=1, verbose=False)
    mods = json.load(open(a.modules, encoding="utf-8"))["modules"]
    rows, npass, ntot = [], 0, 0

    for p in NEG:
        if not os.path.isfile(p):
            continue
        rgb = np.asarray(Image.open(p).convert("RGB"))
        hit, hits = mi.detect(rgb)
        ntot += 1
        ok = hit is None and not hits
        npass += 1 if ok else 0
        rows.append(("NEG", os.path.basename(p), "-", (hit.label if hit else f"假阳性x{len(hits)}"), ok))

    base = None
    for p in NEG:
        if os.path.isfile(p):
            base = np.asarray(Image.open(p).convert("RGB"))
            break
    if base is not None:
        for lab, m in sorted(mods.items()):
            bm = os.path.join(HERE, m.get("bitmap", ""))
            if not os.path.isfile(bm):
                continue
            mk = np.asarray(Image.open(bm).convert("RGB"))
            img = compose(base, mk)
            hit, hits = mi.detect(img)
            ntot += 1
            ok = hit is not None and hit.label == lab
            npass += 1 if ok else 0
            rows.append(("POS", lab, lab, (hit.label if hit else "未检出"), ok))
    print("%-5s %-28s %-7s %-12s %s" % ("类型", "样例", "期望", "实得", "通过"))
    for r in rows:
        print("%-5s %-28s %-7s %-12s %s" % (r[0], r[1], r[2], r[3], "OK" if r[4] else "**FAIL**"))
    print("\n通过 %d/%d = %.1f%%" % (npass, ntot, 100.0 * npass / max(1, ntot)))
    if a.json:
        json.dump([{"kind": r[0], "sample": r[1], "want": r[2], "got": r[3], "pass": r[4]} for r in rows],
                  open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return 0 if npass == ntot else 1

if __name__ == "__main__":
    raise SystemExit(main())
