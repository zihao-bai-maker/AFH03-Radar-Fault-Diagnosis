# -*- coding: utf-8 -*-
"""
markerdet.py -- 纯 numpy 的 4x4 标记检测器（不依赖 OpenCV）

流程：
  灰度 -> 局部自适应二值化(积分图) -> 行程(run)连通域 -> 最小面积外接矩形求朝向
  -> 6x6 模块网格里读 4x4 数据 -> 4 个旋转逐个与字典比对(汉明距离<=1)
  -> 输出：ID、中心、模块像素尺寸 s、朝向角、四个角点、黑白参考亮度(用于曝光归一化)

几何约定见 marker.py。返回的 canonical 基向量：
  r=0: right=+u, down=+v
  r=1: right=+v, down=-u
  r=2: right=-u, down=-v
  r=3: right=-v, down=+u
其中 u=(cosθ, sinθ)，v=(-sinθ, cosθ)。LED 的偏移在 canonical 系里给，
所以标记贴成任意旋转都能自动对上。
"""
import numpy as np

from marker import MOD, GRID, to_bits, from_bits, rot90_bits, ham, build_dictionary

def integral_image(a):
    return np.pad(np.cumsum(np.cumsum(a, axis=0), axis=1), ((1, 0), (1, 0)))

def box_mean(ii, r):
    """半径为 r 的方形窗口均值（用积分图），返回与图像同形的数组"""
    H, W = ii.shape[0] - 1, ii.shape[1] - 1
    ys = np.arange(H)
    xs = np.arange(W)
    y0 = np.clip(ys - r, 0, H)[:, None]
    y1 = np.clip(ys + r + 1, 0, H)[:, None]
    x0 = np.clip(xs - r, 0, W)[None, :]
    x1 = np.clip(xs + r + 1, 0, W)[None, :]
    s = ii[y1, x1] - ii[y0, x1] - ii[y1, x0] + ii[y0, x0]
    n = (y1 - y0) * (x1 - x0)
    return s / np.maximum(n, 1)

def to_gray(img):
    a = np.asarray(img).astype(np.float32)
    if a.ndim == 3:
        a = 0.299 * a[:, :, 0] + 0.587 * a[:, :, 1] + 0.114 * a[:, :, 2]
    return a

def dark_mask(gray, win_frac=0.05, k=0.80, min_win=15):
    H, W = gray.shape
    r = max(min_win, int(round(win_frac * min(H, W)))) // 2
    ii = integral_image(gray)
    m = box_mean(ii, r)
    return gray < (m * k)

def _runs_per_row(mask):
    out = []
    for y in range(mask.shape[0]):
        row = mask[y].astype(np.int8)
        if not row.any():
            out.append([])
            continue
        p = np.concatenate(([0], row, [0]))
        d = np.diff(p)
        st = np.flatnonzero(d == 1)
        en = np.flatnonzero(d == -1) - 1
        out.append(list(zip(st.tolist(), en.tolist())))
    return out

class Comp(object):
    __slots__ = ("area", "sx", "sy", "sxx", "syy", "sxy", "runs", "bbox")

    def __init__(self):
        self.area = 0
        self.sx = self.sy = self.sxx = self.syy = self.sxy = 0.0
        self.runs = []
        self.bbox = [10 ** 9, 10 ** 9, -1, -1]

