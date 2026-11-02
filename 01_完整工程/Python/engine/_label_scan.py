#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""临时半自动打标扫描（只读照片/只读特征库；结果写到临时目录，不碰受保护文件）。

产出：_tmp_partlabel/scan.json
  - 每张图的 OCR 行、appearance top5、marker 命中、图像尺寸/亮度
  - 用于人工复核后写 labels.json（labels.json 也不落到受保护路径）
"""
from __future__ import annotations

import json
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from part_recognizer import (  
    AppearanceBackend, MarkerBackend, RapidOcrBackend, extract_appearance, load_bgr,
)

PHOTO_DIR = r"D:\xuexishengshou\雷达照片_今天\拍照UI照片"
OUT_DIR = r"D:\xuexishengshou\_tmp_partlabel"

def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    names = sorted(f for f in os.listdir(PHOTO_DIR) if f.lower().endswith(".jpg"))
    ocr = RapidOcrBackend()
    app = AppearanceBackend()
    mk = MarkerBackend()
    print("ocr=%s app_parts=%s marker=%s n=%d" % (ocr.ok, len(app.parts), mk.ok, len(names)))
    out = []
    t_all = time.time()
    for i, name in enumerate(names, 1):
        t0 = time.time()
        path = os.path.join(PHOTO_DIR, name)
        bgr = load_bgr(path)
        rec = {"image": name}
        if bgr is None:
            rec["error"] = "read_fail"
            out.append(rec)
            continue
        h, w = bgr.shape[:2]
        gray = float(np.mean(bgr))
        lines = ocr.read(bgr) if ocr.ok else []
        rec["ocr"] = [{"text": str(l.get("text", "")), "score": round(float(l.get("score", 0)), 3),
                       "box": l.get("box")} for l in lines]
        a = app.match(bgr, top_k=5)
        rec["appearance"] = {"top": a.get("top", []), "ood": a.get("ood"),
                             "unknown_similarity": a.get("unknown_similarity")}
        hit = mk.detect(bgr) if mk.ok else None
        rec["marker"] = ({"part": hit.get("part"), "score": hit.get("score")} if hit else None)
        rec["shape"] = [w, h]
        rec["gray"] = round(gray, 1)
        rec["feature"] = [round(float(x), 6) for x in extract_appearance(bgr)]
        rec["elapsed"] = round(time.time() - t0, 2)
        out.append(rec)
        print("[%3d/%3d] %s %5.1fs %s" % (i, len(names), name, rec["elapsed"],
                                          " | ".join(l["text"] for l in rec["ocr"][:6])[:110]))
    payload = {"source": PHOTO_DIR, "n": len(out), "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "elapsed_s": round(time.time() - t_all, 1), "images": out}
    with open(os.path.join(OUT_DIR, "scan.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    print("done %.1fs -> %s" % (time.time() - t_all, os.path.join(OUT_DIR, "scan.json")))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
