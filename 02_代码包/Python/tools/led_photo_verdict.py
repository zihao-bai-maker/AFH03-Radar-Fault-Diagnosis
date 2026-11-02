#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""led_photo_verdict.py —— **照片 → 结论**（用户当前唯一能用的形态：手里只有照片）。

给一张照片，输出：
    ✅ 正常 / ❌ 故障 / ⚠ 未判定      + 一句依据 + 置信度 + 标注图（圈灯 + ON/OFF + 结论）
给一个目录，输出总表（可选与真值逐张比对，报命中/漏检/误检）。

用法
----
    # 单张（近景照片；没有标定也能用 --auto 演示自动算法）
    python3 tools/led_photo_verdict.py -i photo.jpg --part PS_KONG --auto --out-dir /tmp/out
    # 跑一个目录，出总表
    python3 tools/led_photo_verdict.py --dir /data/local/tmp/led_truth --auto --table \
            --out-dir /tmp/led_out --json /tmp/led_verdicts.json
    # 只判已标定 ROI（**出厂默认：没标定 -> 未判定**，防广视角假阳性）
    python3 tools/led_photo_verdict.py -i photo.jpg --part PS_KONG --calib config/led_calib.json
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                                    
import cv2                                                            

from soc_vision.cjk_text import draw_text, install_cv2_puttext_patch  
from soc_vision import led_panel as LP                                
from soc_vision.led_panel import Calib, PanelDetector, fit_long, orient_normalize, lamps_only, detect_candidates  
from soc_vision.led_rules import RuleBook, VERDICT_OK, VERDICT_BAD, VERDICT_UNK      

TRUTH = {
    "150326_1": ("PS_KONG", "正常", 3),
    "150527":   ("PS_KONG", "故障", 2),
    "150558":   ("PS_WENYA", "故障", 0),
    "151324":   ("PS_GONGPIN", "正常", 1),
    "151341":   ("ANT_DIR", "正常", 1),
    "151359":   ("TX_CTRL", "正常", 1),
    "151448":   ("TX_STATE", "正常", 3),
    "151820":   ("ANT_START", "正常", 1),
}

