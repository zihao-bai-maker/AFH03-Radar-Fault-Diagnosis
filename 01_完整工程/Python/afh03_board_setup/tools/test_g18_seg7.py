#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_g18_seg7.py — G18 七段码读数 + Z18 相电压多模态判定 现场自测。

用法（板端）：
    python3 tools/test_g18_seg7.py                  # 自检 + 两张现场照片核对
    python3 tools/test_g18_seg7.py -i IMG           # 只测一张图（自动打印读数/rows/prefill）
    python3 tools/test_g18_seg7.py --no-photo       # 只跑无图自检（分类/证据/rows 契约）

真值（2026-10-29 现场照片，人工目视 + 板端引擎实测）：
    /userdata/afh03_shots/20261029_201402/full.jpg  左 270  中 00336.3  右 228
    /userdata/afh03_shots/20261025_105447/full.jpg  左 270  中 00333.0  右 228
退出码 0 = 全部通过；1 = 有失败（逐条打印原因）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BOARD = os.path.dirname(HERE)
if BOARD not in sys.path:
    sys.path.insert(0, BOARD)
if "/userdata/work2/engine" not in sys.path:
    sys.path.insert(0, "/userdata/work2/engine")

PHOTOS = [
    ("/userdata/afh03_shots/20261029_201402/full.jpg",
     {"left": (270.0, "270"), "middle": (336.3, "00336.3"), "right": (228.0, "228")}),
    ("/userdata/afh03_shots/20261025_105447/full.jpg",
     {"left": (270.0, "270"), "middle": (333.0, "00333.0"), "right": (228.0, "228")}),
]

def _check_photo(G18, path, expect):
    errs = []
    if not os.path.isfile(path):
        return ["照片不存在: %s" % path]
    g = G18.read_g18(path)
    print("  图 %s  %s  ok=%s" % (os.path.basename(path),
                                  g.get("image_size"), g.get("ok")))
    for k, d in (g.get("displays") or {}).items():
        print("    [%-6s] %-4s role=%-13s value=%-8s text=%-8r conf=%.3f bbox=%s reason=%r"
              % (k, d.get("label"), d.get("role"), d.get("value"), d.get("text"),
                 d.get("conf") or 0.0, d.get("bbox"), d.get("reason")))
        want = expect.get(k)
        if want is None:
            continue
        if not d.get("valid"):
            errs.append("%s %s 未读出: %s" % (os.path.basename(path), k, d.get("reason")))
            continue
        if want[1] and str(d.get("text")) != want[1]:

            errs.append("%s %s text=%r 期望 %r" % (os.path.basename(path), k,
                                                   d.get("text"), want[1]))
        if abs(float(d.get("value")) - want[0]) > 0.05:
            errs.append("%s %s value=%r 期望 %r" % (os.path.basename(path), k,
                                                    d.get("value"), want[0]))

    pack = G18.z18_rows(g, phase="A")
    if len(pack["rows"]) != 3:
        errs.append("%s rows 应 3 条，实际 %d" % (os.path.basename(path), len(pack["rows"])))
    if not pack["prefill"]:
        errs.append("%s 缺少 QA 预填" % os.path.basename(path))
    else:
        pf = pack["prefill"]
        print("    prefill: qa=%s measured=%s suggested=%s conf=%.3f mapping_confirmed=%s"
              % (pf["qa_id"], pf["measured"], pf["suggested_answer"], pf["confidence"],
                 pf["mapping_confirmed"]))
        if pf["suggested_answer"] != "done":
            errs.append("%s A 相预填建议应为 done（右表 228V），实际 %r"
                        % (os.path.basename(path), pf["suggested_answer"]))
    if pack["evidence_items"]:
        ev = pack["evidence_items"][0]
        print("    evidence: field=%s value=%s conf=%s measured=%s"
              % (ev["field"], ev["value"], ev["confidence"], ev.get("measured_value")))
        if ev["field"] != G18.PHASE_FIELDS["A"]:
            errs.append("%s 证据字段错: %s" % (os.path.basename(path), ev["field"]))
    print("    结论: %s" % pack["conclusion"]["text"])
    return errs

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--image", default="")
    ap.add_argument("--no-photo", action="store_true")
    a = ap.parse_args()

    from soc_vision import g18_seg7 as G18

    print("=" * 70)
    print("① 无图自检（分类边界 / 证据契约 / rows+prefill 契约）")
    st = G18.selftest()
    print("   %s" % json.dumps(st, ensure_ascii=False))
    errs = [] if st["ok"] else ["selftest: %s" % st["errors"]]

    if not a.no_photo:
        print("=" * 70)
        print("② 现场照片核对")
        if a.image:
            g = G18.read_g18(a.image)
            print(json.dumps(g, ensure_ascii=False, indent=1, default=str))
        else:
            for path, expect in PHOTOS:
                errs += _check_photo(G18, path, expect)
                print("-" * 70)

    print("=" * 70)
    if errs:
        print("FAIL（%d 项）:" % len(errs))
        for e in errs:
            print("  - %s" % e)
        return 1
    print("PASS：读数 / 判定 / 证据 / rows+prefill 全部通过")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
