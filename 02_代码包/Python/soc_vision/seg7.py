#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""seg7.py —— **7 段数码管读数器**（纯 numpy + Pillow，不依赖字体渲染、不依赖 cv2）。

用在 ⑨ 配电盘（真值：电池电压 `26.6`、市电电压 `222`、工作计时器 `00307.6`）。

流程
----
1. 载图（PIL）→ 按宽高比做朝向归一（横拍右转 90°）→ 缩到工作分辨率长边 1600
2. **高饱和红**掩膜（数码管是红色发光段）：`R > max(G,B)*1.4` 且 `R > 80`
3. 连通域标注（自实现 union-find，纯 numpy）→ 过滤尺寸/长宽比
4. **按行/邻近聚类**成分组（同一块数码表的数字彼此近、高度相近）
5. 组内**垂直投影切位**（列方向有墨水的区间）→ 每位一个 cell；底部小成分 = **小数点**
6. 每位数码管按**相对比例**取 7 段区域（a,b,c,d,e,f,g）→ 与组内墨水平均密度比较得 on/off
   → 7 位码查标准表（允许 Hamming ≤1）→ 数字 + **置信度 = 1 - hamming/7**
7. 按 x 顺序拼串（含小数点）；**任一位 Hamming >1 → 该位输出 `?` 并把整串置信度标低**

命令行
------
    python3 tools/seg7_read.py -i photo.jpg --out out/seg7_annot.png [--json out.json]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageOps

WORK_LONG = 1600

SEG_TABLE = {
    "0": "1111110", "1": "0110000", "2": "1101101", "3": "1111001", "4": "0110011",
    "5": "1011011", "6": "1011111", "7": "1110000", "8": "1111111", "9": "1111011",
    "-": "0000001", " ": "0000000",
}
SEG_ORDER = "abcdefg"

@dataclass
class Digit:
    ch: str = "?"
    conf: float = 0.0
    hamming: int = 9
    x0: int = 0
    x1: int = 0
    y0: int = 0
    y1: int = 0
    segs: str = ""
    dot: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {"ch": self.ch, "conf": round(float(self.conf), 3), "hamming": int(self.hamming),
                "x0": int(self.x0), "x1": int(self.x1), "y0": int(self.y0), "y1": int(self.y1),
                "segs": self.segs, "dot": bool(self.dot)}

@dataclass
class Display:
    text: str = ""
    conf: float = 0.0
    digits: List[Digit] = field(default_factory=list)
    box: Tuple[int, int, int, int] = (0, 0, 0, 0)
    n_digits: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {"text": self.text, "conf": round(float(self.conf), 3),
                "box": [int(v) for v in self.box],
                "n_digits": int(self.n_digits), "digits": [d.to_dict() for d in self.digits]}

def load_rgb(path: str, work_long: int = WORK_LONG):
    im = Image.open(path)
    im = ImageOps.exif_transpose(im).convert("RGB")
    a = np.asarray(im).astype(np.uint8)
    H, W = a.shape[:2]
    if W > H:                                   
        a = np.rot90(a, k=-1)
        H, W = a.shape[:2]
    k = float(work_long) / max(H, W)
    if k < 1.0:
        im2 = Image.fromarray(a).resize((max(1, int(W * k)), max(1, int(H * k))), Image.LANCZOS)
        a = np.asarray(im2).astype(np.uint8)
    return a

def red_mask(a: np.ndarray, ratio: float = 1.4, floor: int = 80) -> np.ndarray:
    r = a[:, :, 0].astype(np.int16)
    g = a[:, :, 1].astype(np.int16)
    b = a[:, :, 2].astype(np.int16)
    m = (r > np.maximum(g, b) * ratio) & (r > floor)
    return m

