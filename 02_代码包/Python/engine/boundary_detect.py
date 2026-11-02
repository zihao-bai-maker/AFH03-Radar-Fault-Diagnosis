# -*- coding: utf-8 -*-
"""
boundary_detect.py -- 雷达面板「变色边界」检测 / 自动 ROI 裁剪
================================================================

背景
----
AFH03 雷达机柜是**双色**的：正面是米灰/浅灰漆面（面板），四周压了一圈
**蓝灰色包边/门框**（照片里看就是一条"变色的边界"）。这条边界是可见的、
近似直线的，并且围出一个接近矩形的雷达面板区域。把它找出来有两个用处：

1. 自动 ROI：后续找标记、找灯、找屏只在雷达面板内做，减少背景/地面/人手干扰；
2. 姿态参考：矩形四角可以粗估拍摄角度（左右/俯仰），并给标记搜索一个先验范围。

本文件**不依赖 OpenCV**（本机没有 cv2），只用 numpy + Pillow 实现：
  * sRGB -> CIE Lab（D65）
  * Lab 空间 k-means 颜色分割（k=8）
  * 面板区域生长：只合并"与当前区域相邻 + 颜色接近"的簇
  * 形态学开运算 / 孔洞填充 / 最大连通域
  * 大轮廓 + 最小面积外接矩形（旋转卡壳式角度搜索）
  * Lab 颜色梯度 + Canny 式滞后阈值
  * 每条边做**局部 Hough**（角度 ±4°、rho ±8px）验证"这条边是不是真直线"
  * 边界两侧 Lab 色差 dE 作为置信度证据

限制（必须先看）
----------------
* 这 119 张照片**没有一张拍到整台雷达的四周**：全是 0.5~1m 的近景
  （单块门板/屏幕/配电箱）。所以"整台雷达四周一圈闭合边界"在本数据集上
  **不成立、也无法验证**；能稳定检到的是**单块面板与蓝灰包边之间的边界**。
* 面板占满画面、或边界完全在取景框外时，`found=False`（这是正确行为，不是 bug）。
* 显示器屏幕、白色工作服、过曝墙面可能被当成"面板"（无监督颜色分割的通病），
  见 README_boundary.md 的失败模式。

API
---
    from boundary_detect import detect_boundary, crop_to_boundary

    r = detect_boundary(img)          # img: PIL.Image 或 HxWx3 RGB ndarray
    # r = {
    #   "found": bool,
    #   "polygon": [[x,y], ...],       # 原图坐标；未检出时=整幅图四角
    #   "kind": "rect"|"quad"|"line",  # 4条/2~3条/1条"有颜色台阶"的边
    #   "confidence": 0.0~1.0,
    #   "box_px": [x0,y0,x1,y1],
    #   "lines": [...],                # 每条可见边的色差 dE + 局部 Hough 证据
    #   "edge_type": "blue_trim"|"brightness"|"color"|"",
    #   "area_frac": float, "fill": float,
    #   "visible_sides": int,          # 画面内可见的边数
    #   "supported_sides": int,        # 其中 dE>=3 且可见长度>=85% 的边数
    #   "snapped": [...], "pose": {...},
    #   "panel_lab": [L,a,b], "scale": [W,H],
    #   "note": str
    # }
    crop = crop_to_boundary(img, r)   # 按边界裁出雷达面板（未检出返回原图副本）
    crop = crop_to_boundary(img)      # 也可以不给 r，内部自己跑一遍

只读照片，不写任何文件；可视化/批量测试在 test_boundary_detect.py 里。
"""
from __future__ import annotations

import math
import os
from collections import deque
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw

def _as_rgb(img: Any) -> Image.Image:
    if isinstance(img, Image.Image):
        return img.convert("RGB")
    a = np.asarray(img)
    if a.ndim == 2:
        a = np.stack([a, a, a], axis=-1)
    if a.ndim != 3 or a.shape[2] < 3:
        raise ValueError("img 必须是 PIL.Image 或 HxWx3/4 数组")
    if a.shape[2] == 4:
        a = a[:, :, :3]
    return Image.fromarray(np.ascontiguousarray(a.astype(np.uint8)), "RGB")

