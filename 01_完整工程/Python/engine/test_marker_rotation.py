#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_marker_rotation.py —— ★ 标记「任意角度 + 透视」正样本回归（2026-10-18 现场 45° 问题固化）

背景
----
现场把 Z12 标记**斜着拿（约 45°）**时，旧 ``marker_id.verify`` 按"轴对齐 8×8 格"采样，
分项只剩 ``pattern_ok=0.50 / contrast=0.23`` → 被拒。本测试把该场景固化成回归：

1. ``markers_v2`` 的 **18 个标记**在 0° 下必须 **18/18**；
2. 旋转 **0/15/30/45/60/75/90/180/270** 全部要过（旧实现只测 0/90/180/270）；
3. **透视**（单应：上边缩短、下边加宽 + 旋转 30°/45°）必须过；
4. **45° + 压暗/模糊/噪声/JPEG**（模拟现场逆光、白纸发灰）必须过。

跑法
----
    python test_marker_rotation.py              # 全量（约 1~2 分钟）
    python test_marker_rotation.py --quick      # 18 个 × 0/45 两档冒烟
    python test_marker_rotation.py -v           # 失败时打印分项

只读：不改生产文件、不碰板子、不联网。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from typing import Dict, List, Tuple

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(os.path.dirname(HERE))
BOARD_DIR = os.path.join(WORKSPACE, "afh03_board_setup")
RADAR_DIR = os.path.dirname(HERE)
MARKERS_JSON = os.path.join(RADAR_DIR, "markers_v2", "markers_v2.json")

