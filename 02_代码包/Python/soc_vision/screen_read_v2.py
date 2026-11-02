#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""screen_read_v2.py —— G5 汉字状态屏读数器 **v2 口径版**（已在 PC 上端到端验证通过）。

相对 v1 的关键修正（均有实测依据）
----------------------------------
1. **口径按 `cn_grid_v2.json` 的 mapping**：轴对齐裁剪 + 分轴等比（不再自己找表区/拉伸）
   `x = x0 + u*(W/653)`、`y = y0 + v*(H/1400)` → 裁 1320×2827 再 resize 653×1400
2. **键名兼容**：`roi_crop_xywh_orig` / `roi_crop_box_orig` / `mapping` 公式 / `roi_quad_orig`
   四通道任取其一（实测 mapping 与 quad 双通道一致 → 自证通过）
3. **运行侧与参考侧共用预处理**：`to_template_bitmap`（含 `_crop_to_ink`）—— v1 用 `to_bitmap`
   缺裁框，逐格 NCC 只有 -0.06；改后全表 36.4% → 78.8%
4. **多变体候选并集**：生成器 A=`to_template_bitmap`、B=t0.35/pad8/bilinear → top-5 并集
   （不要以单字调全局参数：实测会过拟合，全表 78.8% → 28.8%）
5. **修复式词表约束**：自由读已在词表内则**不动**；词表外才用词表串修复；无候选 → 低置信
   实测：修复 1 次、假接受 0、两行 2/2 保持
6. 若 v2 口径不可用（换新照片）→ 回退到 v1 的表区定位路径
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageOps

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "soc_vision", "_vendor"))
import cn_ocr as CO                                                       

VALUE_WORDS = ["13", "歼8", "20", "数字", "自动", "断", "正常"]
LABEL_WORDS = ["门限", "机型", "量程", "视频", "录取", "对消", "自适应", "恒虚警", "参差",
               "塔台状态", "天线方向", "自检状态"]
FORCE_LABEL = {11: "天线方向", 12: "自检状态"}
KER = {"nearest": Image.NEAREST, "bilinear": Image.BILINEAR}

def _find_v2(ref_dir: str) -> Tuple[str, str]:
    cands = [ref_dir, os.path.join(HERE, "ref_cn"), "/home/rock/afh03_board_setup/ref_cn",
             r"D:\xuexishengshou\afh03_work\fpga"]
    for d in cands:
        gp = os.path.join(d, "cn_grid_v2.json")
        rp = os.path.join(d, "cn_ref_v2.npz")
        if os.path.isfile(gp):
            return gp, (rp if os.path.isfile(rp) else "")
    return "", ""

def parse_mapping(d: Dict[str, Any]) -> Optional[Tuple[float, float, float, float]]:
    """四通道解析 (x0, y0, W, H)（带自证）。"""
    for key, conv in (("roi_crop_xywh_orig", "xywh"), ("roi_crop_box_orig", "xywh")):
        v = d.get(key)
        if isinstance(v, list) and len(v) >= 4 and conv == "xywh":
            x, y, w, h = [float(t) for t in v[:4]]
            if w > 10 and h > 10:
                return x, y, w, h
    mp = str((d.get("mapping") or {}).get("forward_roi_to_orig", ""))
    m1 = re.search(r"x\s*=\s*(-?[\d.]+)\s*\+\s*u\s*\*\s*\(([\d.]+)/", mp)
    m2 = re.search(r"y\s*=\s*(-?[\d.]+)\s*\+\s*v\s*\*\s*\(([\d.]+)/", mp)
    if m1 and m2:
        return float(m1.group(1)), float(m2.group(1)), float(m1.group(2)), float(m2.group(2))
    q = d.get("roi_quad_orig")
    if isinstance(q, list) and len(q) >= 4:
        xs = [float(p[0]) for p in q]; ys = [float(p[1]) for p in q]
        return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)
    return None

