#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""led_truth_selftest.py —— 用用户口述的 **8 张真值照片**跑规则引擎 + 灯判定，报命中/漏检/误检。

真值（来源：afh03_work/lead/led_ground_truth.md，用户逐条确认）
----------------------------------------------------------------
| 照片 | 部件 | 真值灯态 | 真值判定 |
|---|---|---|---|
| 150326_1 | PS_KONG  | R ON, R ON, G ON      | 正常 |
| 150527   | PS_KONG  | R ON, R ON, G OFF     | 故障 |
| 150558   | PS_WENYA | R OFF,R OFF,G OFF     | 故障 |
| 151324   | PS_GONGPIN | 1 红 ON             | 正常 |
| 151341   | ANT_DIR  | 右向 ON, 左向 OFF     | 正常 |
| 151359   | TX_CTRL  | I ON, II OFF          | 正常 |
| 151448   | TX_STATE | G ON×3, R OFF×2       | 正常 |
| 151820   | ANT_START| R ON                  | 正常 |

两种模式都测：
  * `auto`      ：只用"点亮的灯"候选（不亮的灯无法定位 -> unknown）
  * `auto+lens` ：再叠加 Hough 找**未亮的圆形灯罩**，从而能量出"灭"（这是自动模式的关键）
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

from soc_vision import led_panel as LP
from soc_vision.led_panel import (Calib, PanelDetector, detect_candidates, fit_long, lamps_only,
                                  measure_at, orient_normalize)
from soc_vision.led_rules import LampState, RuleBook, evaluate, evaluate_by_litcount

TRUTH = [

    ("150326_1", "PS_KONG",   ["on", "on", "on"],          "正常", "①②同设备，三灯全亮"),
    ("150527",   "PS_KONG",   ["on", "on", "off"],         "故障", "下方绿灯灭=供电错误"),
    ("150558",   "PS_WENYA",  ["off", "off", "off"],       "故障", "三灯全灭（丝印不同）"),
    ("151324",   "PS_GONGPIN", ["on"],                     "正常", "新部件 1 红亮（横拍）"),
    ("151341",   "ANT_DIR",   ["on", "off"],               "正常", "右向亮/左向灭（横拍，过曝）"),
    ("151359",   "TX_CTRL",   ["on", "off"],               "正常", "I 亮/II 灭（横拍，过曝）"),
    ("151448",   "TX_STATE",  ["on", "on", "on", "off", "off"], "正常", "3 绿亮 2 红灭（横拍）"),
    ("151820",   "ANT_START", ["on"],                      "正常", "天线启动红灯亮（竖拍）"),
]

def find_lenses(bgr, r_min, r_max):
    """Hough 找圆形"灯罩"（含未点亮的），用于自动模式补出"灭"的灯。"""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.medianBlur(gray, 5)
    circles = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, dp=1.2, minDist=int(r_min * 1.8),
                               param1=140, param2=int(os.environ.get("AFH03_HOUGH_P2", "26")),
                               minRadius=int(r_min), maxRadius=int(r_max))
    if circles is None:
        return []
    out = []
    for c in circles[0][:64]:
        out.append((int(c[0]), int(c[1]), int(c[2])))
    return out

