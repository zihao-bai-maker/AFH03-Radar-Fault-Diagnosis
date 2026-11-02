#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""seg7_read.py —— 7 段数码管读数 CLI（⑨ 配电盘）：读数 + 标注图 + 与 numeric_range 联动。

    python3 tools/seg7_read.py -i IMG_20260923_151230.jpg --out out/seg7_annot.png --json out/seg7.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                                    
from PIL import Image                                                  

from soc_vision import seg7                                           

def main():
    ap = argparse.ArgumentParser(description="7 段数码管读数（⑨ 配电盘）")
    ap.add_argument("-i", "--image", required=True)
    ap.add_argument("--out", default="", help="标注图输出路径")
    ap.add_argument("--json", default="", help="读数 JSON 输出路径")
    ap.add_argument("--work-long", type=int, default=seg7.WORK_LONG)
    ap.add_argument("--min-area", type=int, default=12)
    ap.add_argument("--expect", default="", help='真值核对，例如 "26.6,222,00307.6"（逗号分隔）')
    a = ap.parse_args()
    img = seg7.load_rgb(a.image, a.work_long)
    print("图像(工作分辨率) = %dx%d  文件=%s" % (img.shape[1], img.shape[0], os.path.basename(a.image)))
    disps = seg7.read_displays(img, min_area=a.min_area)
    print("检出显示块 = %d 个" % len(disps))
    rows = []
    for d in disps:
        print("  bbox=%-22s 读数=%-14s 位数=%d 平均置信=%.3f"
              % (str(tuple(int(v) for v in d.box)), repr(d.text), d.n_digits, d.conf))
        for dd in d.digits:
            if dd.dot:
                continue
            print("      位 '%s' conf=%.2f hamming=%d segs=%s x=[%d,%d]"
                  % (dd.ch, dd.conf, dd.hamming, dd.segs, dd.x0, dd.x1))
        rows.append(d.to_dict())
    if a.expect:
        want = [x.strip() for x in a.expect.split(",") if x.strip()]
        got = [d.text for d in disps]
        print("\n真值核对：期望 %s" % want)
        for w in want:
            hit = any(g == w for g in got)   
            print("  %-10s -> %s" % (w, "命中 ✔" if hit else "未命中 ✗"))
    if a.out:
        ann = seg7.annotate(img, disps)
        os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
        Image.fromarray(ann).save(a.out)
        print("\n标注图 -> %s" % a.out)
    if a.json:
        os.makedirs(os.path.dirname(os.path.abspath(a.json)) or ".", exist_ok=True)
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"file": os.path.basename(a.image), "displays": rows}, f,
                      ensure_ascii=False, indent=2)
        print("JSON -> %s" % a.json)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