def _rgb2lab(rgb: np.ndarray) -> np.ndarray:
    """sRGB(0..255) -> Lab(D65)。纯 numpy，和 OpenCV 的 Lab 同量级。"""
    a = rgb.astype(np.float32) / 255.0
    a = np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)
    M = np.array([[0.4124564, 0.3575761, 0.1804375],
                  [0.2126729, 0.7151522, 0.0721750],
                  [0.0193339, 0.1191920, 0.9503041]], np.float32)
    xyz = a @ M.T / np.array([0.95047, 1.0, 1.08883], np.float32)
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16.0 / 116.0)
    return np.stack([116.0 * f[..., 1] - 16.0,
                     500.0 * (f[..., 0] - f[..., 1]),
                     200.0 * (f[..., 1] - f[..., 2])], axis=2)

def _kmeans(x: np.ndarray, k: int, iters: int = 14, seed: int = 3) -> np.ndarray:
    """确定性的小 k-means（k<=10 时比 sklearn 还快，够用）。"""
    rng = np.random.default_rng(seed)
    k = int(max(1, min(k, len(x))))
    C = x[rng.choice(len(x), k, replace=False)].copy()
    for _ in range(iters):
        d = ((x[:, None, :] - C[None, :, :]) ** 2).sum(2)
        lb = d.argmin(1)
        for j in range(k):
            m = lb == j
            if m.any():
                C[j] = x[m].mean(0)
    return C

def _dilate(m: np.ndarray, n: int = 1) -> np.ndarray:
    out = m
    for _ in range(n):
        p = out.copy()
        p[1:, :] |= out[:-1, :]
        p[:-1, :] |= out[1:, :]
        p[:, 1:] |= out[:, :-1]
        p[:, :-1] |= out[:, 1:]
        p[1:, 1:] |= out[:-1, :-1]
        p[:-1, :-1] |= out[1:, 1:]
        p[1:, :-1] |= out[:-1, 1:]
        p[:-1, 1:] |= out[1:, :-1]
        out = p
    return out

def _erode(m: np.ndarray, n: int = 1) -> np.ndarray:
    out = m
    for _ in range(n):
        p = out.copy()
        p[1:, :] &= out[:-1, :]
        p[:-1, :] &= out[1:, :]
        p[:, 1:] &= out[:, :-1]
        p[:, :-1] &= out[:, 1:]
        p[1:, 1:] &= out[:-1, :-1]
        p[:-1, :-1] &= out[1:, 1:]
        p[1:, :-1] &= out[:-1, 1:]
        p[:-1, 1:] &= out[1:, :-1]
        out = p
    return out

def _fill_holes(mask: np.ndarray) -> np.ndarray:
    """把被面板包住的洞（屏幕/把手/螺栓）填上，便于外轮廓拟合。"""
    H, W = mask.shape
    bg = ~mask
    vis = np.zeros_like(bg)
    q: deque = deque()
    for x in range(W):
        for y in (0, H - 1):
            if bg[y, x] and not vis[y, x]:
                vis[y, x] = True
                q.append((y, x))
    for y in range(H):
        for x in (0, W - 1):
            if bg[y, x] and not vis[y, x]:
                vis[y, x] = True
                q.append((y, x))
    while q:
        y, x = q.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            yy, xx = y + dy, x + dx
            if 0 <= yy < H and 0 <= xx < W and bg[yy, xx] and not vis[yy, xx]:
                vis[yy, xx] = True
                q.append((yy, xx))
    return mask | (bg & ~vis)

def _largest_component(mask: np.ndarray) -> np.ndarray:
    H, W = mask.shape
    seen = np.zeros_like(mask)
    best: List[Tuple[int, int]] = []
    for y0 in range(0, H, 2):
        for x0 in range(0, W, 2):
            if not mask[y0, x0] or seen[y0, x0]:
                continue
            q = deque([(y0, x0)])
            seen[y0, x0] = True
            comp: List[Tuple[int, int]] = []
            while q:
                y, x = q.popleft()
                comp.append((y, x))
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    yy, xx = y + dy, x + dx
                    if 0 <= yy < H and 0 <= xx < W and mask[yy, xx] and not seen[yy, xx]:
                        seen[yy, xx] = True
                        q.append((yy, xx))
            if len(comp) > len(best):
                best = comp
    out = np.zeros_like(mask)
    if best:
        ys = np.fromiter((p[0] for p in best), dtype=np.int32)
        xs = np.fromiter((p[1] for p in best), dtype=np.int32)
        out[ys, xs] = True
    return out

