#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把未打标照片拼成带编号的 contact sheet，便于人工目检（只写临时目录）。"""
from __future__ import annotations

import json
import os
import sys

import cv2
import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from part_recognizer import load_bgr  

PHOTO_DIR = r"D:\xuexishengshou\雷达照片_今天\拍照UI照片"
OUT_DIR = r"D:\xuexishengshou\_tmp_partlabel\sheets"
SCAN = r"D:\xuexishengshou\_tmp_partlabel\scan.json"
LIB = r"D:\xuexishengshou\雷达判据\engine\part_features.json"

def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    d = json.load(open(LIB, encoding="utf-8"))
    known = {s["image"] for p in d["parts"].values() for s in p["samples"]}
    hold = {h["image"] for h in d["holdout"]}
    unk = {s["image"] for s in d["unknown"]["samples"]}
    scan = json.load(open(SCAN, encoding="utf-8"))
    todo = [x for x in scan["images"] if x["image"] not in known | hold | unk]
    print("todo", len(todo))
    per, cols = 9, 3
    tw, th = 640, 360
    for s in range(0, len(todo), per):
        chunk = todo[s:s + per]
        canvas = np.full((th * ((len(chunk) + cols - 1) // cols), tw * cols, 3), 30, np.uint8)
        for i, x in enumerate(chunk):
            bgr = load_bgr(os.path.join(PHOTO_DIR, x["image"]))
            if bgr is None:
                continue
            im = cv2.resize(bgr, (tw, th), interpolation=cv2.INTER_AREA)
            r, c = divmod(i, cols)
            canvas[r * th:(r + 1) * th, c * tw:(c + 1) * tw] = im
            cv2.rectangle(canvas, (c * tw, r * th), (c * tw + 70, r * th + 42), (0, 0, 0), -1)
            cv2.putText(canvas, "#%d" % (s + i + 1), (c * tw + 6, r * th + 32),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2, cv2.LINE_AA)
        path = os.path.join(OUT_DIR, "sheet_%02d.jpg" % (s // per + 1))
        cv2.imwrite(path, canvas, [cv2.IMWRITE_JPEG_QUALITY, 88])
        print(path, [x["image"] for x in chunk])
        for i, x in enumerate(chunk):
            txt = " | ".join(t["text"] for t in x["ocr"][:6])
            top = x["appearance"]["top"][:2]
            print("  #%d %s  app=%s  ocr=%s" % (
                s + i + 1, x["image"],
                " ".join("%s:%.2f" % (t["part"], t["similarity"]) for t in top), txt[:70]))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
