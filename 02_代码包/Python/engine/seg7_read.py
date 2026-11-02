# -*- coding: utf-8 -*-
"""seg7_read.py — 红色 LED 七段数码管读数（纯 numpy + cv2，纯离线）。

用途
====
配电盘（PD_BOARD）上的两块 XIELI 数字面板表：电池电压（27.0 V，3 位 + 1 位小数）
与市电电压（227 V，3 位整数）。本模块只做「看图 -> 读数」，不做判定、不碰板子、
不写 UI；判定交给调用方（led_rules.json 的 nominal/tol_frac/expect）。

主入口
======
    read_seg7(img, roi=None, ndigits=3, has_dp=True, dp_index_hint=None) -> dict

    返回 {"value":27.1, "digits":[2,7,1], "dp_pos":1, "conf":0.96,   # 负号=-1
          "segments":[[1,1,0,1,1,0,1], ...],   # 每位 a~g 亮灭
          "bbox":[x,y,w,h], "reason":""}
    读不出 ⇒ "value":None（绝不编造），reason 说明卡在哪一步。

附加（便于接入/可视化，不影响主契约）：
    scan_displays(img, ndigits=...)   全图扫描，返回每块表的读数字典列表
    annotate(img, items, ...)         把定位框 / 段亮灭 / 解出的数字画到图上
    imread_u / imwrite_u              兼容中文路径的读写（cv2.imread 不认 CJK）

算法链路
========
 1. 红色 LED 掩膜：HSV(H<=15|H>=170) ∪ (R-max(G,B) 主导) ∪ 贴着红区的「白芯」
    （LED 过曝后字芯发白、光晕发红 ⇒ 白芯才是笔画本体，见 _ink_candidates；
    没有白芯的纯红/合成图自动退回红色几何掩膜）。
 2. 连通域 + 同排水平拼接（_strip_hypotheses：多尺度水平闭运算 + 同排分组）
    ⇒ 候选「数码管显示条」。
 3. 倾角：用「每列墨迹最低点」Theil-Sen 拟合基线（_estimate_angle）⇒ 旋正，
    ±5° 级倾斜由此消除；拟合不出来就按 0°。
 4. 切位：上 80% 行的列投影（避开小数点）⇒ 用「相邻两段的缝」当字符格边界 ⇒
    逐位取墨迹范围当字符框（细窄的 "1" 按右对齐撑到名义宽度）。
 5. 采样：每位按 a~g 固定相对位置判亮灭 —— 横段看行剖面峰值、竖段看列剖面峰值，
    采样前对该位做局部自适应阈值（亮度不均也各自二值化），并做斜切搜索（斜体/残余倾斜）。
 6. 解码：段亮灭 ⇒ 7 位编码 ⇒ 查表（0~9、负号，兼容 7={a,b}/{a,b,c}、9/6 变体）；
    编码非法 ⇒ 该位判不出，绝不用「最像的数字」凑。
 7. 字模兜底：现实面板表不全是标准 7 段（XIELI 市电表把 7 画成「顶横+斜杠」），
    段判糊掉/非法时用渲染字模做 IoU 复核（_glyph_match），并在 reason 里标 glyph_fallback@i。
 8. 小数点：先看「两位之间竖缝底部」的孤立小亮块（_dp_in_gutters），
    缝被光晕糊住时用「解释掉已解笔画后的残差」兜底（_dp_in_residual）；
    强候选 >=2 个 ⇒ multi_dp 拒判。
 9. 置信 = 段裕度 + 位数一致 + 小数点一致 + 字模一致 +（可选）数值范围；
    任一环节失败 ⇒ value=None + reason。

★ 契约：读不出就给 None，绝不用猜测值凑数；conf 只在有读数时才有意义。

2026-10-29（G18 现场）：新增三个**可选**参数，默认值保持旧行为不变 ——
  box_mode="runs"  每位数码管框直接用上 80% 行的墨迹列段（字宽不均时不切掉边缘竖笔；
                   旧口径会把 G18 左表 "270" 的 "2" 左竖笔切掉 ⇒ 段判非法）；
  bin_mode="soft"  单格二值化阈值更宽松（强光晕把笔画蚀断时保笔画；
                   旧口径会把 G18 中间表 "336.3" 蚀成碎片 ⇒ 段判失败）；
  dp_index_hint    多强小数点候选时按「先验位置」裁定（光晕在字缝里造假小数点；
                   旧口径直接 multi_dp 拒判 G18 中间表）。
G18 封装见 soc_vision/g18_seg7.py。

作者：AFH03 视觉子链（离线交付，2026-10-25）
"""

from __future__ import annotations

import os

import cv2
import numpy as np

__all__ = [
    "read_seg7",
    "scan_displays",
    "annotate",
    "imread_u",
    "imwrite_u",
    "SEG_ORDER",
]

SEG_ORDER = ("a", "b", "c", "d", "e", "f", "g")

SEG_WINDOWS = {
    "a": (0.14, 0.86, 0.00, 0.13),
    "b": (0.79, 0.99, 0.10, 0.47),
    "c": (0.79, 0.99, 0.53, 0.90),
    "d": (0.14, 0.86, 0.87, 1.00),
    "e": (0.01, 0.21, 0.53, 0.90),
    "f": (0.01, 0.21, 0.10, 0.47),
    "g": (0.14, 0.86, 0.44, 0.56),
}

_PATTERN_TABLE = [
    ("0", "abcdef"),
    ("1", "bc"),
    ("2", "abdeg"),
    ("3", "abcdg"),
    ("4", "bcfg"),
    ("5", "acdfg"),
    ("6", "acdefg"),
    ("6", "cdefg"),
    ("7", "ab"),
    ("7", "abc"),
    ("8", "abcdefg"),
    ("9", "abcdfg"),
    ("9", "abcfg"),
    ("-", "g"),
]

def _build_lookup():
    lut = {}
    for ch, segs in _PATTERN_TABLE:
        key = frozenset(segs)
        if key in lut and lut[key] != ch:      
            lut[key] = None
        else:
            lut.setdefault(key, ch)
    return lut

_PATTERN_LUT = _build_lookup()

_MAX_DIGITS = 8

def imread_u(path, flags=cv2.IMREAD_COLOR):
    """读图，兼容中文/空格路径。失败返回 None。"""
    try:
        buf = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    if buf.size == 0:
        return None
    return cv2.imdecode(buf, flags)

def imwrite_u(path, img, params=None):
    """写图，兼容中文/空格路径。"""
    ext = os.path.splitext(path)[1]
    if not ext:
        ext = ".png"
        path = path + ext
    ok, buf = cv2.imencode(ext, img, params or [])
    if not ok:
        return False
    buf.tofile(path)
    return True

def _feature_maps(img):
    """BGR -> 红主导度、白芯度、HSV 等派生图（全部 float32，0..255）。"""
    if img is None or img.ndim == 2:
        raise ValueError("read_seg7 需要 BGR 三通道图")
    if img.shape[2] == 4:
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    b = img[:, :, 0].astype(np.float32)
    g = img[:, :, 1].astype(np.float32)
    r = img[:, :, 2].astype(np.float32)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h = hsv[:, :, 0].astype(np.float32)
    s = hsv[:, :, 1].astype(np.float32)
    v = hsv[:, :, 2].astype(np.float32)
    return dict(
        bgr=img,
        b=b,
        g=g,
        r=r,
        h=h,
        s=s,
        v=v,
        minc=np.minimum(np.minimum(r, g), b),      
        reddom=r - np.maximum(g, b),               
    )

