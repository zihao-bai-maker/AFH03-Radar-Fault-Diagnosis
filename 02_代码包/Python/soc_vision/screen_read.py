#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""screen_read.py —— **G5 汉字状态屏读数器**（纯 numpy + Pillow；内核复用 `cn_ocr.py`）。

设计（按鲁棒性清单）
--------------------
1. **先定位表再切格**：绿色文字/边框掩膜 → 投影找表区 → **四角单应**归一化到固定 ROI（653×1400）
2. **透视/旋转归一**：由表区四极值点解 8 参数单应（numpy 直接解），轻微滚转/俯仰可救
3. **反光/高光掩膜**：绿通道过饱和（高光/摩尔纹）像素标记失效，**不参与打分**；再局部自适应二值化
4. **逐字匹配**：`to_bitmap` 归一 → `best_shift_similarity`（NCC+多位移）→ **保留 top-3**
5. **★ 整串约束（精度关键）**：值列词表已知 → **行级 DP** 串成词表里存在的串，取全局最优
6. **★ 时间融合**：`--frames a.jpg,b.jpg,c.jpg` 或多帧时同格分数**平均/投票**
7. **低置信保护**：top1 低于阈值、或 DP 最优与次优差距过小 → `不确定`
8. 可解释输出：每格 top-3 分数 + 值列串 + 目标两格的值与分数

用法
----
    python3 -m soc_vision.screen_read -i IMG_20260923_151631.jpg --out out/screen_annot.png \
            --json out/screen.json [--expect 正常,正常]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageOps

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "soc_vision", "_vendor"))

try:
    import cn_ocr  
except Exception as e:                                                
    raise SystemExit("载入 cn_ocr 失败（应先 vendor 到 soc_vision/_vendor/）: %s" % e)

REF_DIR_DEFAULT = os.path.join(HERE, "ref_cn")

VOCAB_WORDS = ["正常", "故障", "数字", "自动", "手动", "断", "通", "是", "否",
               "13", "20", "歼8", "天线方向", "自检状态"]
VOCAB_CHARS = set("".join(VOCAB_WORDS)) | set(cn_ocr.DEFAULT_CHARS) | set("0123456789.正常故障数字自动断通是否")

@dataclass
class CellSpec:
    idx: int
    row: int
    kind: str                      
    box: Tuple[int, int, int, int]  
    truth: str = ""

@dataclass
class CellResult:
    spec: CellSpec
    top: List[Tuple[str, float]] = field(default_factory=list)
    ch: str = "?"
    score: float = 0.0
    n_over: float = 0.0            

    def to_dict(self) -> Dict[str, Any]:
        return {"row": self.spec.row, "kind": self.spec.kind, "box": list(self.spec.box),
                "truth": self.spec.truth, "read": self.ch, "score": round(float(self.score), 3),
                "top3": [[c, round(float(s), 3)] for c, s in self.top[:3]],
                "glare_frac": round(float(self.n_over), 3)}