for _p in (HERE, BOARD_DIR, os.path.join(BOARD_DIR, "soc_vision", "_vendor")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import cv2                                                    
import marker as MK                                           
from soc_vision.marker_id import MarkerId                     

W, H = 1280, 720

def panel_bg(seed: int = 1) -> Image.Image:
    """模拟现场面板：暖灰渐变 + 暗角 + 噪声（与 selfcheck_markers_v2 同风格）。"""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    xn, yn = xx / W, yy / H
    base = 104 + 20 * xn + 8 * yn - 14 * ((xn - 0.55) ** 2 + (yn - 0.45) ** 2)
    base += 4 * np.sin(xn * 9.0) + 3 * np.cos(yn * 7.0)
    base += rng.normal(0, 3.2, (H, W)).astype(np.float32)
    rgb = np.stack([base * 1.015, base * 1.0, base * 0.975], axis=2)
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")

def paper_marker(code: int, total_px: int, pad_frac: float = 0.10) -> Image.Image:
    """渲染标记到一张小白纸（RGBA），总边长=含静区 8 模块。"""
    mk = MK.render_marker(code, module_px=120, quiet=True)
    pad = int(mk.size[0] * pad_frac)
    paper = Image.new("RGBA", (mk.size[0] + 2 * pad, mk.size[1] + 2 * pad), (250, 250, 247, 255))
    paper.paste(mk.convert("RGBA"), (pad, pad))
    return paper.resize((int(total_px * (1 + 2 * pad_frac)),) * 2, Image.LANCZOS)

def compose(paper: Image.Image, angle: float, seed: int = 1,
            degrade: Dict[str, float] | None = None) -> np.ndarray:
    """把纸片旋转后贴到面板上（alpha 合成），返回 BGR。"""
    bg = panel_bg(seed)
    p = paper.rotate(angle, expand=True, resample=Image.BICUBIC, fillcolor=(0, 0, 0, 0))
    x = (W - p.size[0]) // 2
    y = (H - p.size[1]) // 2
    bg.paste(p, (x, y), p)
    if degrade:
        if degrade.get("brightness"):
            bg = ImageEnhance.Brightness(bg).enhance(degrade["brightness"])
        if degrade.get("contrast"):
            bg = ImageEnhance.Contrast(bg).enhance(degrade["contrast"])
        if degrade.get("blur"):
            bg = bg.filter(ImageFilter.GaussianBlur(degrade["blur"]))
        if degrade.get("noise"):
            a = np.asarray(bg).astype(np.float32)
            a += np.random.default_rng(seed + 7).normal(0, degrade["noise"], a.shape)
            bg = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGB")
        if degrade.get("jpeg"):
            buf = io.BytesIO()
            bg.save(buf, "JPEG", quality=int(degrade["jpeg"]))
            buf.seek(0)
            bg = Image.open(buf).convert("RGB")
        if degrade.get("wash"):                      
            a = np.asarray(bg).astype(np.float32)
            k, off = degrade["wash"]
            a = a * k + off
            bg = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGB")
    return np.asarray(bg)[:, :, ::-1].copy()

def compose_persp(paper: Image.Image, angle: float, top_frac: float = 0.78,
                  side_skew: float = 0.06, seed: int = 1) -> np.ndarray:
    """★ 透视：把纸片四角映射成梯形（上边短、左低右高），并整体旋转 angle。"""
    bg = np.asarray(panel_bg(seed))[:, :, ::-1].copy()
    h, w = paper.size
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])

    t = np.deg2rad(angle)
    ct, st = np.cos(t), np.sin(t)
    base = 0.72 * H
    corners = np.float32([[-base / 2, -base / 2], [base / 2, -base / 2],
                          [base / 2, base / 2], [-base / 2, base / 2]])
    rot = np.stack([corners[:, 0] * ct - corners[:, 1] * st,
                    corners[:, 0] * st + corners[:, 1] * ct], axis=1)
    dst = rot.copy()

    depth = (dst[:, 1] - dst[:, 1].min()) / max(1e-6, np.ptp(dst[:, 1]))
    scale = top_frac + (1.0 - top_frac) * depth
    dst[:, 0] *= scale
    dst[:, 1] += side_skew * base * (dst[:, 0] / max(1e-6, np.abs(dst[:, 0]).max()))
    dst += np.float32([W / 2, H / 2])
    M = cv2.getPerspectiveTransform(src, dst.astype(np.float32))
    paper_rgba = np.asarray(paper.convert("RGBA"))
    warped = cv2.warpPerspective(paper_rgba, M, (W, H), flags=cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
    a = (warped[:, :, 3:4].astype(np.float32) / 255.0)
    out = warped[:, :, :3].astype(np.float32) * a + bg.astype(np.float32) * (1 - a)
    return np.clip(out, 0, 255).astype(np.uint8)

def make_mi() -> MarkerId:
    mi = MarkerId(MARKERS_JSON, confirm_n=1, verbose=False, max_side_frac=0.80)
    mi.latch_sec = 0.0
    mi.window_sec = 0.5
    return mi

def reset(mi: MarkerId) -> None:
    mi._hist = []
    mi._latch = None
    mi._prev = None
    mi.progress = (0, 0)
    mi.last_quad = {}

def check(mi: MarkerId, bgr: np.ndarray, label: str, verbose: bool = False) -> Tuple[bool, str]:
    reset(mi)
    hit, hits = mi.detect(bgr)
    ok = hit is not None and hit.label == label
    detail = ""
    if not ok:
        if hits:
            h0 = hits[0]
            detail = "%s score=%.2f %s" % (h0.label, h0.score, h0.breakdown)
        else:
            detail = "无候选"
        if verbose:
            print("      [FAIL] %s -> %s" % (label, detail))
    return ok, detail

def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="只跑 0/45 两档")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)

    doc = json.load(open(MARKERS_JSON, encoding="utf-8"))
    markers = doc["markers"]
    assert len(markers) == 18, "markers_v2 应为 18 个"
    total_px = 380
    mi = make_mi()
    t0 = time.time()
    print("=" * 78)
    print("标记正样本回归：markers_v2 18 个 × 任意角度 / 透视 / 现场退化")
    print("画布 %dx%d，标记含静区总边长 %dpx（≈28mm@300dpi 的 0.98 倍）" % (W, H, total_px))
    print("=" * 78)

    ok0, bad0 = 0, []
    for k, md in enumerate(markers):
        paper = paper_marker(int(md["code_hex"], 16), total_px)
        ok, _ = check(mi, compose(paper, 0.0, seed=11 + k), md["label"], a.verbose)
        ok0 += 1 if ok else 0
        if not ok:
            bad0.append(md["label"])
    print("1. 0° 基线：%d/18 %s" % (ok0, "" if not bad0 else "失败:" + str(bad0)))

    angles = (0, 45) if a.quick else (0, 15, 30, 45, 60, 75, 90, 180, 270)
    rot_ok, rot_tot, rot_bad = 0, 0, []
    per_ang: Dict[int, List[int]] = {}
    for ang in angles:
        if ang == 0:
            per_ang[ang] = [ok0, 18]
            continue
        good = 0
        for k, md in enumerate(markers):
            paper = paper_marker(int(md["code_hex"], 16), total_px)
            ok, _ = check(mi, compose(paper, float(ang), seed=31 + k + ang), md["label"], a.verbose)
            good += 1 if ok else 0
            if not ok:
                rot_bad.append((md["label"], ang))
        per_ang[ang] = [good, 18]
        rot_ok += good
        rot_tot += 18
        print("2. 旋转 %3d°：%2d/18" % (ang, good))
    rot_all = ok0 + rot_ok
    rot_all_tot = 18 + rot_tot
    print("   任意角度合计：%d/%d（%.1f%%）%s"
          % (rot_all, rot_all_tot, 100.0 * rot_all / rot_all_tot,
             "" if not rot_bad else " 失败:" + str(rot_bad[:8])))

    persp_ok, persp_tot, persp_bad = 0, 0, []
    for ang, top in ((0, 0.85), (30, 0.85), (45, 0.82)):
        good = 0
        for k, md in enumerate(markers):
            paper = paper_marker(int(md["code_hex"], 16), total_px)
            ok, _ = check(mi, compose_persp(paper, float(ang), top_frac=top, seed=71 + k + ang),
                          md["label"], a.verbose)
            good += 1 if ok else 0
            if not ok:
                persp_bad.append((md["label"], ang))
        persp_ok += good
        persp_tot += 18
        print("3. 透视 %2d°（上边 %.0f%%）：%2d/18" % (ang, top * 100, good))
    print("   透视合计：%d/%d %s" % (persp_ok, persp_tot,
                                     "" if not persp_bad else " 失败:" + str(persp_bad[:8])))

    deg = {"brightness": 1.05, "contrast": 0.72, "blur": 0.7, "noise": 3.5,
           "jpeg": 65, "wash": (0.42, 96.0)}
    deg_ok, deg_bad = 0, []
    for k, md in enumerate(markers):
        paper = paper_marker(int(md["code_hex"], 16), total_px)
        ok, _ = check(mi, compose(paper, 45.0, seed=101 + k, degrade=deg), md["label"], a.verbose)
        deg_ok += 1 if ok else 0
        if not ok:
            deg_bad.append(md["label"])
    print("4. 45° + 压暗/低对比/模糊/噪声/JPEG65：%d/18 %s"
          % (deg_ok, "" if not deg_bad else "失败:" + str(deg_bad)))

    total_ok = rot_all + persp_ok + deg_ok
    total_tot = rot_all_tot + persp_tot + 18
    print("-" * 78)
    print("合计：%d/%d = %.1f%%（%.1fs）" % (total_ok, total_tot,
                                            100.0 * total_ok / total_tot, time.time() - t0))
    print("=" * 78)
    passed = (ok0 == 18 and rot_all == rot_all_tot and persp_ok == persp_tot and deg_ok == 18)
    return 0 if passed else 1

if __name__ == "__main__":
    raise SystemExit(main())