def label_components(mask: np.ndarray, min_area: int = 8):
    """纯 numpy union-find 4 邻域连通域。返回 (labels, n, stats[(x0,y0,x1,y1,area)])。"""
    H, W = mask.shape
    lab = np.zeros((H, W), np.int32)
    parent: List[int] = [0]

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a_, b_):
        ra, rb = find(a_), find(b_)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    nxt = 1
    for y in range(H):
        row = mask[y]
        if not row.any():
            continue
        for x in np.nonzero(row)[0]:
            up = lab[y - 1, x] if y > 0 else 0
            lf = lab[y, x - 1] if x > 0 else 0
            if up and lf:
                lab[y, x] = min(up, lf)
                union(up, lf)
            elif up:
                lab[y, x] = up
            elif lf:
                lab[y, x] = lf
            else:
                parent.append(nxt)
                lab[y, x] = nxt
                nxt += 1
    stats: List[Tuple[int, int, int, int, int]] = []
    flat: Dict[int, List[int]] = {}
    for y in range(H):
        for x in np.nonzero(lab[y])[0]:
            r = find(int(lab[y, x]))
            lab[y, x] = r
            s = flat.setdefault(r, [x, y, x, y, 0])
            s[0] = min(s[0], x); s[1] = min(s[1], y)
            s[2] = max(s[2], x); s[3] = max(s[3], y); s[4] += 1
    keep = {}
    for r, s in flat.items():
        if s[4] >= min_area:
            keep[r] = len(keep) + 1
            stats.append((s[0], s[1], s[2], s[3], s[4]))
    out = np.zeros_like(lab)
    for r, idx in keep.items():
        out[lab == r] = idx
    return out, len(keep), stats

def _seg_regions(w: int, h: int) -> Dict[str, Tuple[int, int, int, int]]:
    """按相对比例给出 7 段区域（x0,y0,x1,y1）——对常见 7 段字体足够稳。"""
    t = 0.18
    return {
        "a": (int(0.20 * w), int(0.02 * h), int(0.80 * w), int(0.02 * h + t * h)),
        "b": (int(0.80 * w), int(0.10 * h), int(0.98 * w), int(0.48 * h)),
        "c": (int(0.80 * w), int(0.52 * h), int(0.98 * w), int(0.90 * h)),
        "d": (int(0.20 * w), int(0.98 * h - t * h), int(0.80 * w), int(0.98 * h)),
        "e": (int(0.02 * w), int(0.52 * h), int(0.20 * w), int(0.90 * h)),
        "f": (int(0.02 * w), int(0.10 * h), int(0.20 * w), int(0.48 * h)),
        "g": (int(0.20 * w), int(0.44 * h), int(0.80 * w), int(0.56 * h)),
    }

def read_digit(mask: np.ndarray, x0: int, y0: int, x1: int, y1: int) -> Digit:
    """单格读数（**纯函数**：不改外部状态）。★ 入口断言：必须真有墨迹（防"状态泄漏"）。"""
    if mask is None or mask.size == 0 or not mask.any():
        return Digit(ch="?", conf=0.0, hamming=9)

    sub = mask[y0:y1 + 1, x0:x1 + 1]
    h, w = sub.shape
    d = Digit(x0=x0, y0=y0, x1=x1, y1=y1)
    if h < 8 or w < 4:
        return d
    density = float(sub.mean())
    if density <= 0.005:
        d.ch, d.conf, d.hamming = " ", 1.0, 0
        return d
    bits, ink = [], []
    for s in SEG_ORDER:
        rx0, ry0, rx1, ry1 = _seg_regions(w, h)[s]
        rx0, ry0 = max(0, rx0), max(0, ry0)
        rx1, ry1 = min(w, max(rx0 + 1, rx1)), min(h, max(ry0 + 1, ry1))
        region = sub[ry0:ry1, rx0:rx1]
        frac = float(region.mean()) if region.size else 0.0
        ink.append(frac)
        bits.append("1" if frac > max(0.30 * density, 0.02) else "0")
    code = "".join(bits)
    best, best_h, best_c = "?", 9, 0.0
    for ch, ref in SEG_TABLE.items():
        ham = sum(1 for a_, b_ in zip(code, ref) if a_ != b_)
        if ham < best_h:
            best, best_h, best_c = ch, ham, 1.0 - ham / 7.0
    d.segs, d.hamming, d.conf = code, best_h, round(best_c, 3)
    d.ch = best if best_h <= 1 else "?"
    return d

