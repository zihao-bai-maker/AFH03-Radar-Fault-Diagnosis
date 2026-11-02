#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_scope_rules.py —— 28 项判据库核对 + judge() 单元 + 合成拍屏 + 真图回归

用法：
    python test_scope_rules.py                 # 全跑（含真图 scope_screen_1.jpg）
    python test_scope_rules.py --photo D:\\...\\scope_screen_1.jpg
    python test_scope_rules.py --verbose       # 逐条打印

退出码：0 = 全部通过；1 = 有失败。
产物：只打印；不写文件（不污染 engine 目录）。
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import traceback

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scope_rules as sr                                        

DEFAULT_PHOTO = r"D:\xuexishengshou\工作区2\photos\scope_screen_1.jpg"

RESULTS = []
_CUR = ["(未分组)"]
_VERBOSE = [False]

def section(name):
    _CUR[0] = name

def check(name, cond, detail=""):
    ok = bool(cond)
    RESULTS.append({"section": _CUR[0], "name": name, "ok": ok, "detail": str(detail)})
    if not ok:
        print("  FAIL [%s] %s | %s" % (_CUR[0], name, str(detail)[:400]))
    elif _VERBOSE[0]:
        print("  ok   [%s] %s" % (_CUR[0], name))

def run(name, fn):
    section(name)
    try:
        fn()
    except Exception:                                           
        check("本节无异常", False, traceback.format_exc().strip().splitlines()[-1])

SCR_W, SCR_H, H_DIV, V_DIV = 800, 480, 10, 8

def _font(sz=18):
    for p in ("C:/Windows/Fonts/consola.ttf", "C:/Windows/Fonts/arial.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"):
        try:
            return ImageFont.truetype(p, sz)
        except Exception:                                       
            pass
    return ImageFont.load_default()

def _sdiv(ns):
    if ns < 1000:
        return "%gns" % ns
    if ns < 1e6:
        return "%gus" % (ns / 1e3)
    return "%gms" % (ns / 1e6)

def render_scope(freq_hz=0.0, ns_per_div=100.0, vpp_v=3.3, mode="wave"):
    """画一块 RIGOL 风格屏幕：暗底 + 栅格 + 黄线 + 白字（白字 warm≈0，不会被当波形）。

    mode: wave=有周期波形 / flat=平线（Freq=*****）/ blank=只有栅格文字（无波形亮线）
    """
    im = Image.new("RGB", (SCR_W, SCR_H), (12, 20, 28))
    d = ImageDraw.Draw(im)
    cw, ch = SCR_W / H_DIV, SCR_H / V_DIV
    for i in range(H_DIV + 1):
        x = int(i * cw)
        for y in range(0, SCR_H, 8):
            d.line([(x, y), (x, y + 3)], fill=(40, 55, 70))
    for j in range(V_DIV + 1):
        y = int(j * ch)
        for x in range(0, SCR_W, 8):
            d.line([(x, y), (x + 3, y)], fill=(40, 55, 70))
    mid = SCR_H * 0.55
    t = np.arange(SCR_W)
    if mode == "blank":
        y = None
    elif mode == "flat":
        y = np.full(SCR_W, mid)
    else:
        total = float(ns_per_div) * 1e-9 * H_DIV
        phase = (t / float(SCR_W) * (float(freq_hz) * total)) % 1.0
        v = np.where(phase < 0.5, 1.0, -1.0)
        y = mid - v * (ch * 1.5)
    if y is not None:
        for x in range(1, SCR_W):
            d.line([(x - 1, y[x - 1]), (x, y[x])], fill=(240, 230, 60), width=2)
    f = _font(18)
    if mode == "flat":
        txt = "Freq = *****   Vpp = 80.0mV"
    elif mode == "blank":
        txt = "Freq = *****   Vpp = 0.0mV"
    else:
        txt = "Freq = %.2fMHz   Vpp = %.2fV" % (freq_hz / 1e6, vpp_v)
    d.text((12, 8), txt, fill=(220, 220, 220), font=f)
    d.text((12, SCR_H - 26), "H %s" % _sdiv(ns_per_div), fill=(220, 220, 220), font=f)
    return im

