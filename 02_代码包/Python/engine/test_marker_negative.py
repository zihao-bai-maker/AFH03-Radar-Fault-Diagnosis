#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_marker_negative.py —— **真图无标记 => 0 误检**的负样本回归（项目铁律：宁可不判，绝不误判）。

为什么要有这个测试
------------------
现场 119 张 ``雷达照片_今天/拍照UI照片`` **一张标记都没贴**。只要标记模态误检一次，
``part_recognizer`` 里 marker 权重 1.00 => 融合分被顶到 ≥0.95 => 直接误判部位。
2026-10-18 实测：``IMGP_20260427_201938.jpg``（Z31 电源控制面板）被判成 **Z4 score=0.96**，
根因是方形按钮"上亮下暗"的纹理凑巧与 Z4 码字差 1 bit，而旧的 pattern 门限只有 0.55 且
``max(a1, 1-a1)`` 极性无关 => 15/16 也放行。本文件把这个场景固化成回归。

跑法
----
    python test_marker_negative.py              # 119 张全跑（marker_id 检测接口，约 4~6 分钟）
    python test_marker_negative.py --sample 20  # 冒烟：只跑前 20 张
    python test_marker_negative.py --with-part  # 额外用 part_recognizer.MarkerBackend 再跑一遍
    python test_marker_negative.py --quick      # 只跑 201938 这一张锚点用例（秒级）

判定
----
* **硬指标**：``命中数 == 0``（任何一张判出标记 => 退出码 1，并打印文件名 + id + 全部分项）；
* 同时打印**被否决的候选**（近失），便于看清"差多少被拦住"——这是防止下次放松门限的可视化；
* 每张图都重置单帧状态（生产里 MarkerBackend 用 confirm_n=1 / latch_sec=0）。

只读：本测试不改任何生产文件、不碰板子、不联网。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(os.path.dirname(HERE))
BOARD_DIR = os.path.join(WORKSPACE, "afh03_board_setup")
RADAR_DIR = os.path.dirname(HERE)
PHOTO_DIR = os.path.join(WORKSPACE, "雷达照片_今天", "拍照UI照片")
MARKERS_JSON = os.path.join(RADAR_DIR, "markers_v2", "markers_v2.json")
ANCHOR = "IMGP_20260427_201938.jpg"          

