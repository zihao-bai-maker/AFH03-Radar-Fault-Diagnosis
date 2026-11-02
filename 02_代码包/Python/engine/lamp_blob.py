#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lamp_blob.py —— 颜色亮点检测 + 灯位自动定位（纯离线；numpy + cv2，不联网/不装包）

为什么要有这个模块
==================
旧做法把"第几颗灯"写死成照片坐标（``led_rules.json`` 的 ``measured.photo_xy``）。
机位一变（手持、站远一点、斜一点）坐标就落到面板空白处 ⇒ **灯明明亮着，系统判"灯不亮"**。
这里改成"先找画面里亮的红/绿/白/琥珀斑块，再判每块是不是自发光"——
不需要预先知道灯在哪，机位变了也能重新定位。

算法（与用户给的方案一致；偏离处见下）
======================================
1. **可选 ROI**：``roi=(x, y, w, h)``，不给就全图；全图时靠面积/形状/亮度门排除大面积亮背景。
2. **颜色掩膜（HSV，OpenCV 口径 H∈[0,179]、S/V∈[0,255]）**：见 :data:`HSV_RANGES`。
3. **形态学**：先开运算（去孤立噪点）再闭运算（把被高光切断的同一颗灯合并）。
4. **连通域**：``cv2.connectedComponentsWithStats``（无 cv2 时退化为内置 numpy 并查集），
   过滤 ``area∈[min_area, max_area]`` + 长宽比 + 实心比（bbox 填充率）+ 半径区间：
   长条亮带（实心比低/长宽比大）和方形按钮面（实心比≈1.0）都会被挡掉。
5. **自发光判定**：中心盘（0.55r）中位 V − 环带（1.35r~1.95r）中位 V = ``delta_v``（归一化 0~1）；
   ``delta_v ≥ dv_thresh`` ⇒ ``on=True``。暗灯（on=False）照样输出，只是"没亮"。
6. **去重/合并**：同心/重叠的同类斑块合并，保留置信度高的。
7. **排序**：按 y 再 x 升序（``xy`` 始终是原图坐标）。

与用户方案的偏离（都属于"允许改进"，逐条说明）
==============================================
* **红/绿的下限 V 放宽到 70**（用户给的是 90/70）：真实现场很多灭灯灯罩是"暗红/暗绿透镜"，
  V 只有 70~105。不放宽就永远找不到"没亮的那颗"，也没法做"2 红 + 1 绿"的整组映射。
  ``S`` 下限保持 90/80，所以灰白面板不会进掩膜。
* **增加形状门**：``extent``（连通域 / bbox 面积）上限 0.86 —— 绿/红**方形按钮面**的
  extent≈0.89~0.95，必须排除，否则 Z31 的〔通〕〔断〕两颗方按钮会被数成灯。
* **增加半径区间**（按图像长边自适应）：太小的是噪点，太大的是面板/纸张/墙面。
  另加一条：**不亮的色斑半径 ≤ 0.012×长边**（1600 → 19 px）—— 实测 Z14 的红色"电源"
  方按钮（r≈26、delta_v=+0.16）在暗门板上看着像"亮"，其实是一整块红塑料；
  不亮的大色块不是灯罩，直接不当灯。
* **增加 ``solidity``/``circularity``**（有 cv2 时）：细长反光条、丝印笔画会被挡掉。
  面积 ≥100 px 的斑块要求更严（solidity≥0.85、circularity≥0.55）——实测 Z14 的红色
  方按钮 circ=0.56、Z31 的绿色方形按钮 circ=0.75，都会被 extent/circ 挡；真正的圆灯 circ≈0.86。
  面积 < 30 px 的小灯罩不卡这两项（像素太少，形状量本身不可靠）。
* **白灯更严**：白灯掩膜（S≤40, V≥200）会把面板上所有反光点都吃进来。实测一张 Z31
  照片能出 60+ 个 2~4 px 的高光点，所以白灯要求 面积≥24、半径≥0.0028×长边、
  solidity≥0.85、circularity≥0.70 —— 只留"圆、够大"的白灯，宁缺毋滥。
* **``on`` = ``delta_v ≥ dv_thresh`` 且 ``center_v ≥ 0.45``**：用户方案只看"中心 vs 环带"，
  这里再要一个绝对亮度下限。实测 Z14 红色"电源"按钮面 delta_v=+0.16（塑料面比暗门板亮）
  但 center_v 只有 0.43，会被这条挡掉；真红灯 center_v=0.79~0.93。