def _cluster(stats: Sequence[Tuple[int, int, int, int, int]], h: int) -> List[List[int]]:
    """按"高度相近 + 水平邻近"把成分聚成显示块。"""
    idx = sorted(range(len(stats)), key=lambda i: (stats[i][1], stats[i][0]))
    groups: List[List[int]] = []
    for i in idx:
        x0, y0, x1, y1, area = stats[i]
        hh = y1 - y0 + 1
        placed = False
        for g in groups:
            gx0 = min(stats[j][0] for j in g); gx1 = max(stats[j][2] for j in g)
            gy0 = min(stats[j][1] for j in g); gy1 = max(stats[j][3] for j in g)
            gh = gy1 - gy0 + 1
            if abs(hh - gh) <= 0.6 * max(hh, gh) and (y0 <= gy1 + 0.5 * gh) and (y1 >= gy0 - 0.5 * gh) \
               and (x0 <= gx1 + 1.2 * max(hh, gh)) and (x1 >= gx0 - 1.2 * max(hh, gh)):
                g.append(i); placed = True; break
        if not placed:
            groups.append([i])
    return groups

def drop_solid_blobs(mask: np.ndarray, lab, stats, fill_thr: float = 0.75) -> np.ndarray:
    """★ 坑①：把"实心"连通成分（填充率 > fill_thr，如红按钮/色块）**直接从掩膜里删掉**。

    实测（fpga-roi-accel）：比"过滤掉不作为字形"更稳，能抹掉 A 区 3 个实心红块；否则它们会被读成 `8`。
    """
    out = mask.copy()
    for i, (x0, y0, x1, y1, area) in enumerate(stats, start=1):
        box = (x1 - x0 + 1) * (y1 - y0 + 1)
        if box > 0 and area / float(box) > fill_thr:
            out[lab == i] = False
    return out

