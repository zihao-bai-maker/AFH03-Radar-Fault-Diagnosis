#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""半自动打标 + 候选库评估（只写临时目录；最终覆盖前先评估）。"""
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
from part_recognizer import (  
    AppearanceBackend, PART_INFO, build_feature_library, load_bgr,
)

PHOTO_DIR = r"D:\xuexishengshou\雷达照片_今天\拍照UI照片"
TMP = r"D:\xuexishengshou\_tmp_partlabel"
LIB = os.path.join(HERE, "part_features.json")
SCAN = os.path.join(TMP, "scan.json")
LABELS = os.path.join(TMP, "labels_candidate.json")
CAND = os.path.join(TMP, "part_features_candidate.json")

NEW_TRAIN = {
    "IMGP_20260427_200555.jpg": ("z14", "可见丝印 Z14/信处（暗光，仍可读）"),
    "IMGP_20260427_200616.jpg": ("z15", "可见丝印 Z15/显示电路（原库误标 z14，纠正）"),
    "IMGP_20260427_200617.jpg": ("z15", "可见丝印 Z15/显示电路（画面下方边缘另有 Z14，主体为 Z15）"),
    "IMGP_20260427_201942.jpg": ("z31", "可见丝印 Z31/电源控制 + 电源控制面板"),
    "IMGP_20260427_201947.jpg": ("z31", "可见丝印 Z31/电源控制 + 电源控制面板"),
    "IMGP_20260427_202008.jpg": ("z31", "可见丝印 Z31/电源控制 + 电源控制面板"),
    "IMGP_20260427_202014.jpg": ("z18", "可见丝印 Z18 控制面板 + 数码表 211/003 18.8/228"),
    "IMGP_20260427_202037.jpg": ("z18", "可见丝印 Z18 控制面板 + 数码表 822/003 18.8/271"),
    "IMGP_20260427_202039.jpg": ("z18", "可见丝印 Z18 控制面板 + 数码表 271/003 18.8/227"),
    "IMGP_20260427_202045.jpg": ("z18", "可见丝印 Z18 控制面板 + 220V/1A 丝印"),
    "IMGP_20260427_202047.jpg": ("z18", "可见丝印 Z18 控制面板 + 220V/1A 丝印"),
    "IMGP_20260427_202048.jpg": ("z18", "可见丝印 Z18 控制面板 + 220V/1A 丝印"),
}

NEW_HOLDOUT = {
    "IMGP_20260427_201926.jpg": ("z31", "Z31 电源控制面板"),
    "IMGP_20260427_202006.jpg": ("z31", "Z31 电源控制面板"),
    "IMGP_20260427_202011.jpg": ("z18", "Z18 控制面板（数码表 211/003 18.8/221）"),
    "IMGP_20260427_202036.jpg": ("z18", "Z18 控制面板（数码表 822/003 18.8/271）"),
    "IMGP_20260427_202057.jpg": ("z18", "Z18 控制面板（数码表 112/003 18.8/227）"),
}

UNKNOWN_WHY = {
    "IMGP_20260427_195023.jpg": "失焦/天花板", "IMGP_20260427_195026.jpg": "失焦/天花板",
    "IMGP_20260427_195028.jpg": "失焦/天花板", "IMGP_20260427_195032.jpg": "失焦/天花板",
    "IMGP_20260427_195034.jpg": "失焦/天花板", "IMGP_20260427_195036.jpg": "失焦/天花板",
    "IMGP_20260427_195040.jpg": "失焦/天花板", "IMGP_20260427_195104.jpg": "失焦/白墙",
    "IMGP_20260427_195107.jpg": "失焦/白墙", "IMGP_20260427_195125.jpg": "失焦/白墙",
    "IMGP_20260427_195300.jpg": "失焦/白墙", "IMGP_20260427_200346.jpg": "过曝/失焦",
    "IMGP_20260427_195100.jpg": "操显屏幕特写（Z17 内容）", "IMGP_20260427_195101.jpg": "操显屏幕特写（Z17 内容）",
    "IMGP_20260427_195111.jpg": "操显屏幕特写（Z17 内容）", "IMGP_20260427_195112.jpg": "操显屏幕特写（Z17 内容）",
    "IMGP_20260427_195120.jpg": "操显屏幕特写（Z17 内容）", "IMGP_20260427_195145.jpg": "操显屏幕特写（Z17 内容）",
    "IMGP_20260427_195146.jpg": "操显屏幕特写（Z17 内容）", "IMGP_20260427_195615.jpg": "操显屏幕特写（Z17 内容）",
    "IMGP_20260427_195616.jpg": "操显屏幕特写（Z17 内容）", "IMGP_20260427_195625.jpg": "操显屏幕特写（Z17 内容）",
    "IMGP_20260427_195636.jpg": "操显屏幕特写（Z17 内容）",
    "IMGP_20260427_195155.jpg": "暗帧（几乎全黑）", "IMGP_20260427_195156.jpg": "暗帧（几乎全黑）",
    "IMGP_20260427_200043.jpg": "暗帧（几乎全黑）",
    "IMGP_20260427_202219.jpg": "示波器屏幕（非 18 部位）", "IMGP_20260427_202225.jpg": "示波器屏幕（非 18 部位）",
    "IMGP_20260427_202236.jpg": "示波器屏幕（非 18 部位）",
    "IMGP_20260427_202233.jpg": "Z17 操显面板（不在 18 清单）", "IMGP_20260427_202235.jpg": "Z17 操显面板（不在 18 清单）",
    "IMGP_20260427_202242.jpg": "Z17 操显面板（不在 18 清单）", "IMGP_20260427_202246.jpg": "Z17 操显面板（不在 18 清单）",
    "IMGP_20260427_202247.jpg": "Z17 操显面板（不在 18 清单）", "IMGP_20260427_202248.jpg": "Z17 操显面板（不在 18 清单）",
    "IMGP_20260427_202249.jpg": "Z17 操显面板（不在 18 清单）", "IMGP_20260427_202250.jpg": "Z17 操显面板（不在 18 清单）",
    "IMGP_20260427_202251.jpg": "Z17 操显面板（不在 18 清单）",
}