对外接口
========
``detect_lamps(img, roi=None, colors=("red","green","white","amber"), min_area=6,
max_area=None, dv_thresh=0.10) -> list[dict]``

每条::

    {"xy": (x, y), "r": 6.2, "color": "red|green|white|amber",
     "hsv": (h, s, v), "center_v": 0.93, "ring_v": 0.47, "delta_v": 0.46,
     "on": True, "conf": 0.95, "area": 218}

另附 ``group_lamps()``（把斑块按"同一排/同一列"聚成灯组，供判定层做整组映射）与
``draw_lamps()``（画带坐标的标注框，给离线报告用）。

依赖：numpy（必需）、cv2（可选；没有 cv2 时用 numpy 形态学 + 并查集，结果略慢但一致）。
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

try:                                                        
    import cv2                                              
except Exception:                                           
    cv2 = None

__all__ = ["detect_lamps", "group_lamps", "draw_lamps", "HSV_RANGES", "RED_LENS_RANGES",
           "COLOR_CN"]

HSV_RANGES: Dict[str, List[Tuple[int, int, int, int]]] = {

    
    "red":   [(0, 15, 90, 70), (170, 179, 90, 70)],   
    "green": [(35, 85, 80, 70)],
    "amber": [(15, 35, 90, 90)],
    "white": [(0, 179, 0, 200)],                      
}

RED_LENS_RANGES: List[Tuple[int, int, int, int]] = [(0, 20, 70, 60), (170, 179, 70, 60)]
WHITE_S_MAX = 40                                          
WHITE_MIN_AREA = 24                                       
WHITE_MIN_R_FRAC = 0.0028                                 
V_ON_MIN = 0.45                                           

COLOR_CN = {"red": "红", "green": "绿", "white": "白", "amber": "琥珀"}

_DRAW_BGR = {"red": (0, 0, 255), "green": (0, 200, 0),
             "white": (0, 220, 220), "amber": (0, 190, 255)}
_DRAW_OFF = (128, 128, 128)

def _dilate(mask: np.ndarray, r: int = 1) -> np.ndarray:
    out = np.ascontiguousarray(mask, dtype=bool).copy()
    for _ in range(int(r)):
        m = out.copy()
        out[1:, :] |= m[:-1, :]
        out[:-1, :] |= m[1:, :]
        m = out.copy()
        out[:, 1:] |= m[:, :-1]
        out[:, :-1] |= m[:, 1:]
    return out

def _erode(mask: np.ndarray, r: int = 1) -> np.ndarray:
    return ~_dilate(~np.ascontiguousarray(mask, dtype=bool), r)

def _open_close(mask: np.ndarray) -> np.ndarray:
    """开运算去噪 + 闭运算合并（cv2 有就用 cv2，没有就 numpy 4 邻域）。"""
    m = np.ascontiguousarray(mask, dtype=np.uint8) * 255
    if cv2 is not None:
        k3 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, k3)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k3)
        return m > 0
    return _erode(_dilate(_erode(_dilate(m > 0, 1)), 1), 1)

def _cc_numpy(mask: np.ndarray, min_area: int) -> List[Dict[str, Any]]:
    """连通域（4 邻接 + 并查集），返回 [{area,x0,y0,w,h,cx,cy}]（按面积降序）。"""
    m = np.ascontiguousarray(mask, dtype=bool)
    h, w = m.shape
    parent: List[int] = []

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    runs: List[Tuple[int, int, int, int]] = []
    prev: List[Tuple[int, int, int]] = []
    for y in range(h):
        row = m[y]
        if not row.any():
            prev = []
            continue
        d = np.diff(np.concatenate(([0], row.view(np.int8), [0])))
        starts = np.flatnonzero(d == 1)
        ends = np.flatnonzero(d == -1)
        cur: List[Tuple[int, int, int]] = []
        for x0, x1 in zip(starts, ends):
            lab = len(parent)
            parent.append(lab)
            runs.append((y, int(x0), int(x1), lab))
            cur.append((int(x0), int(x1), lab))
        j = 0
        for (x0, x1, lab) in cur:
            while j < len(prev) and prev[j][1] <= x0:
                j += 1
            k = j
            while k < len(prev) and prev[k][0] < x1:
                union(lab, prev[k][2])
                k += 1
        prev = cur
    if not runs:
        return []
    groups: Dict[int, Dict[str, Any]] = {}
    for (y, x0, x1, lab) in runs:
        r = find(lab)
        g = groups.get(r)
        if g is None:
            groups[r] = {"area": x1 - x0, "x0": x0, "x1": x1, "y0": y, "y1": y}
        else:
            g["area"] += x1 - x0
            g["x0"] = min(g["x0"], x0)
            g["x1"] = max(g["x1"], x1)
            g["y0"] = min(g["y0"], y)
            g["y1"] = max(g["y1"], y)
    out: List[Dict[str, Any]] = []
    for g in groups.values():
        if g["area"] < min_area:
            continue
        g["w"] = g["x1"] - g["x0"] + 1
        g["h"] = g["y1"] - g["y0"] + 1
        g["cx"] = 0.5 * (g["x0"] + g["x1"])
        g["cy"] = 0.5 * (g["y0"] + g["y1"])
        out.append(g)
    out.sort(key=lambda z: -z["area"])
    return out

