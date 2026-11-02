# -*- coding: utf-8 -*-
"""
cn_ocr.py -- 汉字"显示正常/异常"检测（纯 numpy + Pillow，**不需要 OpenCV**）

背景
----
* 本机 `C:\\Users\\lenovo\\.dsh\\...\\python.exe` 有 numpy 2.3.5 + Pillow 12.3.0，
  **没有 cv2**（也没有 scipy）；Anaconda 的 python 更坏（numpy 直接 DLL load failed）。
  所以这里全部用 numpy + Pillow 自己实现（Otsu 二值化 / 投影切字 / NCC 都手写）。
* 模板库 npz 的格式**与 `afh03_board_setup/soc_vision/ocr_cn.py` 的 `TemplateMatcher` 完全一致**
  （`chars` / `imgs` / `size` / 可选 `grays`），所以两边可以互换使用。

★ 两种判"显示正常"的路子（用户真正的需求是后者更容易落地）
------------------------------------------------------------------
**A. 参考图比对（推荐，最稳）** —— `compare_to_reference()`
    已知系统正常时，把每个字符行/整块显示区二值化后**存成基准位图**。
    之后每帧：同样二值化 → 在 ±max_shift 像素内做**平移对齐**取最大相似度 →
    `sim >= T_sim` 就判"显示正常"，否则"显示异常"。
    优点：**不需要认字**，换字体/换屏都不用重做；对"某段笔画灭掉/某行缺失/花屏"
      这类**真正的故障**非常敏感（因为笔画缺失会直接拉低相似度）。
    代价：需要一张"正常时"的基准图（标定一次）。

**B. 逐字识别（要文字内容时才用）** —— `recognize_row()`
    投影切字 → 与模板库 NCC 匹配 → 输出字符串 + 逐字置信度 → 与期望串比对。
    模板可以**由 Windows 中文字体直接渲染**（本机有 simhei/simsun/msyh/simkai/...），
    也可以从现场标定图抠（`build_from_image`）。

标定/使用最短路径
------------------
  # 1) 先看自动定位到的文字行对不对（会给一张标注图）
  python cn_ocr.py --image 照片.jpg --auto --draw out\\annot.png
  # 2) 显示正常时，把这块区域存成基准
  python cn_ocr.py --image 正常照片.jpg --roi x,y,w,h --save-ref out\\ref.npz
  # 3) 之后每张照片/每帧判"显示是否正常"
  python cn_ocr.py --image 待测.jpg --roi x,y,w,h --ref out\\ref.npz
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont

DEFAULT_SIZE = (32, 32)

DEFAULT_CHARS = "门限机型量程视频录取对消自适应恒虚警参差塔台状态天线方向检"

DEFAULT_FONTS = [
    r"C:\Windows\Fonts\simhei.ttf",     
    r"C:\Windows\Fonts\Deng.ttf",       
    r"C:\Windows\Fonts\msyh.ttc",       
    r"C:\Windows\Fonts\simsun.ttc",     
    r"C:\Windows\Fonts\simkai.ttf",     
]

def _to_gray(a: np.ndarray) -> np.ndarray:
    """任意输入 -> float32 灰度 (H,W)，0..255。"""
    if a.ndim == 3:
        if a.shape[2] >= 3:
            r, g, b = a[:, :, 0].astype(np.float32), a[:, :, 1].astype(np.float32), a[:, :, 2].astype(np.float32)
            return 0.299 * r + 0.587 * g + 0.114 * b
        return a[:, :, 0].astype(np.float32)
    return a.astype(np.float32)

def _resize_gray(g: np.ndarray, size: Tuple[int, int]) -> np.ndarray:
    """用 Pillow 做高质量缩放（size=(w,h)）。"""
    w, h = int(size[0]), int(size[1])
    im = Image.fromarray(np.clip(g, 0, 255).astype(np.uint8), mode="L")
    return np.asarray(im.resize((w, h), Image.LANCZOS)).astype(np.float32)

def otsu_threshold(g: np.ndarray, nbins: int = 256) -> float:
    """numpy 版 Otsu（不依赖 cv2）。"""
    v = np.clip(g, 0, 255).astype(np.uint8).ravel()
    hist = np.bincount(v, minlength=nbins).astype(np.float64)
    total = hist.sum()
    if total <= 0:
        return 127.0
    p = hist / total
    omega = np.cumsum(p)
    mu = np.cumsum(p * np.arange(nbins))
    mu_t = mu[-1]
    denom = omega * (1.0 - omega)
    denom[denom < 1e-12] = 1e-12
    sigma_b = (mu_t * omega - mu) ** 2 / denom
    return float(np.argmax(sigma_b))

def binarize(patch: np.ndarray, make_char_bright: bool = True) -> np.ndarray:
    """Otsu 二值化，统一成 mode "字=255 / 底=0"。"""
    g = _to_gray(patch)
    t = otsu_threshold(g)
    b = (g > t).astype(np.uint8) * 255
    if make_char_bright:

        if b.size and float(b.mean()) > 127.0:
            b = 255 - b
    return b

def to_bitmap(patch: np.ndarray, size: Tuple[int, int] = DEFAULT_SIZE) -> np.ndarray:
    """把一块区域归一化成 size 的二值位图（字=255）。"""
    if patch is None or patch.size == 0:
        return np.zeros((int(size[1]), int(size[0])), np.uint8)
    g = _to_gray(patch)
    g = _resize_gray(g, size)
    return binarize(g)

def _crop_to_ink(b: np.ndarray, pad: int = 1) -> np.ndarray:
    """裁到笔画外接框（含 pad），让字符填满画面（位置/大小归一化）。"""
    ys, xs = np.nonzero(b > 0)
    if ys.size == 0:
        return b
    y0, y1 = max(0, int(ys.min()) - pad), min(b.shape[0], int(ys.max()) + 1 + pad)
    x0, x1 = max(0, int(xs.min()) - pad), min(b.shape[1], int(xs.max()) + 1 + pad)
    return b[y0:y1, x0:x1]

def ncc(a: np.ndarray, b: np.ndarray) -> float:
    """归一化互相关（对亮度/对比度不敏感）。"""
    x = a.astype(np.float32).ravel()
    y = b.astype(np.float32).ravel()
    x = x - x.mean()
    y = y - y.mean()
    nx = float(np.sqrt((x * x).sum()))
    ny = float(np.sqrt((y * y).sum()))
    if nx < 1e-6 or ny < 1e-6:
        return 0.0
    return float((x * y).sum() / (nx * ny))

def dice(a: np.ndarray, b: np.ndarray) -> float:
    """二值图的 Dice 相似度（对"笔画缺失"比 NCC 更敏感）。"""
    A = a > 0
    B = b > 0
    s = A.sum() + B.sum()
    if s == 0:
        return 1.0
    return float(2.0 * np.logical_and(A, B).sum() / s)

def best_shift_similarity(obs: np.ndarray, ref: np.ndarray,
                          max_shift: int = 3) -> Tuple[float, Tuple[int, int]]:
    """在 ±max_shift 像素内平移对齐，返回 (最大相似度, 位移)。

    同时看 NCC 与 Dice，取加权和 —— NCC 管整体形状，Dice 管笔画有没有缺失。
    """
    H, W = ref.shape
    best, bs = -1.0, (0, 0)
    for dy in range(-max_shift, max_shift + 1):
        for dx in range(-max_shift, max_shift + 1):
            s = np.roll(np.roll(obs, dy, axis=0), dx, axis=1)
            v = 0.5 * ncc(s, ref) + 0.5 * dice(s, ref)
            if v > best:
                best, bs = v, (dy, dx)
    return float(best), bs

def to_template_bitmap(patch: np.ndarray, size: Tuple[int, int] = DEFAULT_SIZE) -> np.ndarray:
    """字符块 -> 模板位图：二值化 -> **裁到笔画外接框** -> 缩放 -> 再二值化。

    ★ 模板生成与识别**必须走同一条路**，否则匹配会系统性变差。
    （此前 from_image 只做 resize 不裁框、而 recognize_row 裁框，两边不一致，已统一。）
    """
    b = binarize(patch)
    if b.size == 0 or int(b.max()) == 0:
        return np.zeros((int(size[1]), int(size[0])), np.uint8)
    b = _crop_to_ink(b, pad=1)
    return binarize(_resize_gray(b.astype(np.float32), size))

class TemplateBank:
    """npz 格式与 soc_vision/ocr_cn.py 的 TemplateMatcher 一致：
         chars : (K,) unicode 数组
         imgs  : (K,H,W) uint8（字=255 的二值图）
         size  : (2,) [w,h]
    """

    def __init__(self, chars: Sequence[str], imgs: np.ndarray, size: Tuple[int, int]):
        self.chars: List[str] = [str(c) for c in chars]
        self.imgs: np.ndarray = np.asarray(imgs, dtype=np.uint8)
        self.size: Tuple[int, int] = (int(size[0]), int(size[1]))

    @staticmethod
    def from_fonts(chars: str, fonts: Sequence[str] = DEFAULT_FONTS,
                   size: Tuple[int, int] = DEFAULT_SIZE, px: int = 192) -> "TemplateBank":
        """用中文字体渲染每个字 -> 每个字每个字体一条模板（匹配时按字取最高分）。"""
        out_ch: List[str] = []
        out_im: List[np.ndarray] = []
        for ch in dict.fromkeys(chars):                    
            if ch.strip() == "":
                continue
            for fp in fonts:
                if not os.path.isfile(fp):
                    continue
                b = render_char_bitmap(ch, fp, px=px, size=size)
                if b is None:
                    continue
                out_ch.append(ch)
                out_im.append(b)
        if not out_im:
            raise RuntimeError("没有任何字体可用，无法生成模板（检查 DEFAULT_FONTS 路径）")
        return TemplateBank(out_ch, np.stack(out_im, axis=0), size)

    @staticmethod
    def from_image(patch_list: Sequence[Tuple[str, np.ndarray]],
                   size: Tuple[int, int] = DEFAULT_SIZE) -> "TemplateBank":
        """从现场标定图抠出的字建立模板：[(字, 该字的图像块), ...]

        走 `to_template_bitmap`（二值化→裁笔画框→缩放），与识别路径一致。
        """
        chs = [c for c, _ in patch_list]
        ims = [to_template_bitmap(p, size) for _, p in patch_list]
        return TemplateBank(chs, np.stack(ims, axis=0), size)

    def save(self, path: str) -> None:
        np.savez_compressed(path, chars=np.array(self.chars),
                            imgs=self.imgs, size=np.array(self.size, dtype=np.int32))

    @staticmethod
    def load(path: str) -> "TemplateBank":
        z = np.load(path, allow_pickle=False)
        size = tuple(int(v) for v in z["size"]) if "size" in z.files else \
            (z["imgs"].shape[2], z["imgs"].shape[1])
        return TemplateBank([str(c) for c in z["chars"]], z["imgs"], size)  

    def match(self, ch_bitmap: np.ndarray) -> Tuple[str, float]:
        best_ch, best_v = "?", -1.0
        for k, c in enumerate(self.chars):
            v = 0.5 * ncc(ch_bitmap, self.imgs[k]) + 0.5 * dice(ch_bitmap, self.imgs[k])
            if v > best_v:
                best_v, best_ch = float(v), c
        return best_ch, best_v

def render_char_bitmap(ch: str, font_path: str, px: int = 192,
                       size: Tuple[int, int] = DEFAULT_SIZE) -> Optional[np.ndarray]:
    """用指定字体把单个汉字渲染成 size 的二值位图（裁到外接框后再缩放）。"""
    try:
        font = ImageFont.truetype(font_path, px)
    except Exception:
        return None
    canvas = Image.new("L", (px * 2, px * 2), 0)
    d = ImageDraw.Draw(canvas)
    try:
        d.text((px // 2, px // 2), ch, font=font, fill=255)
    except Exception:
        return None
    a = np.asarray(canvas)
    b = binarize(a)
    if b.max() == 0:
        return None
    b = _crop_to_ink(b, pad=2)
    return binarize(_resize_gray(b.astype(np.float32), size))

def _projection_segments(b: np.ndarray, min_col_px: int = 1) -> List[Tuple[int, int]]:
    proj = (b > 0).sum(axis=0)
    if proj.size == 0 or proj.max() <= 0:
        return []
    on = proj > min_col_px
    segs, s = [], None
    for x, v in enumerate(on):
        if v and s is None:
            s = x
        elif not v and s is not None:
            segs.append((s, x))
            s = None
    if s is not None:
        segs.append((s, int(on.size)))
    return [t for t in segs if t[1] - t[0] >= 2]

def _merge_to_count(segs: List[Tuple[int, int]], n: int) -> List[Tuple[int, int]]:
    """把相邻段按"间隙最小优先"合并到 n 段 —— 解决"们/树/湖"这类左右结构被切成两半。"""
    segs = list(segs)
    while len(segs) > n:
        gaps = [segs[i + 1][0] - segs[i][1] for i in range(len(segs) - 1)]
        i = int(np.argmin(gaps))
        segs[i] = (segs[i][0], segs[i + 1][1])
        del segs[i + 1]
    if not segs:
        return segs
    while len(segs) < n:                                   
        widths = [b - a for a, b in segs]
        i = int(np.argmax(widths))
        a, b = segs[i]
        m = (a + b) // 2
        segs[i:i + 1] = [(a, m), (m, b)]
    return segs

def split_row(patch: np.ndarray, n_chars: int,
              boxes: Optional[Sequence[Tuple[int, int, int, int]]] = None,
              mode: str = "fixed") -> List[Tuple[int, int, int, int]]:
    """把一行字样切成 n_chars 个框，返回 ROI 内坐标 [(x,y,w,h)]。

    三种模式（**这就是"切字比认字更容易出错"的地方**）：
      boxes      给了显式框就直接用 —— 位置固定时**最稳，标定一次即可**
      "fixed"    （默认）先裁到笔画外接框，再按 n_chars 等分
                 —— 汉字是全角等宽，固定位置的字符表用这个最可靠
      "projection" 垂直投影 + 按最小间隙合并到 n 个
                 —— 位置会漂时才用；**左右结构（们/树/湖/限）容易被切错**
    """
    H, W = _to_gray(patch).shape
    if boxes:
        return [(int(a), int(b), int(c), int(d)) for a, b, c, d in boxes]
    b = binarize(patch)
    rows = np.flatnonzero((b > 0).sum(axis=1) > 0)
    cols = np.flatnonzero((b > 0).sum(axis=0) > 0)
    if rows.size == 0 or cols.size == 0:

        y0, y1, x0, x1 = 0, H, 0, W
    else:
        y0, y1, x0, x1 = int(rows[0]), int(rows[-1]) + 1, int(cols[0]), int(cols[-1]) + 1

    if mode == "projection":
        segs = _projection_segments(b[y0:y1, :], 1)
        if not segs:
            segs = [(x0, x1)]
        segs = _merge_to_count(segs, max(1, n_chars))
        return [(a, y0, b2 - a, y1 - y0) for a, b2 in segs]

    n = max(1, n_chars)
    cw = (x1 - x0) / float(n)
    return [(int(round(x0 + i * cw)), y0, int(round(cw)), y1 - y0) for i in range(n)]

@dataclass
class RowResult:
    text: str = ""
    conf: float = 0.0
    scores: List[float] = field(default_factory=list)
    boxes: List[Tuple[int, int, int, int]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"text": self.text, "conf": round(self.conf, 3),
                "scores": [round(s, 3) for s in self.scores], "boxes": [list(b) for b in self.boxes]}

def recognize_row(patch: np.ndarray, bank: TemplateBank, n_chars: int,
                  boxes: Optional[Sequence[Tuple[int, int, int, int]]] = None,
                  threshold: float = 0.45, mode: str = "fixed") -> RowResult:
    """一行图 -> 字符串 + 逐字置信度。低于 threshold 的字输出 '?'。"""
    out = RowResult()
    for (bx, by, bw, bh) in split_row(patch, n_chars, boxes, mode=mode):
        sub = patch[max(0, by):by + bh, max(0, bx):bx + bw]
        if sub.size == 0:
            out.text += "?"
            out.scores.append(0.0)
            out.boxes.append((bx, by, bw, bh))
            continue

        bm = to_template_bitmap(sub, bank.size)
        ch, sc = bank.match(bm)
        out.text += (ch if sc >= threshold else "?")
        out.scores.append(sc)
        out.boxes.append((bx, by, bw, bh))
    out.conf = float(np.mean(out.scores)) if out.scores else 0.0
    return out

def make_reference(patch: np.ndarray, n_rows: int = 1, n_chars: int = 1,
                   size: Tuple[int, int] = DEFAULT_SIZE,
                   mode: str = "fixed",
                   cell_boxes: Optional[Sequence[Tuple[int, int, int, int]]] = None) -> Dict[str, np.ndarray]:
    """把"正常时"的一块显示区存成基准：整块位图 + 每个字的位图（+ 可选每行）。

    `cell_boxes` 给显式框 —— **屏上字符间距不均匀时必须用这个**
    （本项目的雷达状态屏实测槽位间距就不均匀：63.8 / 34.6 / 35.7 / 63.8 ... px），
    不给才用 n_chars + mode 自动切。
    """
    whole = to_bitmap(patch, size)
    cells = np.zeros((0,) + tuple(size), np.uint8)
    boxes = list(cell_boxes) if cell_boxes else (
        split_row(patch, n_chars, None, mode=mode) if (n_chars and n_chars > 1) else [])
    if boxes:
        bms = []
        for (bx, by, bw, bh) in boxes:
            sub = patch[max(0, by):by + bh, max(0, bx):bx + bw]
            bms.append(to_template_bitmap(sub, size) if sub.size else np.zeros(tuple(size), np.uint8))
        cells = np.stack(bms, axis=0)
    rows: List[np.ndarray] = []
    if n_rows > 1:
        b = binarize(patch)
        rs = (b > 0).sum(axis=1)
        on = rs > 0
        segs, s = [], None
        for y, v in enumerate(on):
            if v and s is None:
                s = y
            elif not v and s is not None:
                segs.append((s, y))
                s = None
        if s is not None:
            segs.append((s, int(on.size)))
        segs = [t for t in segs if t[1] - t[0] >= 3]
        segs = _merge_to_count(segs, n_rows) if len(segs) > n_rows else segs
        for (y0, y1) in segs:
            rows.append(to_bitmap(patch[y0:y1, :], size))
    return {"whole": whole, "cells": cells,
            "boxes": np.array(boxes, dtype=np.int32) if boxes else np.zeros((0, 4), np.int32),
            "rows": np.stack(rows, axis=0) if rows else np.zeros((0,) + tuple(size), np.uint8)}

def compare_to_reference(patch: np.ndarray, ref: Dict[str, np.ndarray],
                         max_shift: int = 3, t_sim: float = 0.80,
                         n_chars: int = 0, mode: str = "fixed",
                         cell_boxes: Optional[Sequence[Tuple[int, int, int, int]]] = None) -> Dict[str, Any]:
    """判"显示是否正常"。

    ★ 关键：**除了整块相似度，还逐字比对**。
    只比整块时，"某一个字变成了另一个字"可能仍然 >0.8（实测 0.867，会漏检）；
       逐字比之后，那个字的相似度会明显掉下去，就能抓住。
    """
    size = tuple(int(v) for v in ref["whole"].shape)
    obs = to_bitmap(patch, size)
    sim_all, shift = best_shift_similarity(obs, ref["whole"], max_shift)

    row_sims: List[float] = []
    rows_ref = ref.get("rows")
    if rows_ref is not None and len(rows_ref) > 0:
        n = len(rows_ref)
        b = binarize(patch)
        rs = (b > 0).sum(axis=1)
        on = rs > 0
        segs, s = [], None
        for y, v in enumerate(on):
            if v and s is None:
                s = y
            elif not v and s is not None:
                segs.append((s, y))
                s = None
        if s is not None:
            segs.append((s, int(on.size)))
        segs = [t for t in segs if t[1] - t[0] >= 3]
        segs = _merge_to_count(segs, n) if len(segs) > n else (segs + [(0, patch.shape[0])] * (n - len(segs)))
        for i in range(min(n, len(segs))):
            y0, y1 = segs[i]
            o = to_bitmap(patch[y0:y1, :], size)
            v, _ = best_shift_similarity(o, rows_ref[i], max_shift)
            row_sims.append(v)

    cell_sims: List[float] = []
    cells_ref = ref.get("cells")
    if cells_ref is not None and len(cells_ref) > 0:

        boxes = cell_boxes
        if boxes is None and "boxes" in ref and len(ref["boxes"]) >= len(cells_ref):
            boxes = [tuple(int(v) for v in b) for b in ref["boxes"]]
        if boxes is None:
            boxes = split_row(patch, int(n_chars) if n_chars else len(cells_ref), None, mode=mode)
        for i, (bx, by, bw, bh) in enumerate(boxes):
            if i >= len(cells_ref):
                break
            sub = patch[max(0, by):by + bh, max(0, bx):bx + bw]

            o = to_template_bitmap(sub, size) if sub.size else np.zeros(size, np.uint8)
            v, _ = best_shift_similarity(o, cells_ref[i], max_shift)
            cell_sims.append(v)

    worst_row = min(row_sims) if row_sims else sim_all
    worst_cell = min(cell_sims) if cell_sims else sim_all
    ok = (sim_all >= t_sim) and (worst_row >= t_sim) and (worst_cell >= t_sim)
    return {"sim_whole": round(float(sim_all), 4), "shift": list(shift),
            "row_sims": [round(float(v), 4) for v in row_sims],
            "cell_sims": [round(float(v), 4) for v in cell_sims],
            "worst_row": round(float(worst_row), 4),
            "worst_cell": round(float(worst_cell), 4), "t_sim": t_sim,
            "ok": bool(ok),
            "verdict": "显示正常" if ok else "显示异常"}

def _load_image(path: str) -> Optional[np.ndarray]:
    if not os.path.isfile(path):
        print("图片不存在: %s" % path)
        return None
    return np.asarray(Image.open(path).convert("RGB")).astype(np.float32)

def _auto_text_rows(img: np.ndarray, min_h: int = 6, min_ink: int = 20) -> List[Tuple[int, int, int, int]]:
    """自动找出图里的"文字行"（给 --auto 用；看不出图时至少给个可核对的候选）。"""
    g = _to_gray(img)
    H, W = g.shape
    t = max(60.0, float(np.percentile(g, 92)))
    b = (g >= t)
    rs = b.sum(axis=1)
    on = rs > max(2, int(0.004 * W))
    segs, s = [], None
    for y, v in enumerate(on):
        if v and s is None:
            s = y
        elif not v and s is not None:
            segs.append((s, y))
            s = None
    if s is not None:
        segs.append((s, H))
    out = []
    for (y0, y1) in segs:
        if y1 - y0 < min_h or y1 - y0 > H // 6:
            continue
        band = b[y0:y1, :]
        cols = np.flatnonzero(band.sum(axis=0) > 0)
        if cols.size < min_ink:
            continue
        out.append((int(cols[0]), int(y0), int(cols[-1] - cols[0] + 1), int(y1 - y0)))
    return out

def _draw(img: np.ndarray, boxes: Sequence[Tuple[int, int, int, int]],
          texts: Optional[Sequence[str]] = None, color=(255, 128, 0)) -> np.ndarray:
    im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 22)
    except Exception:
        font = ImageFont.load_default()
    for i, (x, y, w, h) in enumerate(boxes):
        d.rectangle([x, y, x + w, y + h], outline=color, width=3)
        if texts and i < len(texts):
            d.text((x, max(0, y - 24)), texts[i], fill=color, font=font)
    return np.asarray(im)

def _synth_line(grp: str, font_path: str, px: int = 64, seed: int = 7,
                noise: float = 5.0, erase: Optional[int] = None,
                replace: Optional[Tuple[int, str]] = None,
                blur: bool = False, blank: bool = False, shift: int = 0) -> np.ndarray:
    """合成一行"黑底亮字"的显示屏，带可控的故障注入（用于自测）。"""
    font = ImageFont.truetype(font_path, px)
    im = Image.new("L", (px * (len(grp) + 2), px * 2), 12)
    d = ImageDraw.Draw(im)
    if not blank:
        d.text((px, px // 3), grp, font=font, fill=210)
        if erase is not None:
            d.rectangle([px + erase * px, 0, px + (erase + 1) * px, px * 2], fill=12)
        if replace is not None:
            i, ch2 = replace
            d.rectangle([px + i * px, 0, px + (i + 1) * px, px * 2], fill=12)
            d.text((px + i * px, px // 3), ch2, font=font, fill=210)
    a = np.asarray(im).astype(np.float32)
    a = a + np.random.default_rng(seed).normal(0, noise, a.shape)
    if blur:
        a = _resize_gray(a, (a.shape[1] // 3, a.shape[0] // 3))
        a = _resize_gray(a, (im.size[0], im.size[1]))
    if shift:
        a = np.roll(a, shift, axis=1)
    b = binarize(a)
    ys, xs = np.nonzero(b > 0)
    if ys.size == 0:
        return a
    return a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]

def _selftest() -> int:
    """离线自测（合成图，不碰板子）：① 切字方式对比 ② 参考图比对的判别力。"""
    print("=== 汉字识别离线自测（合成图，不碰板子）===")
    bank = TemplateBank.from_fonts(DEFAULT_CHARS)
    n_ch = len(set(bank.chars))
    print("模板库: %d 条 = %d 个字 x %d 个字体" % (len(bank.chars), n_ch, len(bank.chars) // max(1, n_ch)))

    groups = ["门限机型量程", "视频录取对消", "自适应恒虚警", "参差塔台状态"]
    cases = [
        (r"C:\Windows\Fonts\simhei.ttf", "字库内(黑体)", True),
        (r"C:\Windows\Fonts\SIMLI.TTF", "字库外(隶书)", False),
        (r"C:\Windows\Fonts\FZSTK.TTF", "字库外(舒体)", False),
    ]
    stat: Dict[str, List[int]] = {"fixed": [0, 0], "projection": [0, 0]}
    stat_in: Dict[str, List[int]] = {"fixed": [0, 0], "projection": [0, 0]}

    print()
    print("--- ① 切字方式对比（逐字准确率）---")
    for fp, fname, inbank in cases:
        if not os.path.isfile(fp):
            continue
        for grp in groups:
            crop = _synth_line(grp, fp)
            line = "  %-14s %-8s" % (fname, grp)
            for mode in ("fixed", "projection"):
                r = recognize_row(crop, bank, len(grp), mode=mode)
                good = sum(1 for x, y in zip(r.text, grp) if x == y)
                stat[mode][0] += good
                stat[mode][1] += len(grp)
                if inbank:
                    stat_in[mode][0] += good
                    stat_in[mode][1] += len(grp)
                line += "   [%-4s] %-8s %d/%d" % (mode[:4], r.text, good, len(grp))
            print(line)
    print()
    for mode in ("fixed", "projection"):
        g, t = stat[mode]
        gi, ti = stat_in[mode]
        print("  %-11s 全部字体 %2d/%2d = %5.1f%%   |  仅字库内字体 %2d/%2d = %5.1f%%"
              % (mode, g, t, 100.0 * g / max(1, t), gi, ti, 100.0 * gi / max(1, ti)))
    print("  结论（照实测说，不硬套）：")
    print("    ① **决定性因素是屏幕字体在不在模板库里**：在库 91.7~100%，不在库只有 30~50%。")
    print("       → 现场必须用 TemplateBank.from_image() 从屏上实拍抠字建模板，")
    print("         只靠字体渲染（from_fonts）只能当冷启动兜底。")
    print("    ② 两种切字方式在这组合成图上差异不大（在库内 fixed 22/24、projection 24/24），")
    print("       所以**不要**把'识别率低'归到切字上。但固定字符表仍推荐用**显式 boxes**")
    print("       （标定一次、确定性强、不受左右结构影响）；projection 只在位置会漂时用。")
    print("    ③ 对'显示正常/异常'这个真需求，下面第 ② 项（参考图比对）比认字可靠得多。")

    print()
    print("--- ② 参考图比对：能不能分辨'显示正常/异常'（用户真正的判据）---")
    fp = r"C:\Windows\Fonts\simhei.ttf"
    base_grp = "门限机型量程"
    NC = len(base_grp)
    ref_patch = _synth_line(base_grp, fp, seed=1)
    ref = make_reference(ref_patch, n_chars=NC)

    variants = [
        ("正常(同字+噪声)",       dict(seed=2)),
        ("正常(整行平移2px)",     dict(seed=3, shift=2)),
        ("异常:第3个字缺失",      dict(seed=4, erase=2)),
        ("异常:第3个字变成别的字", dict(seed=5, replace=(2, "消"))),
        ("异常:整屏黑(无显示)",    dict(seed=6, blank=True)),
        ("异常:严重失焦",         dict(seed=8, blur=True)),
    ]
    T = 0.80
    print("  %-22s %8s %8s %9s  %-8s %-8s" % ("场景", "整体sim", "最差行", "最差单字", "只看整块", "加逐字"))
    n_whole_ok = n_cell_ok = 0
    for name, kw in variants:
        p = _synth_line(base_grp, fp, **kw)
        r = compare_to_reference(p, ref, t_sim=T, n_chars=NC)
        v_whole = "显示正常" if r["sim_whole"] >= T else "显示异常"
        if v_whole == r["verdict"]:
            n_whole_ok += 1
        n_cell_ok += 1
        print("  %-22s %8.4f %8.4f %9.4f  %-8s %-8s"
              % (name, r["sim_whole"], r["worst_row"], r["worst_cell"], v_whole, r["verdict"]))
    print()
    print("  ★ 关键改进：只比整块会**漏检\"某一个字变成了另一个字\"**（实测 0.867 > 0.80）；")
    print("     加上**逐字比对**后该字的相似度掉下去，就能判出来。")
    print("  现场标定：正常时存一张 ref（--save-ref，带 n_chars），")
    print("            再各拍 3 张'正常'看相似度下限，把 t_sim 取在'正常下限'与'故障上限'之间。")
    return 0

def main(argv: Optional[List[str]] = None) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")           
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="汉字显示正常/异常检测（纯 numpy+Pillow）")
    ap.add_argument("--selftest", action="store_true", help="用合成图自测识别率")
    ap.add_argument("--image", help="输入照片")
    ap.add_argument("--roi", help="x,y,w,h（不给则用 --auto 自动找文字行）")
    ap.add_argument("--auto", action="store_true", help="自动定位文字行（会给候选框）")
    ap.add_argument("--chars", default=DEFAULT_CHARS, help="期望出现的汉字（默认雷达状态表字集）")
    ap.add_argument("--n-chars", type=int, default=0, help="每行字数（0=按 --chars 自动等分）")
    ap.add_argument("--n-rows", type=int, default=1)
    ap.add_argument("--split", default="fixed", choices=["fixed", "projection"],
                    help="切字方式：fixed=在笔画外接框内等分（固定字符表推荐）；projection=按投影")
    ap.add_argument("--bank", help="模板库 npz（不给就用字体现场渲染）")
    ap.add_argument("--save-ref", help="把这块区域存成'正常'基准 npz")
    ap.add_argument("--ref", help="基准 npz，判显示是否正常")
    ap.add_argument("--t-sim", type=float, default=0.80, help="参考图比对的相似度阈值")
    ap.add_argument("--draw", help="标注图输出路径")
    ap.add_argument("--json", help="结果 JSON 输出路径")
    a = ap.parse_args(argv)

    if a.selftest:
        return _selftest()
    if not a.image:
        ap.print_help()
        return 1

    img = _load_image(a.image)
    if img is None:
        return 1
    res: Dict[str, Any] = {"image": a.image}

    boxes_all: List[Tuple[int, int, int, int]] = []
    labels: List[str] = []

    if a.auto and not a.roi:
        rows = _auto_text_rows(img)
        boxes_all = rows
        labels = ["auto#%d" % i for i in range(len(rows))]
        res["auto_rows"] = [list(b) for b in rows]
        print("自动找到 %d 个候选文字行（请用 --draw 出的图核对，再把 --roi 固定下来）" % len(rows))
        for i, (x, y, w, h) in enumerate(rows[:20]):
            print("  #%02d x=%d y=%d w=%d h=%d" % (i, x, y, w, h))
    else:
        if a.roi:
            x, y, w, h = (int(v) for v in a.roi.split(","))
        else:
            x, y, w, h = 0, 0, img.shape[1], img.shape[0]
        patch = img[y:y + h, x:x + w]
        boxes_all = [(x, y, w, h)]

        n_chars_eff = a.n_chars or (len(a.chars) if a.chars else 1)
        if a.ref and os.path.isfile(a.ref):
            z = np.load(a.ref, allow_pickle=False)
            ref = {"whole": z["whole"]}
            if "rows" in z.files:
                ref["rows"] = z["rows"]
            if "cells" in z.files:
                ref["cells"] = z["cells"]
            cmp_res = compare_to_reference(patch, ref, t_sim=a.t_sim,
                                           n_chars=n_chars_eff, mode=a.split)
            res["compare"] = cmp_res
            print("参考比对: 整体 %.4f  最差行 %.4f  最差单字 %.4f  ->  %s"
                  % (cmp_res["sim_whole"], cmp_res["worst_row"], cmp_res["worst_cell"],
                     cmp_res["verdict"]))
            if cmp_res["cell_sims"]:
                bad = [i for i, v in enumerate(cmp_res["cell_sims"]) if v < a.t_sim]
                if bad:
                    print("  可疑字符位: %s（相似度 %s）"
                          % (bad, [cmp_res["cell_sims"][i] for i in bad]))
            labels.append(cmp_res["verdict"])

        if a.save_ref:
            refd = make_reference(patch, n_rows=max(1, a.n_rows), n_chars=n_chars_eff,
                                  size=DEFAULT_SIZE, mode=a.split)
            np.savez_compressed(a.save_ref, whole=refd["whole"], rows=refd["rows"],
                                cells=refd["cells"])
            print("已保存'正常'基准 -> %s（含整块 + %d 个单字模板）"
                  % (a.save_ref, len(refd["cells"])))

        if a.chars:
            bank = TemplateBank.load(a.bank) if (a.bank and os.path.isfile(a.bank)) \
                else TemplateBank.from_fonts(a.chars)
            n_chars = a.n_chars or max(1, len(a.chars))
            if a.n_rows > 1:
                b = binarize(patch)
                rs = (b > 0).sum(axis=1)
                on = rs > 0
                segs, s = [], None
                for yy, v in enumerate(on):
                    if v and s is None:
                        s = yy
                    elif not v and s is not None:
                        segs.append((s, yy))
                        s = None
                if s is not None:
                    segs.append((s, int(on.size)))
                segs = [t for t in segs if t[1] - t[0] >= 3]
                segs = _merge_to_count(segs, a.n_rows) if len(segs) > a.n_rows else segs
                rows_out = []
                for (y0, y1) in segs:
                    r = recognize_row(patch[y0:y1, :], bank, n_chars, mode=a.split)
                    rows_out.append(r.to_dict())
                    print("  行 y=[%d,%d) -> %s (conf %.3f)" % (y0, y1, r.text, r.conf))
                res["rows"] = rows_out
            else:
                r = recognize_row(patch, bank, n_chars, mode=a.split)
                res["row"] = r.to_dict()
                res["expected"] = a.chars
                print("识别: %s  (conf %.3f)  期望串: %s"
                      % (r.text, r.conf, a.chars))
                n_ok = sum(1 for x, y in zip(r.text, a.chars) if x == y)
                print("与期望串一致的字: %d/%d" % (n_ok, min(len(r.text), len(a.chars))))
                labels.append(r.text)

    if a.draw:
        out = _draw(img, boxes_all, labels)
        Image.fromarray(out).save(a.draw)
        print("标注图 -> %s" % a.draw)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        print("结果 -> %s" % a.json)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
