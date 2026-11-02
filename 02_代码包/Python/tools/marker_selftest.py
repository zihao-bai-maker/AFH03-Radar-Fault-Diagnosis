#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""marker_selftest.py —— 标记识别自检：把 M1..M9 合成到实拍帧上（多尺度/多朝向）→ 报识别率与误检。

做法（不需要真实打印纸）：
  把每个 M*.png 缩放后**贴到实拍帧的一个已知位置**（可再加旋转 0/90/180/270），
  跑 `MarkerId.detect` -> 看是否return 出正确的 label；统计 命中率 / 误检 / 阈值。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                                    
import cv2                                                            

def composite(frame, mk, scale, rot, x, y):
    """把标记位图缩放/旋转后贴到 frame 的 (x,y)。"""
    h, w = mk.shape[:2]
    size = max(24, int(round(w * scale)))
    m = cv2.resize(mk, (size, size), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
    if rot:
        m = np.rot90(m, rot // 90)
    mh, mw = m.shape[:2]
    fh, fw = frame.shape[:2]
    x, y = max(0, min(fw - mw, x)), max(0, min(fh - mh, y))
    out = frame.copy()
    out[y:y + mh, x:x + mw] = m
    return out

def main():
    ap = argparse.ArgumentParser(description="标记识别自检（合成贴图）")
    ap.add_argument("--markers", default="/home/rock/afh03_board_setup/markers")
    ap.add_argument("--frame", default="/data/local/tmp/led_all/IMG_20260923_150326_1.jpg")
    ap.add_argument("--json", default="/home/rock/afh03_board_setup/markers_modules.json")
    ap.add_argument("--scales", default="0.10,0.16,0.22,0.30")
    ap.add_argument("--rot", default="0,90,180,270")
    ap.add_argument("--out-dir", default="/home/rock/afh03_board_setup/out/marker_selftest")
    a = ap.parse_args()
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from soc_vision.marker_id import MarkerId
    os.makedirs(a.out_dir, exist_ok=True)
    frame = cv2.imread(a.frame, cv2.IMREAD_COLOR)
    if frame is None:
        print("读不到实拍帧 %s" % a.frame)
        return 1
    W = 1536
    k = W / max(frame.shape[:2])
    if k < 1:
        frame = cv2.resize(frame, (int(frame.shape[1] * k), int(frame.shape[0] * k)))
    print("实拍帧尺寸 = %dx%d" % (frame.shape[1], frame.shape[0]))

    

    with open(a.json, encoding="utf-8") as _jf:
        _mods = (json.load(_jf).get("modules") or {})
    files = []
    for _lab, _m in sorted(_mods.items()):
        _bm = _m.get("bitmap") or ""
        _p = _bm if os.path.isabs(_bm) else os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), _bm)
        if os.path.isfile(_p):
            files.append(_p)
        else:
            print("  警告：JSON 指定的模板不存在 %s" % _p)
    print("从 JSON 取到 %d 个模板（**不做 glob**，避免 M/G 混判）" % len(files))
    mi = MarkerId(a.json, confirm_n=1, verbose=False)
    print("映射载入: %d 个模块；码本=%s" % (len(mi.by_id), "有" if mi._codes else "无"))
    scales = [float(x) for x in a.scales.split(",")]
    rots = [int(x) for x in a.rot.split(",")]
    tot = ok = 0
    rows = []
    false_pos = 0
    for f in files:
        mk = cv2.imread(f, cv2.IMREAD_COLOR)
        if mk is None:
            continue
        label = os.path.splitext(os.path.basename(f))[0]
        want = int(((mi.data.get("modules", {}).get(label, {}) or {}).get("marker_id", -1)))
        for sc in scales:
            for rot in rots:
                tot += 1
                img = composite(frame, mk, sc, rot,
                                x=int(frame.shape[1] * 0.25) + rot,
                                y=int(frame.shape[0] * 0.35) + int(sc * 300))
                hit, hits = mi.detect(img)
                got = hit.label if hit else ""
                good = (got == label)
                ok += 1 if good else 0
                if hits and not good:
                    pass
                rows.append((label, sc, rot, got, (hit.score if hit else 0.0), len(hits)))
                if good and len(hits) > 1:
                    false_pos += len(hits) - 1
    print("\n%-6s %-7s %-5s %-6s %-7s %s" % ("标记", "缩放", "旋转", "识别", "分数", "候选数"))
    for r in rows[:24]:
        print("%-6s %-7.2f %-5d %-6s %-7.2f %d" % (r[0], r[1], r[2], r[3] or "-", r[4], r[5]))
    if len(rows) > 24:
        print("…（共 %d 条，省略后 %d 条）" % (len(rows), len(rows) - 24))
    print("\n**识别率 = %d/%d = %.1f%%** ；多余候选(误检线索) = %d"
          % (ok, tot, 100.0 * ok / max(1, tot), false_pos))

    if files:
        mk = cv2.imread(files[5] if len(files) > 5 else files[0], cv2.IMREAD_COLOR)
        img = composite(frame, mk, scales[1] if len(scales) > 1 else scales[0], 0,
                        int(frame.shape[1] * 0.25), int(frame.shape[0] * 0.35))
        p = os.path.join(a.out_dir, "composite_sample.jpg")
        cv2.imwrite(p, img)
        print("样例合成图 -> %s" % p)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