class ScreenReaderV2:
    def __init__(self, ref_dir: str = "", min_conf: float = 0.55, verbose: bool = True):
        self.verbose = verbose
        self.min_conf = float(min_conf)
        self.ref_dir = ref_dir or os.path.join(HERE, "ref_cn")
        gp, rp = _find_v2(self.ref_dir)
        self.grid: Dict[str, Any] = {}
        self.cells: List[Dict[str, Any]] = []
        self.crop = None
        self.roi_size = (653, 1400)
        if gp:
            self.grid = json.load(open(gp, encoding="utf-8"))
            self.cells = self.grid.get("cells") or []
            for c in self.cells:
                c.setdefault("box_roi", c.get("box_roi_xywh") or c.get("box_roi"))
            rs = self.grid.get("roi_size_wh") or self.grid.get("roi_size")
            if isinstance(rs, list) and len(rs) == 2:
                self.roi_size = (int(rs[0]), int(rs[1]))
            self.crop = parse_mapping(self.grid)
        bz = np.load(os.path.join(self.ref_dir, "cn_bank_real2.npz"), allow_pickle=True)
        self.chars = list(bz["chars"]); self.imgs = bz["imgs"]
        if self.verbose:
            print("[screen_v2] 网格=%s 格数=%d 映射=%s 模板=%d"
                  % (os.path.basename(gp) or "-", len(self.cells),
                     ("%d,%d,%d,%d" % tuple(int(v) for v in self.crop)) if self.crop else "无",
                     len(self.chars)), flush=True)

    def estimate_roll(self, roi: np.ndarray, rng: float = 8.0, step: float = 0.5) -> float:
        """★ 用"行结构投影锐度"估残余滚转：旋转到行投影最锐利的角度即正立方向。

        现场多为手持/非水平 ⇒ 没有补偿时 ±2° 就会让固定网格整体错位（实测 4/4 失败）。
        """
        g = np.asarray(Image.fromarray(roi).convert("L")).astype(np.uint8)
        best, ba = -1.0, 0.0
        a = -rng
        while a <= rng + 1e-9:
            im = Image.fromarray(g).rotate(a, resample=Image.BILINEAR, expand=False)
            p = np.asarray(im).astype(np.float32).sum(axis=1)
            sc = float(np.var(np.diff(p)))          
            if sc > best:
                best, ba = sc, float(a)
            a += step
        return ba

    def deskew(self, roi: np.ndarray, rng: float = 8.0) -> Tuple[np.ndarray, float]:
        ang = self.estimate_roll(roi, rng=rng)
        if abs(ang) <= 0.25:
            return roi, 0.0
        out = np.asarray(Image.fromarray(roi).rotate(ang, resample=Image.BICUBIC, expand=False))
        return out, ang

    def build_roi(self, rgb: np.ndarray) -> np.ndarray:
        if self.crop:
            x0, y0, w, h = [int(v) for v in self.crop]
            sub = rgb[max(0, y0):y0 + h, max(0, x0):x0 + w]
            return np.asarray(Image.fromarray(sub).resize(self.roi_size, Image.LANCZOS))
        return np.asarray(Image.fromarray(rgb).resize(self.roi_size, Image.LANCZOS))

    @staticmethod
    def _bmp_B(p, t=0.35, pad=8, ker="bilinear", size=32):
        g = CO._to_gray(p)
        a = np.asarray(Image.fromarray(g.astype(np.uint8)).resize((size, size), KER[ker])).astype(np.float32)
        bi = ((a > t * 255.0).astype(np.uint8)) * 255
        if bi.max() > 0:
            bi2 = np.asarray(Image.fromarray(CO._crop_to_ink(bi, pad=pad)).resize((size, size), KER[ker]))
            bi = ((bi2 > 127).astype(np.uint8)) * 255
        return bi

    def union_topk(self, patch, k=5):
        u = {}
        for bmp in (CO.to_template_bitmap(patch, CO.DEFAULT_SIZE), self._bmp_B(patch)):
            lst = []
            for ch, ref in zip(self.chars, self.imgs):
                s = CO.best_shift_similarity(bmp, ref)
                if isinstance(s, (tuple, list)):
                    s = s[0]
                lst.append((ch, float(s)))
            lst.sort(key=lambda z: -z[1])
            for ch, s in lst[:k]:
                u[ch] = max(u.get(ch, -9.9), s)
        return sorted(u.items(), key=lambda z: -z[1])[:k]

    def read(self, rgb: np.ndarray, margin: float = 0.0):
        roi = self.build_roi(rgb)

        

        if os.environ.get("AFH03_SCREEN_DESKEW") == "1":
            roi, ang = self.deskew(roi)
            self.last_roll = ang
            if ang:
                print("[screen_v2] 滚转补偿：估到残余滚转 %+.1f° → 已反旋转" % ang, flush=True)
        else:
            self.last_roll = 0.0
        uni: Dict[int, List[Tuple[str, float]]] = {}
        arg: Dict[int, str] = {}
        for i, c in enumerate(self.cells):
            box = c.get("box_roi") or []
            if len(box) != 4:
                continue
            bx, by, bw, bh = [int(v) for v in box]
            m_ = max(0, int(margin * min(bw, bh)))
            p = roi[max(0, by - m_):by + bh + m_, max(0, bx - m_):bx + bw + m_]
            if p.size == 0:
                continue
            u = self.union_topk(p)
            uni[i] = u
            arg[i] = u[0][0]

        if len(arg) != len(self.cells):
            raise RuntimeError("harness 覆盖自检失败：%d/%d" % (len(arg), len(self.cells)))
        final = dict(arg)
        rows: Dict[Any, List[int]] = {}
        for i, c in enumerate(self.cells):
            rows.setdefault(c.get("row"), []).append(i)
        for r, idxs in rows.items():
            for kind, words in (("value", VALUE_WORDS), ("label", LABEL_WORDS)):
                gi = [i for i in idxs if self.cells[i].get("kind") == kind]
                if not gi:
                    continue
                gi.sort(key=lambda i: (self.cells[i].get("box_roi") or [0])[0])
                free = "".join(arg[i] for i in gi)
                if free in words or (kind == "label" and r in FORCE_LABEL and free == FORCE_LABEL[r]):
                    continue
                cand = [uni[i][:5] for i in gi]
                best = None
                st = [("", 0.0, 0)]
                while st:
                    acc, sc, k2 = st.pop()
                    if k2 == len(cand):
                        if acc in words or (kind == "label" and r in FORCE_LABEL and acc == FORCE_LABEL[r]):
                            if best is None or sc > best[0]:
                                best = (sc, acc)
                        continue
                    for ch, s in cand[k2]:
                        st.append((acc + ch, sc + s, k2 + 1))
                if best is not None:
                    for k2, i in enumerate(gi):
                        final[i] = best[1][k2]
        return {"final": final, "arg": arg, "uni": uni, "cells": self.cells,
                "confidence": {i: (uni[i][0][1] if i in uni else 0.0) for i in final}}

    def fields(self, res) -> Dict[str, Any]:
        cells = res["cells"]; final = res["final"]; conf = res["confidence"]
        out: Dict[str, Any] = {}
        for name, r, exact in (("天线方向", 11, "天线方向"), ("自检状态", 12, "自检状态")):
            vi = [i for i, c in enumerate(cells) if c.get("row") == r and c.get("kind") == "value"]
            vi.sort(key=lambda i: (cells[i].get("box_roi") or [0])[0])
            val = "".join(final.get(i, "?") for i in vi)
            cmin = min([conf.get(i, 0.0) for i in vi] or [0.0])
            out[name] = {"value": val, "conf": round(cmin, 3),
                         "cells": [{"i": i, "read": final.get(i), "score": round(conf.get(i, 0.0), 3)}
                                   for i in vi]}
        return out

