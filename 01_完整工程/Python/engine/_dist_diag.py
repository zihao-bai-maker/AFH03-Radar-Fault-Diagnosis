#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_dist_diag.py —— 单个尺寸的单例诊断（看候选/分项/ROI 上采样细节）。只读。"""
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

def main():
    sizes = [int(x) for x in (sys.argv[1].split(",") if len(sys.argv) > 1 else ["18", "20", "24", "28"])]
    doc = json.load(open(JSON_PATH, encoding="utf-8"))
    mi = MarkerId(JSON_PATH, confirm_n=1, verbose=False)
    codes = mi._codes
    for S in sizes:
        print("=" * 70)
        print("S=%dpx" % S)
        for md in doc["markers"][:3]:
            bg = panel_bg(seed=11)
            m = render_total(int(md["code_hex"], 16), S)
            im = bg.copy(); im.paste(m, (900, 480))
            bgr = np.asarray(im)[:, :, ::-1].copy()
            gray = (bgr[:, :, 0] * 0.114 + bgr[:, :, 1] * 0.587 + bgr[:, :, 2] * 0.299).astype(np.uint8)
            res = mi.md.detect_markers(gray, codes, min_side_px=3, max_side_px=1058,
                                       max_hamming=1, dark_win_frac=0.25) or []
            print(" %s: 原始候选 %d 个 %s" % (md["part"], len(res),
                  [(round(x.s, 2), round(8 * x.s, 1), x.rot, round(x.theta, 1)) for x in res[:4]]))
            for x in res[:2]:
                mod = mi.by_id.get(int(x.mid))
                if mod is None:
                    continue
                core = mi._verify_core(bgr, x, mod)
                got = mi._small_roi(bgr, x)
                print("   候选 mid=%d s=%.2f total=%.1f" % (x.mid, x.s, 8 * x.s))
                print("   core: pattern=%s sep=%s black=%s quiet=%s ink=%s mode=%s qc=%s dark_frac=%s veto=%s"
                      % (core.get("pattern_ok"), core.get("sep"), core.get("black_ok"), core.get("quiet"),
                         core.get("quiet_ink"), core.get("quad_mode"), core.get("quad_conf"),
                         core.get("dark_frac"), core.get("veto")))
                if got is not None:
                    up, m2, gain = got
                    b2 = mi._verify_core(up, m2, mod)
                    print("   up x%.1f: shape=%s s2=%.2f cx2=%.1f cy2=%.1f" % (gain, up.shape, m2.s, m2.cx, m2.cy))
                    print("   up  : pattern=%s sep=%s black=%s quiet=%s ink=%s mode=%s qc=%s dark_frac=%s fb=%s qz=%s dz=%s veto=%s"
                          % (b2.get("pattern_ok"), b2.get("sep"), b2.get("black_ok"), b2.get("quiet"),
                             b2.get("quiet_ink"), b2.get("quad_mode"), b2.get("quad_conf"),
                             b2.get("dark_frac"), b2.get("fb"), b2.get("qz"), b2.get("dz"), b2.get("veto")))
                    print("   up  : mode=%s conf=%s quad=%s" % (b2.get("quad_mode"), b2.get("quad_conf"),
                          mi.last_quad.get("quad")))
                    q, qc, qm = mi._find_quad(up, m2.cx, m2.cy, m2.s, m2.theta, rad_scale=7.0)
                    print("   find_quad: mode=%s conf=%s quad=%s" % (qm, qc, None if q is None else np.round(q, 1).tolist()))

                    if "-save" in sys.argv:
                        Image.fromarray(up).save(os.path.join(HERE, "_diag_up_%d.png" % S))

if __name__ == "__main__":
    raise SystemExit(main())