def mount(scope):
    """把屏幕贴进一张 1920x1080『板子拍照』背景里（屏幕占中间偏左）。"""
    bg = Image.new("RGB", (1920, 1080), (150, 150, 150))
    d = ImageDraw.Draw(bg)
    for i in range(0, 1920, 40):
        d.rectangle([i, 0, i + 20, 1080],
                    fill=(170, 170, 165) if (i // 40) % 2 else (120, 120, 118))
    bg.paste(scope.resize((1280, 768)), (300, 260))
    return np.asarray(bg)

def t_library():
    lib = sr.library()
    items = lib.items
    check("项数 = 28", len(items) == 28, len(items))
    check("信号数 = 14", len(lib.signals) == 14, len(lib.signals))
    check("flow 分布 22:8 / 23:6 / 27:8 / 28:6",
          lib.summary()["by_flow"] == {"22": 8, "23": 6, "27": 8, "28": 6},
          lib.summary()["by_flow"])
    fields = [it["field"] for it in items]
    check("field 唯一", len(set(fields)) == 28, len(set(fields)))
    fids = [it["feature_id"] for it in items]
    check("feature_id 唯一且非空", len(set(fids)) == 28 and all(fids), len(set(fids)))
    check("part 只有 z14 / z11", {it["part"] for it in items} == {"z14", "z11"},
          sorted({it["part"] for it in items}))
    check("route 只有 I / II", {it["route"] for it in items} == {"I", "II"})
    check("判据来源全部非空", all(str(it.get("判据来源") or "").strip() for it in items))
    check("每项判据来源指向 判据库_SOP.csv",
          all("判据库_SOP.csv" in it["判据来源"] for it in items))

    freq_items = [it for it in items if it["judge_mode"] == "freq"]
    check("频率项 = 6（3 信号 × I/II）", len(freq_items) == 6, len(freq_items))
    got = {}
    for it in freq_items:
        got.setdefault(it["signal"], it["expect_freq_hz"])
    check("10M相参基准 期望 = 10 MHz", got.get("10M相参基准") == 10_000_000, got)
    check("30M发射中频 期望 = 30 MHz", got.get("30M发射中频") == 30_000_000, got)
    check("40M时钟 期望 = 40 MHz", got.get("40M时钟") == 40_000_000, got)
    check("★ 全库没有 20 MHz 期望（修掉旧 20/40 错误）",
          all(it["expect_freq_hz"] != 20_000_000 for it in items))
    check("容差都在 3~5%", all(3.0 <= float(it["tol_pct"]) <= 5.0 for it in freq_items))
    check("信号名里没有 20M", all("20M" not in it["signal"] for it in items))

    presence = [it for it in items if it["judge_mode"] == "presence"]
    check("存在性项 = 22 且不设频率", len(presence) == 22
          and all(it["expect_freq_hz"] is None for it in presence), len(presence))

    csv_path = os.path.join(os.path.dirname(HERE), "判据库_SOP.csv")
    check("判据库_SOP.csv 存在", os.path.isfile(csv_path), csv_path)
    if os.path.isfile(csv_path):
        with open(csv_path, encoding="utf-8-sig") as f:
            rows = [r for r in csv.DictReader(f)
                    if (r.get("method") or "").strip() == "采集示波器输出数据"]
        check("CSV 示波器行 = 28", len(rows) == 28, len(rows))
        csv_keys = {(r["flow_no"].strip(), (r.get("check_item") or "").strip()) for r in rows}
        lib_keys = {(str(it["flow_no"]), it["check_item"]) for it in items}
        check("flow + 项目原文 与 CSV 完全一致", csv_keys == lib_keys,
              "差异=%s" % (list(csv_keys ^ lib_keys)[:4],))

    check("part 为小写 token（schema §3）", all(it["part"] == it["part"].lower() for it in items))
    check("field 前缀 (scope)（schema §4）",
          all(it["field"].startswith("(scope)_") for it in items))
    check("feature_id = F_<field>_<abnormal_value>",
          all(it["feature_id"] == "F_%s_%s" % (it["field"], it["abnormal_value"])
              for it in items))
    check("flow 28 已标注 flow_name 笔误",
          all("flow_name_note" in it for it in items if it["flow_no"] == 28))

    bad = []
    for it in items:
        ev = sr.judge(it["check_item"], it["expect_freq_hz"], route=it["route"],
                      wave_present=True)
        if ev["field"] != it["field"] or ev["value"] != "normal":
            bad.append((it["item_id"], ev["field"], ev["value"]))
    check("28 项按项目原文都能定位到自己的 field", not bad, bad[:4])

def t_judge():
    ev = sr.judge("10M相参基准", 10.01e6, 3.3, 0.95, route="I")
    check("10M/10.01MHz/I → normal",
          ev["value"] == "normal" and ev["field"] == "(scope)_route_one_10m_reference",
          ev.get("reason"))
    check("part = z14", ev["part"] == "z14", ev["part"])
    check("normal 时 feature_id 为空", ev["feature_id"] == "")
    check("evidence/v1 必填字段齐",
          all(k in ev for k in ("part", "route", "modality", "field", "value",
                                "confidence", "evidence", "ts")) and ev["modality"] == "scope")
    check("ts 是 ISO-8601 带时区", "T" in str(ev["ts"]) and len(str(ev["ts"])) >= 19, ev["ts"])

    ev = sr.judge("30M发射中频", 30.15e6, route="II")
    check("30M/30.15MHz/II → normal",
          ev["value"] == "normal" and ev["field"] == "(scope)_route_two_30m_if"
          and ev["route"] == "II", ev.get("reason"))

    ev = sr.judge("40M时钟", 39.2e6, route="I")
    check("40M/39.2MHz(-2%) → normal", ev["value"] == "normal", ev.get("reason"))

    ev = sr.judge("40M时钟", 43.0e6, route="II")
    check("40M/43MHz(+7.5%) → abnormal",
          ev["value"] == "abnormal"
          and ev["feature_id"] == "F_(scope)_route_two_40m_clock_freq_out_of_tol",
          ev.get("reason"))
    check("abnormal 带 abnormal_value=freq_out_of_tol", ev["abnormal_value"] == "freq_out_of_tol")

    ev = sr.judge("10M相参基准", 20.0e6, route="I")
    check("★ 10M 实测 20MHz → abnormal（旧逻辑会误判正常）",
          ev["value"] == "abnormal", ev.get("reason"))
    ev = sr.judge("30M发射中频", 20.0e6, route="I")
    check("★ 30M 实测 20MHz → abnormal（旧逻辑会误判正常）",
          ev["value"] == "abnormal", ev.get("reason"))

    ev = sr.judge("10M相参基准", 10.0e6, confidence=0.10, route="I")
    check("置信度 0.10 → undetermined", ev["value"] == "undetermined"
          and ev["feature_id"] == "", ev.get("reason"))
    ev = sr.judge("10M相参基准", None, route="I")
    check("无频率读数 → undetermined", ev["value"] == "undetermined", ev.get("reason"))

    ev = sr.judge("10M相参基准", None, route="I", wave_present=False)
    check("无波形（默认策略）→ undetermined", ev["value"] == "undetermined", ev.get("reason"))
    ev = sr.judge("10M相参基准", None, route="I", wave_present=False,
                  no_signal_verdict="abnormal")
    check("无波形 + 严格策略 → abnormal/no_signal",
          ev["value"] == "abnormal"
          and ev["feature_id"] == "F_(scope)_route_one_10m_reference_no_signal",
          ev.get("reason"))

    ev = sr.judge("显示同步", None, route="I", wave_present=True)
    check("显示同步（判据库无频率）有波形 → normal",
          ev["value"] == "normal" and ev["criterion"] == "presence", ev.get("reason"))
    ev = sr.judge("显示同步", route="I")
    check("显示同步 无波形信息 → undetermined", ev["value"] == "undetermined", ev.get("reason"))

    ev = sr.judge("杂波", 1.0)
    check("库外且名称无频率 → undetermined", ev["value"] == "undetermined", ev.get("reason"))

    ev = sr.judge("55M", 55.0e6)
    check("名称频率兜底 55M/55MHz → normal（library_match=False）",
          ev["value"] == "normal" and ev["library_match"] is False, ev.get("reason"))

    ev = sr.judge(None, 10.0e6, flow_no=27, check_item="测量10M相参基准波形正常")
    check("flow27+原文 → route II / z14",
          ev["value"] == "normal" and ev["route"] == "II"
          and ev["field"] == "(scope)_route_two_10m_reference", ev.get("reason"))
    ev = sr.judge(None, 10.0e6, flow_no=22, sub_no=4)
    check("flow22 sub4 → normal", ev["value"] == "normal", ev.get("reason"))
    ev = sr.judge(None, None, flow_no=23)
    check("flow23 单独定位（6 项歧义）→ undetermined",
          ev["value"] == "undetermined" and "命中" in ev["reason"], ev.get("reason"))

    ev = sr.judge(None, 10.02e6, item_id="f22_01")
    check("item_id=f22_01 → 正常（I 路 10M）",
          ev["value"] == "normal" and ev["field"] == "(scope)_route_one_10m_reference",
          ev.get("reason"))
    ev = sr.judge(None, 40e6, item_id="no_such_item")
    check("未知 item_id → undetermined", ev["value"] == "undetermined", ev.get("reason"))

    ev = sr.judge("30M发射中频", 31.2e6, route="I", tol_pct=3.0)
    check("容差可配：31.2M/+4% 在 ±3% 下 abnormal", ev["value"] == "abnormal", ev.get("reason"))
    ev = sr.judge("30M发射中频", 31.2e6, route="I", tol_pct=5.0)
    check("容差可配：31.2M/+4% 在 ±5% 下 normal", ev["value"] == "normal", ev.get("reason"))

    ev = sr.judge("10M相参基准", 10.0e6)
    check("未指定 route → 取 I 并标记 route_assumed",
          ev["route"] == "I" and ev["route_assumed"] is True, ev.get("route_assumed"))

    v1 = sr.as_evidence_v1(sr.judge("10M相参基准", None, route="I", wave_present=False,
                                    no_signal_verdict="abnormal"))
    check("as_evidence_v1：no_signal → value=no（schema 值域）",
          v1["value"] == "no" and v1["route"] == "I", v1.get("value"))
    batch = sr.evidence_batch([sr.judge("40M时钟", 40.0e6, route="I")])
    check("evidence_batch 包装 = evidence/v1",
          batch["schema"] == "evidence/v1" and len(batch["evidence"]) == 1)

def t_text_parse():
    p = sr.parse_measurement_text("Freq = 10.00MHz   Vpp = 3.30V")
    check("Freq/Vpp 解析", abs(p["freq_hz"] - 10e6) < 1 and abs(p["vpp_v"] - 3.3) < 1e-6, p)
    p = sr.parse_measurement_text("频率 = *****")
    check("Freq=***** → None", p["freq_hz"] is None, p)
    p = sr.parse_measurement_text("s/div = 50ns")
    check("s/div=50ns → 50", abs((p["ns_per_div"] or 0) - 50.0) < 1e-6, p)
    p = sr.parse_measurement_text("H 500ns")
    check("RIGOL 底栏 H 500ns → 500", abs((p["ns_per_div"] or 0) - 500.0) < 1e-6, p)
    p = sr.parse_measurement_text("频率=1.234kHz")
    check("kHz 解析", abs(p["freq_hz"] - 1234.0) < 1e-6, p)
    p = sr.parse_measurement_text("峰峰值=80.00mV")
    check("mV → V", abs(p["vpp_v"] - 0.08) < 1e-9, p)
    p = sr.parse_measurement_text("Freq = 40.00MHz   Vpp = 2.50V   H 25ns")
    check("一行内频率+幅度+时基", abs(p["freq_hz"] - 40e6) < 1
          and abs(p["ns_per_div"] - 25.0) < 1e-6, p)

def _read(img, ns=None, **kw):
    return sr.read_scope_screen(img, ns_per_div=ns, **kw)

def _case(name, f_true, ns, sig, route, expect, tol_pct=None):
    img = mount(render_scope(f_true, ns))
    rd = _read(img, ns)
    f = rd.get("freq_hz")
    err = abs(f - f_true) / f_true * 100.0 if f else 999.0
    check("%s 读数误差 < 3%%" % name, err < 3.0,
          "测得 %s，真值 %.2f MHz，误差 %.2f%%" % (sr.fmt_hz(f), f_true / 1e6, err))
    ev = sr.judge(sig, f, rd.get("vpp_v"), rd.get("confidence"), route=route,
                  wave_present=rd.get("wave_present"),
                  **({"tol_pct": tol_pct} if tol_pct is not None else {}))
    check("%s 判定 = %s" % (name, expect), ev["value"] == expect,
          "%s | %s" % (ev["value"], ev.get("reason")))
    return rd, ev

def t_synthetic():
    _case("10M @100ns/div", 10e6, 100.0, "10M相参基准", "I", "normal")
    _case("30M @50ns/div", 30e6, 50.0, "30M发射中频", "I", "normal")
    _case("40M @50ns/div", 40e6, 50.0, "40M时钟", "II", "normal")
    _case("10.2M(+2%) @100ns/div", 10.2e6, 100.0, "10M相参基准", "I", "normal")
    _case("38.5M(-3.75%) @50ns/div", 38.5e6, 50.0, "40M时钟", "I", "normal")
    _case("12M 当 10M 判", 12e6, 100.0, "10M相参基准", "I", "abnormal")
    _case("20M 当 10M 判（旧逻辑陷阱）", 20e6, 100.0, "10M相参基准", "I", "abnormal")
    _case("35M 当 30M 判", 35e6, 50.0, "30M发射中频", "I", "abnormal")

    img = mount(render_scope(0, 100.0, mode="flat"))
    rd = _read(img, 100.0)
    check("平线：识别为无波形", rd.get("wave_present") is False, rd.get("reason"))
    ev = sr.judge("10M相参基准", rd.get("freq_hz"), None, rd.get("confidence"),
                  route="I", wave_present=rd.get("wave_present"))
    check("平线 → undetermined（宁可不判）", ev["value"] == "undetermined", ev.get("reason"))
    check("undetermined 的 confidence ≤ 0.5（schema §6，原始值另存）",
          ev["confidence"] <= 0.5 and ev["confidence_raw"] >= ev["confidence"],
          (ev["confidence"], ev["confidence_raw"]))

    img = mount(render_scope(0, 100.0, mode="blank"))
    rd = _read(img, 100.0)
    ev = sr.judge("10M相参基准", rd.get("freq_hz"), None, rd.get("confidence"),
                  route="I", wave_present=rd.get("wave_present"))
    check("无亮线 → undetermined", ev["value"] == "undetermined", ev.get("reason"))

    img = mount(render_scope(10e6, 100.0))
    rd = _read(img, None)
    check("无时基：不硬算频率", rd.get("freq_hz") is None and rd.get("wave_present") is True,
          rd.get("reason"))
    check("无时基：原因提到 s/div 时基", "时基" in str(rd.get("reason")), rd.get("reason"))
    ev = sr.judge("10M相参基准", rd.get("freq_hz"), None, rd.get("confidence"),
                  route="I", wave_present=rd.get("wave_present"))
    check("无时基 → undetermined", ev["value"] == "undetermined", ev.get("reason"))

    img = mount(render_scope(0, 100.0, mode="flat"))
    rd = sr.read_scope_screen(img, ns_per_div=None,
                              ocr_fn=lambda _crop: "Freq = 30.00MHz   Vpp = 3.30V")
    check("屏幕文字优先：Freq=30MHz 直读", rd.get("source") == "screen_text"
          and abs((rd.get("freq_hz") or 0) - 30e6) < 1, rd)
    ev = sr.judge("30M发射中频", rd.get("freq_hz"), rd.get("vpp_v"), rd.get("confidence"),
                  route="I", wave_present=rd.get("wave_present"))
    check("屏幕文字优先 → normal", ev["value"] == "normal", ev.get("reason"))

    img = mount(render_scope(10e6, 100.0))
    rd = _read(img, 100.0)
    ev10 = sr.judge("10M相参基准", rd["freq_hz"], None, rd["confidence"], route="I",
                    wave_present=rd["wave_present"])
    ev40 = sr.judge("40M时钟", rd["freq_hz"], None, rd["confidence"], route="I",
                    wave_present=rd["wave_present"])
    check("多信号：同一读数 10M→normal / 40M→abnormal",
          ev10["value"] == "normal" and ev40["value"] == "abnormal"
          and ev10["field"] != ev40["field"], (ev10["value"], ev40["value"]))

    img_bgr = img[:, :, ::-1].copy()
    rdb = sr.read_scope_screen(img_bgr, ns_per_div=100.0)
    check("BGR 相机帧（auto 通道序）仍读 10 MHz",
          rdb.get("freq_hz") is not None
          and abs(rdb["freq_hz"] - 10e6) / 10e6 < 0.03, rdb.get("freq_hz"))

    img = mount(render_scope(30e6, 50.0))
    ev = sr.measure_item(img, "30M发射中频", route="II", ns_per_div=50.0)
    check("measure_item 端到端 → normal + reading 元数据",
          ev["value"] == "normal" and ev["freq_source"] == "period_timebase"
          and ev["part"] == "z14" and (ev.get("reading_confidence") or 0) > 0.5,
          ev.get("reason"))
    check("measure_item 频率误差 < 3%",
          abs((ev.get("measured_freq_hz") or 0) - 30e6) / 30e6 < 0.03,
          ev.get("measured_freq_hz"))

    evs = sr.judge_batch([{"signal": "10M相参基准", "freq_hz": 10e6, "route": "I"},
                          {"signal": "40M时钟", "freq_hz": 43e6, "route": "I"}])
    check("judge_batch 两行：normal + abnormal",
          len(evs) == 2 and evs[0]["value"] == "normal" and evs[1]["value"] == "abnormal",
          [e["value"] for e in evs])

def t_photo(path):
    check("真图存在: %s" % path, os.path.isfile(path), path)
    if not os.path.isfile(path):
        return
    img = np.asarray(Image.open(path).convert("RGB"))
    scr = sr.locate_screen(img)
    w = scr["box"][2] - scr["box"][0]
    h = scr["box"][3] - scr["box"][1]
    check("真图定位到屏幕", scr["ok"] and w > 200 and h > 100,
          "box=%s %dx%d" % (scr["box"], w, h))
    rd = sr.read_scope_screen(img, ns_per_div=None)
    check("真图：屏幕内是平线（无有效信号）", rd.get("wave_present") is False, rd.get("reason"))
    check("真图：没有时基/频率不硬算", rd.get("freq_hz") is None, rd)
    ev = sr.judge("10M相参基准", rd.get("freq_hz"), rd.get("vpp_v"), rd.get("confidence"),
                  route="I", wave_present=rd.get("wave_present"))
    check("真图 → undetermined（不误判为正常/故障）", ev["value"] == "undetermined",
          ev.get("reason"))
    check("真图 undetermined 无 feature_id", ev["feature_id"] == "")
    print("  真图: box=%s  屏幕=%dx%d  cols=%s  yspan=%s  结论=%s"
          % (scr["box"], w, h, rd.get("cols"),
             (sr.extract_trace(img, scr["box"]) or {}).get("yspan"), ev["value"]))

def report():
    sections = []
    for r in RESULTS:
        if r["section"] not in sections:
            sections.append(r["section"])
    print("\n================ 结果 ================")
    total = passed = 0
    for s in sections:
        rs = [r for r in RESULTS if r["section"] == s]
        p = sum(1 for r in rs if r["ok"])
        total += len(rs)
        passed += p
        print("%-28s %2d/%2d %s" % (s, p, len(rs), "" if p == len(rs) else "  <-- 有失败"))
    print("--------------------------------------")
    print("合计 %d/%d = %.1f%%" % (passed, total, 100.0 * passed / max(1, total)))
    return 0 if passed == total else 1

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--photo", default=DEFAULT_PHOTO)
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    _VERBOSE[0] = a.verbose
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                           
        pass
    print("Python %s | numpy %s | scope_rules=%s"
          % (sys.version.split()[0], np.__version__, sr.__file__))
    print("ui_kiosk.wave_from_frame 可用: %s" % (sr._uk_wave_from_frame is not None))

    run("1 判据库（28 项 / CSV 核对）", t_library)
    run("2 judge() 单元", t_judge)
    run("3 屏幕文字解析", t_text_parse)
    run("4 合成拍屏（10M/30M/40M/异常/无信号）", t_synthetic)
    run("5 真图回归", lambda: t_photo(a.photo))
    return report()

if __name__ == "__main__":
    sys.exit(main())
