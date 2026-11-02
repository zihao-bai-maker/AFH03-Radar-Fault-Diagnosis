#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按部位打印留出集 top1/top3/need_confirm（同场次真图，非跨站）。"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from part_recognizer import FEATURES_JSON, PartRecognizer  

PHOTO_DIR = r"D:\xuexishengshou\雷达照片_今天\拍照UI照片"

def main() -> int:
    lib = json.load(open(FEATURES_JSON, encoding="utf-8"))
    hold = lib.get("holdout") or []
    rec = PartRecognizer()
    per = defaultdict(lambda: {"n": 0, "top1": 0, "top3": 0, "need": 0})
    rows = []
    for h in hold:
        r = rec.recognize(os.path.join(PHOTO_DIR, h["image"]), use_marker=False)
        top = [c["part"] for c in r.get("candidates") or []]
        pred = r.get("part", "")
        ok1 = int(pred == h["part"])
        ok3 = int(h["part"] in top[:3])
        per[h["part"]]["n"] += 1
        per[h["part"]]["top1"] += ok1
        per[h["part"]]["top3"] += ok3
        per[h["part"]]["need"] += int(bool(r.get("need_confirm")))
        rows.append((h["image"], h["part"], pred, ok1, ok3, r.get("confidence", 0), top[:3]))
    n = len(rows)
    need = sum(v["need"] for v in per.values())
    print("holdout=%d  top1=%d/%d=%.1f%%  top3=%d/%d=%.1f%%  need=%d/%d=%.1f%%" % (
        n, sum(x[3] for x in rows), n, 100 * sum(x[3] for x in rows) / n,
        sum(x[4] for x in rows), n, 100 * sum(x[4] for x in rows) / n,
        need, n, 100 * need / n))
    print("| part | n | top1 | top3 | need_confirm |")
    print("|---|---:|---:|---:|---:|")
    for p in sorted(per):
        v = per[p]
        print("| %s | %d | %d/%d | %d/%d | %d |" % (
            p, v["n"], v["top1"], v["n"], v["top3"], v["n"], v["need"]))
    for name, true, pred, ok1, ok3, conf, top in rows:
        if not ok1:
            print("ERR %-26s true=%-4s pred=%-4s conf=%.2f top3=%s" % (name, true, pred, conf, top))
    print("confusion:")
    conf = defaultdict(Counter)
    for _n, true, pred, _a, _b, _c, _t in rows:
        conf[true][pred or "-"] += 1
    for t in sorted(conf):
        print("  %-5s -> %s" % (t, dict(conf[t])))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