def main() -> int:
    old = json.load(open(LIB, encoding="utf-8"))
    scan = {x["image"]: x for x in json.load(open(SCAN, encoding="utf-8"))["images"]}
    labels = {}
    for p, info in old["parts"].items():
        for s in info["samples"]:
            labels[s["image"]] = {"part": p, "label_source": s["label_source"] or "原库 32 张已知样本"}
    for h in old["holdout"]:
        labels[h["image"]] = {"part": "__holdout__:" + h["part"], "label_source": "原库 25 张留出"}
    for s in old["unknown"]["samples"]:
        labels[s["image"]] = {"part": "unknown", "label_source": s["label_source"] or "原库 unknown"}

    labels["IMGP_20260427_200616.jpg"] = {"part": "z15", "label_source": "可见丝印 Z15/显示电路（原库误标 z14，纠正）"}
    for name, (part, why) in NEW_TRAIN.items():
        labels[name] = {"part": part, "label_source": why}
    for name, (part, why) in NEW_HOLDOUT.items():
        labels[name] = {"part": "__holdout__:" + part, "label_source": why}
    for name, why in UNKNOWN_WHY.items():
        labels[name] = {"part": "unknown", "label_source": why}

    missing = sorted(set(scan) - set(labels))
    extra = sorted(set(labels) - set(scan))
    assert not missing, "未打标：%s" % missing[:10]
    assert not extra, "多出：%s" % extra[:10]

    items, holdout = [], []
    for name in sorted(labels):
        rec = labels[name]
        p = rec["part"]
        if p.startswith("__holdout__:"):
            holdout.append({"image": os.path.join(PHOTO_DIR, name), "part": p.split(":", 1)[1]})
        else:
            items.append({"image": os.path.join(PHOTO_DIR, name), "part": p,
                          "label_source": rec["label_source"]})
    print("items=%d unknown=%d holdout=%d total=%d" % (
        sum(1 for x in items if x["part"] != "unknown"),
        sum(1 for x in items if x["part"] == "unknown"), len(holdout),
        len(items) + len(holdout)))
    print("train counts", Counter(x["part"] for x in items if x["part"] != "unknown"))
    print("holdout counts", Counter(h["part"] for h in holdout))

    json.dump({"source": "119 张同场次真图；人工按可见丝印打标（2026-10-18 复核）",
               "items": items, "holdout": holdout},
              open(LABELS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    res = build_feature_library(items, out_path=CAND, holdout=holdout,
                                source="119 张同场次真图；人工按可见丝印/面板文字打标；unknown 不入库")
    print("built", res)

    app = AppearanceBackend(CAND)
    rows = []
    for h in holdout:
        bgr = load_bgr(os.path.join(PHOTO_DIR, h["image"]))
        m = app.match(bgr, top_k=5)
        top = [x["part"] for x in m["top"]]
        rows.append((h["part"], top[:3], top[0] if top else "", m.get("best_score", 0.0)))
    n = len(rows)
    top1 = sum(1 for t, _a, p, _s in rows if p == t)
    top3 = sum(1 for t, a, _p, _s in rows if t in a)
    print("appearance-only holdout top1=%d/%d=%.1f%% top3=%d/%d=%.1f%%" % (
        top1, n, 100 * top1 / n, top3, n, 100 * top3 / n))
    conf = defaultdict(Counter)
    for t, a, p, _s in rows:
        conf[t][p or "-"] += 1
    for t in sorted(conf):
        print("  %-5s -> %s" % (t, dict(conf[t])))
    for t, a, p, s in rows:
        if p != t:
            print("  ERR true=%s pred=%s top3=%s sim=%.3f" % (t, p, a, s))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