def guess_part(bgr, book: RuleBook):
    """没有 --part 时：先用丝印 OCR（若模板在位），失败则用"亮灯数"缩小到唯一部件，否则放弃。"""
    try:
        from soc_vision import ocr_cn, config as svconfig           
        tmpl = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "models", "cn_templates.npz")
        if os.path.isfile(tmpl):
            cfg = svconfig.load_config(None)
            eng = ocr_cn.CnRecognizer(cfg.ocr, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            res = eng.recognize(bgr)
            text = "".join(getattr(r, "text", "") or "" for r in res)
            if text:
                rule = book.match_by_silk(text)
                if rule is not None:
                    return rule.pid, "丝印OCR匹配「%s」-> %s" % (text[:24], rule.pid)
    except Exception as e:                                            
        note = "OCR 不可用(%s)" % type(e).__name__
    else:
        note = "OCR 未识别出文字"
    n_lit = len(lamps_only(detect_candidates(bgr)))
    cands = [p for p in book.parts if len(p.lamps) == n_lit]
    if len(cands) == 1:
        return cands[0].pid, "按亮灯数 %d 唯一匹配 -> %s（%s）" % (n_lit, cands[0].pid, note)
    return "", "无法确定部件（%s；亮灯数 %d 匹配 %d 个部件）" % (note, n_lit, len(cands))

def annotate(bgr, rows, vobj, extra: str = "") -> "np.ndarray":
    img = bgr.copy()
    col = (80, 200, 90) if vobj["verdict"] == VERDICT_OK else (
        (60, 60, 230) if vobj["verdict"] == VERDICT_BAD else (170, 170, 170))
    icon = "OK" if vobj["verdict"] == VERDICT_OK else ("FAULT" if vobj["verdict"] == VERDICT_BAD else "UNKNOWN")
    W = img.shape[1]
    cv2.rectangle(img, (0, 0), (W, 74), (24, 24, 28), -1)
    draw_text(img, "%s %s" % (icon, vobj["verdict"]), (14, 58), scale=2.2, color=col, th=2)
    draw_text(img, (vobj.get("reason") or "")[:44], (14, 104), scale=0.75, color=(240, 240, 240))
    if extra:
        draw_text(img, extra[:60], (14, 132), scale=0.55, color=(190, 190, 190))
    for r in rows:
        if r.get("x", -1) < 0:
            continue
        c = (80, 200, 90) if r.get("on") else ((60, 60, 230) if r.get("on") is False else (170, 170, 170))
        cv2.circle(img, (int(r["x"]), int(r["y"])), int(max(6, r.get("r", 10))), c, 3)
        draw_text(img, "%s %s" % (str(r["name"])[:8], "ON" if r.get("on") else
                                  ("?" if r.get("on") is None else "OFF")),
                  (int(r["x"]) - int(r.get("r", 10)), int(r["y"]) - int(r.get("r", 10)) - 6),
                  scale=0.5, color=c)
    return img

def judge_photo(path: str, book: RuleBook, part: str, calib, det: PanelDetector,
                allow_auto: bool, auto_part: bool):
    raw = cv2.imread(path, cv2.IMREAD_COLOR)
    if raw is None:
        return None
    bgr, rotated = orient_normalize(raw)
    bgr = fit_long(bgr, LP.WORK_LONG)
    note = ""
    if not part and auto_part:
        part, note = guess_part(bgr, book)
    if not part:
        return {"file": os.path.basename(path), "verdict": VERDICT_UNK,
                "reason": note or "未指定部件（--part）→ 未判定", "confidence": 0.0,
                "rows": [], "rotated": rotated, "n_lit": len(lamps_only(detect_candidates(bgr))),
                "image": bgr}
    if not calib and not allow_auto:
        return {"file": os.path.basename(path), "verdict": VERDICT_UNK,
                "reason": "未标定 ROI → 未判定（默认拒绝硬判；演示可用 --auto）", "confidence": 0.0,
                "rows": [], "rotated": rotated, "n_lit": len(lamps_only(detect_candidates(bgr))),
                "image": bgr}
    v, info = LP.analyze(bgr, book, part, calib, det=det)
    rows = []
    for st in v.to_dict().get("lamps", []):
        rows.append({"name": st["name"], "on": st["on"], "delta": st["delta"], "source": st["source"],
                     "x": st.get("x", -1), "y": st.get("y", -1), "r": st.get("r", 0)})
    if not any(r["x"] >= 0 for r in rows):
        for i, c in enumerate((info.get("candidates") or [])[:8]):
            rows.append({"name": "灯%d" % (i + 1), "on": True, "delta": c["delta"], "source": "sw",
                         "x": c["x"], "y": c["y"], "r": c["r"]})
    return {"file": os.path.basename(path), "part": part, "verdict": v.verdict, "reason": v.reason,
            "bad_lamps": v.bad_lamps, "confidence": round(float(v.confidence), 3),
            "rows": rows, "rotated": rotated, "path": info.get("path"),
            "geometry_gate": info.get("geometry_gate"), "n_lit": info.get("geometry_gate", {}).get("n_lit"),
            "image": bgr, "note": note}

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="照片 -> 正常/故障 + 依据 + 标注图")
    ap.add_argument("-i", "--image", default="")
    ap.add_argument("--dir", default="", help="跑一个目录")
    ap.add_argument("--part", default=os.environ.get("AFH03_PART", ""))
    ap.add_argument("--auto-part", action="store_true", help="没给 --part 时尝试用丝印OCR/亮灯数猜")
    ap.add_argument("--auto", action="store_true", help="无标定也判（演示/离线复现真值）")
    ap.add_argument("--calib", default=os.environ.get("AFH03_CALIB", ""))
    ap.add_argument("--rules", default="")
    ap.add_argument("--out-dir", default="/tmp/led_verdict_out")
    ap.add_argument("--json", default="")
    ap.add_argument("--table", action="store_true")
    ap.add_argument("--truth-suffix", default="", help="文件名匹配真值的关键字前缀（默认用末尾数字段）")
    ap.add_argument("--use-truth-part", action="store_true",
                    help="**仅用于回归**：对 8 张真值照片使用真值文档里注明的部件（表格里会打 * 号）")
    a = ap.parse_args(argv)

    install_cv2_puttext_patch()
    book = RuleBook.load(a.rules or None)
    calib = Calib.load(a.calib) if a.calib and os.path.isfile(a.calib) else None
    det = PanelDetector(calib)
    files = sorted(glob.glob(os.path.join(a.dir, "*.jpg"))) if a.dir else ([a.image] if a.image else [])
    if not files:
        ap.print_help()
        return 1
    os.makedirs(a.out_dir, exist_ok=True)
    results, hit, tot, miss, fp, truth_rows = [], 0, 0, 0, 0, 0
    for f in files:
        part_use = a.part
        tagged = ""
        if not part_use:
            key = next((k for k in TRUTH if k in os.path.basename(f)), None)
            if key and a.use_truth_part:
                part_use = TRUTH[key][0]
                tagged = "*真值注明的部件"
        r = judge_photo(f, book, part_use, calib, det, a.auto, a.auto_part)
        if r is None:
            print("  读不到 %s" % f)
            continue
        img = annotate(r.pop("image"), r["rows"], r,
                       extra="部件=%s 路径=%s 帧=%s %s" % (r.get("part", "-"), r.get("path", "-"),
                                                          "旋转90°" if r["rotated"] else "未旋转", tagged))
        out_png = os.path.join(a.out_dir, os.path.splitext(os.path.basename(f))[0] + "_verdict.jpg")
        cv2.imwrite(out_png, img)
        r["annotated"] = out_png
        key = next((k for k in TRUTH if k in os.path.basename(f)), None)
        if key:
            tp, tv, tn = TRUTH[key]
            r["truth"] = {"part": tp, "verdict": tv, "n_on": tn}
            tot += 1
            if r["n_lit"] == tn:
                hit += 1
            miss += max(0, tn - (r["n_lit"] or 0))
            fp += max(0, (r["n_lit"] or 0) - tn)
            truth_rows += 1
        results.append(r)

    icon = {VERDICT_OK: "✅ 正常", VERDICT_BAD: "❌ 故障", VERDICT_UNK: "⚠ 未判定"}
    if a.table:
        print("=" * 118)
        print("%-28s %-11s %-9s %-5s %-6s %-6s %s" % ("照片", "部件", "结论", "亮灯", "真值亮", "判定", "依据"))
        print("-" * 118)
        for r in results:
            t = r.get("truth") or {}
            mark = ""
            if t:
                mark = "OK" if r["verdict"] == t["verdict"] else "错"
            print("%-28s %-11s %-9s %-5s %-6s %-6s %s"
                  % (r["file"][:28], r.get("part", "-"), icon.get(r["verdict"], "?"),
                     r.get("n_lit"), t.get("n_on", "-"), mark, (r.get("reason") or "")[:44]))
        print("-" * 118)
        if truth_rows:
            print("8 条真值汇总：**亮灯数命中 %d/%d** ；漏检 %d ；误检 %d"
                  % (hit, tot, miss, fp))
        print("标注图目录：%s（共 %d 张）" % (a.out_dir, len(results)))
    else:
        for r in results:
            print("%s  %s\n  依据：%s\n  置信度=%.2f  亮灯=%s  部件=%s  标注图=%s"
                  % (icon.get(r["verdict"], "?"), r["file"], r.get("reason"),
                     r.get("confidence", 0.0), r.get("n_lit"), r.get("part"), r["annotated"]))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fo:
            json.dump({"results": results, "truth": {"photos": tot, "lit_hit": hit,
                                                     "miss": miss, "fp": fp}}, fo,
                      ensure_ascii=False, indent=2)
        print("JSON -> %s" % a.json)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