def _red_geometry(feat):
    """红色几何掩膜：HSV 红区 ∪ 红主导区。返回 uint8 0/1。"""
    h, s, v = feat["h"], feat["s"], feat["v"]
    reddom, minc = feat["reddom"], feat["minc"]
    hue_dist = np.minimum(np.abs(h - 0.0), 180.0 - np.abs(h - 0.0))
    hsv_red = (hue_dist <= 15.0) & (s >= 55.0) & (v >= 85.0)
    dom_red = (reddom >= 45.0) & (v >= 85.0)
    m = (hsv_red | dom_red).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    return m

def _ink_candidates(feat, red_geo):
    """给出若干「墨迹」候选掩膜，按可信度排序（白芯优先，纯红兜底）。

    白芯：过曝的 LED 笔画本体（三通道都高），但必须贴着红区，避免白墙/白纸误入。
    若该画面没有白芯（LED 未过曝 / 合成图），自动退回红色几何掩膜。
    """
    minc, v, reddom = feat["minc"], feat["v"], feat["reddom"]
    out = []

    red_px = int(red_geo.sum())
    if red_px > 0:
        pos = np.percentile(minc[red_geo > 0], 99.0)
        core_thr = max(105.0, 0.55 * pos)
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        near_red = cv2.dilate(red_geo, k) > 0
        core = ((minc >= core_thr) & near_red).astype(np.uint8)
        core = cv2.morphologyEx(core, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        core_px = int(core.sum())

        if core_px >= max(40, 0.08 * red_px):
            out.append(("core", core))

    red = red_geo.copy()
    if int(red.sum()) > 0:
        cell = max(1, int(round(min(img_dim(feat)) * 0.004)))
        if cell >= 2:
            red = cv2.erode(red, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (cell, cell)))
        if int(red.sum()) > 0:
            out.append(("red", red))
    return out

def img_dim(feat):
    return (feat["bgr"].shape[0], feat["bgr"].shape[1])

def _components(mask, min_area=40):
    """连通域列表（已按面积降序）。"""
    n, lab, st, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    out = []
    for i in range(1, n):
        x, y, w, h, a = (int(v) for v in st[i])
        if a < min_area or h < 8 or w < 4:
            continue
        out.append(dict(x=x, y=y, w=w, h=h, area=a, label=i))
    out.sort(key=lambda c: -c["area"])
    return out, lab

def _strip_hypotheses(mask):
    """多尺度水平闭运算 ⇒ 「一整排数字」的候选框。

    真实面板表的数字被光晕连成一片，先按「典型字高」选水平核宽把字缝连起来，
    再拿候选框去过 digit 拟合（_fit_digits），过不了的自然被淘汰。
    """
    comps, _ = _components(mask, min_area=40)
    if not comps:
        return []
    hs = [c["h"] for c in comps if c["area"] >= 60]
    if not hs:
        return []
    hmed = float(np.median(hs))
    kerns = sorted({max(3, int(round(hmed * r))) for r in (0.30, 0.50, 0.85)} |
                   {7, 13, 21})
    cands = []
    for kw in kerns:
        if kw >= max(mask.shape[:2]):
            continue
        ker = cv2.getStructuringElement(cv2.MORPH_RECT, (kw, 3))
        closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, ker)
        cs, _ = _components(closed, min_area=60)
        for c in cs:
            if c["h"] < 8 or c["w"] < 1.5 * c["h"]:
                continue
            if c["w"] / float(c["h"]) > 12.0:
                continue
            cands.append((c["x"], c["y"], c["w"], c["h"]))

    for gp in _group_in_row(comps, hmed):
        x0 = min(c["x"] for c in gp)
        x1 = max(c["x"] + c["w"] for c in gp)
        y0 = min(c["y"] for c in gp)
        y1 = max(c["y"] + c["h"] for c in gp)
        if len(gp) >= 2 and (x1 - x0) >= 1.4 * (y1 - y0):
            cands.append((x0, y0, x1 - x0, y1 - y0))
    if not cands:
        return []

    uniq = []
    for bb in sorted(cands, key=lambda b: -b[2] * b[3]):
        if all(_iou(bb, u) < 0.75 for u in uniq):
            uniq.append(bb)
    return uniq

def _group_in_row(comps, hmed):
    """把同排、水平相邻的连通域串成若干「一排」假设（用来生成显示条候选框）。

    - 从面积大的开始种组，保证先立起「整位数字」，再把负号/小数点这类小元素并进去；
    - 合排的间距门限按「该排已有高度」算（真实面板表字间距约 0.2~0.4 个字高）；
    - 完全落在排内的矮元素（负号横杠、小数点）允许并入，不受高度比例限制。
    """
    cs = sorted([c for c in comps if c["area"] >= 30], key=lambda c: -c["area"])
    groups = []
    for c in cs:
        best = None
        for gp in groups:
            gy0 = min(o["y"] for o in gp)
            gy1 = max(o["y"] + o["h"] for o in gp)
            gh = max(1, gy1 - gy0)
            inside = (c["y"] >= gy0 - 0.10 * gh) and (c["y"] + c["h"] <= gy1 + 0.10 * gh)
            if not inside:
                if c["h"] < 0.5 * gh or c["h"] > 2.0 * gh:
                    continue
                cy = c["y"] + c["h"] / 2.0
                if not (gy0 - 0.15 * gh <= cy <= gy1 + 0.15 * gh):
                    continue
            gx0 = min(o["x"] for o in gp)
            gx1 = max(o["x"] + o["w"] for o in gp)
            gap = max(0, max(c["x"] - gx1, gx0 - (c["x"] + c["w"])))
            limit = max(0.62 * max(gh, c["h"], hmed), 6)
            if gap <= limit and (best is None or gap < best[0]):
                best = (gap, gp)
        if best is None:
            groups.append([c])
        else:
            best[1].append(c)
    return [gp for gp in groups if len(gp) >= 2]

def _iou(a, b):
    ax0, ay0, ax1, ay1 = a[0], a[1], a[0] + a[2], a[1] + a[3]
    bx0, by0, bx1, by1 = b[0], b[1], b[0] + b[2], b[1] + b[3]
    ix = max(0, min(ax1, bx1) - max(ax0, bx0))
    iy = max(0, min(ay1, by1) - max(ay0, by0))
    inter = ix * iy
    ua = a[2] * a[3] + b[2] * b[3] - inter
    return inter / float(ua) if ua > 0 else 0.0