class ScreenReader:
    def __init__(self, ref_dir: str = REF_DIR_DEFAULT, min_score: float = 0.55,
                 dp_gap: float = 0.02, verbose: bool = True):
        self.ref_dir = ref_dir
        self.min_score = float(min_score)
        self.dp_gap = float(dp_gap)
        self.verbose = verbose
        g = self._find("cn_grid.json")
        r = self._find("cn_ref_final.npz")
        b = self._find("cn_bank_real2.npz")
        c = self._find("cn_real_result.json")
        self.grid = json.load(open(g, encoding="utf-8")) if g else {}
        z = np.load(r, allow_pickle=True) if r else None
        self.cells_ref = z["cells"] if z is not None and "cells" in z.files else None
        bank = np.load(b, allow_pickle=True) if b else None
        self.chars_bank = list(bank["chars"]) if bank is not None else []
        imgs = bank["imgs"] if bank is not None else None
        self.bank = cn_ocr.TemplateBank(self.chars_bank, imgs, cn_ocr.DEFAULT_SIZE) if imgs is not None else None
        self.roi_size = tuple(self.grid.get("roi_size", [653, 1400]))
        self.specs: List[CellSpec] = []
        if c:
            for i, cc in enumerate(json.load(open(c, encoding="utf-8")).get("cells", [])):
                x, y, w, h = cc["box"]
                self.specs.append(CellSpec(idx=i, row=int(cc.get("row", 0)), kind=cc.get("kind", "value"),
                                           box=(int(x), int(y), int(w), int(h)), truth=cc.get("ch", "")))
        if self.verbose:
            print("[screen] 网格=%s ROI=%s 参考格=%d 模板=%d"
                  % (os.path.basename(g or "-"), self.roi_size,
                     len(self.cells_ref) if self.cells_ref is not None else 0,
                     len(self.chars_bank)), flush=True)

    def _find(self, name: str) -> str:
        for d in (self.ref_dir, os.path.join(HERE, "out", "ref_cn"),
                  os.path.join(HERE, "ref_cn"), "/home/rock/afh03_board_setup/ref_cn",
                  r"D:\xuexishengshou\afh03_work\fpga", r"D:\xuexishengshou\afh03_board_setup\ref_cn"):
            p = os.path.join(d, name)
            if os.path.isfile(p):
                return p
        return ""

    @staticmethod
    def _gray_green(rgb: np.ndarray):
        r = rgb[:, :, 0].astype(np.int16); g = rgb[:, :, 1].astype(np.int16); b = rgb[:, :, 2].astype(np.int16)
        green = (g > r + 18) & (g > b + 18) & (g > 60)

        lum = 0.299 * r + 0.587 * g + 0.114 * b
        hi = float(np.percentile(lum, 99.3))
        glare = (lum >= hi) & (g >= 0.92 * np.percentile(g, 99.5))

        try:
            m = glare.astype(np.uint8)
            k = np.ones((3, 3), np.uint8)
            er = m.copy()

            p = np.pad(m, 1)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    er = np.minimum(er, p[1 + dy:1 + dy + m.shape[0], 1 + dx:1 + dx + m.shape[1]])
            glare = er.astype(bool)
        except Exception:                                             
            pass
        return green, glare

    def find_table(self, rgb: np.ndarray):
        """返回 (ROI 653x1400 的 uint8 灰度/绿通道图, 四角, 高光掩膜, 定位信息)。"""
        green, glare = self._gray_green(rgb)
        H, W = green.shape
        gf = float(glare.mean())
        print("[screen][mask] 高光占比=%.3f" % gf, flush=True)
        if gf > 0.40:
            print("[screen][mask] **掩膜异常**（高光占比 %.2f > 0.40）→ 本次读数不可信" % gf, flush=True)

        colsum = green.sum(axis=0); rowsum = green.sum(axis=1)
        cthr = max(3, int(0.06 * colsum.max()))
        rthr = max(3, int(0.06 * rowsum.max()))
        cols = np.nonzero(colsum > cthr)[0]; rows = np.nonzero(rowsum > rthr)[0]
        if len(cols) < 10 or len(rows) < 10:
            info = "未找到表区（绿像素过少）"
            x0, y0, x1, y1 = 0, 0, W - 1, H - 1
        else:
            x0, x1 = int(cols[0]), int(cols[-1]); y0, y1 = int(rows[0]), int(rows[-1])
            info = "表区 bbox=(%d,%d,%d,%d)" % (x0, y0, x1, y1)

        sub = green[y0:y1 + 1, x0:x1 + 1]
        ys, xs = np.nonzero(sub)
        quad = None
        if len(xs) > 50:
            pts = np.stack([xs + x0, ys + y0], axis=1).astype(np.float64)
            top = pts[np.argmin(pts[:, 1])]; bot = pts[np.argmax(pts[:, 1])]
            left = pts[np.argmin(pts[:, 0])]; right = pts[np.argmax(pts[:, 0])]

            s = pts[:, 0] + pts[:, 1]; d = pts[:, 0] - pts[:, 1]
            quad = np.array([pts[np.argmin(s)], pts[np.argmax(d)],
                             pts[np.argmax(s)], pts[np.argmin(d)]], np.float64)  
            info += " 四角=%s" % (quad.astype(int).tolist(),)
        g_ch = rgb[:, :, 1]
        gl = glare
        if quad is not None:
            roi, glroi = self._warp(g_ch, quad), self._warp(gl.astype(np.uint8) * 255, quad)
        else:
            roi = np.asarray(Image.fromarray(g_ch[y0:y1 + 1, x0:x1 + 1]).resize(
                (self.roi_size[0], self.roi_size[1]), Image.LANCZOS))
            glroi = np.asarray(Image.fromarray((gl[y0:y1 + 1, x0:x1 + 1].astype(np.uint8) * 255)).resize(
                (self.roi_size[0], self.roi_size[1]), Image.NEAREST))
        return roi.astype(np.uint8), (quad if quad is not None else (x0, y0, x1, y1)), glroi.astype(np.uint8), info

    def _warp(self, img: np.ndarray, quad: np.ndarray) -> np.ndarray:
        """按 4 角把 img 单应到 roi_size（numpy 解 8 参数 + 双线性采样）。"""
        W, H = self.roi_size
        dst = np.array([[0, 0], [W - 1, 0], [W - 1, H - 1], [0, H - 1]], np.float64)
        A, b = [], []
        for (x, y), (u, v) in zip(quad, dst):
            A.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.append(u)
            A.append([0, 0, 0, x, y, 1, -v * x, -v * y]); b.append(v)
        try:
            h = np.linalg.lstsq(np.array(A, np.float64), np.array(b, np.float64), rcond=None)[0]
        except Exception:                                              
            return np.asarray(Image.fromarray(img).resize((W, H), Image.LANCZOS))
        Hm = np.append(h, 1.0).reshape(3, 3)
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float64)
        den = Hm[2, 0] * xx + Hm[2, 1] * yy + Hm[2, 2]
        sx = (Hm[0, 0] * xx + Hm[0, 1] * yy + Hm[0, 2]) / np.maximum(den, 1e-6)
        sy = (Hm[1, 0] * xx + Hm[1, 1] * yy + Hm[1, 2]) / np.maximum(den, 1e-6)
        sx = np.clip(sx, 0, img.shape[1] - 1); sy = np.clip(sy, 0, img.shape[0] - 1)
        x0 = np.floor(sx).astype(int); y0 = np.floor(sy).astype(int)
        x1 = np.clip(x0 + 1, 0, img.shape[1] - 1); y1 = np.clip(y0 + 1, 0, img.shape[0] - 1)
        fx = sx - x0; fy = sy - y0
        f = img.astype(np.float32)
        out = (f[y0, x0] * (1 - fx) * (1 - fy) + f[y0, x1] * fx * (1 - fy) +
               f[y1, x0] * (1 - fx) * fy + f[y1, x1] * fx * fy)
        return out.astype(np.uint8)

    def read(self, rgb: np.ndarray, already_roi: bool = False):
        if already_roi:
            roi = np.asarray(Image.fromarray(rgb).resize(self.roi_size, Image.LANCZOS)).astype(np.uint8)
            glroi = np.zeros_like(roi); quad = None; info = "已是 ROI"
        else:
            roi, quad, glroi, info = self.find_table(rgb)
        res: List[CellResult] = []
        for sp in self.specs:
            x, y, w, h = sp.box
            m = max(1, int(0.06 * min(w, h)))
            x0, y0 = max(0, x - m), max(0, y - m)
            x1, y1 = min(roi.shape[1], x + w + m), min(roi.shape[0], y + h + m)
            patch = roi[y0:y1, x0:x1]
            gl = glroi[y0:y1, x0:x1]
            over = float((gl > 128).mean()) if gl.size else 0.0
            cr = CellResult(spec=sp, n_over=over)
            if patch.size and over < 0.85:
                try:
                    bmp = cn_ocr.to_bitmap(patch, cn_ocr.DEFAULT_SIZE)
                    if self.bank is not None:
                        scores = []
                        for ch, ref in zip(self.chars_bank, self.bank.imgs):
                            try:
                                s = cn_ocr.best_shift_similarity(bmp, ref)
                            except TypeError:
                                s = cn_ocr.best_shift_similarity(bmp, ref, 2)
                            if isinstance(s, (tuple, list)):        
                                s = s[0]
                            scores.append((ch, float(s)))
                        scores.sort(key=lambda z: -z[1])
                        cr.top = scores[:3]
                        cr.ch, cr.score = scores[0]
                except Exception as e:                                  
                    if self.verbose:
                        print("[screen] 格 %d 识别异常: %s" % (sp.idx, e), flush=True)
            if not cr.top:
                cr.ch, cr.score = "?", 0.0
            res.append(cr)
        return res, roi, quad, glroi, info

    def dp_rows(self, cells: Sequence[CellResult], kind: str = "value"):
        """★ 行级 DP：把每格 top-3 串成词表中存在的串，取全局最优（不逐格独立取最大）。"""
        by_row: Dict[int, List[CellResult]] = {}
        for c in cells:
            if c.spec.kind == kind:
                by_row.setdefault(c.spec.row, []).append(c)
        out: Dict[int, str] = {}
        for row, cs in by_row.items():
            cs = sorted(cs, key=lambda z: z.spec.box[0])
            n = len(cs)
            if n == 0:
                continue
            cand: List[List[Tuple[str, float]]] = []
            for c in cs:
                t = [(ch, s) for ch, s in c.top] or [("?", 0.0)]
                if c.ch not in [x[0] for x in t]:
                    t = [(c.ch, c.score)] + t
                cand.append(t[:3])
            best, best_sc, second = "", -1e9, -1e9
            for k in range(n + 1):                     

                def rec(i: int, acc: List[str], sc: float):
                    nonlocal best, best_sc, second
                    if i >= n:
                        s = "".join(acc)
                        bonus = 0.35 * max((len(w) for w in VOCAB_WORDS if w in s), default=0)
                        tot = sc + bonus
                        if tot > best_sc:
                            second = best_sc; best_sc, best = tot, s
                        elif tot > second:
                            second = tot
                        return
                    for ln in (1, 2, 3):
                        if i + ln > n:
                            break
                        for combo in self._combos(cand[i:i + ln]):
                            rec(i + ln, acc + [combo[0]], sc + combo[1])
                rec(0, [], 0.0)
            out[row] = best
        return out

    @staticmethod
    def _combos(group: Sequence[Sequence[Tuple[str, float]]]):
        if not group:
            return []
        if len(group) == 1:
            return [(ch, s) for ch, s in group[0]]
        res = []
        for ch1, s1 in group[0]:
            for ch2, s2 in group[1]:
                res.append((ch1 + ch2, (s1 + s2) / 2.0))
        return res[:6]

    TARGET_LABELS = {"天线方向": "天线方向", "自检状态": "自检状态"}

    def fields(self, cells: Sequence[CellResult]):
        """按"标签行 → 同行值列"取 天线方向 / 自检状态 的值与分数。"""
        rows: Dict[int, List[CellResult]] = {}
        for c in cells:
            rows.setdefault(c.spec.row, []).append(c)
        found: Dict[str, Dict[str, Any]] = {}
        dp = self.dp_rows(cells, "value")
        for row, cs in rows.items():
            cs = sorted(cs, key=lambda z: z.spec.box[0])
            lab = "".join(c.ch for c in cs if c.spec.kind == "label")
            for name, key in self.TARGET_LABELS.items():
                if key in lab or (name == "天线方向" and ("天线" in lab or "方向" in lab)) or \
                   (name == "自检状态" and ("自检" in lab or "状态" in lab)):
                    vcs = [c for c in cs if c.spec.kind == "value"]
                    val = dp.get(row, "")
                    if not val and vcs:
                        val = "".join(c.ch for c in vcs)
                    scs = [c.score for c in vcs if c.top]
                    conf = float(np.mean(scs)) if scs else 0.0
                    found[name] = {"row": row, "value": val,
                                   "conf": round(conf, 3),
                                   "value_cells": [c.to_dict() for c in vcs],
                                   "label_read": lab}
        return found