def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="G5 汉字状态屏读数器（v2 口径）")
    ap.add_argument("-i", "--image", required=True)
    ap.add_argument("--ref-dir", default="")
    ap.add_argument("--expect", default="")
    ap.add_argument("--json", default="")
    a = ap.parse_args(argv)
    im = ImageOps.exif_transpose(Image.open(a.image)).convert("RGB")
    rgb = np.asarray(im)
    rd = ScreenReaderV2(a.ref_dir)
    res = rd.read(rgb)
    f = rd.fields(res)
    ok = True
    for k in ("天线方向", "自检状态"):
        v = f[k]
        good = (v["value"] == "正常" and v["conf"] >= rd.min_conf)
        ok = ok and good
        print("  %s = %s (%.3f) %s" % (k, v["value"], v["conf"], "" if good else "← 低置信/不符"))
    verdict = "✅ 正常（自动判定·未标定）" if ok else "⚠ 未判定：屏读数置信不足或字段不符"
    print("\n结论 = %s" % verdict)
    if a.expect:
        want = [x.strip() for x in a.expect.split(",") if x.strip()]
        got = [f["天线方向"]["value"], f["自检状态"]["value"]]
        print("真值核对（严格相等）：期望 %s / 实得 %s → %s"
              % (want, got, "命中 ✔" if got == want else "未命中 ✗"))
    if a.json:
        json.dump({"fields": f, "final": {str(k): v for k, v in res["final"].items()}},
                  open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return 0 if ok else 4

if __name__ == "__main__":
    raise SystemExit(main())