def _estimate_angle(mask):
    """用「每列墨迹最低点」拟合基线斜率来估倾角（面板表各位数字共用一条基线）。

    比 minAreaRect 稳：光晕把外接矩形糊成一个斜方块时，minAreaRect 给出的是
    与字形无关的角度；而字底边一定在一条直线上。用 Theil-Sen（成对斜率取中位数）
    抗「没有 d 段的 7」造成的基线跳变。
    """
    ys, xs = np.where(mask > 0)
    if len(xs) < 30:
        return None
    x0, x1 = int(xs.min()), int(xs.max())
    if x1 - x0 < 12:
        return None
    bot = np.full(x1 - x0 + 1, np.nan, dtype=np.float32)
    for x in range(x0, x1 + 1):
        col = np.where(mask[:, x] > 0)[0]
        if col.size:
            bot[x - x0] = col.max()
    ok = ~np.isnan(bot)
    if ok.sum() < 12:
        return None
    xx = np.arange(x0, x1 + 1, dtype=np.float32)[ok]
    yy = bot[ok]

    step = max(1, len(xx) // 40)
    sx, sy = xx[::step], yy[::step]
    slopes = []
    for i in range(len(sx) - 1):
        dx = sx[i + 1:] - sx[i]
        m = np.abs(dx) > 1e-6
        if m.any():
            slopes.append((sy[i + 1:][m] - sy[i]) / dx[m])
    if not slopes:
        return None
    slope = float(np.median(np.concatenate(slopes)))

    resid = yy - (slope * xx + (np.median(yy) - slope * np.median(xx)))
    mad = float(np.median(np.abs(resid - np.median(resid)))) + 1e-3
    w = (np.abs(resid - np.median(resid)) <= max(2.0, 4.0 * mad)).astype(np.float32)
    if w.sum() >= 8:
        try:
            a, _b = np.polyfit(xx, yy, 1, w=w)
            slope = float(a)
        except Exception:
            pass

    ang = float(np.degrees(np.arctan(slope)))
    if abs(ang) < 0.5:
        return 0.0
    if abs(ang) > 15.0:
        return None
    return ang

def _straighten(mask, feat, box, pad=0.18):
    """裁出候选框并旋转到水平。返回 dict（含旋正后的掩膜/特征/逆映射）。"""
    H, W = mask.shape[:2]
    px = int(round(box[2] * pad)) + 8
    py = int(round(box[3] * pad)) + 8
    x0 = max(0, box[0] - px)
    y0 = max(0, box[1] - py)
    x1 = min(W, box[0] + box[2] + px)
    y1 = min(H, box[1] + box[3] + py)
    sub = mask[y0:y1, x0:x1]
    if sub.size == 0:
        return None

    ang = _estimate_angle(sub)
    if ang is None:
        ang = 0.0

    center = (sub.shape[1] / 2.0, sub.shape[0] / 2.0)
    if abs(ang) >= 0.6:

        def _ini_height(angle):
            M0 = cv2.getRotationMatrix2D(center, angle, 1.0)
            m0 = cv2.warpAffine(sub, M0, (sub.shape[1], sub.shape[0]),
                                flags=cv2.INTER_NEAREST, borderValue=0)
            bbx0 = _ink_bbox(m0)
            return 10 ** 9 if bbx0 is None else (bbx0[3] - bbx0[1] + 1)

        if _ini_height(ang) >= 0.98 * _ini_height(0.0):
            ang = 0.0

    M = cv2.getRotationMatrix2D(center, ang, 1.0)
    out = {}
    for key in ("mask", "minc", "reddom", "v"):
        src = sub if key == "mask" else feat[key][y0:y1, x0:x1]
        flag = cv2.INTER_NEAREST if key == "mask" else cv2.INTER_LINEAR
        out[key] = cv2.warpAffine(src, M, (sub.shape[1], sub.shape[0]), flags=flag,
                                  borderValue=0)
    out["angle"] = ang
    out["M"] = M
    out["offset"] = (x0, y0)
    out["size"] = (sub.shape[1], sub.shape[0])
    return out

def _to_original(rect, st):
    """旋正坐标下的矩形 -> 原图坐标（用于标注/回传 bbox）。"""
    x, y, w, h = rect
    pts = np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], dtype=np.float32)
    Mi = cv2.invertAffineTransform(st["M"])
    p = cv2.transform(pts.reshape(1, -1, 2), Mi).reshape(-1, 2)
    p[:, 0] += st["offset"][0]
    p[:, 1] += st["offset"][1]
    x0, y0 = float(p[:, 0].min()), float(p[:, 1].min())
    x1, y1 = float(p[:, 0].max()), float(p[:, 1].max())
    return [x0, y0, x1 - x0, y1 - y0]

def _runs(profile, thr, min_len=1, gap_bridge=0):
    """一维投影 -> 连续段列表 [(start, end)]（end 为闭区间）。"""
    on = profile > thr
    if gap_bridge > 0 and on.any():
        idx = np.where(on)[0]
        for a, b in zip(idx[:-1], idx[1:]):
            if 0 < b - a <= gap_bridge:
                on[a:b] = True
    out = []
    i = 0
    n = len(on)
    while i < n:
        if on[i]:
            j = i
            while j + 1 < n and on[j + 1]:
                j += 1
            if j - i + 1 >= min_len:
                out.append((i, j))
            i = j + 1
        else:
            i += 1
    return out

def _ink_bbox(mask):
    ys, xs = np.where(mask > 0)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())