def connected_components(mask, min_area=40):
    rows = _runs_per_row(mask)
    parent = []

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            if ra < rb:
                parent[rb] = ra
            else:
                parent[ra] = rb

    all_runs = []          
    prev = []              
    for y, cur in enumerate(rows):
        nxt = []
        for (x0, x1) in cur:
            lab = len(parent)
            parent.append(lab)
            for (px0, px1, plab) in prev:
                if x0 <= px1 and px0 <= x1:
                    union(lab, plab)
            nxt.append((x0, x1, lab))
            all_runs.append((y, x0, x1, lab))
        prev = nxt

    comps = {}
    s2 = lambda v: v * (v + 1) * (2 * v + 1) // 6
    for (y, x0, x1, lab) in all_runs:
        root = find(lab)
        c = comps.get(root)
        if c is None:
            c = Comp()
            comps[root] = c
        n = x1 - x0 + 1
        sumx = (x0 + x1) * n // 2
        sumx2 = s2(x1) - s2(x0 - 1)
        c.area += n
        c.sx += sumx
        c.sy += y * n
        c.sxx += sumx2
        c.syy += y * y * n
        c.sxy += y * sumx
        c.runs.append((y, x0, x1))
        c.bbox[0] = min(c.bbox[0], x0)
        c.bbox[1] = min(c.bbox[1], y)
        c.bbox[2] = max(c.bbox[2], x1)
        c.bbox[3] = max(c.bbox[3], y)

    return [c for c in comps.values() if c.area >= min_area]

def min_area_rect(c, coarse=1.0, fine=0.1):
    """返回 (cx, cy, ext_u, ext_v, theta)。角度 theta 是 u 轴与 x 轴夹角，范围 [0, pi/2)。"""
    pts = np.empty((len(c.runs) * 2, 2), dtype=np.float64)
    for i, (y, x0, x1) in enumerate(c.runs):
        pts[2 * i] = (x0, y)
        pts[2 * i + 1] = (x1, y)

    def box(deg):
        t = np.deg2rad(deg)
        ct, st = np.cos(t), np.sin(t)
        u = pts[:, 0] * ct + pts[:, 1] * st
        v = -pts[:, 0] * st + pts[:, 1] * ct
        du = u.max() - u.min()
        dv = v.max() - v.min()
        return du * dv, du, dv, u.min(), u.max(), v.min(), v.max(), ct, st

    best = None
    for deg in np.arange(0.0, 90.0, coarse):
        b = box(deg)
        if best is None or b[0] < best[0][0]:
            best = (b, deg)
    d0 = best[1]
    for deg in np.arange(max(0.0, d0 - coarse), d0 + coarse, fine):
        b = box(deg)
        if b[0] < best[0][0]:
            best = (b, deg)
    area, du, dv, umin, umax, vmin, vmax, ct, st = best[0]
    deg = best[1]
    t = np.deg2rad(deg)
    ct, st = np.cos(t), np.sin(t)

    uc = 0.5 * (umin + umax)
    vc = 0.5 * (vmin + vmax)
    cx = uc * ct - vc * st
    cy = uc * st + vc * ct
    return cx, cy, du, dv, deg

def sample_cell(gray, cx, cy, theta_deg, s, i, j, frac=0.30):
    """采样 (i,j) 格中心附近的小方块，返回中位数灰度"""
    t = np.deg2rad(theta_deg)
    ct, st = np.cos(t), np.sin(t)
    u = (j - (GRID - 1) / 2.0) * s
    v = (i - (GRID - 1) / 2.0) * s
    x = cx + u * ct - v * st
    y = cy + u * st + v * ct
    rad = max(1.0, s * frac)
    x0 = int(max(0, np.floor(x - rad)))
    x1 = int(min(gray.shape[1] - 1, np.ceil(x + rad)))
    y0 = int(max(0, np.floor(y - rad)))
    y1 = int(min(gray.shape[0] - 1, np.ceil(y + rad)))
    if x1 < x0 or y1 < y0:
        return None
    return float(np.median(gray[y0:y1 + 1, x0:x1 + 1]))

class Marker(object):
    def __init__(self, mid, cx, cy, s, theta, rot, corners, black_ref, white_ref):
        self.mid = mid
        self.cx, self.cy = cx, cy
        self.s = s                       
        self.theta = theta               
        self.rot = rot                   
        self.corners = corners           
        self.black_ref = black_ref       
        self.white_ref = white_ref

    def canonical_axes(self):
        t = np.deg2rad(self.theta)
        u = np.array([np.cos(t), np.sin(t)])
        v = np.array([-np.sin(t), np.cos(t)])
        if self.rot == 0:
            return u, v
        if self.rot == 1:
            return v, -u
        if self.rot == 2:
            return -u, -v
        return -v, u

    def __repr__(self):
        return "Marker(id=%d, c=(%.1f,%.1f), s=%.2fpx, theta=%.1f, rot=%d)" % (
            self.mid, self.cx, self.cy, self.s, self.theta, self.rot)