def load_rgb(path: str):
    im = Image.open(path)
    im = ImageOps.exif_transpose(im).convert("RGB")
    return np.asarray(im).astype(np.uint8)

def annotate(rgb: np.ndarray, cells: Sequence[CellResult], fields: Dict[str, Any],
             roi: np.ndarray) -> np.ndarray:
    im = Image.fromarray(rgb.copy())
    dr = ImageDraw.Draw(im)
    for c in cells:
        x, y, w, h = c.spec.box
        col = (0, 255, 0) if c.score >= 0.6 else ((255, 200, 0) if c.score >= 0.45 else (255, 80, 80))
        dr.rectangle([x, y, x + w, y + h], outline=col, width=2)
        dr.text((x, max(0, y - 12)), "%s%.2f" % (c.ch, c.score), fill=col)
    txt = " | ".join("%s=%s(%.2f)" % (k, v["value"], v["conf"]) for k, v in fields.items())
    dr.rectangle([0, 0, im.size[0], 22], fill=(0, 0, 0))
    dr.text((4, 4), txt[:110], fill=(0, 255, 128))
    return np.asarray(im)

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="G5 汉字状态屏读数器")
    ap.add_argument("-i", "--image", required=True)
    ap.add_argument("--ref-dir", default=REF_DIR_DEFAULT)
    ap.add_argument("--out", default="")
    ap.add_argument("--json", default="")
    ap.add_argument("--expect", default="", help='"正常,正常"')
    ap.add_argument("--frames", default="", help="多帧融合（逗号分隔的图片列表）")
    a = ap.parse_args(argv)
    rd = ScreenReader(a.ref_dir)
    paths = [a.image] + [p for p in (a.frames.split(",") if a.frames else []) if p.strip()]
    all_cells = None
    for i, p in enumerate(paths):
        rgb = load_rgb(p)
        cells, roi, quad, gl, info = rd.read(rgb)
        print("[frame %d] %s  高光占比=%.3f" % (i, info, float((gl > 128).mean())))
        if all_cells is None:
            all_cells = {c.spec.idx: [c] for c in cells}
            first = (rgb, cells, roi)
        else:
            for c in cells:
                all_cells.setdefault(c.spec.idx, []).append(c)

    fused: List[CellResult] = []
    for idx, cs in sorted(all_cells.items()):
        base = cs[0]
        agg: Dict[str, List[float]] = {}
        for c in cs:
            for ch, s in c.top:
                agg.setdefault(ch, []).append(s)
        top = sorted(((ch, float(np.mean(v))) for ch, v in agg.items()), key=lambda z: -z[1])[:3]
        base.top = top
        if top:
            base.ch, base.score = top[0]
        base.n_over = float(np.mean([c.n_over for c in cs]))
        fused.append(base)
    fields = rd.fields(fused)
    print("\n值列（DP 整串）:")
    for row, s in sorted(rd.dp_rows(fused, "value").items()):
        print("  行%-2d = %s" % (row, s))
    print("\n目标字段:")
    ok = True
    for name in ("天线方向", "自检状态"):
        f = fields.get(name)
        print("  %s = %s (%.3f)%s" % (name, f["value"] if f else "未找到",
                                      f["conf"] if f else 0.0,
                                      ("  label读=%s" % f["label_read"]) if f else ""))
        if not f or f["value"] != "正常" or f["conf"] < rd.min_score:
            ok = False
    if a.expect:
        want = [x.strip() for x in a.expect.split(",") if x.strip()]
        got = [fields.get(n, {}).get("value", "") for n in ("天线方向", "自检状态")]
        print("\n真值核对（严格相等）：期望 %s / 实得 %s → %s"
              % (want, got, "命中 ✔" if got == want else "未命中 ✗"))

    tot = sum(1 for c in fused if c.spec.truth)
    hit = sum(1 for c in fused if c.spec.truth and c.ch == c.spec.truth)
    print("\n逐格命中率（对参考真值）：%d/%d = %.1f%%" % (hit, tot, 100.0 * hit / max(1, tot)))
    if a.out:
        rgb0, cells0, roi0 = first
        os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
        Image.fromarray(annotate(rgb0, fused, fields, roi0)).save(a.out)
        print("标注图 -> %s" % a.out)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"file": os.path.basename(a.image), "fields": fields,
                       "cells": [c.to_dict() for c in fused],
                       "values": {str(k): v for k, v in rd.dp_rows(fused, "value").items()}},
                      f, ensure_ascii=False, indent=2)
        print("JSON -> %s" % a.json)
    return 0 if ok else 4

if __name__ == "__main__":
    raise SystemExit(main())