def states_auto_lens(bgr, rule, book_unused=None):
    """自动模式（两层）：
    1. **尺寸一致性过滤**亮点（剔除丝印白点/镜面眩光的 r 异常小亮点）；
    2. 能定位全部灯位 → 走**向量路径**（亮点=on、吸附到的暗灯罩=off）；
       否则走**亮灯数路径** `evaluate_by_litcount`（用户规则本身大多只用亮灯数）。
    ON 的判据 = **亮点掩膜命中**（自发光），绝不用 delta 单独判亮（实测会误检）。
    """
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    long_side = max(bgr.shape[:2])
    r_min = max(3, int(round(LP.R_MIN_FRAC * long_side)))
    r_max = max(r_min + 1, int(round(LP.R_MAX_FRAC * long_side)))
    lit = lamps_only(detect_candidates(bgr))

    if len(lit) >= 2:
        r_med = float(np.median([c.r for c in lit]))
        lit = [c for c in lit if c.r >= 0.55 * r_med]
    spots = [(c.x, c.y, c.r, True) for c in lit]
    lenses = find_lenses(bgr, r_min, r_max)
    for (x, y, r) in lenses:
        if all((x - sx) ** 2 + (y - sy) ** 2 > (0.8 * max(r, sr)) ** 2 for sx, sy, sr, _ in spots):
            spots.append((x, y, r, False))
    measured = []
    for (x, y, r, is_bright) in spots:
        if not (r_min <= r <= r_max):
            continue
        m = measure_at(bgr, hsv, x, y, r)
        if m is None:
            continue
        measured.append(dict(x=x, y=y, r=r, delta=m["delta"], color=m["color"], is_bright=is_bright))
    need = len(rule.lamps)
    n_bright = len([z for z in measured if z["is_bright"]])
    n_dark = len([z for z in measured if not z["is_bright"]])
    sel = LP.pick_lamp_slots(measured, need, long_side)
    complete = len(sel) >= need
    if complete:
        states = []
        for i, z in enumerate(sel[:need]):
            ls = rule.lamps[i]
            states.append(LampState(name=ls.name,
                                    color=(z["color"] if z["color"] != "W" else ls.color),
                                    on=bool(z["is_bright"]), delta=z["delta"],
                                    thr_on=LP.DELTA_ON, thr_off=LP.DELTA_OFF,
                                    x=z["x"], y=z["y"], r=z["r"], source="sw",
                                    reason=("亮点掩膜命中（自发光）" if z["is_bright"]
                                            else "仅暗灯罩，delta=%.1f → 灭" % z["delta"])))
        return states, {"ok": True, "path": "vector", "n_bright": n_bright, "n_dark": n_dark,
                        "lens": len(lenses),
                        "reason": "向量路径：亮点 %d + 暗灯罩 %d，灯位全部定位" % (n_bright, n_dark)}

    lit_names = [rule.lamps[i].name for i in range(min(n_bright, need))]
    v = evaluate_by_litcount(rule, n_bright, panel_present=(n_bright + len(lenses) > 0),
                             lit_names=lit_names, lens_evidence=len(lenses))
    states = v.lamps
    return states, {"ok": True, "path": "litcount", "n_bright": n_bright, "n_dark": n_dark,
                    "lens": len(lenses), "litcount_verdict": v.verdict,
                    "reason": "亮灯数路径：亮点 %d（灯位未全定位，按用户规则用亮灯数判定）" % n_bright,
                    "litcount_reason": v.reason}