def _fit_digits(mask, ndigits, box_mode="cells"):
    """在旋正后的掩膜里切出 ndigits 个字符框（只用上 80% 行，避开小数点）。

    返回 dict(count=..., boxes=[{x0,x1,cx,w,narrow}], L, T, R, B, H, pitch) 或 None。

    box_mode="cells"（默认）沿用旧口径（缝隙中点推等距字格 + 框内再收缩）；
    box_mode="runs" 直接用上 80% 行的墨迹列段当每位字符框（2026-10-29 G18 新增：
    旧口径在「字宽不均」时会把宽字的边缘竖笔切掉，见 G18 左表 270 的 "2"）。
    """
    bb = _ink_bbox(mask)
    if bb is None:
        return None
    L, T, R, B = bb
    H = B - T + 1
    if H < 8 or (R - L + 1) < H * 0.8:
        return None

    bh = max(4, int(round(H * 0.80)))
    band = mask[T:T + bh, :]                      
    prof = band[:, L:R + 1].sum(axis=0).astype(np.float32)
    if prof.size == 0 or prof.max() <= 0:
        return None
    pos_cols = prof[prof > 0]
    med_pos = float(np.median(pos_cols)) if pos_cols.size else float(prof.max())

    

    thr = max(1.0, min(0.16 * float(prof.max()), 0.50 * med_pos))
    runs = _runs(prof, thr, min_len=max(2, int(round(H * 0.06))),
                 gap_bridge=max(1, int(round(H * 0.05))))
    runs = [(int(a), int(b)) for a, b in runs]

    while len(runs) > ndigits:
        gaps = [(runs[i + 1][0] - runs[i][1], i) for i in range(len(runs) - 1)]
        _, gi = min(gaps)
        runs[gi] = (runs[gi][0], runs[gi + 1][1])
        del runs[gi + 1]
    widths = [r[1] - r[0] + 1 for r in runs]

    if box_mode == "runs" and len(runs) == ndigits:
        starts = [r[0] for r in runs]
        dd = [b - a for a, b in zip(starts[:-1], starts[1:]) if b - a > 0]
        pitch = float(np.median(dd)) if dd else float(R - L + 1) / float(ndigits)
        boxes = []
        ok = True
        for i, (s, e) in enumerate(runs):
            xa, xb = int(s + L), int(e + L)
            narrow = False

            if xb - xa + 1 < 0.45 * pitch:
                xb = min(mask.shape[1] - 1, xb)
                xa = max(0, xb - int(round(0.72 * pitch)))
                narrow = True

            if i > 0:
                prev_e = runs[i - 1][1] + L
                xa = max(xa, (prev_e + xa) // 2)
            if i + 1 < ndigits:
                next_s = runs[i + 1][0] + L
                xb = min(xb, (xb + next_s) // 2)
            if xb - xa < 3:
                ok = False
                break
            boxes.append(dict(x0=int(xa), x1=int(xb), cx=(s + e) / 2.0 + L,
                              w=int(xb - xa + 1), narrow=narrow))
        if ok and pitch > 2:
            return dict(count=ndigits, boxes=boxes, L=L, T=T, R=R, B=B, H=H,
                        pitch=pitch)

    cells = None
    if len(runs) == ndigits and ndigits >= 3:

        
        bounds = [(runs[i][1] + runs[i + 1][0]) / 2.0 + L for i in range(ndigits - 1)]
        diffs = np.diff(bounds)
        pitch = float(np.median(diffs)) if diffs.size else float(R - L + 1) / ndigits
        if pitch <= 2:
            cells = None
        else:
            b0 = bounds[0] - pitch
            bl = bounds[-1] + pitch
            edges = [b0] + list(bounds) + [bl]
            cells = [(edges[i], edges[i + 1]) for i in range(ndigits)]
    if cells is None and len(runs) == ndigits:
        centers = [L + (r[0] + r[1]) / 2.0 for r in runs]
        idx = np.arange(ndigits, dtype=np.float64)
        if ndigits >= 2:
            A = np.vstack([np.ones_like(idx), idx]).T
            (c0, p), *_ = np.linalg.lstsq(A, np.asarray(centers, dtype=np.float64),
                                          rcond=None)
            pitch = float(abs(p)) if abs(p) > 1e-6 else float(R - L + 1) / ndigits
        else:
            pitch = float(R - L + 1)
        centers = [float(c0 + i * p * np.sign(p)) for i in range(ndigits)] \
            if ndigits >= 2 else [float(centers[0])]
        cells = [(c - pitch / 2.0, c + pitch / 2.0) for c in centers]
    if cells is None:

        pitch = (R - L + 1) / float(ndigits)
        cells = [(L + i * pitch, L + (i + 1) * pitch) for i in range(ndigits)]
    if not (pitch > 2):
        return None

    boxes = []
    pad = max(1, int(round(0.04 * pitch)))
    for i in range(ndigits):
        left, right = cells[i]
        a = int(max(0, round(left + pad)))
        b = int(min(mask.shape[1] - 1, round(right - pad)))
        if b - a < 3:
            a = int(max(0, round(left)))
            b = int(min(mask.shape[1] - 1, round(right)))
        if b - a < 3:
            return None
        cx = (left + right) / 2.0
        prof2 = band[:, a:b + 1].sum(axis=0).astype(np.float32)
        mx = float(prof2.max()) if prof2.size else 0.0
        cols = np.where(prof2 > max(1.0, 0.12 * mx))[0] if mx > 0 else np.array([])
        if cols.size:
            xa, xb = a + int(cols[0]), a + int(cols[-1])
        else:
            xa, xb = int(round(left + 0.10 * pitch)), int(round(right - 0.10 * pitch))
        narrow = False
        if xb - xa + 1 < 0.45 * pitch:      
            xb = min(mask.shape[1] - 1, xb)
            xa = xb - int(round(0.72 * pitch))
            narrow = True
        maxw = int(round(0.94 * pitch))
        if xb - xa + 1 > maxw:              
            mid = (xa + xb) / 2.0
            xa = int(round(mid - maxw / 2.0))
            xb = xa + maxw - 1
        xa = max(0, xa)
        xb = min(mask.shape[1] - 1, xb)
        if xb <= xa:
            return None
        boxes.append(dict(x0=int(xa), x1=int(xb), cx=float(cx),
                          w=int(xb - xa + 1), narrow=narrow))
    return dict(count=ndigits, boxes=boxes, L=L, T=T, R=R, B=B, H=H, pitch=pitch)

SEG_BANDS = {
    "a": ("h", (0.18, 0.82), (0.00, 0.20)),   
    "g": ("h", (0.18, 0.82), (0.38, 0.62)),
    "d": ("h", (0.18, 0.82), (0.80, 1.00)),
    "b": ("v", (0.72, 1.00), (0.16, 0.44)),
    "c": ("v", (0.72, 1.00), (0.56, 0.86)),
    "e": ("v", (0.00, 0.28), (0.56, 0.86)),
    "f": ("v", (0.00, 0.28), (0.16, 0.44)),
}

def _cell_binary(feat_s, box, box_y, mode, bin_mode="auto"):
    """按「字符框」做局部自适应阈值，返回 0/1 掩膜（只在该框内）。

    mode='core' 用白芯度（minc），'red' 用红主导度；阈值取该框自身分布的分位数，
    所以同一排数字亮度不均（左暗右亮）也能各自二值化（局部自适应 ✔）。

    bin_mode='soft'（2026-10-29 G18 现场新增，默认 "auto" 不变旧行为）：
    旧口径要 0.42/0.30 的高分位，现场光晕强、笔画边缘偏暗时会把笔画蚀断
    （实测 G18 中间表 "336.3" 被切成碎片 → 段判失败）；soft 把分位降到
    0.25/0.15，保住笔画，再由段采样的峰值口径压掉背景。
    """
    x0, x1 = box["x0"], box["x1"]
    y0, y1 = box_y
    src = feat_s["minc"] if mode == "core" else feat_s["reddom"]
    sub = src[max(0, y0):y1 + 1, max(0, x0):x1 + 1]
    if sub.size == 0:
        return None
    pos = float(np.percentile(sub, 99.0))
    med = float(np.median(sub))
    if bin_mode == "soft":
        thr = max(med + 0.25 * (pos - med), 0.15 * pos, 8.0)
    else:
        thr = max(med + 0.42 * (pos - med), 0.30 * pos, 12.0 if mode == "red" else 60.0)
    return (sub >= thr).astype(np.uint8)

def _shear_cell(bin_img, shear):
    """按斜切量把字符框「摆正」（shear 单位：框宽的倍数 / 框高）。"""
    if abs(shear) < 1e-3:
        return bin_img
    h, w = bin_img.shape[:2]
    if h < 3 or w < 3:
        return bin_img
    k = shear * w / float(max(1, h - 1))
    M = np.array([[1.0, k, -0.5 * k * (h - 1)], [0.0, 1.0, 0.0]], dtype=np.float32)
    return cv2.warpAffine(bin_img, M, (w, h), flags=cv2.INTER_NEAREST, borderValue=0)

def _fill_profile(prof, smooth):
    """一维剖面 -> 「有没有一条亮带」的置信（0..1）。

    先用与笔画宽度同量级的窗口做平滑（抑制单像素噪声），再取峰值。
    """
    if prof.size == 0:
        return 0.0
    k = max(1, int(round(smooth)))
    if k > 1:
        ker = np.ones(k, dtype=np.float32) / k
        prof = np.convolve(prof.astype(np.float32), ker, mode="same")
    return float(np.clip(prof.max(), 0.0, 1.0))

def _sample_segments(bin_img, shear=0.0):
    """在字符框内按 a~g 固定相对位置判定亮/灭，返回 {seg: fill} (0..1)。"""
    h, w = bin_img.shape[:2]
    if h < 6 or w < 4:
        return None
    cell = _shear_cell(bin_img.astype(np.float32), shear)
    out = {}
    for seg in SEG_ORDER:
        kind, span, band = SEG_BANDS[seg]
        if kind == "h":
            r0 = int(np.clip(round(band[0] * (h - 1)), 0, h - 1))
            r1 = int(np.clip(round(band[1] * (h - 1)), 0, h - 1))
            c0 = int(np.clip(round(span[0] * (w - 1)), 0, w - 1))
            c1 = int(np.clip(round(span[1] * (w - 1)), 0, w - 1))
            if r1 < r0 or c1 < c0:
                out[seg] = 0.0
                continue
            prof = cell[r0:r1 + 1, c0:c1 + 1].mean(axis=1)
            out[seg] = _fill_profile(prof, max(1.0, 0.055 * h))
        else:
            c0 = int(np.clip(round(span[0] * (w - 1)), 0, w - 1))
            c1 = int(np.clip(round(span[1] * (w - 1)), 0, w - 1))
            r0 = int(np.clip(round(band[0] * (h - 1)), 0, h - 1))
            r1 = int(np.clip(round(band[1] * (h - 1)), 0, h - 1))
            if c1 < c0 or r1 < r0:
                out[seg] = 0.0
                continue
            prof = cell[r0:r1 + 1, c0:c1 + 1].mean(axis=0)
            out[seg] = _fill_profile(prof, max(1.0, 0.055 * w))
    return out

def _decode(fill, thr=0.48):
    """fill 字典 -> (digit 字符或 None, bits, margin, key)。"""
    bits = tuple(1 if fill[s] >= thr else 0 for s in SEG_ORDER)
    key = frozenset(s for s, b in zip(SEG_ORDER, bits) if b)
    ch = _PATTERN_LUT.get(key)
    margin = float(np.mean([abs(fill[s] - 0.5) * 2.0 for s in SEG_ORDER]))
    return ch, bits, margin, key

def _pattern_crisp(fill, digit):
    """该位「亮/灭」有多干脆：最弱的亮段 - 最强的灭段（0..1）。

    越小说明笔画糊/字形不是标准 7 段，段判结论就不可靠。
    """
    if digit is None:
        return 0.0
    segs = None
    for ch, ss in _PATTERN_TABLE:
        if ch == digit:
            segs = set(ss)
            break
    if not segs:
        return 0.0
    on = [fill[s] for s in segs]
    off = [fill[s] for s in SEG_ORDER if s not in segs]
    lo_on = min(on) if on else 1.0
    hi_off = max(off) if off else 0.0
    return float(lo_on - hi_off)

_TEMPLATE_SIZE = (48, 64)          
_TEMPLATE_CACHE = {}

def _template_segs():
    return dict(
        zero="abcdef", one="bc", two="abdeg", three="abcdg", four="bcfg",
        five="acdfg", six="acdefg", seven="abc", eight="abcdefg",
        nine="abcdfg", minus="g",
    )

def _render_templates():
    """渲染 0~9 / 负号 的 7 段字模 + 「斜杠 7」字形字模。返回 {ch: uint8}。"""
    w, h = _TEMPLATE_SIZE
    lut = {}

    def blank():
        return np.zeros((h, w), dtype=np.uint8)

    def put(img, x0, x1, y0, y1):
        a = int(round(x0 * (w - 1)))
        b = int(round(x1 * (w - 1)))
        c = int(round(y0 * (h - 1)))
        d = int(round(y1 * (h - 1)))
        img[max(0, c):d + 1, max(0, a):b + 1] = 1

    for ch, name in (("0", "zero"), ("1", "one"), ("2", "two"), ("3", "three"),
                     ("4", "four"), ("5", "five"), ("6", "six"), ("7", "seven"),
                     ("8", "eight"), ("9", "nine"), ("-", "minus")):
        img = blank()
        for seg in _template_segs()[name]:
            a, b, y0, y1 = SEG_WINDOWS[seg]
            put(img, a, b, y0, y1)
        lut.setdefault(ch, []).append(img)

    img = blank()
    put(img, 0.10, 0.96, 0.00, 0.15)
    cv2.line(img, (int(0.90 * (w - 1)), int(0.10 * (h - 1))),
             (int(0.28 * (w - 1)), int(0.94 * (h - 1))), 1, max(2, int(0.15 * w)))
    lut.setdefault("7", []).append(img)

    img = blank()
    put(img, 0.72, 0.94, 0.04, 0.96)
    lut.setdefault("1", []).append(img)
    return lut

def _get_templates():
    if not _TEMPLATE_CACHE:
        _TEMPLATE_CACHE.update(_render_templates())
    return _TEMPLATE_CACHE

def _glyph_match(bin_cell):
    """字符框二值图 -> (最佳字符或 None, 最佳分, 次佳分, 明细)。

    用 IoU；字符框先归一化到固定网格，消除字号差异。
    """
    h, w = bin_cell.shape[:2]
    if h < 6 or w < 4:
        return None, 0.0, 0.0, {}
    tw, th = _TEMPLATE_SIZE
    cell = cv2.resize(bin_cell.astype(np.float32), (tw, th), interpolation=cv2.INTER_AREA)
    cell = (cell >= 0.5)
    best = {}
    for ch, tpls in _get_templates().items():
        sc = 0.0
        for t in tpls:
            tt = t.astype(bool)
            inter = float(np.logical_and(cell, tt).sum())
            union = float(np.logical_or(cell, tt).sum())
            sc = max(sc, inter / union if union > 0 else 0.0)
        best[ch] = sc
    order = sorted(best.items(), key=lambda kv: -kv[1])
    if not order:
        return None, 0.0, 0.0, best
    return order[0][0], order[0][1], order[1][1] if len(order) > 1 else 0.0, best

def _render_digit_into(canvas, x0, y0, w, h, digit):
    """把某数字的段几何画进 canvas（用于「解释掉」已知笔画）。

    一个字可能对应多种段编码（如 7 = {a,b} 或 {a,b,c}），这里全部画上，
    宁可多覆盖一点，也要把真笔画解释干净，剩下的残差才可能是小数点。
    """
    segs = set()
    for ch, ss in _PATTERN_TABLE:
        if ch == digit:
            segs |= set(ss)
    if not segs:
        return
    for seg in segs:
        a, b, c, d = SEG_WINDOWS[seg]
        xa = int(round(x0 + a * (w - 1)))
        xb = int(round(x0 + b * (w - 1)))
        ya = int(round(y0 + c * (h - 1)))
        yb = int(round(y0 + d * (h - 1)))
        canvas[max(0, ya):yb + 1, max(0, xa):xb + 1] = 1

def _dp_in_gutters(st, fit):
    """在「相邻两位之间的竖缝」底部找孤立小亮块（小数点物理上就长在这儿）。"""
    mask = st["mask"]
    boxes = fit["boxes"]
    T, B, H = fit["T"], fit["B"], fit["H"]
    if H < 10:
        return []
    y0 = int(round(T + 0.50 * H))
    y1 = B
    min_area = max(4, int(round(0.008 * H * fit["pitch"])))
    out = []
    n = len(boxes)
    for i in range(n):
        xa = boxes[i]["x1"] - 1
        if i + 1 < n:
            xb = boxes[i + 1]["x0"] + 1
        else:
            xb = int(round(boxes[i]["x1"] + 0.55 * fit["pitch"]))
        xa = int(max(0, xa))
        xb = int(min(mask.shape[1] - 1, xb))
        if xb - xa < 2:
            continue
        sub = mask[y0:y1 + 1, xa:xb + 1]
        if sub.size == 0 or int(sub.sum()) < min_area:
            continue
        nn, lab, stt, _ = cv2.connectedComponentsWithStats(sub, 8)
        for k in range(1, nn):
            x, y, w, h, a = (int(v) for v in stt[k])
            if a < min_area:
                continue
            if h > 0.45 * H or w > 0.45 * fit["pitch"]:
                continue
            if (y + y0) < T + 0.58 * H:        
                continue
            score = float(a) / float(max(1.0, 0.03 * H * fit["pitch"]))
            out.append((i, min(1.0, score), "gutter", w, h))
    return out

def _dp_in_residual(st, fit, digits):
    """兜底：把已解出的笔画「解释掉」，剩下的孤立小块也算小数点候选。"""
    mask = st["mask"]
    T, B, H = fit["T"], fit["B"], fit["H"]
    if H < 10:
        return []
    canvas = np.zeros_like(mask)
    for i, bx in enumerate(fit["boxes"]):
        d = digits[i] if i < len(digits) else None
        if d is None:
            continue
        _render_digit_into(canvas, bx["x0"], T, bx["w"], H, d)
    k = max(1, int(round(0.08 * H)) | 1)
    cover = cv2.dilate(canvas, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    resid = mask.copy()
    resid[cover > 0] = 0
    if int(resid.sum()) == 0:
        return []
    min_area = max(4, int(round(0.008 * H * fit["pitch"])))
    out = []
    nn, lab, stt, _ = cv2.connectedComponentsWithStats(resid, 8)
    for i in range(1, nn):
        x, y, w, h, a = (int(v) for v in stt[i])
        if a < min_area:
            continue
        if h > 0.45 * H or w > 0.45 * fit["pitch"]:
            continue
        if y + h < T + 0.62 * H:
            continue
        score = float(a) / float(max(1.0, 0.03 * H * fit["pitch"]))
        cx = x + w / 2.0
        pos = None
        for j, bx in enumerate(fit["boxes"]):
            if cx >= bx["x1"] - 0.22 * fit["pitch"]:
                pos = j
        if pos is not None:
            out.append((pos, min(1.0, score), "resid", w, h))
    return out

def _detect_dp(st, fit, digits):
    """小数点检测。返回 (dp_pos 或 None, 强度, 强候选个数, 宽, 高, 按位置明细)。

    主口径：小数点只能长在「两位之间的竖缝」底部（_dp_in_gutters）；
    竖缝被膨胀的白色光晕糊住时，再用「解释掉笔画后的残差」兜底。
    强候选 >= 2 个 ⇒ 口径不明（如 8.8.8），上层据此拒判；
    但上层若拿到 dp_index_hint（小数点位置先验）且该位置本身有强候选，
    可按先验裁定（见 _read_strip）。
    第 6 个返回值 by_pos: {pos: (score, kind, w, h)}，供上层按先验挑位置。
    """
    cands = _dp_in_gutters(st, fit)
    if not cands:
        cands = _dp_in_residual(st, fit, digits)
    if not cands:
        return None, 0.0, 0, 0, 0, {}

    best_by_pos = {}
    for pos, sc, kind, w, h in cands:
        if pos not in best_by_pos or sc > best_by_pos[pos][0]:
            best_by_pos[pos] = (sc, kind, w, h)
    strong = sum(1 for v in best_by_pos.values() if v[0] >= 0.45)
    pos, (sc, kind, w, h) = max(best_by_pos.items(), key=lambda kv: kv[1][0])
    return pos, sc, strong, int(w), int(h), best_by_pos

def _read_strip(feat, ink_mask, mode, box, ndigits, has_dp, dp_index_hint,
                value_range, debug=False, box_mode="cells", bin_mode="auto"):
    st = _straighten(ink_mask, feat, box)
    if st is None:
        return None
    fit = _fit_digits(st["mask"], ndigits, box_mode=box_mode)
    if fit is None:
        return None
    T, B, H = fit["T"], fit["B"], fit["H"]
    if H < 12:
        return None

    if not (0.28 <= fit["pitch"] / float(H) <= 1.35):
        return None
    for bx in fit["boxes"]:
        cell = st["mask"][T:B + 1, bx["x0"]:bx["x1"] + 1]
        if cell.size == 0 or cell.mean() < 0.03:
            return None

    best = None
    for shear in (0.0, 0.12, -0.12, 0.22, -0.22, 0.32, -0.32):
        fills, digits, bits, margins, glyphs, bins = [], [], [], [], [], []
        oks = True
        for bx in fit["boxes"]:
            if bx["x1"] <= bx["x0"]:
                oks = False
                break
            bin_img = _cell_binary(st, bx, (T, B), mode, bin_mode=bin_mode)
            if bin_img is None or bin_img.shape[0] < 4:
                oks = False
                break
            f = _sample_segments(bin_img, shear)
            if f is None:
                oks = False
                break
            ch, bb, mg, key = _decode(f)
            gch, gsc, g2, _ = _glyph_match(bin_img)
            fills.append(f)
            digits.append(ch)
            bits.append(bb)
            margins.append(mg)
            glyphs.append((gch, gsc, g2))
            bins.append(bin_img)
        if not oks or not fills:
            continue
        n_ok = sum(1 for d in digits if d is not None)
        margin = float(np.mean(margins))

        score = n_ok * 2.0 + margin - 0.50 * abs(shear)
        if n_ok < ndigits:
            score -= 1.5 * (ndigits - n_ok)
        if best is None or score > best["score"]:
            best = dict(score=score, shear=shear, fills=fills, digits=digits,
                        bits=bits, margins=margins, margin=margin, n_ok=n_ok,
                        glyphs=glyphs, bins=bins)

    if best is None:
        return None

    

    fallback = []
    for i, d in enumerate(best["digits"]):
        gch, gsc, g2 = best["glyphs"][i]
        crisp = _pattern_crisp(best["fills"][i], d)
        glyph_ok = (gch is not None and gsc >= 0.50 and (gsc - g2) >= 0.12)
        if d is None:
            if glyph_ok and gsc >= 0.42:
                best["digits"][i] = gch
                fallback.append(i)
        elif glyph_ok and gch != d and crisp < 0.35:
            best["digits"][i] = gch
            fallback.append(i)
    if debug:
        print(f"[seg7] mode={mode} box={box} angle={st['angle']:.2f} "
              f"shear={best['shear']:+.2f} pitch={fit['pitch']:.1f} H={H} "
              f"fallback={fallback}")
        for i, f in enumerate(best["fills"]):
            print("   d%d %s %s glyph=%s(%.2f/%.2f)" %
                  (i, best["digits"][i],
                   " ".join("%s=%.2f" % (s, f[s]) for s in SEG_ORDER),
                   best["glyphs"][i][0], best["glyphs"][i][1], best["glyphs"][i][2]))
    n_ok = sum(1 for d in best["digits"] if d is not None)
    if n_ok < ndigits:
        return dict(value=None, digits=None, dp_pos=None, conf=0.0,
                    segments=best["bits"], bbox=box,
                    reason="seg_pattern_invalid:%s" % (best["digits"],),
                    meta=dict(mode=mode, angle=st["angle"], shear=best["shear"],
                              pitch=fit["pitch"], digit_boxes=fit["boxes"],
                              straighten=st, fit=fit, fills=best["fills"],
                              fallback=fallback))

    dp_pos, dp_strength, n_dp, dp_width, dp_height, dp_by_pos = \
        _detect_dp(st, fit, best["digits"])
    dstr = "".join(str(d) for d in best["digits"])

    reason = []
    conf = 0.0
    val = None
    ok = True
    if has_dp:
        if dp_pos is None:
            ok = False
            reason = ["dp_not_found"]
        elif n_dp >= 2:

            

            hinted = None
            if dp_index_hint is not None:
                hinted = dp_by_pos.get(int(dp_index_hint))
            if hinted is not None and hinted[0] >= 0.45:
                dp_pos = int(dp_index_hint)
                dp_strength = hinted[0]
                reason = ["multi_dp_hint_resolved(%d)" % n_dp]
            else:
                ok = False
                reason = ["multi_dp(%d)" % n_dp]
        elif dp_index_hint is not None and dp_pos != dp_index_hint:
            reason.append("dp_pos!=hint(%s)" % dp_index_hint)
    else:
        if dp_pos is not None:

            
            compact = (dp_width <= 0.26 * fit["pitch"]) and (dp_height <= 0.32 * H)
            if dp_strength >= 0.90 and compact:
                ok = False
                reason = ["dp_unexpected"]
            else:

                reason.append("dp_weak_ignored")

    if ok:
        try:
            if best["digits"][0] == "-":
                body = best["digits"][1:]
                sign = -1.0
            else:
                body = best["digits"]
                sign = 1.0
            if not body or any(ch is None for ch in body):
                raise ValueError("digit")
            if has_dp:
                k = int(dp_pos) + 1 - (1 if best["digits"][0] == "-" else 0)
                k = max(0, min(len(body), k))
                s = "".join(body[:k]) + "." + "".join(body[k:])
            else:
                s = "".join(body)
            val = sign * float(s if s not in (".", "-.") else "0")
            if not has_dp and "." in s:
                raise ValueError("dp")
        except Exception:
            ok = False
            reason = ["value_parse_failed"]

    nd_ok = 1.0 if len(best["digits"]) == ndigits else 0.0
    uniq = 1.0
    if has_dp:
        dp_ok = 1.0 if dp_pos is not None else 0.0
    else:
        dp_ok = 1.0 if dp_pos is None else 0.60
    rng_ok = 1.0
    if ok and value_range is not None and val is not None:
        lo, hi = value_range
        rng_ok = 1.0 if (lo <= val <= hi) else 0.25
        if rng_ok < 1.0:
            reason.append("out_of_range")

    agree = []
    for g, d in zip(best["glyphs"], best["digits"]):
        if g[0] is None or g[1] < 0.45:
            agree.append(0.5)
        else:
            agree.append(1.0 if g[0] == d else 0.0)
    glyph_agree = float(np.mean(agree)) if agree else 0.5
    if fallback:
        reason.append("glyph_fallback@%s" % (",".join(str(i) for i in fallback)))
    if glyph_agree < 0.55:
        reason.append("glyph_disagree")

    if ok:
        conf = (0.44 * best["margin"] + 0.16 * nd_ok + 0.13 * dp_ok +
                0.10 * uniq + 0.07 * rng_ok + 0.10 * glyph_agree)
        conf -= 0.05 * len(fallback)
        conf = float(np.clip(conf, 0.0, 1.0))

    chars = best["digits"]
    digits_out = None
    if ok:
        digits_out = [(-1 if ch == "-" else int(ch)) for ch in chars]
    return dict(
        value=val if ok else None,
        digits=digits_out,
        dp_pos=dp_pos if has_dp else None,
        conf=conf,
        segments=[[int(b) for b in bb] for bb in best["bits"]],
        bbox=list(box),
        reason=";".join(reason),
        meta=dict(mode=mode, angle=st["angle"], shear=best["shear"],
                  pitch=fit["pitch"], digit_boxes=fit["boxes"], straighten=st,
                  fit=fit, fills=best["fills"], margin=best["margin"],
                  text=dstr, dp_strength=dp_strength, fallback=fallback,
                  glyph_agree=round(glyph_agree, 3),
                  glyphs=[(g[0], round(g[1], 3), round(g[2], 3)) for g in best["glyphs"]],
                  segments_fill=[{s: round(f[s], 3) for s in SEG_ORDER}
                                 for f in best["fills"]]),
    )

def read_seg7(img, roi=None, ndigits=3, has_dp=True, dp_index_hint=None,
              value_range=None, debug=False, box_mode="cells", bin_mode="auto"):
    """读一块红色 LED 七段数码管面板表。

    参数
    ----
    img : np.ndarray  BGR 图（或路径）
    roi : [x, y, w, h] 或 (x0,y0,x1,y1)；None ⇒ 全图搜
    ndigits : 位数（不含小数点）
    has_dp : 是否应出现小数点
    dp_index_hint : 小数点应落在第几位之后（0 基），None 不约束。
        给定时若检出多个强小数点候选，会优先采用「恰好在 hint 位置」的那个
        （G18 面板中表的光晕会在缝隙里造出假小数点，实测必需）。
    value_range : (lo, hi) 物理合理区间，仅用于置信打分（不改变读数）
    debug : 打印每位 a~g 的采样值
    box_mode : "cells"（默认，旧口径）| "runs"
        字符框口径。"cells" 用相邻墨迹段缝隙中点推等距字格；
        "runs" 直接用「上 80% 行」的墨迹列段当每位数码管框，适合字宽不均
        （如 270 的 "2" 宽、"7" 窄）导致旧口径把左竖笔切掉的面板表。
    bin_mode : "auto"（默认，旧口径）| "soft"
        单格二值化阈值。"soft" 用更低的分位数阈值，适合 LED 光晕强、
        笔画边缘偏暗（旧口径会把笔画蚀断）的现场照片。

    返回: dict（见模块头）。读不出 ⇒ value=None + reason，绝不编造。

    注：box_mode/bin_mode 为 2026-10-29 G18 现场新增的可选项，默认值保持旧行为
    不变（既有调用方不受影响）。
    """
    if isinstance(img, str):
        img = imread_u(img)
    if img is None:
        return _fail("no_image", None)
    if img.ndim != 3 or img.shape[2] < 3:
        return _fail("not_bgr", None)
    try:
        ndigits = int(ndigits)
    except Exception:
        return _fail("bad_ndigits", None)
    if not (1 <= ndigits <= _MAX_DIGITS):
        return _fail("bad_ndigits", None)

    off = (0, 0)
    work = img
    if roi is not None:
        r = _norm_roi(roi, img.shape)
        if r is None:
            return _fail("bad_roi", None)
        x, y, w, h = r
        work = img[y:y + h, x:x + w]
        off = (x, y)
        if work.size == 0:
            return _fail("empty_roi", [x, y, w, h])

    feat = _feature_maps(work)
    red_geo = _red_geometry(feat)
    if int(red_geo.sum()) < 30:
        return _fail("no_led_strip", [off[0], off[1], work.shape[1], work.shape[0]])

    rows = _read_all_strips(feat, red_geo, ndigits, has_dp, dp_index_hint,
                            value_range, debug=debug, box_mode=box_mode,
                            bin_mode=bin_mode)
    if not rows:
        return _fail("no_display_fit", [off[0], off[1], work.shape[1], work.shape[0]])

    
    best = max(rows, key=lambda r: r["_rank"])
    bb = best["bbox"]
    best["bbox"] = [bb[0] + off[0], bb[1] + off[1], bb[2], bb[3]]
    _relocate(best, off)
    return _finish(best, work, off)

def _read_all_strips(feat, red_geo, ndigits, has_dp, dp_index_hint, value_range,
                     debug=False, box_mode="cells", bin_mode="auto"):
    """把所有「候选显示条 × 墨迹模式」都读一遍，返回带 `_rank` 的结果列表。"""
    cands = []
    for mode, mask in _ink_candidates(feat, red_geo):
        for box in _strip_hypotheses(mask):
            cands.append((mode, mask, box))
    if not cands:
        return []
    seen = set()
    ordered = []
    for mode, mask, box in cands:
        key = (box, mode)
        if key in seen:
            continue
        seen.add(key)
        ordered.append((mode, mask, box))

    ordered.sort(key=lambda t: (0 if t[0] == "core" else 1, -t[2][2] * t[2][3]))
    rows = []
    for mode, mask, box in ordered:
        res = _read_strip(feat, mask, mode, box, ndigits, has_dp, dp_index_hint,
                          value_range, debug=debug, box_mode=box_mode,
                          bin_mode=bin_mode)
        if res is None:
            continue
        res["_rank"] = _candidate_rank(res, mode)
        rows.append(res)
    return rows

def _candidate_rank(res, mode):
    """候选排序分：有读数 > 位型全对但小数点失败 > 乱码；白芯小幅加成。"""
    conf = float(res.get("conf") or 0.0)
    digits = res.get("digits")
    meta = res.get("meta") or {}
    reason = res.get("reason") or ""
    if res.get("value") is not None:
        base = 0.70 + 0.30 * conf
    elif digits is not None and reason.startswith(("dp_", "out_of_range")):
        base = 0.45 + 0.25 * float(meta.get("margin") or 0.0)
    else:
        base = 0.10 * float(meta.get("margin") or 0.0)
    if mode == "core":
        base += 0.05
    return base

def _relocate(res, off):
    """把 meta 里的字符框换算回原图坐标（标注用）。"""
    st = res.get("meta", {}).get("straighten")
    fit = res.get("meta", {}).get("fit")
    if st is None or fit is None:
        return
    boxes = []
    for bx in fit["boxes"]:
        rect = (bx["x0"], fit["T"], bx["x1"] - bx["x0"], fit["B"] - fit["T"] + 1)
        b = _to_original(rect, st)
        b[0] += off[0]
        b[1] += off[1]
        boxes.append([round(v, 1) for v in b])
    res["meta"]["digit_boxes_orig"] = boxes

def _finish(res, work, off):
    """补全返回字段（对外只暴露契约 + 必要附加）。"""
    out = dict(
        value=res.get("value"),
        digits=res.get("digits"),
        dp_pos=res.get("dp_pos"),
        conf=float(res.get("conf") or 0.0),
        segments=res.get("segments") or [],
        bbox=res.get("bbox"),
        reason=res.get("reason") or "",
    )
    meta = res.get("meta") or {}
    out["seg_fill"] = meta.get("segments_fill") or []
    out["digit_boxes"] = meta.get("digit_boxes_orig") or []
    out["conf_detail"] = dict(margin=round(float(meta.get("margin") or 0.0), 3),
                              shear=meta.get("shear"), angle=round(float(meta.get("angle") or 0.0), 2),
                              mask=meta.get("mode"), pitch=round(float(meta.get("pitch") or 0.0), 1),
                              dp_strength=round(float(meta.get("dp_strength") or 0.0), 3))
    out["text"] = meta.get("text") or ""
    return out

def _fail(reason, bbox):
    return dict(value=None, digits=None, dp_pos=None, conf=0.0, segments=[],
                bbox=bbox, reason=reason, seg_fill=[], digit_boxes=[],
                conf_detail={}, text="")

def _norm_roi(roi, shape):
    """roi = [x, y, w, h]（与 led_rules.json 的 roi_hint 一致）；越界自动夹紧。"""
    try:
        v = [int(round(float(t))) for t in roi]
    except Exception:
        return None
    if len(v) != 4:
        return None
    H, W = shape[:2]
    x, y, w, h = v
    x = max(0, min(x, W - 1))
    y = max(0, min(y, H - 1))
    w = max(1, min(w, W - x))
    h = max(1, min(h, H - y))
    return x, y, w, h

def scan_displays(img, ndigits=(3, 4, 5, 6), has_dp=None, min_conf=0.0,
                  include_rejected=False, debug=False, box_mode="cells",
                  bin_mode="auto"):
    """全图扫描：把**每一块**候选显示条都读一遍，返回去重后的结果列表。

    和 `read_seg7(roi=None)` 的区别：后者只返回「最可信的那一块」，
    这里把全图所有候选都试一遍，能读出来的都返回（照片里一次找齐多块表靠它）。
    `include_rejected=True` 时才把「切不出合法位型」的候选也列出来（排查用）。
    """
    if isinstance(img, str):
        img = imread_u(img)
    if img is None:
        return []
    if img.ndim != 3 or img.shape[2] < 3:
        return []
    feat = _feature_maps(img)
    red_geo = _red_geometry(feat)
    if int(red_geo.sum()) < 30:
        return []
    out = []
    for nd in ndigits:
        try:
            nd = int(nd)
        except Exception:
            continue
        if not (1 <= nd <= _MAX_DIGITS):
            continue
        for dp in ((True, False) if has_dp is None else (bool(has_dp),)):
            for res in _read_all_strips(feat, red_geo, nd, dp, None, None,
                                        debug=debug, box_mode=box_mode,
                                        bin_mode=bin_mode):
                if res.get("value") is None and not include_rejected:
                    continue
                out.append(res)

    keep = []
    order = sorted(out, key=lambda z: (z.get("value") is None, -float(z.get("_rank") or 0.0)))
    for r in order:
        if any(_iou(r["bbox"], k["bbox"]) > 0.55 for k in keep):
            continue
        keep.append(r)
    keep = [k for k in keep if (k.get("conf") or 0) >= min_conf]
    return [_finish(k, img, (0, 0)) for k in keep]

def annotate(img, items, scale=1.0, show_segments=True, show_fill=False):
    """把定位框 / 每位字符框 / a~g 亮灭 / 解出的数字画到图上。

    items: read_seg7 的返回（或它的列表）。返回新图（BGR）。
    """
    if isinstance(items, dict):
        items = [items]
    out = img.copy()
    if out.ndim == 2:
        out = cv2.cvtColor(out, cv2.COLOR_GRAY2BGR)
    H, W = out.shape[:2]
    fs = max(0.35, min(1.0, W / 1800.0)) * scale
    th = max(1, int(round(2 * fs)))
    for it in items:
        bb = it.get("bbox")
        if not bb:
            continue
        x, y, w, h = [int(round(v)) for v in bb]
        ok = it.get("value") is not None
        col = (0, 220, 0) if ok else (0, 165, 255)
        cv2.rectangle(out, (x, y), (x + w, y + h), col, th)
        txt = ("%.1f" % it["value"]) if ok else "None"
        label = "%s  conf=%.2f" % (txt, it.get("conf") or 0.0)
        if it.get("text"):
            label = "%s  [%s]" % (label, it["text"])
        if not ok and it.get("reason"):
            label = "None  %s" % it["reason"][:34]
        ty = max(12, y - 6)
        cv2.putText(out, label, (x, ty), cv2.FONT_HERSHEY_SIMPLEX, fs * 0.9,
                    (0, 0, 0), th + 2, cv2.LINE_AA)
        cv2.putText(out, label, (x, ty), cv2.FONT_HERSHEY_SIMPLEX, fs * 0.9,
                    col, th, cv2.LINE_AA)
        boxes = it.get("digit_boxes") or []
        segs = it.get("segments") or []
        fills = it.get("seg_fill") or []
        for i, db in enumerate(boxes):
            dx, dy, dw, dh = [int(round(v)) for v in db]
            cv2.rectangle(out, (dx, dy), (dx + dw, dy + dh), (255, 200, 0), max(1, th - 1))
            if show_segments and i < len(segs):
                _draw_segments(out, db, segs[i], fs, th)
            if i < len(fills) and fills[i]:
                _draw_digit_label(out, db, i, segs[i] if i < len(segs) else None, fs, th)
    return out

def _seg_rect(db, seg):
    x, y, w, h = db
    x0 = x + SEG_WINDOWS[seg][0] * w
    x1 = x + SEG_WINDOWS[seg][1] * w
    y0 = y + SEG_WINDOWS[seg][2] * h
    y1 = y + SEG_WINDOWS[seg][3] * h
    return int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1))

def _draw_segments(out, db, bits, fs, th):
    for seg, b in zip(SEG_ORDER, bits):
        x0, y0, x1, y1 = _seg_rect(db, seg)
        if b:
            cv2.rectangle(out, (x0, y0), (x1, y1), (60, 255, 60), max(1, th - 1))
        else:
            cv2.rectangle(out, (x0, y0), (x1, y1), (90, 90, 90), 1)

    for seg in ("a", "g", "d"):
        x0, y0, x1, y1 = _seg_rect(db, seg)
        cv2.putText(out, seg, (x0, max(8, y0 - 2)), cv2.FONT_HERSHEY_SIMPLEX,
                    fs * 0.55, (255, 255, 0), max(1, th - 1), cv2.LINE_AA)

def _draw_digit_label(out, db, idx, bits, fs, th):
    x, y, w, h = [int(round(v)) for v in db]
    txt = "d%d" % idx
    ty = y + h + int(14 * fs)
    cv2.putText(out, txt, (x, ty), cv2.FONT_HERSHEY_SIMPLEX, fs * 0.7,
                (0, 0, 0), th + 2, cv2.LINE_AA)
    cv2.putText(out, txt, (x, ty), cv2.FONT_HERSHEY_SIMPLEX, fs * 0.7,
                (0, 255, 255), th, cv2.LINE_AA)
