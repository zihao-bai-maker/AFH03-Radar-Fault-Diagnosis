#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_dist_probe.py —— 远距离（小像素尺寸）识别率探针（离屏，不碰板子、不改生产文件）。

做法
----
把 markers_v2 的 18 个标记按 **含静区总边长 S px** 渲染，贴到 1920x1080 的模拟面板
（暖灰渐变 + 噪声）上，用**与板端 MarkerWorker 完全一致**的调用方式跑
``MarkerId.detect(frame, min_side_px=max(16,int(0.015*short)), max_side_px=int(0.98*short))``，
统计每个 S 的识别率（18 个标记里成功几个）。

跑法
----
    python _dist_probe.py                          # 默认 18/20/24/28/32/40/80/200/400
    python _dist_probe.py --sizes 16,18,20,22,24    # 自定义
    python _dist_probe.py --blur 0.6 --angle 15     # 模拟镜头模糊 / 手持角度
    python _dist_probe.py --fail                    # 打印失败用例的 veto 分项

只读：不改 marker_id.py / 不写任何生产 JSON。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

import numpy as np
from PIL import Image, ImageFilter

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

def render_total(code: int, total_px: int, blur: float = 0.0,
                 dx: float = 0.0, dy: float = 0.0) -> Image.Image:
    hi = MK.render_marker(code, module_px=160, quiet=True)
    m = hi.resize((int(total_px), int(total_px)), Image.LANCZOS)
    if blur > 0:
        m = m.filter(ImageFilter.GaussianBlur(float(blur)))
    if dx or dy:

        
        m = m.transform(m.size, Image.AFFINE, (1, 0, -dx, 0, 1, -dy),
                        resample=Image.BICUBIC, fillcolor=(255, 255, 255))
    return m

def make_mi(min_total: float = 0.0, small_total: float = 0.0):
    mi = MarkerId(JSON_PATH, confirm_n=1, verbose=False,
                  min_total_px=min_total, small_total_px=small_total)
    mi.latch_sec = 0.0
    mi.window_sec = 0.5
    return mi

def reset(mi):
    mi._hist = []
    mi._latch = None
    mi._prev = None
    mi.progress = (0, 0)

def one(mi, bgr, lo, hi):
    return mi.detect(bgr, min_side_px=lo, max_side_px=hi)

def run_sizes(sizes: List[int], reps: int = 1, blur: float = 0.0, angle: float = 0.0,
              fail: bool = False, seed0: int = 700, min_total: float = 0.0,
              small_total: float = 0.0) -> Dict[str, Any]:
    doc = json.load(open(JSON_PATH, encoding="utf-8"))
    markers = doc["markers"]
    mi = make_mi(min_total, small_total)
    out: Dict[str, Any] = {"sizes": {}, "blur": blur, "angle": angle, "reps": reps}

    rec: List[Dict[str, Any]] = []
    orig_verify = mi.verify

    def _verify(bgr, m, mod=None):
        br = orig_verify(bgr, m, mod)
        rec.append({"label": (mod or {}).get("label", "?"), "side": float(getattr(m, "s", 0)),
                    "br": dict(br)})
        return br

    mi.verify = _verify          
    H, W = 1080, 1920
    lo = max(16, int(0.015 * min(H, W)))
    hi = int(0.98 * min(H, W))
    for S in sizes:
        ok = 0
        tot = 0
        bad = []
        t0 = time.perf_counter()
        for rep in range(reps):
            for idx, md in enumerate(markers):
                code = int(md["code_hex"], 16)
                seed = seed0 + idx * 13 + rep * 101 + S
                bg = panel_bg(seed=seed)

                rng0 = np.random.default_rng(seed + 3)
                dx = float(rng0.uniform(-0.5, 0.5))
                dy = float(rng0.uniform(-0.5, 0.5))
                m = render_total(code, S, blur=blur, dx=dx, dy=dy)
                if angle:
                    m = m.rotate(angle, expand=True, resample=Image.BICUBIC,
                                 fillcolor=tuple(np.asarray(bg)[0, 0].tolist()))

                rng = np.random.default_rng(seed + 5)
                x = int((W - m.size[0]) / 2 + rng.integers(-60, 61))
                y = int((H - m.size[1]) / 2 + rng.integers(-40, 41))
                x = max(0, min(W - m.size[0], x))
                y = max(0, min(H - m.size[1], y))
                im = bg.copy()
                im.paste(m, (x, y))
                bgr = np.asarray(im)[:, :, ::-1].copy()
                reset(mi)
                rec.clear()
                hit, hits = one(mi, bgr, lo, hi)
                tot += 1
                good = hit is not None and int(hit.marker_id) == int(md["id"])
                ok += 1 if good else 0
                if not good:
                    vs = [r["br"].get("veto", "") for r in rec] or ["(无候选)"]
                    bad.append({"part": md["part"], "id": md["id"],
                                "score": (hit.score if hit is not None else 0.0),
                                "n_hits": len(hits),
                                "votes": vs[:3],
                                "bd": rec[0]["br"] if rec else {}})
        rate = (100.0 * ok / tot) if tot else 0.0
        out["sizes"][str(S)] = {"ok": ok, "tot": tot, "rate": round(rate, 1),
                                "sec": round(time.perf_counter() - t0, 1),
                                "bad": bad}
        print("  S=%4dpx : %2d/%2d = %5.1f%%  (%.1fs)"
              % (S, ok, tot, rate, time.perf_counter() - t0), flush=True)
        if fail:
            for b in bad[:6]:
                bd = b["bd"]
                print("        - %-4s id=%-2d score=%.2f n_hits=%d veto=%s | pattern=%s sep=%s "
                      "black=%s dz=%s dark_frac=%s quiet=%s mode=%s qc=%s"
                      % (b["part"], b["id"], b["score"], b["n_hits"],
                         "|".join(str(v) for v in b["votes"]),
                         bd.get("pattern_ok"), bd.get("sep"), bd.get("black_ok"),
                         bd.get("dz"), bd.get("dark_frac"), bd.get("quiet"),
                         bd.get("quad_mode"), bd.get("quad_conf")))
            if len(bad) > 6:
                print("        ... 其余 %d 个失败略" % (len(bad) - 6))
    return out

def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="小像素尺寸识别率探针")
    ap.add_argument("--sizes", default="18,20,24,28,32,40,80,200,400")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--blur", type=float, default=0.0)
    ap.add_argument("--angle", type=float, default=0.0)
    ap.add_argument("--fail", action="store_true")
    ap.add_argument("--min-total", type=float, default=0.0)
    ap.add_argument("--small-total", type=float, default=0.0)
    ap.add_argument("--json", default="")
    a = ap.parse_args(argv)
    sizes = [int(x) for x in a.sizes.split(",") if x.strip()]
    print("markers_v2 18 个；含静区总边长 S=18..400px；1920x1080 模拟面板")
    if a.blur or a.angle:
        print("退化：blur=%.2fpx angle=%.1f°" % (a.blur, a.angle))
    res = run_sizes(sizes, reps=a.reps, blur=a.blur, angle=a.angle, fail=a.fail,
                    min_total=a.min_total, small_total=a.small_total)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        print("-> %s" % a.json)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

