#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""silk_match.py —— **用丝印汉字自动认部件**（不依赖任何训练/OCR 词库）。

为什么不用现成的 ocr_cn
-----------------------
`models/cn_templates.npz` 只有 5,384 B，是**标定页那 17 个字**的模板，
**不包含面板丝印词**（空调电源指示 / 稳压工频电源指示 / 发电机电源 / 位置指示 …）；
而且 `load_config()` 需要必填 path（传 None 会 TypeError）。

本模块的做法（**合成模板 + 相关匹配**）
------------------------------------
1. 候选词来自 `config/led_rules.json` 每个部件的 `silk` 列表（可配置，不写死）；
2. 用**字体渲染**（`soc_vision.cjk_text`，本板 Pango 可用）把每个候选词渲染成二值模板，
   多个尺度（对应画面里丝印的实际高度）；
3. 对照片做**自适应二值化**（丝印=深底浅字/浅底深字都能适配），用 `cv2.matchTemplate`
   的归一化相关打分，取每个部件的最佳得分；
4. 得分最高且超过阈值 -> 认定为该部件；**得分接近时不硬认**（返回 None，交上层输出"未判定"）。

这样"同版式不同丝印"（`空调电源指示/市电电源/控制` vs `稳压工频电源指示/发电机电源/控制`）也能分开。
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

try:
    import cv2
except Exception:                                                 
    cv2 = None

from soc_vision.cjk_text import draw_text, has_non_ascii

def render_mask(text: str, height: int, pad: int = 3) -> Optional["np.ndarray"]:
    """把文字渲染成 0/255 的二值模板（白字黑底）。需要 cjk_text 的后端可用。"""
    if not text:
        return None
    w = int(height * len(text) * 0.78) + 2 * pad
    h = int(height * 1.7) + 2 * pad
    if w < 8 or h < 8:
        return None
    canvas = np.zeros((h, w, 3), np.uint8)
    draw_text(canvas, text, (pad, h - pad), scale=height / 26.0, color=(255, 255, 255), th=1)
    g = cv2.cvtColor(canvas, cv2.COLOR_BGR2GRAY)
    bw = (g > 60).astype(np.uint8) * 255
    ys, xs = np.where(bw > 0)
    if len(xs) == 0:
        return None
    return bw[ys.min():ys.max() + 1, xs.min():xs.max() + 1]

def _prep_scene(bgr) -> "np.ndarray":
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    th = cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 31, -12)
    return th

def score_text(scene_bw, tmpl_bw) -> Tuple[float, Tuple[int, int]]:
    """归一化相关匹配；返回 (最佳得分, 位置)。模板比场景大时返回 (-1,(0,0))。"""
    sh, sw = scene_bw.shape[:2]
    th, tw = tmpl_bw.shape[:2]
    if th >= sh or tw >= sw:
        return -1.0, (0, 0)
    r = cv2.matchTemplate(scene_bw, tmpl_bw, cv2.TM_CCOEFF_NORMED)
    _mn, mx, _ml, ml = cv2.minMaxLoc(r)
    return float(mx), (int(ml[0]), int(ml[1]))

def match_parts(bgr, book, heights: Sequence[int] = (16, 20, 25, 31, 38),
                topk: int = 3) -> List[dict]:
    """给照片打"是哪个部件"的分。返回按得分降序的 [{pid, score, word, height, where}]。"""
    scene = _prep_scene(bgr)
    scene_inv = cv2.bitwise_not(scene)
    out: List[dict] = []
    for part in book.parts:
        best = -1.0
        best_info = None
        for word in (part.silk or []):
            if not word:
                continue
            for h in heights:
                t = render_mask(word, h)
                if t is None:
                    continue
                for sc, tag in ((scene, "normal"), (scene_inv, "inverted")):
                    s, where = score_text(sc, t)
                    if s > best:
                        best, best_info = s, {"word": word, "height": h, "polarity": tag,
                                              "where": where}
        out.append({"pid": part.pid, "name": part.name, "score": round(best, 4),
                    "info": best_info})
    out.sort(key=lambda z: -z["score"])
    return out[:max(1, topk)]

def recognize_part(bgr, book, min_score: float = 0.45, margin: float = 0.06) -> Tuple[str, str]:
    """返回 (pid, 说明)。得分不够或与第二名差距太小 -> ('', 原因)（**不硬认**）。"""
    tops = match_parts(bgr, book, topk=3)
    if not tops or tops[0]["score"] < min_score:
        return "", "丝印匹配得分不足（最高 %.2f < %.2f）→ 无法确定部件" % (
            tops[0]["score"] if tops else 0.0, min_score)
    if len(tops) > 1 and (tops[0]["score"] - tops[1]["score"]) < margin:
        return "", ("丝印匹配不唯一（%s %.2f vs %s %.2f，差距 < %.2f）→ 无法确定部件"
                    % (tops[0]["pid"], tops[0]["score"], tops[1]["pid"], tops[1]["score"], margin))
    i = tops[0]["info"] or {}
    return tops[0]["pid"], ("丝印匹配「%s」(h=%s, %s, 位置%s) 得分 %.2f"
                            % (i.get("word"), i.get("height"), i.get("polarity"),
                               i.get("where"), tops[0]["score"]))

def main(argv=None) -> int:
    import argparse
    import os as _os
    import sys
    sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    from soc_vision.led_panel import fit_long, orient_normalize
    from soc_vision.led_rules import RuleBook
    ap = argparse.ArgumentParser(description="丝印汉字认部件（合成模板 + 相关匹配）")
    ap.add_argument("-i", "--image", required=True)
    ap.add_argument("--rules", default="")
    ap.add_argument("--topk", type=int, default=5)
    a = ap.parse_args(argv)
    book = RuleBook.load(a.rules or None)
    bgr = cv2.imread(a.image, cv2.IMREAD_COLOR)
    if bgr is None:
        print("读不到 %s" % a.image)
        return 1
    bgr, rot = orient_normalize(bgr)
    bgr = fit_long(bgr, 1536)
    print("== %s（旋转归一=%s）==" % (_os.path.basename(a.image), rot))
    for r in match_parts(bgr, book, topk=a.topk):
        i = r["info"] or {}
        print("   %-12s %-34s 得分=%.3f  最佳词「%s」h=%s %s @%s"
              % (r["pid"], r["name"], r["score"], i.get("word"), i.get("height"),
                 i.get("polarity"), i.get("where")))
    pid, why = recognize_part(bgr, book)
    print("结论: %s" % (("部件 = %s（%s）" % (pid, why)) if pid else why))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
