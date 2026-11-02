#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给 part_features.json 补审计元数据（不重算特征，不改 samples/mean）。"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

P = r"D:\xuexishengshou\雷达判据\engine\part_features.json"
TZ = timezone(timedelta(hours=8))

def main() -> int:
    d = json.load(open(P, encoding="utf-8"))
    d["photo_dir"] = "D:/xuexishengshou/雷达照片_今天/拍照UI照片"
    d["updated"] = datetime.now(TZ).isoformat(timespec="seconds")
    d["labeling_pass"] = {
        "date": "2026-10-18",
        "method": "119 张逐张 contact sheet 目检 + RapidOCR 面板文字 + 现有外观 top5 交叉；拿不准一律 unknown",
        "reviewer": "半自动（脚本 _label_scan.py / _label_sheets.py）+ 人工目检",
        "images_total": 119,
        "known_samples": int(d.get("total_samples", 0)),
        "unknown_samples": int((d.get("unknown") or {}).get("n", 0)),
        "holdout": len(d.get("holdout") or []),
        "same_session": True,
        "cross_site": False,
    }
    d["corrections"] = [
        {"image": "IMGP_20260427_200616.jpg", "from": "z14", "to": "z15",
         "why": "画面右上丝印清晰为 Z15/显示电路；原库按底部边缘的 Z14 字样误标为 z14"},
    ]
    d["coverage"] = {
        "target_parts": 18,
        "covered_parts": len(d.get("parts") or {}),
        "counts": d.get("counts"),
        "missing_parts": {
            "z4": "119 张里没有 Z4 天线控制单元整机/铭牌",
            "z5": "只有 Z11/Z12 分机门，没有 Z5 收发机柜整柜或 Z5 铭牌",
            "z16": "没有 Z16 指示分机",
            "z11-1": "Z11 门内模块不可见，无频综丝印",
            "z11-3": "Z11 门内模块不可见，无固态功放丝印",
            "z11-4": "Z11 门内模块不可见，无接收前端丝印",
            "z11-5": "Z11 门内模块不可见，无近程增益丝印",
            "z12-GL": "Z12 电源模块未见 GL1/GL2/GL3 丝印",
            "z14-CLK": "Z14 门内时钟板不可见",
            "z15-IF": "Z15 接口板不可见",
            "z15-CPU": "Z15 CPU 板不可见",
        },
        "note": "7/18 覆盖；缺的 11 个部位在 119 张同场次照片里没有可辨识样本，未硬标",
    }
    d["holdout_added"] = [
        {"image": "IMGP_20260427_201926.jpg", "part": "z31", "why": "新增留出：Z31 电源控制面板"},
        {"image": "IMGP_20260427_202006.jpg", "part": "z31", "why": "新增留出：Z31 电源控制面板"},
        {"image": "IMGP_20260427_202011.jpg", "part": "z18", "why": "新增留出：Z18 控制面板"},
        {"image": "IMGP_20260427_202036.jpg", "part": "z18", "why": "新增留出：Z18 控制面板"},
        {"image": "IMGP_20260427_202057.jpg", "part": "z18", "why": "新增留出：Z18 控制面板"},
    ]
    d["holdout_note"] = ("这些真图**不参与建库**，仅用于 test_part_recognizer.py 的留出测试；"
                         "30 张 = 原 25 张 + 新增 5 张（z31 2、z18 3）")
    json.dump(d, open(P, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("updated", P)
    print("counts", d["counts"], "total", d["total_samples"], "unknown", d["unknown"]["n"],
          "holdout", len(d["holdout"]))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