def detect_markers(gray, codes, min_side_px=14, max_side_px=None, max_hamming=1,
                   dark_win_frac=0.05, dark_k=0.80, min_area=40, min_fill=0.30,
                   max_fill=0.82, verbose=False):
    """返回 Marker 列表。
    min_side_px / max_side_px 指的是「标记黑框外沿边长」的像素范围（不是模块尺寸）。"""
    H, W = gray.shape
    if max_side_px is None:
        max_side_px = 0.6 * min(H, W)
    mask = dark_mask(gray, dark_win_frac, dark_k)
    comps = connected_components(mask, min_area=min_area)

    dict_bits = [to_bits(c) for c in codes]
    found = []
    for c in comps:
        cx, cy, du, dv, deg = min_area_rect(c)
        if du < min_side_px or dv < min_side_px:
            continue
        if du > max_side_px or dv > max_side_px:
            continue
        ar = du / max(dv, 1e-6)
        if ar < 0.72 or ar > 1.39:
            continue
        fill = c.area / max(du * dv, 1e-6)
        if fill < min_fill or fill > max_fill:
            continue
        s = 0.5 * (du + dv) / MOD

        med = np.zeros((GRID, GRID))
        ok = True
        for i in range(GRID):
            for j in range(GRID):
                m = sample_cell(gray, cx, cy, deg, s, i, j)
                if m is None:
                    ok = False
                    break
                med[i, j] = m
            if not ok:
                break
        if not ok:
            continue
        lo = np.percentile(med, 15)
        hi = np.percentile(med, 85)
        if hi - lo < 6:            
            continue
        thr = 0.5 * (lo + hi)
        obs = from_bits((med < thr).astype(np.uint8))

        best = None
        for k, cbits in enumerate(dict_bits):
            for r in range(4):
                d = ham(obs, from_bits(rot90_bits(cbits, r)))
                if d <= max_hamming and (best is None or d < best[0]):
                    best = (d, k, r)
        if best is None:
            if verbose:
                print("  [reject] c=(%.0f,%.0f) s=%.1f fill=%.2f obs=%04x" %
                      (cx, cy, s, fill, obs))
            continue

        d, k, r = best
        t = np.deg2rad(deg)
        ct, st = np.cos(t), np.sin(t)
        half = MOD * s / 2.0
        corners = []
        for (uu, vv) in ((-half, -half), (half, -half), (half, half), (-half, half)):
            corners.append((cx + uu * ct - vv * st, cy + uu * st + vv * ct))
        found.append(Marker(k, cx, cy, s, deg, r, corners, lo, hi))

    found.sort(key=lambda m: -m.s)
    out = []
    for m in found:
        if all((m.cx - o.cx) ** 2 + (m.cy - o.cy) ** 2 > (1.5 * max(m.s, o.s)) ** 2
               for o in out):
            out.append(m)
    return out

if __name__ == "__main__":
    import sys, os
    from PIL import Image
    codes = build_dictionary(24, 4)

    from marker import render_marker
    for rot in (0, 1, 2, 3):
        for mp in (10, 16, 24):
            m = render_marker(codes[5], module_px=mp, quiet=True).rotate(
                -90 * rot, expand=True, fillcolor=(255, 255, 255))
            bg = Image.new("RGB", (m.size[0] + 80, m.size[1] + 80), (210, 210, 205))
            bg.paste(m, (40, 40))
            g = to_gray(bg)
            res = detect_markers(g, codes)
            tag = "OK " if (res and res[0].mid == 5 and res[0].rot == rot) else "FAIL"
            print("%s rot=%d module=%dpx -> %s" % (tag, rot, mp, res))