def main():
    ap = argparse.ArgumentParser(description="LED 真值自测（8 张照片）")
    ap.add_argument("--dir", default="/data/local/tmp/led_truth")
    ap.add_argument("--rules", default="")
    ap.add_argument("--mode", choices=["auto", "auto+lens", "both"], default="both")
    ap.add_argument("--json-out", default="")
    a = ap.parse_args()
    book = RuleBook.load(a.rules or None)
    files = sorted(glob.glob(os.path.join(a.dir, "*.jpg")))
    if not files:
        print("没找到照片：%s" % a.dir)
        return 1

    total = dict(lamp_hit=0, lamp_miss=0, lamp_fp=0, lamp_truth=0, extra=0,
                 verdict_hit=0, verdict_tot=0, photos=0)
    rows = []
    detail = {}
    for key, part, truth_states, truth_verdict, note in TRUTH:
        f = next((x for x in files if key in os.path.basename(x)), None)
        if f is None:
            print("!! 缺照片 %s" % key)
            continue
        raw = cv2.imread(f, cv2.IMREAD_COLOR)
        bgr0, rotated = orient_normalize(raw)
        bgr = fit_long(bgr0)
        rule = book.get(part)
        if rule is None:
            print("!! 规则表缺部件 %s" % part)
            continue
        res = {}
        for mode in (["auto", "auto+lens"] if a.mode == "both" else [a.mode]):
            det = PanelDetector(None)
            if mode == "auto":
                states, gate = det.states_auto(bgr, part, rule)
                v = evaluate(rule, states)
                n_lit = sum(1 for s in states if s.on)
            else:
                states, gate = states_auto_lens(bgr, rule)
                n_lit = int(gate.get("n_bright", 0))

                v = evaluate_by_litcount(
                    rule, n_lit, panel_present=(n_lit + int(gate.get("lens", 0)) > 0),
                    lit_names=[rule.lamps[i].name for i in range(min(n_lit, len(rule.lamps)))],
                    lens_evidence=int(gate.get("lens", 0)))
                if gate.get("path") == "vector":
                    v_vec = evaluate(rule, states)
                    if v_vec.verdict == v.verdict:
                        v.bad_lamps = list(v_vec.bad_lamps)
                        v.lamps = list(v_vec.lamps)
                        gate["detail_path"] = "vector"
                    else:
                        gate["detail_path"] = "litcount(向量与亮灯数结论不一致，以亮灯数为准)"
            truth_on = sum(1 for t in truth_states if t == "on")
            res[mode] = dict(states=[s.tri for s in states], verdict=v.verdict, reason=v.reason,
                             bad=v.bad_lamps, n_lit=n_lit, truth_on=truth_on,
                             lit_hit=(n_lit == truth_on),
                             fp=max(0, n_lit - truth_on), miss=max(0, truth_on - n_lit),
                             path=gate.get("path", "vector" if mode == "auto" else "?"),
                             gate=gate, conf=v.confidence, n_lamp=len(rule.lamps),
                             deltas=[round(float(s.delta), 1) for s in states],
                             reasons=[s.reason for s in states])
            if mode == "auto+lens":
                total["lamp_hit"] += (1 if n_lit == truth_on else 0)
                total["lamp_truth"] += 1
                total["lamp_miss"] += max(0, truth_on - n_lit)
                total["lamp_fp"] += max(0, n_lit - truth_on)
                total["extra"] += 0
                total["verdict_tot"] += 1
                total["verdict_hit"] += 1 if v.verdict == truth_verdict else 0
        total["photos"] += 1
        rows.append((key, part, truth_states, truth_verdict, res))
        detail[key] = dict(part=part, rotated=bool(rotated), truth=truth_states,
                           truth_verdict=truth_verdict, res=res)

    print("=" * 108)
    print("LED 真值自测（8 张照片）  规则表=%s" % (a.rules or "config/led_rules.json 默认"))
    print("=" * 108)
    hdr = "%-11s %-10s %-14s %-4s | %-16s %-6s | %-22s" % (
        "照片", "部件", "真值(亮灯数)", "真值", "auto 路径/判定", "亮灯", "auto+lens 路径/判定/亮灯")
    print(hdr)
    print("-" * 108)
    for key, part, ts, tv, res in rows:
        def fmt(mode):
            r = res.get(mode)
            if not r:
                return "-", "-", "-"
            ok = "✓" if r["lit_hit"] else ("✗fp%d" % r["fp"] if r["fp"] else "✗漏%d" % r["miss"])
            return r["path"], "%s%s" % (r["verdict"], "" if r["verdict"] == tv else "✗"), ok
        a_s, a_v, a_h = fmt("auto")
        l_s, l_v, l_h = fmt("auto+lens")
        print("%-11s %-10s %-14s %-4s | %-16s %-6s | %-22s" % (
            key, part, "%d 亮" % sum(1 for t in ts if t == "on"), tv,
            "%s %s" % (a_s, a_v), a_h, "%s %s 亮%s" % (l_s, l_v, l_h)))
    print("-" * 108)
    n = total["lamp_truth"]
    print("auto+lens 汇总：**亮灯数** 命中 %d/%d 张 = %.1f%% ；漏检(该亮没判亮) %d ；"
          "**误检(把灭判成亮) %d**"
          % (total["lamp_hit"], n, 100.0 * total["lamp_hit"] / max(1, n),
             total["lamp_miss"], total["lamp_fp"]))
    print("           部件判定命中 %d/%d = %.1f%%"
          % (total["verdict_hit"], total["verdict_tot"],
             100.0 * total["verdict_hit"] / max(1, total["verdict_tot"])))
    print("           （auto 模式：只有亮点能定位 → 灭灯多为 unknown → 结论多为「未判定」，属**诚实降级**）")
    if a.json_out:
        with open(a.json_out, "w", encoding="utf-8") as f:
            json.dump({"total": total, "detail": detail}, f, ensure_ascii=False, indent=2)
        print("JSON -> %s" % a.json_out)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