for _p in (HERE, BOARD_DIR, os.path.join(BOARD_DIR, "soc_vision", "_vendor")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    import numpy as np
except Exception:  
    np = None  

try:
    import cv2
except Exception:  
    cv2 = None  

_PASS: List[str] = []
_FAIL: List[str] = []

def check(name: str, fn) -> None:
    t0 = time.time()
    try:
        detail = fn()
        _PASS.append(name)
        print("  [PASS] %-34s %6.1fs  %s" % (name, time.time() - t0, detail or ""))
    except Exception as e:  
        _FAIL.append("%s: %s" % (name, e))
        print("  [FAIL] %-34s %6.1fs  %s: %s" % (name, time.time() - t0, type(e).__name__, e))

def load_bgr(path: str):
    if cv2 is None:
        return None
    try:
        return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    except Exception:  
        return None

def list_photos() -> List[str]:
    if not os.path.isdir(PHOTO_DIR):
        return []
    return sorted(f for f in os.listdir(PHOTO_DIR) if f.lower().endswith((".jpg", ".jpeg", ".png")))

def make_marker_id():
    from soc_vision.marker_id import MarkerId  
    mi = MarkerId(MARKERS_JSON, confirm_n=1, verbose=False)

    mi.latch_sec = 0.0
    mi.window_sec = 0.5
    return mi

def _reset(mi) -> None:
    mi._hist = []
    mi._latch = None
    mi._prev = None
    mi.progress = (0, 0)

def raw_candidates(mi, bgr) -> List[Dict[str, Any]]:
    """诊断用：把**原始候选**（含被 verify 否决的）连分项一起拿出来。

    只读内部接口；拿不到就返回空（不影响主判定的硬指标）。
    """
    md = getattr(mi, "md", None)
    codes = getattr(mi, "_codes", None)
    if md is None or codes is None or cv2 is None:
        return []
    gray = (bgr[:, :, 0] * 0.114 + bgr[:, :, 1] * 0.587 + bgr[:, :, 2] * 0.299).astype("uint8")
    h, w = bgr.shape[:2]
    mn = max(3, int(24 / 8.0))
    mx = int(0.9 * min(h, w))
    try:
        res = md.detect_markers(gray, codes, min_side_px=mn, max_side_px=mx,
                                max_hamming=int(getattr(mi, "max_hamming", 1)),
                                dark_win_frac=float(getattr(mi, "dark_win_frac", 0.25))) or []
    except Exception:  
        return []
    out: List[Dict[str, Any]] = []
    for m in res:
        mid = int(getattr(m, "mid", getattr(m, "id", -1)))
        mod = (getattr(mi, "by_id", {}) or {}).get(mid)
        if mod is None:
            continue
        try:
            br = mi.verify(bgr, m, mod)
        except Exception:  
            br = {}
        out.append({"label": mod.get("label", "?"), "marker_id": mid,
                    "rot": int(getattr(m, "rot", -1)), "score": float(br.get("score", 0.0)),
                    "breakdown": br})
    return out

def scan_marker_id(mi, images: Sequence[str],
                   collect_near: bool = False) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """返回 (误检列表, 被否决候选列表)。误检 = detect() 确认出标记。

    ``collect_near=True`` 会额外跑一遍原始候选做诊断（耗时约 x2），默认关闭。
    """
    false_hits: List[Dict[str, Any]] = []
    near: List[Dict[str, Any]] = []
    for k, name in enumerate(images):
        bgr = load_bgr(os.path.join(PHOTO_DIR, name))
        if bgr is None:
            continue
        _reset(mi)
        hit, _hits = mi.detect(bgr)
        if hit is not None:
            false_hits.append({"image": name, "hit": hit.to_dict(), "breakdown": dict(hit.breakdown)})
        if collect_near:
            for c in raw_candidates(mi, bgr):
                if not str(c["breakdown"].get("veto", "")):
                    continue    
                near.append(dict(c, image=name))
        if (k + 1) % 20 == 0:
            print("        scanned %d/%d  命中=%d  否决候选=%d"
                  % (k + 1, len(images), len(false_hits), len(near)), flush=True)
    return false_hits, near

def _fmt(bd: Dict[str, Any]) -> str:
    keys = ("contrast", "quiet", "quiet_ink", "rel", "black_ok", "pattern_ok", "data_ok", "theta", "score")
    return " ".join("%s=%s" % (k, bd.get(k)) for k in keys)

def report_false_hits(false_hits: List[Dict[str, Any]], near: List[Dict[str, Any]], n_img: int) -> str:
    print("        真图 %d 张：**误检 %d 个**" % (n_img, len(false_hits)))
    for r in false_hits:
        print("        [X] %-26s -> %-6s id=%-2d score=%.2f  %s"
              % (r["image"], r["hit"].get("label"), int(r["hit"].get("marker_id", -1)),
                 float(r["hit"].get("score", 0.0)), _fmt(r["breakdown"])))
    if near:
        print("        被否决的候选（近失，供核对门限余量）：%d 个" % len(near))
        for r in near[:20]:
            bd = r["breakdown"]
            print("          ~ %-26s %-6s id=%-2d score=%.2f pattern=%s veto=%s"
                  % (r["image"], r["label"], r["marker_id"], r["score"],
                     bd.get("pattern_ok"), bd.get("veto")))
        if len(near) > 20:
            print("          ... 其余 %d 个略" % (len(near) - 20))
    return "命中=%d/%d 近失=%d" % (len(false_hits), n_img, len(near))

def t_anchor() -> str:
    path = os.path.join(PHOTO_DIR, ANCHOR)
    assert os.path.isfile(path), "缺锚点图 %s" % path
    mi = make_marker_id()
    bgr = load_bgr(path)
    assert bgr is not None, "读不到 %s" % ANCHOR
    hit, hits = mi.detect(bgr)
    if hit is not None:
        raise AssertionError("%s 仍被误判为 %s id=%d score=%.2f 分项=%s"
                             % (ANCHOR, hit.label, hit.marker_id, hit.score, _fmt(hit.breakdown)))
    return "0 命中（候选 %d 个已被否决）" % len(hits)

def t_all_photos(sample: int = 0, collect_near: bool = False) -> str:
    images = list_photos()
    assert images, "照片目录为空/不存在：%s" % PHOTO_DIR
    if sample:
        images = images[:sample]
    mi = make_marker_id()
    false_hits, near = scan_marker_id(mi, images, collect_near=collect_near)
    detail = report_false_hits(false_hits, near, len(images))
    assert not false_hits, "真图无标记却误检 %d 个（见上表）" % len(false_hits)
    return detail

def t_part_backend(sample: int = 0) -> str:
    from part_recognizer import MarkerBackend  
    be = MarkerBackend(MARKERS_JSON, verbose=False)
    assert be.ok, "MarkerBackend 不可用：%s" % be.error
    images = list_photos()
    assert images, "照片目录为空"
    if sample:
        images = images[:sample]
    bad = []
    for k, name in enumerate(images):
        bgr = load_bgr(os.path.join(PHOTO_DIR, name))
        if bgr is None:
            continue
        r = be.detect(bgr)
        if r:
            bad.append((name, r))
        if (k + 1) % 25 == 0:
            print("        part-backend scanned %d/%d 误检=%d" % (k + 1, len(images), len(bad)), flush=True)
    for name, r in bad:
        print("        [X] %-26s -> %s id=%s score=%.2f" %
              (name, r.get("part"), r.get("marker_id"), float(r.get("score", 0))))
    assert not bad, "part_recognizer marker 模态误检 %d 个" % len(bad)
    return "0 命中/%d" % len(images)

def main(argv: Optional[Sequence[str]] = None) -> int:
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(errors=replace)      
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="真图无标记 => 0 误检（负样本回归）")
    ap.add_argument("--sample", type=int, default=0, help="只跑前 N 张（冒烟用）")
    ap.add_argument("--with-part", action="store_true", help="再用 part_recognizer.MarkerBackend 跑一遍")
    ap.add_argument("--near", action="store_true", help="额外统计被否决的候选（耗时 x2，诊断用）")
    ap.add_argument("--quick", action="store_true", help="只跑锚点单张")
    a = ap.parse_args(argv)

    print("=" * 78)
    print("marker 负样本回归：真图无标记 => 期望 0 误检")
    print("图片目录：%s" % PHOTO_DIR)
    print("=" * 78)
    if not os.path.isdir(PHOTO_DIR):
        print("  [FAIL] 照片目录不存在")
        return 1

    check("1. 锚点 201938（曾误判 Z4）", t_anchor)
    if not a.quick:
        check("2. 全部真图 0 误检", lambda: t_all_photos(a.sample, collect_near=a.near))
        if a.with_part:
            check("3. part_recognizer marker 模态", lambda: t_part_backend(a.sample))

    print("-" * 78)
    print("PASS %d / %d" % (len(_PASS), len(_PASS) + len(_FAIL)))
    for f in _FAIL:
        print("  FAIL:", f)
    print("=" * 78)
    return 0 if not _FAIL else 1

if __name__ == "__main__":
    raise SystemExit(main())