def _hull(points: np.ndarray) -> np.ndarray:
    pts = sorted(set(map(tuple, np.round(points, 1).tolist())))
    if len(pts) <= 2:
        return np.array(pts, dtype=np.float64)

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: List[Tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: List[Tuple[float, float]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return np.array(lower[:-1] + upper[:-1], dtype=np.float64)

def _min_area_rect(points: np.ndarray):
    """最小面积外接矩形：0.25° 角度搜索（纯 numpy，稳且够快）。"""
    h = _hull(points)
    if len(h) < 3:
        return None
    best = None
    for deg in np.arange(0.0, 90.0, 0.25):
        t = math.radians(deg)
        ct, st = math.cos(t), math.sin(t)
        u = h[:, 0] * ct + h[:, 1] * st
        v = -h[:, 0] * st + h[:, 1] * ct
        area = (u.max() - u.min()) * (v.max() - v.min())
        if best is None or area < best[0]:
            best = (area, deg, u.min(), u.max(), v.min(), v.max())
    area, deg, umin, umax, vmin, vmax = best
    t = math.radians(deg)
    ct, st = math.cos(t), math.sin(t)
    corners = []
    for uu, vv in ((umin, vmin), (umax, vmin), (umax, vmax), (umin, vmax)):
        corners.append((uu * ct - vv * st, uu * st + vv * ct))
    return np.array(corners, dtype=np.float64), float(deg), float(area)

def _clip_poly_rect(poly: Sequence[Sequence[float]], W: int, H: int) -> List[List[float]]:
    def clip(p, inside, inter):
        out = []
        for i in range(len(p)):
            A, B = p[i], p[(i + 1) % len(p)]
            fa, fb = inside(A), inside(B)
            if fa >= 0:
                out.append(A)
            if (fa > 0 and fb < 0) or (fa < 0 and fb > 0):
                t = fa / (fa - fb)
                out.append(inter(A, B, t))
        return out

    p = [tuple(q) for q in poly]
    p = clip(p, lambda q: q[0], lambda A, B, t: (0.0, A[1] + t * (B[1] - A[1])))
    p = clip(p, lambda q: W - q[0], lambda A, B, t: (float(W), A[1] + t * (B[1] - A[1])))
    p = clip(p, lambda q: q[1], lambda A, B, t: (A[0] + t * (B[0] - A[0]), 0.0))
    p = clip(p, lambda q: H - q[1], lambda A, B, t: (A[0] + t * (B[0] - A[0]), float(H)))
    return [[float(x), float(y)] for x, y in p]

def _poly_area(p: Sequence[Sequence[float]]) -> float:
    if len(p) < 3:
        return 0.0
    s = 0.0
    for i in range(len(p)):
        x1, y1 = p[i]
        x2, y2 = p[(i + 1) % len(p)]
        s += x1 * y2 - x2 * y1
    return abs(s) * 0.5

def _color_edges(lab: np.ndarray, pct: float = 94.0):
    """Lab 颜色梯度 + Canny 式滞后阈值（强边缘 + 弱边缘连通）。"""
    L = lab[..., 0]
    A = lab[..., 1]
    B = lab[..., 2]

    def grad(a):
        gx = np.zeros_like(a)
        gy = np.zeros_like(a)
        gx[:, 1:-1] = (a[:, 2:] - a[:, :-2]) * 0.5
        gy[1:-1, :] = (a[2:, :] - a[:-2, :]) * 0.5
        return gx, gy

    def blur(a):
        p = np.pad(a, 1, mode="edge")
        return (p[:-2, 1:-1] + p[2:, 1:-1] + p[1:-1, :-2] + p[1:-1, 2:] + p[1:-1, 1:-1]) / 5.0

    L, A, B = blur(L), blur(A), blur(B)
    gx, gy = grad(L)
    gxa, gya = grad(A)
    gxb, gyb = grad(B)
    mag = np.sqrt(gx ** 2 + gy ** 2 + 1.6 * (gxa ** 2 + gya ** 2) + 2.0 * (gxb ** 2 + gyb ** 2))
    hi = float(np.percentile(mag, pct))
    lo = 0.35 * hi
    strong = mag >= hi
    weak = mag >= lo
    e = strong.copy()
    for _ in range(10):
        e2 = _dilate(e) & weak
        if np.array_equal(e2, e):
            break
        e = e2
    return e, mag

def _local_hough(pts: np.ndarray, p0, p1, mag: np.ndarray,
                 search_deg: float = 4.0, search_px: float = 8.0):
    """一条边附近的局部 Hough：返回 (theta, rho, votes, support)。"""
    p0 = np.asarray(p0, dtype=np.float64)
    p1 = np.asarray(p1, dtype=np.float64)
    d = p1 - p0
    length = float(np.hypot(d[0], d[1]))
    if length < 8 or len(pts) == 0:
        return None
    base = math.atan2(d[1], d[0]) + math.pi / 2.0
    mid = (p0 + p1) / 2.0
    rho0 = mid[0] * math.cos(base) + mid[1] * math.sin(base)
    t0 = 0.0
    ux, uy = d[0] / length, d[1] / length
    proj = (pts[:, 0] - p0[0]) * ux + (pts[:, 1] - p0[1]) * uy
    perp = -(pts[:, 0] - p0[0]) * uy + (pts[:, 1] - p0[1]) * ux
    near = ((proj > length * 0.04) & (proj < length * 0.96)
            & (np.abs(perp) <= 16.0))
    sel = pts[near]
    if len(sel) < 8:
        return None
    best = (0, float(base), float(rho0), 0.0)
    for dth in np.arange(-search_deg, search_deg + 1e-6, 1.0):
        th = base + math.radians(dth)
        ct, st = math.cos(th), math.sin(th)
        base_r = sel[:, 0] * ct + sel[:, 1] * st
        for dr in np.arange(-search_px, search_px + 1e-6, 2.0):
            r = rho0 + dr
            votes = int((np.abs(base_r - r) <= 1.6).sum())
            if votes > best[0]:

                idx = np.abs(base_r - r) <= 1.6
                if idx.any():
                    pr = proj[near][idx]
                    cover = float(pr.max() - pr.min()) / max(1.0, length)
                else:
                    cover = 0.0
                best = (votes, float(th), float(r), cover)
    if best[0] < 6:
        return None
    return {"votes": best[0], "theta": round(math.degrees(best[1]) % 180.0, 2),
            "rho": round(best[2], 2), "coverage": round(best[3], 3)}

def _side_stats(lab: np.ndarray, p0, p1, centroid, r: int = 6):
    """边两侧各取 6px 的颜色；返回 (dE, inside_lab, outside_lab, edge_type)。"""
    p0 = np.asarray(p0, dtype=np.float64)
    p1 = np.asarray(p1, dtype=np.float64)
    d = p1 - p0
    length = float(np.hypot(d[0], d[1]))
    if length < 8:
        return None
    ux, uy = d[0] / length, d[1] / length
    nx, ny = -uy, ux
    mid = (p0 + p1) / 2.0
    if (mid[0] - centroid[0]) * nx + (mid[1] - centroid[1]) * ny > 0:
        nx, ny = -nx, -ny       
    H, W = lab.shape[:2]
    vals_in, vals_out = [], []
    for t in np.linspace(0.08, 0.92, 13):
        base = p0 + d * t
        for s, dst in ((1, vals_in), (-1, vals_out)):
            x = int(round(base[0] + s * nx * r))
            y = int(round(base[1] + s * ny * r))
            if 2 <= x < W - 2 and 2 <= y < H - 2:
                dst.append(np.median(lab[y - 2:y + 3, x - 2:x + 3].reshape(-1, 3), axis=0))
    if len(vals_in) < 4 or len(vals_out) < 4:
        return None
    ci = np.median(np.array(vals_in), axis=0)
    co = np.median(np.array(vals_out), axis=0)
    dE = float(np.linalg.norm(ci - co))
    chroma_out = float(np.hypot(co[1], co[2]))
    if co[2] < ci[2] - 3.0 and chroma_out < 20:
        kind = "blue_trim"
    elif abs(ci[0] - co[0]) >= 6.0:
        kind = "brightness"
    else:
        kind = "color"
    return {"dE": round(dE, 2), "inside_lab": [round(float(v), 1) for v in ci],
            "outside_lab": [round(float(v), 1) for v in co], "edge_type": kind}

def _clip_segment_rect(p0, p1, W: int, H: int):
    """Liang-Barsky 线段裁剪；返回 (cp0, cp1, 可见长度占比) 或 None。"""
    x0, y0 = float(p0[0]), float(p0[1])
    x1, y1 = float(p1[0]), float(p1[1])
    dx, dy = x1 - x0, y1 - y0
    u1, u2 = 0.0, 1.0
    for p, q in ((-dx, x0 - 0.0), (dx, float(W) - x0), (-dy, y0 - 0.0), (dy, float(H) - y0)):
        if abs(p) < 1e-9:
            if q < 0:
                return None
            continue
        r = q / p
        if p < 0:
            if r > u2:
                return None
            u1 = max(u1, r)
        else:
            if r < u1:
                return None
            u2 = min(u2, r)
    if u2 <= u1:
        return None
    cp0 = (x0 + u1 * dx, y0 + u1 * dy)
    cp1 = (x0 + u2 * dx, y0 + u2 * dy)
    full = math.hypot(dx, dy)
    vis = math.hypot(cp1[0] - cp0[0], cp1[1] - cp0[1])
    return cp0, cp1, (vis / full if full > 1e-6 else 0.0)

def _visible_sides(corners: np.ndarray, W: int, H: int, min_frac: float = 0.55):
    """矩形的 4 条边里，哪些在画面内可见（允许两端出画，只要可见段够长）。"""
    out = []
    for i in range(4):
        p0, p1 = corners[i], corners[(i + 1) % 4]
        cl = _clip_segment_rect(p0, p1, W, H)
        if cl is None:
            continue
        cp0, cp1, frac = cl
        if frac < min_frac or math.hypot(cp1[0] - cp0[0], cp1[1] - cp0[1]) < 20:
            continue
        on_border = ((abs(cp0[0]) < 2 and abs(cp1[0]) < 2) or
                     (abs(cp0[0] - W) < 2 and abs(cp1[0] - W) < 2) or
                     (abs(cp0[1]) < 2 and abs(cp1[1]) < 2) or
                     (abs(cp0[1] - H) < 2 and abs(cp1[1] - H) < 2))
        if on_border:
            continue
        out.append((i, np.array(cp0), np.array(cp1), frac))
    return out

def _profile_step(prof: np.ndarray, start: int, direction: int, max_dist: int,
                  want_larger_b: bool):
    """在 1D Lab 剖面上找第一个"颜色台阶"。

    want_larger_b=True  : 沿 direction 走，b* 变大的一侧 = 面板侧（暖）
    want_larger_b=False : b* 变小的一侧 = 面板侧
    """
    N = len(prof)
    if N < 12:
        return None
    for k in range(0, max_dist + 1):
        i = start + direction * k
        if i < 6 or i > N - 6:
            continue
        a = np.median(prof[max(0, i - 5):i], axis=0)       
        b = np.median(prof[i:min(N, i + 5)], axis=0)       
        dE = float(np.linalg.norm(a - b))
        db = float((b[2] - a[2]) if want_larger_b else (a[2] - b[2]))
        if dE >= 4.0 and db >= 2.0:
            return {"index": int(i), "dE": round(dE, 2), "db": round(db, 2),
                    "lab_a": [round(float(v), 1) for v in a],
                    "lab_b": [round(float(v), 1) for v in b]}
    return None

def _snap_rect(corners: np.ndarray, lab: np.ndarray, mask: np.ndarray,
               W: int, H: int):
    """用行/列颜色剖面把矩形四边"吸附"到真正的面板/包边色阶上。

    k-means 有时会把包边外的墙/背景也并进面板（同一颜色），导致矩形顶到画面边；
    颜色剖面能在矩形内部找到"墙 -> 蓝灰包边 -> 面板"的台阶，把边拉回面板边缘。
    """
    top_edge = corners[1] - corners[0]
    ang = abs(math.degrees(math.atan2(top_edge[1], top_edge[0])))
    if 10.0 < ang < 80.0:          
        return corners, []
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return corners, []
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    xa = int(x0 + 0.15 * (x1 - x0)); xb = int(x1 - 0.15 * (x1 - x0))
    ya = int(y0 + 0.15 * (y1 - y0)); yb = int(y1 - 0.15 * (y1 - y0))
    xa, xb = max(2, min(xa, W - 2)), max(xa + 2, min(xb, W - 1))
    ya, yb = max(2, min(ya, H - 2)), max(ya + 2, min(yb, H - 1))
    prof_row = np.median(lab[:, xa:xb, :], axis=1)      
    prof_col = np.median(lab[ya:yb, :, :], axis=0)      

    out = corners.astype(np.float64).copy()
    snaps = []

    def apply(which, val, old):
        if which == "top":
            out[0, 1] = val; out[1, 1] = val
        elif which == "bottom":
            out[2, 1] = val; out[3, 1] = val
        elif which == "left":
            out[0, 0] = val; out[3, 0] = val
        elif which == "right":
            out[1, 0] = val; out[2, 0] = val
        snaps.append({"side": which, "from": round(float(old), 1), "to": round(float(val), 1)})

    st = _profile_step(prof_row, int(round(min(out[0, 1], out[1, 1]))), +1,
                       int(0.18 * H), True)
    if st and 0 <= st["index"] < H:
        apply("top", st["index"], min(out[0, 1], out[1, 1])); snaps[-1].update(st)

    st = _profile_step(prof_row, int(round(max(out[2, 1], out[3, 1]))), -1,
                       int(0.18 * H), False)
    if st and 0 <= st["index"] < H:
        apply("bottom", st["index"], max(out[2, 1], out[3, 1])); snaps[-1].update(st)

    st = _profile_step(prof_col, int(round(min(out[0, 0], out[3, 0]))), +1,
                       int(0.18 * W), True)
    if st and 0 <= st["index"] < W:
        apply("left", st["index"], min(out[0, 0], out[3, 0])); snaps[-1].update(st)

    st = _profile_step(prof_col, int(round(max(out[1, 0], out[2, 0]))), -1,
                       int(0.18 * W), False)
    if st and 0 <= st["index"] < W:
        apply("right", st["index"], max(out[1, 0], out[2, 0])); snaps[-1].update(st)
    return out, snaps

def _poly_coverage(poly, mask: np.ndarray) -> float:
    """多边形里有多少比例落在面板 mask 上（比 mask/rect 更贴近真实填充率）。"""
    H, W = mask.shape
    im = Image.new("L", (W, H), 0)
    ImageDraw.Draw(im).polygon([tuple(p) for p in poly], fill=1)
    pm = np.asarray(im) > 0
    n = int(pm.sum())
    if n == 0:
        return 0.0
    return float((mask & pm).sum()) / n

def detect_boundary(img: Any, max_side: int = 720, k: int = 8,
                    min_area: float = 0.08, min_fill: float = 0.60,
                    return_debug: bool = False) -> Dict[str, Any]:
    """检测雷达面板的「变色边界」。

    参数
    ----
    img : PIL.Image / HxWx3 RGB ndarray
    max_side : 工作分辨率长边（默认 720；越大越准越慢）
    k : k-means 簇数（默认 8；6~10 都稳）
    min_area : 面板区域最小面积占比
    min_fill : 面板区域 / 外接矩形 的最小填充率（<0.60 判为"不是一块面板"）
    """
    im0 = _as_rgb(img)
    W0, H0 = im0.size
    im = im0.copy()
    im.thumbnail((int(max_side), int(max_side)), Image.LANCZOS)
    W, H = im.size
    sx, sy = W0 / float(W), H0 / float(H)
    lab = _rgb2lab(np.asarray(im).astype(np.float32))
    L, A, B = lab[..., 0], lab[..., 1], lab[..., 2]

    sub = lab[::2, ::2].reshape(-1, 3)
    C = _kmeans(sub, k, iters=14, seed=3)
    d = ((lab.reshape(-1, 3)[:, None, :] - C[None, :, :]) ** 2).sum(2)
    full = d.argmin(1).reshape(H, W)
    counts = np.bincount(full.ravel(), minlength=len(C)).astype(np.float64)
    total = counts.sum()

    info = []
    for j in range(len(C)):
        Lj, aj, bj = (float(C[j, 0]), float(C[j, 1]), float(C[j, 2]))
        chroma = float(math.hypot(aj, bj))
        paint = float(math.exp(-((bj - 1.5) ** 2) / (2 * 7.0 ** 2) - (chroma ** 2) / (2 * 12.0 ** 2)))
        if not (38.0 <= Lj <= 82.0):
            paint *= 0.15
        m = full == j
        border = (float(m[0, :].sum() + m[-1, :].sum() + m[:, 0].sum() + m[:, -1].sum())
                  / max(1.0, float(m.sum())))
        frac = float(counts[j] / total)
        score = frac ** 0.6 * paint * (0.55 + 0.45 * min(1.0, border * 8.0))
        info.append({"j": j, "frac": frac, "L": Lj, "a": aj, "b": bj, "chroma": chroma,
                     "paint": paint, "border": border, "score": score})
    info.sort(key=lambda z: -z["score"])
    seed = info[0]

    active = {seed["j"]}
    mask = full == seed["j"]
    for _ in range(3):
        dil = _dilate(mask)
        for z in info[1:]:
            j = z["j"]
            if j in active or z["frac"] < 0.03:
                continue
            if abs(z["b"] - seed["b"]) > 2.4 or abs(z["L"] - seed["L"]) > 15.0:
                continue
            if z["chroma"] > 22.0:
                continue
            touch = int((dil & (full == j)).sum())
            if touch > max(50, 0.02 * counts[j]):
                active.add(j)
                mask |= (full == j)
    mask = _dilate(_erode(mask, 2), 2)
    mask = _largest_component(_fill_holes(mask))
    if int(mask.sum()) < 500:
        return _empty_result(W0, H0, "面板颜色区域太小")

    pts = np.argwhere(mask)[:, ::-1].astype(np.float32)
    rect = _min_area_rect(pts)
    if rect is None:
        return _empty_result(W0, H0, "轮廓退化")
    corners, angle, rect_area = rect

    corners, snaps = _snap_rect(corners, lab, mask, W, H)
    poly = _clip_poly_rect(corners, W, H)
    area_frac = _poly_area(poly) / float(W * H)
    fill = _poly_coverage(poly, mask)

    e, mag = _color_edges(lab, pct=94.0)
    edge_pts = np.argwhere(e)[:, ::-1].astype(np.float32)
    cx, cy = float(np.mean(pts[:, 0])), float(np.mean(pts[:, 1]))
    lines = []
    dEs, hough_ok = [], 0
    vis = _visible_sides(corners, W, H)
    for (i, p0, p1, vfrac) in vis:
        st = _side_stats(lab, p0, p1, (cx, cy), r=6)
        if st is None:
            continue
        hg = _local_hough(edge_pts, p0, p1, mag)

        mx, my = (p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0
        side = (("left" if mx < cx else "right") if abs(p1[0] - p0[0]) < abs(p1[1] - p0[1])
                else ("top" if my < cy else "bottom"))
        if hg is not None:
            hough_ok += 1
        dEs.append(st["dE"])
        lines.append({
            "side": side,
            "p0": [round(float(p0[0]) * sx, 1), round(float(p0[1]) * sy, 1)],
            "p1": [round(float(p1[0]) * sx, 1), round(float(p1[1]) * sy, 1)],
            "length_px": round(float(np.hypot(p1[0] - p0[0], p1[1] - p0[1]) * sx), 1),
            "visible_frac": round(float(vfrac), 3),
            "dE": st["dE"], "edge_type": st["edge_type"],
            "inside_lab": st["inside_lab"], "outside_lab": st["outside_lab"],
            "hough": hg, "hough_ok": bool(hg is not None),
        })

    n_vis = len(vis)

    
    for z in lines:
        z["supported"] = bool(z["dE"] >= 3.0 and z["visible_frac"] >= 0.85)
    sup = [z for z in lines if z["supported"]]
    n_sup = len(sup)
    mean_dE = float(np.mean([z["dE"] for z in sup])) if sup else 0.0
    hough_sup = sum(1 for z in sup if z["hough_ok"])
    edge_type = ""
    if sup:
        from collections import Counter
        edge_type = Counter([z["edge_type"] for z in sup]).most_common(1)[0][0]

    fill_n = float(np.clip((fill - 0.45) / 0.40, 0, 1))
    area_n = float(np.clip((area_frac - min_area) / 0.35, 0, 1))
    sides_n = float(np.clip(n_sup / 2.0, 0, 1))
    edge_n = float(np.clip((mean_dE - 3.0) / 9.0, 0, 1))
    hough_n = float(hough_sup / max(1, n_sup))
    conf = float(np.clip(0.22 * fill_n + 0.18 * area_n + 0.22 * sides_n
                         + 0.22 * edge_n + 0.16 * hough_n, 0, 1))
    found = bool(area_frac >= min_area and fill >= min_fill and n_sup >= 1
                 and conf >= 0.30)

    kind = "line" if n_sup == 1 else ("rect" if (n_sup == 4 and len(poly) == 4) else "quad")
    if not found:
        note = "未检出可靠边界（可能：面板占满画面/边界在取景框外/过曝/遮挡）"
        poly = [[0.0, 0.0], [float(W), 0.0], [float(W), float(H)], [0.0, float(H)]]
    else:
        note = "面板与%s之间的边界" % ("蓝灰包边" if edge_type == "blue_trim" else
                                        "背景（亮度/颜色突变）" if edge_type == "brightness" else "背景（颜色突变）")
    poly_o = [[round(float(x) * sx, 1), round(float(y) * sy, 1)] for x, y in poly]
    xs = [p[0] for p in poly_o]
    ys = [p[1] for p in poly_o]

    
    ml, mt = min(xs) / W0, min(ys) / H0
    mr, mb = (W0 - max(xs)) / W0, (H0 - max(ys)) / H0
    yaw_hint = ("画面只看到面板右侧→相机偏右" if ml < 0.02 and mr > 0.05 else
                "画面只看到面板左侧→相机偏左" if mr < 0.02 and ml > 0.05 else "面板左右基本完整")
    pitch_hint = ("画面只看到面板下半→相机偏高" if mt < 0.02 and mb > 0.05 else
                  "画面只看到面板上半→相机偏低" if mb < 0.02 and mt > 0.05 else "面板上下基本完整")
    pose = {"roll_deg": round(float(angle), 2),
            "margins_lrtb": [round(ml, 3), round(mr, 3), round(mt, 3), round(mb, 3)],
            "yaw_hint": yaw_hint, "pitch_hint": pitch_hint,
            "note": "滚转角来自矩形拟合；yaw/pitch 仅为构图提示，单目无标定不可当角度测量"}
    if not found:
        pose = {"roll_deg": 0.0, "margins_lrtb": [0.0, 0.0, 0.0, 0.0],
                "yaw_hint": "", "pitch_hint": "",
                "note": "未检出边界，姿态提示不可用"}

    res = {
        "found": found,
        "polygon": poly_o,
        "kind": kind,
        "confidence": round(conf, 3),
        "box_px": [int(round(min(xs))), int(round(min(ys))),
                   int(round(max(xs))), int(round(max(ys)))],
        "lines": lines,
        "edge_type": edge_type,
        "area_frac": round(area_frac, 3),
        "fill": round(fill, 3),
        "visible_sides": int(n_vis),
        "supported_sides": int(n_sup),
        "hough_sides": int(hough_sup),
        "snapped": snaps,
        "angle_deg": round(float(angle), 2),
        "pose": pose,
        "panel_lab": [round(float(seed["L"]), 1), round(float(seed["a"]), 1),
                      round(float(seed["b"]), 1)],
        "panel_chroma": round(float(seed["chroma"]), 1),
        "scale": [int(W0), int(H0)],
        "work_scale": [int(W), int(H)],
        "note": note,
    }
    if return_debug:
        res["_debug"] = {"mask": mask, "lab": lab, "edges": e, "corners": corners,
                         "clusters": info, "active": sorted(active), "sx": sx, "sy": sy}
    return res

def _empty_result(W: int, H: int, note: str) -> Dict[str, Any]:
    return {"found": False, "polygon": [[0.0, 0.0], [float(W), 0.0], [float(W), float(H)],
                                        [0.0, float(H)]],
            "kind": "rect", "confidence": 0.0,
            "box_px": [0, 0, int(W), int(H)], "lines": [], "edge_type": "",
            "area_frac": 0.0, "fill": 0.0, "visible_sides": 0, "supported_sides": 0,
            "hough_sides": 0, "snapped": [], "angle_deg": 0.0, "panel_lab": [0, 0, 0],
            "panel_chroma": 0.0,
            "scale": [int(W), int(H)], "note": note}

def crop_to_boundary(img: Any, result: Optional[Dict[str, Any]] = None,
                     margin: float = 0.0, return_box: bool = False):
    """按边界裁出雷达面板。

    margin : 0~0.2，向四周留的余量（相对边界框边长）。
    未检出边界时返回整幅图（不报错），保证下游流程不中断。
    """
    im = _as_rgb(img)
    W, H = im.size
    if result is None:
        result = detect_boundary(im)
    if result.get("found"):
        x0, y0, x1, y1 = result["box_px"]
        if margin > 0:
            mx, my = int((x1 - x0) * margin), int((y1 - y0) * margin)
            x0, y0, x1, y1 = x0 - mx, y0 - my, x1 + mx, y1 + my
        x0, y0 = max(0, int(x0)), max(0, int(y0))
        x1, y1 = min(W, int(x1)), min(H, int(y1))
        if x1 - x0 < 8 or y1 - y0 < 8:
            x0, y0, x1, y1 = 0, 0, W, H
    else:
        x0, y0, x1, y1 = 0, 0, W, H
    out = im.crop((x0, y0, x1, y1))
    return (out, [x0, y0, x1, y1]) if return_box else out

if __name__ == "__main__":

    import sys
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(0)
    im = Image.open(sys.argv[1]).convert("RGB")
    r = detect_boundary(im)
    print({k: r[k] for k in ("found", "kind", "confidence", "box_px", "area_frac",
                             "fill", "visible_sides", "hough_sides", "edge_type", "note")})
    if len(sys.argv) > 2:
        from PIL import ImageDraw
        d = ImageDraw.Draw(im)
        d.line([tuple(p) for p in r["polygon"]] + [tuple(r["polygon"][0])], fill=(0, 255, 0), width=4)
        im.save(sys.argv[2], quality=90)
        print("->", sys.argv[2])

