#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_dist_quad_diag.py —— 直接复现 _find_quad 的轮廓过滤，看被哪一步筛掉。只读。"""
from __future__ import annotations
import json, os, sys
import numpy as np
from PIL import Image
HERE = os.path.dirname(os.path.abspath(__file__))
RADAR_DIR = os.path.dirname(HERE); WORKSPACE = os.path.dirname(RADAR_DIR)
BOARD = os.path.join(WORKSPACE, "afh03_board_setup")
JSON_PATH = os.path.join(RADAR_DIR, "markers_v2", "markers_v2.json")
for _p in (WORKSPACE, BOARD, os.path.join(BOARD, "soc_vision", "_vendor")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import cv2
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

def main():
    S = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    doc = json.load(open(JSON_PATH, encoding="utf-8"))
    mi = MarkerId(JSON_PATH, confirm_n=1, verbose=False)
    md = doc["markers"][int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 0]
    bg = panel_bg(seed=11)
    im = bg.copy(); im.paste(render_total(int(md["code_hex"], 16), S), (900, 480))
    bgr = np.asarray(im)[:, :, ::-1].copy()
    gray = (bgr[:, :, 0] * 0.114 + bgr[:, :, 1] * 0.587 + bgr[:, :, 2] * 0.299).astype(np.uint8)
    res = mi.md.detect_markers(gray, mi._codes, min_side_px=3, max_side_px=1058, max_hamming=1,
                               dark_win_frac=0.25) or []
    print("cands", [(round(r.s, 2), round(r.cx, 1), round(r.cy, 1)) for r in res])
    if not res:
        return
    x = res[0]
    got = mi._small_roi(bgr, x)
    up, m2, gain = got
    s = m2.s
    print("up", up.shape, "s2=%.2f cx=%.1f cy=%.1f gain=%.1f" % (s, m2.cx, m2.cy, gain))
    rad = 7.0 * s
    x0 = int(max(0, np.floor(m2.cx - rad))); x1 = int(min(up.shape[1], np.ceil(m2.cx + rad) + 1))
    y0 = int(max(0, np.floor(m2.cy - rad))); y1 = int(min(up.shape[0], np.ceil(m2.cy + rad) + 1))
    roi = up[y0:y1, x0:x1]
    print("roi", roi.shape, "cropcond", (x1 - x0) < 3.0 * s, (y1 - y0) < 3.0 * s)
    block = int(max(5, round(2.2 * s))); block += 1 if block % 2 == 0 else 0
    cut = float(max(5.0, 0.16 * s))
    bw = cv2.adaptiveThreshold(roi, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, block, cut)
    bw2 = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    for name, m in (("adapt", bw), ("otsu", bw2)):
        found = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cnts = found[0] if len(found) == 2 else found[1]
        tgt = (6.0 * s) ** 2
        print("%s: n=%d tgt=%.0f" % (name, len(cnts), tgt))
        for c in cnts:
            a = float(cv2.contourArea(c)); bx, by, bwd, bht = cv2.boundingRect(c)
            print("   a=%.0f a/tgt=%.2f bbox=%d,%d %dx%d  sizeok=%s centerok=%s"
                  % (a, a / tgt, bx, by, bwd, bht,
                     not (a < 0.20 * tgt or a > 2.6 * tgt) and not (bwd > 9.5 * s or bht > 9.5 * s
                     or bwd < 3.0 * s or bht < 3.0 * s),
                     (bx - 0.2 * s) <= (m2.cx - x0) <= (bx + bwd + 0.2 * s)
                     and (by - 0.2 * s) <= (m2.cy - y0) <= (by + bht + 0.2 * s)))
    if "--save" in sys.argv:
        Image.fromarray(up).save(os.path.join(HERE, "_quad_up_%d.png" % S))
        Image.fromarray(roi).save(os.path.join(HERE, "_quad_roi_%d.png" % S))
        Image.fromarray(bw).save(os.path.join(HERE, "_quad_bw_%d.png" % S))

if __name__ == "__main__":
    raise SystemExit(main())