def _components(mask: np.ndarray, min_area: int) -> List[Dict[str, Any]]:
    """连通域列表；有 cv2 时用 ``connectedComponentsWithStats``（按规格）。"""
    if cv2 is not None:
        n, lab, stats, cents = cv2.connectedComponentsWithStats(
            np.ascontiguousarray(mask, dtype=np.uint8), connectivity=8)
        out: List[Dict[str, Any]] = []
        for i in range(1, n):
            x, y, w, h, area = (int(v) for v in stats[i])
            if area < min_area:
                continue
            out.append({"area": area, "x0": x, "y0": y, "w": int(w), "h": int(h),
                        "cx": float(cents[i][0]), "cy": float(cents[i][1]), "label": i})
        out.sort(key=lambda z: -z["area"])
        return out
    return _cc_numpy(mask, min_area)

def _shape_quality(mask: np.ndarray, cc: Dict[str, Any]) -> Tuple[float, float]:
    """返回 (solidity, circularity)；无 cv2 或面积太小时给 1.0（不参与过滤）。"""
    if cv2 is None or cc.get("label") is None:
        return 1.0, 1.0
    x0, y0 = cc["x0"], cc["y0"]
    w, h = cc["w"], cc["h"]
    sub = np.ascontiguousarray(mask[y0:y0 + h, x0:x0 + w], dtype=np.uint8)
    cnts, _ = cv2.findContours(sub, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cnts:
        return 1.0, 1.0
    c = max(cnts, key=cv2.contourArea)
    a = float(cv2.contourArea(c))
    p = float(cv2.arcLength(c, True))
    hull = cv2.convexHull(c)
    ha = float(cv2.contourArea(hull))
    solidity = a / max(ha, 1e-6)
    circ = 4.0 * math.pi * a / max(p * p, 1e-6)
    return float(min(1.0, solidity)), float(min(1.0, circ))

def _hsv_image(bgr: np.ndarray) -> np.ndarray:
    """BGR uint8 → HSV（OpenCV 口径）。无 cv2 时用 numpy 手算，H 折算回 0-179。"""
    if cv2 is not None:
        return cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    a = bgr.astype(np.float32) / 255.0
    b, g, r = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    mx = np.max(a, axis=2)
    mn = np.min(a, axis=2)
    d = mx - mn
    h = np.zeros_like(mx)
    nz = d > 1e-6
    rm = nz & (mx == r)
    gm = nz & (mx == g) & ~rm
    bm = nz & (mx == b) & ~rm & ~gm
    with np.errstate(invalid="ignore", divide="ignore"):
        h = np.where(rm, 60.0 * (((g - b) / np.where(d == 0, 1, d)) % 6.0), h)
        h = np.where(gm, 60.0 * (((b - r) / np.where(d == 0, 1, d)) + 2.0), h)
        h = np.where(bm, 60.0 * (((r - g) / np.where(d == 0, 1, d)) + 4.0), h)
    s = np.where(mx > 1e-6, d / np.maximum(mx, 1e-6), 0.0)
    out = np.dstack([h % 360.0 / 2.0, s * 255.0, mx * 255.0])
    return np.clip(out, 0, 255).astype(np.uint8)

def _color_mask(hsv: np.ndarray, color: str,
                ranges: Optional[Dict[str, List[Tuple[int, int, int, int]]]] = None
                ) -> Optional[np.ndarray]:
    """单个颜色的 HSV 掩膜（bool）。未知颜色返回 None。

    ``ranges``：本调用临时覆盖 :data:`HSV_RANGES`（Fix2：灭红灯用
    :data:`RED_LENS_RANGES` 的更宽掩膜；不传就是模块默认）。
    """
    rng = (ranges or {}).get(color) or HSV_RANGES.get(color)
    if not rng:
        return None
    h = hsv[:, :, 0].astype(np.int16)
    s = hsv[:, :, 1].astype(np.int16)
    v = hsv[:, :, 2].astype(np.int16)
    m = np.zeros(h.shape, dtype=bool)
    for (h_lo, h_hi, s_min, v_min) in rng:
        if color == "white":
            m |= (s <= WHITE_S_MAX) & (v >= v_min)
        else:
            m |= (h >= h_lo) & (h <= h_hi) & (s >= s_min) & (v >= v_min)
    return m

def _disc_ring_stats(v: np.ndarray, cx: float, cy: float, r: float
                     ) -> Optional[Tuple[float, float]]:
    """在 V 图上量 中心盘(0.55r) 与 环带(1.35r~1.95r) 的中位亮度（0-255）。"""
    if r < 1.0:
        return None
    h, w = v.shape[:2]
    if not (0 <= cx < w and 0 <= cy < h):
        return None
    rr = 2.0 * r + 2
    x0, x1 = int(max(0, math.floor(cx - rr))), int(min(w, math.ceil(cx + rr) + 1))
    y0, y1 = int(max(0, math.floor(cy - rr))), int(min(h, math.ceil(cy + rr) + 1))
    if x1 - x0 < 3 or y1 - y0 < 3:
        return None
    yy, xx = np.mgrid[y0:y1, x0:x1]
    d2 = (yy - cy) ** 2.0 + (xx - cx) ** 2.0
    disc = d2 <= (0.55 * r) ** 2
    ring = (d2 >= (1.35 * r) ** 2) & (d2 <= (1.95 * r) ** 2)
    if int(disc.sum()) < 3 or int(ring.sum()) < 8:
        return None
    sub = v[y0:y1, x0:x1]
    return float(np.median(sub[disc])), float(np.median(sub[ring]))

def _conf(delta_v: float, dv_thresh: float, area: float) -> float:
    """置信度：亮灯看超过阈值多少；灭灯看低于阈值多少；再乘一个面积质量因子。"""
    thr = max(1e-6, float(dv_thresh))
    if delta_v >= thr:
        t = (delta_v - thr) / thr
        c = 0.55 + 0.40 * min(1.0, t)
    else:
        t = (thr - delta_v) / thr
        c = 0.55 + 0.35 * min(1.0, max(0.0, t))
    q = 0.90 + 0.10 * min(1.0, float(area) / 60.0)
    return float(max(0.0, min(0.98, c * q)))

def detect_lamps(img: np.ndarray,
                 roi: Optional[Sequence[float]] = None,
                 colors: Sequence[str] = ("red", "green", "white", "amber"),
                 min_area: int = 6,
                 max_area: Optional[int] = None,
                 dv_thresh: float = 0.10,
                 ranges: Optional[Dict[str, List[Tuple[int, int, int, int]]]] = None
                 ) -> List[Dict[str, Any]]:
    """在面板区域内找"亮的红/绿/白/琥珀斑块"，并逐块判自发光。

    参数
    ----
    img : np.ndarray
        BGR uint8 图（OpenCV 口径）。中文路径请用
        ``cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)`` 读。
    roi : (x, y, w, h) | None
        只在框内找；坐标始终返回**原图**坐标。``None`` = 全图（靠形状/面积排除大面积亮背景）。
    colors : 序列
        要检测的颜色子集，取值 ``red/green/white/amber``。
    min_area : int
        连通域面积下限（像素）。
    max_area : int | None
        面积上限；``None`` = 按图像大小自适应（``0.25%`` 画面，且 ≥64）。
    dv_thresh : float
        自发光阈值（归一化 0~1）：``delta_v = (中心V - 环带V)/255 ≥ 该值`` 且
        ``center_v ≥ V_ON_MIN(0.45)`` ⇒ ``on=True``。
    ranges : dict | None
        本调用临时覆盖 :data:`HSV_RANGES`（如 ``{"red": RED_LENS_RANGES}``
        用来找"有灯罩但没亮"的暗红透镜）；``None`` = 模块默认掩膜。

    返回
    ----
    list[dict]：按 ``(y, x)`` 升序；每条见模块 docstring。
    """
    if img is None or not isinstance(img, np.ndarray) or img.size == 0:
        return []
    if img.ndim == 2:
        img = np.dstack([img] * 3)
    H, W = img.shape[:2]
    if H < 3 or W < 3:
        return []

    if roi is not None:
        try:
            rx, ry, rw, rh = [int(round(float(v))) for v in roi]
        except Exception:
            rx, ry, rw, rh = 0, 0, W, H
        rx = max(0, min(W - 1, rx))
        ry = max(0, min(H - 1, ry))
        rw = max(1, min(W - rx, rw))
        rh = max(1, min(H - ry, rh))
    else:
        rx, ry, rw, rh = 0, 0, W, H
    sub_bgr = img[ry:ry + rh, rx:rx + rw]
    sub_hsv = _hsv_image(sub_bgr)
    sub_v = sub_hsv[:, :, 2].astype(np.float32)

    long_side = max(H, W)
    if max_area is None:
        max_area = max(64, int(0.0025 * W * H))
    r_lo = max(1.8, 0.0014 * long_side)      
    r_hi = max(r_lo + 2.0, 0.022 * long_side)
    r_off_max = max(r_lo + 1.0, 0.012 * long_side)   
    max_area = int(min(max_area, math.pi * r_hi * r_hi))

    out: List[Dict[str, Any]] = []
    for color in colors:
        m = _color_mask(sub_hsv, color, ranges)
        if m is None or not m.any():
            continue
        m = _open_close(m)
        if not m.any():
            continue
        c_min_area = max(int(min_area), WHITE_MIN_AREA) if color == "white" else int(min_area)
        c_r_lo = max(r_lo, WHITE_MIN_R_FRAC * long_side) if color == "white" else r_lo
        for cc in _components(m, int(c_min_area)):
            area = int(cc["area"])
            if area > max_area:
                continue
            w, h = int(cc["w"]), int(cc["h"])
            if w < 2 or h < 2:
                continue
            extent = area / float(max(1, w * h))         
            if not (0.40 <= extent <= 0.86):
                continue                                 
            aspect = w / float(max(1, h))
            if not (0.45 <= aspect <= 2.2):
                continue                                 
            r = max(math.sqrt(area / math.pi), 0.5 * min(w, h))
            if not (c_r_lo <= r <= r_hi):
                continue
            sol, circ = _shape_quality(m, cc)
            if color == "white":
                if sol < 0.85 or circ < 0.70:
                    continue                             
            elif area >= 100:
                if sol < 0.85 or circ < 0.55:
                    continue                             
            elif area >= 30:
                if sol < 0.70 or circ < 0.50:
                    continue                             
            cx = float(cc["cx"]) + rx
            cy = float(cc["cy"]) + ry
            stats = _disc_ring_stats(sub_v, cc["cx"], cc["cy"], r)
            if stats is None:
                continue
            center_v, ring_v = stats
            delta_v = (center_v - ring_v) / 255.0
            on = bool(delta_v >= float(dv_thresh) and center_v / 255.0 >= V_ON_MIN)
            if (not on) and r > r_off_max:
                continue              

            ys, xs = np.nonzero(m[cc["y0"]:cc["y0"] + h, cc["x0"]:cc["x0"] + w])
            if len(xs) == 0:
                continue
            pix = sub_hsv[cc["y0"] + ys, cc["x0"] + xs]
            hsv_med = tuple(int(v) for v in np.median(pix, axis=0))
            out.append({
                "xy": (int(round(cx)), int(round(cy))),
                "r": round(float(r), 2),
                "color": color,
                "hsv": hsv_med,
                "center_v": round(float(center_v) / 255.0, 3),
                "ring_v": round(float(ring_v) / 255.0, 3),
                "delta_v": round(float(delta_v), 3),
                "on": on,
                "conf": round(_conf(delta_v, dv_thresh, area), 3),
                "area": area,
                "fill": round(extent, 3),
            })

    out.sort(key=lambda b: -b["conf"])
    merged: List[Dict[str, Any]] = []
    for b in out:
        dup = False
        for k in merged:
            d = math.hypot(b["xy"][0] - k["xy"][0], b["xy"][1] - k["xy"][1])
            same = (b["color"] == k["color"])
            if same and d < 0.75 * (b["r"] + k["r"]):
                dup = True
                break

            if (not same) and d < 0.55 * max(b["r"], k["r"]):
                dup = True
                break
        if not dup:
            merged.append(b)
    merged.sort(key=lambda b: (b["xy"][1], b["xy"][0]))
    return merged

def group_lamps(blobs: Sequence[Dict[str, Any]], tol: float = 0.0,
                long_side: int = 0, max_gap: float = 0.0) -> List[List[Dict[str, Any]]]:
    """把斑块按"同一排 / 同一列"聚成灯组（供判定层做整组映射）。

    现实里的灯面板一定是"横排"或"竖排"：同组 = x 坐标几乎相同（竖排）
    或 y 坐标几乎相同（横排）。Z31 的三颗灯是**竖排**（x≈958，y=228/308/437）。

    做法（**不做传递闭包**，避免"隔两颗灯一路连成一大片"）：
      1. 竖排：先按 x 聚（x 差 ≤ ``tol``），簇内按 y 排序，相邻灯距 > ``max_gap`` 就切开；
      2. 横排：先按 y 聚（y 差 ≤ ``tol``），簇内按 x 排序，相邻灯距 > ``max_gap`` 就切开；
      3. 两种切法得到的组取并集（按斑块集合去重），单颗灯也单独成组。

    ``tol``：对齐容差（像素）；``0`` 时按 ``long_side*0.02``（1600 长边 → 32 px）。
    ``max_gap``：组内最大灯间距；``0`` 时按 ``long_side*0.15``（1600 → 240 px）。
    """
    n = len(blobs)
    if n == 0:
        return []
    ls = float(long_side or 1600)
    if tol <= 0:
        tol = max(4.0, 0.02 * ls)
    if max_gap <= 0:
        max_gap = max(24.0, 0.15 * ls)

    seen: Dict[Tuple[int, ...], List[Dict[str, Any]]] = {}

    def add(idxs: Sequence[int]) -> None:
        key = tuple(sorted(set(int(i) for i in idxs)))
        if key and key not in seen:
            g = [blobs[i] for i in key]
            g.sort(key=lambda b: (b["xy"][1], b["xy"][0]))
            seen[key] = g

    for axis in (0, 1):                       
        other = 1 - axis
        order = sorted(range(n), key=lambda i: (blobs[i]["xy"][axis], blobs[i]["xy"][other]))
        i = 0
        while i < n:

            base = blobs[order[i]]["xy"][axis]
            line = [order[i]]
            j = i + 1
            while j < n and abs(blobs[order[j]]["xy"][axis] - base) <= tol:
                line.append(order[j])
                j += 1

            line.sort(key=lambda k: blobs[k]["xy"][other])
            seg = [line[0]]
            for k in line[1:]:
                if abs(blobs[k]["xy"][other] - blobs[seg[-1]]["xy"][other]) > max_gap:
                    add(seg)
                    seg = [k]
                else:
                    seg.append(k)
            add(seg)
            i = j

    for i in range(n):
        add([i])
    res = list(seen.values())
    res.sort(key=lambda g: (-len(g), g[0]["xy"][1], g[0]["xy"][0]))
    return res

def draw_lamps(img: np.ndarray, blobs: Sequence[Dict[str, Any]],
               path: str = "") -> np.ndarray:
    """在图上画标注框 + 坐标文字（红框=红、绿框=绿、黄框=白/琥珀、灰框=灭）。

    走 ``cv2.imencode(...).tofile(path)`` 落盘 —— 中文路径下 ``cv2.imwrite`` 会失败。
    返回画好的 BGR 图。
    """
    vis = img.copy()
    for b in blobs or []:
        x, y = int(b["xy"][0]), int(b["xy"][1])
        r = max(3.0, float(b["r"]))
        h = int(round(r * 2.2))
        col = _DRAW_BGR.get(b["color"], (0, 255, 255)) if b.get("on") else _DRAW_OFF
        if cv2 is not None:
            cv2.rectangle(vis, (x - h, y - h), (x + h, y + h), col, 2)
            cv2.drawMarker(vis, (x, y), col, cv2.MARKER_CROSS, 8, 1)
            txt = "%s(%d,%d) d=%+.2f %s" % (
                COLOR_CN.get(b["color"], b["color"]), x, y, b["delta_v"],
                "ON" if b.get("on") else "off")
            cv2.putText(vis, txt, (x + h + 3, y - 2), cv2.FONT_HERSHEY_SIMPLEX,
                        0.45, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(vis, txt, (x + h + 3, y - 2), cv2.FONT_HERSHEY_SIMPLEX,
                        0.45, col, 1, cv2.LINE_AA)
        else:                                            
            vis[max(0, y - 1):y + 2, max(0, x - h):x + h + 1] = col
            vis[max(0, y - h):y + h + 1, max(0, x - 1):x + 2] = col
    if path and cv2 is not None:
        ok, buf = cv2.imencode(".png", vis)
        if ok:
            buf.tofile(path)
    return vis
