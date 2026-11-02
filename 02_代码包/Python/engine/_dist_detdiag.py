#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_dist_detdiag.py —— 诊断：小尺寸下"检测器级"召回（markerdet 4x4 读取）vs "验证门"召回。只读。"""
from __future__ import annotations
import json, os, sys
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
RADAR_DIR = os.path.dirname(HERE)
WORKSPACE = os.path.dirname(RADAR_DIR)
BOARD = os.path.join(WORKSPACE, "afh03_board_setup")
JSON_PATH = os.path.join(RADAR_DIR, "markers_v2", "markers_v2.json")
for _p in (WORKSPACE, BOARD, os.path.join(BOARD, "soc_vision", "_vendor")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import marker as MK
from soc_vision.marker_id import MarkerId

def panel_bg(w=1920, h=1080, seed=1):
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    xn, yn = xx / w, yy / h
    base = 104 + 20 * xn + 8 * yn - 14 * ((xn - 0.55) ** 2 + (yn - 0.45) ** 2)
    base += 4 * np.sin(xn * 9.0) + 3 * np.cos(yn * 7.0)
    base += rng.normal(0, 3.2, (h, w)).astype(np.float32)
    rgb = np.stack([base * 1.015, base * 1.0, base * 0.975], axis=2)
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")

def render_total(code, total_px):
    return MK.render_marker(code, module_px=160, quiet=True).resize((int(total_px), int(total_px)),
                                                                    Image.LANCZOS)

def to_gray(bgr):
    return (bgr[:, :, 0] * 0.114 + bgr[:, :, 1] * 0.587 + bgr[:, :, 2] * 0.299).astype(np.uint8)

def main():
    doc = json.load(open(JSON_PATH, encoding="utf-8"))
    markers = doc["markers"]
    mi = MarkerId(JSON_PATH, confirm_n=1, verbose=False)
    codes = mi._codes
    sizes = [18, 20, 22, 24, 26, 28]
    print("%-6s %-12s %-12s %-12s %-10s %-10s" % ("S", "native", "up2x", "hamming2", "up2x+ham2", "avg_s"))
    for S in sizes:
        ok_n = ok_u = ok_h = ok_uh = 0
        ss = []
        for idx, md in enumerate(markers):
            bg = panel_bg(seed=500 + idx)
            im = bg.copy()
            m = render_total(int(md["code_hex"], 16), S)
            x, y = (1920 - S) // 2 + 20, (1080 - S) // 2 + 10
            im.paste(m, (x, y))
            bgr = np.asarray(im)[:, :, ::-1].copy()
            g = to_gray(bgr)
            up = mi._resize_up(g, 2.0)
            up3 = mi._resize_up(g, 3.0)

            def hit(gray, ham=1, scale=1.0, off=(0, 0)):
                r = mi.md.detect_markers(gray, codes, min_side_px=3, max_side_px=int(0.9 * min(gray.shape)),
                                         max_hamming=ham, dark_win_frac=0.25) or []
                if not r:
                    return False, None
                best = r[0]
                return int(best.mid) == int(md["id"]), best.s

            a, s1 = hit(g)
            b, s2 = hit(up)
            c, _ = hit(g, ham=2)
            d, _ = hit(up, ham=2)
            ok_n += 1 if a else 0
            ok_u += 1 if b else 0
            ok_h += 1 if c else 0
            ok_uh += 1 if d else 0
            if s1:
                ss.append(s1)
        print("%-6d %-12s %-12s %-12s %-12s %s"
              % (S, "%d/18" % ok_n, "%d/18" % ok_u, "%d/18" % ok_h, "%d/18" % ok_uh,
                 ("%.2f" % (sum(ss) / len(ss))) if ss else "-"))

if __name__ == "__main__":
    raise SystemExit(main())