def read_displays(a: np.ndarray, min_area: int = 12, min_digits: int = 1) -> List[Display]:
    mask = red_mask(a)
    lab, n, stats = label_components(mask, min_area=min_area)
    if n == 0:
        return []

    m2 = drop_solid_blobs(mask, lab, stats)
    mask = m2
    lab, n, stats = label_components(mask, min_area=min_area)
    if n == 0:
        return []
    groups = _cluster(stats, a.shape[0])
    out: List[Display] = []
    for g in groups:
        if len(g) < min_digits:
            continue
        x0 = min(stats[i][0] for i in g); x1 = max(stats[i][2] for i in g)
        y0 = min(stats[i][1] for i in g); y1 = max(stats[i][3] for i in g)
        hh, ww = y1 - y0 + 1, x1 - x0 + 1
        if ww < 8 or hh < 12:
            continue
        sub = (lab[y0:y1 + 1, x0:x1 + 1] > 0)
        col = sub.sum(axis=0)

        on = col > 0
        runs, s = [], None
        for i, v in enumerate(on):
            if v and s is None:
                s = i
            elif not v and s is not None:
                runs.append((s, i - 1)); s = None
        if s is not None:
            runs.append((s, len(on) - 1))

        merged: List[List[int]] = []
        for r in runs:
            if merged and (r[0] - merged[-1][1]) <= max(1, int(0.06 * hh)):
                merged[-1][1] = r[1]
            else:
                merged.append([r[0], r[1]])

        
        grid_cells = []
        n_dig = max(1, int(round(ww / max(6.0, 0.62 * hh))))     
        if 1 <= n_dig <= 8:
            bw = ww / float(n_dig)
            best_off, best_sc = 0.0, -1.0
            for off in np.linspace(-0.25 * bw, 0.25 * bw, 11):
                sc = 0.0
                for k2 in range(n_dig):
                    gx0 = int(max(0, off + k2 * bw))
                    gx1 = int(min(ww - 1, off + (k2 + 1) * bw - 1))
                    if gx1 <= gx0:
                        continue
                    sub = sub_mask = (lab[y0:y1 + 1, x0 + gx0:x0 + gx1 + 1] > 0)
                    if sub_mask.sum() < 4:
                        continue

                    dd = read_digit((lab > 0).astype(np.uint8) * 255, x0 + gx0, y0, x0 + gx1, y1)
                    sc += (1.0 - dd.hamming / 7.0)
                if sc > best_sc:
                    best_sc, best_off = sc, off
            grid_cells = [(int(max(0, best_off + k2 * bw)),
                           int(min(ww - 1, best_off + (k2 + 1) * bw - 1)), False)
                          for k2 in range(n_dig)]
        cells: List[Tuple[int, int, bool]] = []
        for r in merged:
            w_r = r[1] - r[0] + 1

            colmask = sub[:, r[0]:r[1] + 1]
            ys = np.nonzero(colmask.any(axis=1))[0]
            if len(ys) and (ys.max() - ys.min() + 1) < 0.28 * hh and w_r <= 0.25 * hh:
                cells.append((r[0], r[1], True))
            else:
                cells.append((r[0], r[1], False))

        if grid_cells:
            gd = [read_digit((lab > 0).astype(np.uint8) * 255, x0 + g[0], y0, x0 + g[1], y1)
                  for g in grid_cells]
            gscore = float(np.mean([1.0 - d2.hamming / 7.0 for d2 in gd])) if gd else -1.0
            pscore = -1.0
            if cells:
                pd = [read_digit((lab > 0).astype(np.uint8) * 255, x0 + r[0], y0, x0 + r[1], y1)
                      for r in cells if not r[2]]
                pscore = float(np.mean([1.0 - d2.hamming / 7.0 for d2 in pd])) if pd else -1.0
            if gscore > pscore:
                cells = grid_cells
        digits: List[Digit] = []
        for (cx0, cx1, is_dot) in cells:
            if is_dot:
                dd = Digit(ch=".", conf=1.0, hamming=0, x0=x0 + cx0, x1=x0 + cx1,
                           y0=y1 - int(0.25 * hh), y1=y1, segs="dot", dot=True)
                digits.append(dd)
                continue
            dd = read_digit(mask, x0 + cx0, y0, x0 + cx1, y1)
            digits.append(dd)
        text = "".join(d.ch for d in digits)
        confs = [d.conf for d in digits if not d.dot and d.ch != " "]
        disp = Display(text=text.strip(), conf=float(np.mean(confs)) if confs else 0.0,
                       digits=digits, box=(int(x0), int(y0), int(x1), int(y1)),
                       n_digits=sum(1 for d in digits if not d.dot))
        if disp.n_digits >= min_digits:
            out.append(disp)
    out.sort(key=lambda z: (z.box[1], z.box[0]))
    return out

def annotate(a: np.ndarray, disps: Sequence[Display]) -> "np.ndarray":
    """画框 + 读数文字（纯 PIL，不依赖字体渲染；用默认位图字体画 ASCII）。"""
    im = Image.fromarray(a.copy())
    try:
        from PIL import ImageDraw
    except Exception:                                                  
        return a
    dr = ImageDraw.Draw(im)
    for d in disps:
        x0, y0, x1, y1 = d.box
        col = (0, 255, 0) if d.conf >= 0.75 else (255, 200, 0)
        dr.rectangle([x0, y0, x1, y1], outline=col, width=3)
        for dd in d.digits:
            if dd.dot:
                continue
            c = (0, 255, 0) if dd.conf >= 0.75 else (255, 80, 80)
            dr.rectangle([dd.x0, dd.y0, dd.x1, dd.y1], outline=c, width=2)
        dr.text((x0, max(0, y0 - 16)), "7SEG=%s conf=%.2f" % (d.text, d.conf), fill=col)
    return np.asarray(im)
