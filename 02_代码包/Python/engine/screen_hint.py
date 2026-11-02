#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""screen_hint.py —— 屏幕视觉判定的**薄封装**：只输出参考提示，不作判定依据。

设计修正（作者 2026-10-18）
==========================
    **屏幕识别只做粗略/参考；真正的确认用「屏幕状态问答」（screen_qa.py）。**

本文件只调用 `vision_rules.py` 已有的屏幕判定（**不修改它**），把结果翻译成一句
人话提示，并恒定标注：

* ``reliable: false`` —— 永远不可靠；
* ``hint_only: true`` —— 只用于预选 / 提示；
* ``decided_by: "qa"`` —— 最终结论由问答给出。

底噪类（航向噪声 / 下滑噪声）**视觉绝不判**：现场没有"底噪长什么样 / 没有底噪长
什么样"的参考样本，`classify_screen()` 的 ``no_echo`` 也只是"看不到亮回波"，
不能拿来当"有/无底噪"的结论。本模块对 ``course_noise`` / ``glide_noise``
直接返回 ``available: false``，把判断权交给问答。

用法
----
    python screen_hint.py --image photo.jpg
    python screen_hint.py --image photo.jpg --item 19.7
    python screen_hint.py --image photo.jpg --binding-ref course_echo
    python screen_hint.py --selftest

返回示例
--------
.. code-block:: json

    {"schema": "screen_hint/v1",
     "vision_hint": "画面偏黄", "vision_value": "yellow_screen",
     "confidence": 0.72, "reliable": false, "hint_only": true,
     "available": true, "decided_by": "qa",
     "note": "视觉粗判仅作预选/提示，不作判定依据；屏幕状态以问答为准",
     "source": "vision_rules.classify_screen"}

依赖：`vision_rules.py` 需要 numpy / Pillow；缺依赖时本模块返回
``available: false`` 而不抛异常（板端没有视觉库时也能安全 import）。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from typing import Any, Dict, Optional

__version__ = "1.0.0"
SCHEMA = "screen_hint/v1"
POLICY_NOTE = "视觉粗判仅作预选/提示，不作判定依据；屏幕状态以问答（screen_qa.py）为准"
NOISE_REASON = "底噪类没有参考样本：视觉绝不判「有/无底噪」，必须用问答确认"

_HINT_TEXT = {
    "ok": "画面正常",
    "black_screen": "画面全黑",
    "yellow_screen": "画面偏黄",
    "garbled": "画面花屏",
    "no_echo": "看不到明显回波",
    "no_scan": "画面像静止/不扫描",
    "no": "无回波/不扫描",
    "weak": "回波弱",
    "no_noise": "看不到底噪",
    "abnormal": "线条/方向异常",
    "undetermined": "看不出明确状态",
}

_ALIASES = {
    "ok": "ok", "normal": "ok", "正常": "ok", "画面正常": "ok",
    "black_screen": "black_screen", "黑屏": "black_screen", "画面全黑": "black_screen",
    "yellow_screen": "yellow_screen", "黄屏": "yellow_screen", "偏黄": "yellow_screen",
    "garbled": "garbled", "花屏": "garbled",
    "no_echo": "no_echo", "无回波": "no_echo", "看不到明显回波": "no_echo",
    "no_scan": "no_scan", "不扫描": "no_scan", "静止": "no_scan",
    "no": "no", "weak": "weak", "回波弱": "weak",
    "no_noise": "no_noise", "无噪声": "no_noise", "无底噪": "no_noise",
    "abnormal": "abnormal", "异常": "abnormal",
    "undetermined": "undetermined", "看不清": "undetermined",
}

_TEXT_ORDER = [
    ("黑", "black_screen"),
    ("黄", "yellow_screen"),
    ("花", "garbled"),
    ("无回波", "no_echo"),
    ("不扫描", "no_scan"),
    ("静止", "no_scan"),
    ("无噪声", "no_noise"),
    ("无底噪", "no_noise"),
    ("回波弱", "weak"),
    ("正常", "ok"),
    ("看不清", "undetermined"),
]

def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")

def _canonical(value: Any = "", text: str = "") -> str:
    v = str(value or "").strip()
    if v in _ALIASES:
        return _ALIASES[v]
    t = str(text or "").strip()
    if t in _ALIASES:
        return _ALIASES[t]
    for kw, canon in _TEXT_ORDER:
        if kw in t:
            return canon
    return "undetermined"

def _is_noise(binding_ref: str = "", field: str = "") -> bool:
    s = ("%s %s" % (binding_ref or "", field or "")).lower()
    return "noise" in s or "底噪" in s

def _base(*, vision_hint: str, vision_value: Optional[str], confidence: Any,
          available: bool, source: str, reason: str = "", evidence: str = "",
          item_key: str = "", binding_ref: str = "", field: str = "",
          suppressed: bool = False) -> Dict[str, Any]:
    return {
        "schema": SCHEMA,
        "vision_hint": vision_hint,
        "vision_value": vision_value,
        "confidence": (round(float(confidence), 3)
                       if isinstance(confidence, (int, float)) else None),
        "reliable": False,
        "hint_only": True,
        "available": bool(available),
        "decided_by": "qa",
        "note": POLICY_NOTE,
        "reason": reason,
        "source": source,
        "vision_evidence": evidence,
        "item_key": item_key,
        "binding_ref": binding_ref,
        "field": field,
        "suppressed": bool(suppressed),
        "ts": _now_iso(),
    }

def no_hint(reason: str, *, source: str = "screen_hint", item_key: str = "",
            binding_ref: str = "", field: str = "", suppressed: bool = False) -> Dict[str, Any]:
    """明确的"没有可用视觉提示"——不是"正常"，也不是"异常"。"""
    return _base(vision_hint="", vision_value=None, confidence=None, available=False,
                 source=source, reason=reason, item_key=item_key,
                 binding_ref=binding_ref, field=field, suppressed=suppressed)

def hint_from_vision(value: Any, confidence: Any = None, evidence: str = "", *,
                     binding_ref: str = "", field: str = "", item_key: str = "",
                     source: str = "vision_rules") -> Dict[str, Any]:
    """把 vision_rules 的屏幕结论翻译成参考提示（纯函数，不读图）。"""
    if _is_noise(binding_ref, field) or _canonical(value) == "no_noise":
        return no_hint(NOISE_REASON, source=source, item_key=item_key,
                       binding_ref=binding_ref, field=field, suppressed=True)

    canon = _canonical(value)
    if canon == "undetermined":
        return no_hint("视觉没有给出明确状态（undetermined）", source=source,
                       item_key=item_key, binding_ref=binding_ref, field=field)

    ref = (binding_ref or "").lower()
    text = _HINT_TEXT.get(canon, "画面状态异常")
    if canon == "no":
        if ref.endswith("_echo"):
            text = "无回波"
        elif ref.endswith("_scan"):
            text = "不扫描"
    elif canon == "ok":
        if ref.endswith("_echo"):
            text = "有回波（视觉粗判）"
        elif ref.endswith("_scan"):
            text = "画面在扫描（视觉粗判）"
        elif ref.endswith("_line"):
            text = "线结构可见（视觉粗判）"
        elif ref.endswith("_noise"):
            return no_hint(NOISE_REASON, source=source, item_key=item_key,
                           binding_ref=binding_ref, field=field, suppressed=True)
    elif canon == "abnormal":
        text = "线条/方向异常（视觉粗判）"

    return _base(vision_hint=text, vision_value=canon, confidence=confidence,
                 available=True, source=source, evidence=evidence,
                 item_key=item_key, binding_ref=binding_ref, field=field)

def hint_for_photo(path: str = "", bgr: Any = None, *, item_key: str = "",
                   binding_ref: str = "", field: str = "", ts: str = "") -> Dict[str, Any]:
    """对一张照片做屏幕粗判，返回只读提示。

    * 不传 ``item_key`` / ``binding_ref``：整屏状态（黑/黄/花/正常/看不准）；
    * 传 ``item_key``（如 ``19.7``）或 ``binding_ref``（如 ``course_echo``）：
      只判该屏幕项；
    * 底噪类（``course_noise`` / ``glide_noise``）**一律不判**，返回 available=false。
    """
    if _is_noise(binding_ref, field):
        return no_hint(NOISE_REASON, binding_ref=binding_ref, field=field,
                       suppressed=True)

    try:
        import vision_rules as V  
    except Exception as exc:  
        return no_hint("vision_rules 不可用：%s" % exc, binding_ref=binding_ref,
                       field=field)

    try:
        if bgr is None:
            if not path:
                return no_hint("需要图片路径或 bgr", binding_ref=binding_ref, field=field)
            bgr, _ = V.load_bgr(path)
        ctx = V.PhotoCtx(path=path or "", ts=ts or _now_iso())
        ctx.scene = V.scene_gate(bgr)
        ctx.screen = V.find_screen(bgr)
        ctx.scene.has_target = bool(ctx.screen)

        if item_key or binding_ref:
            target = None
            for it in V.load_catalog():
                if item_key and it.key == item_key:
                    target = it
                    break
                if binding_ref and it.binding == "screen" and it.binding_ref == binding_ref:
                    target = it
                    break
            if target is None:
                return no_hint("vision_rules 目录里找不到屏幕项（item_key=%r, binding_ref=%r）"
                               % (item_key, binding_ref), binding_ref=binding_ref, field=field)
            if _is_noise(target.binding_ref, target.field):
                return no_hint(NOISE_REASON, item_key=target.key,
                               binding_ref=target.binding_ref, field=target.field,
                               suppressed=True)
            evs = V.evaluate_items([target], ctx, bgr=bgr)
            if not evs:
                return no_hint("vision_rules 没有返回该屏幕项的证据", item_key=target.key,
                               binding_ref=target.binding_ref, field=target.field)
            ev = evs[0]
            return hint_from_vision(ev.value, ev.confidence, ev.evidence,
                                    binding_ref=target.binding_ref, field=target.field,
                                    item_key=target.key,
                                    source="vision_rules.evaluate_items")

        sc = ctx.screen
        if sc is None:
            return no_hint("画面里没有定位到显示屏", binding_ref=binding_ref, field=field)
        return hint_from_vision(sc.state, sc.confidence, sc.evidence,
                                binding_ref=binding_ref, field=field,
                                source="vision_rules.classify_screen")
    except Exception as exc:  
        return no_hint("视觉粗判异常（%s: %s）⇒ 只信问答" % (type(exc).__name__, exc),
                       binding_ref=binding_ref, field=field)

def selftest() -> Dict[str, Any]:
    """不读图的纯映射自检。"""
    cases = [
        ("yellow_screen", "", "画面偏黄", True),
        ("黑屏", "", "画面全黑", True),
        ("no", "course_scan", "不扫描", True),
        ("no", "course_echo", "无回波", True),
        ("weak", "glide_echo", "回波弱", True),
        ("ok", "", "画面正常", True),
        ("no_noise", "course_noise", "", False),
        ("ok", "glide_noise", "", False),
        ("undetermined", "", "", False),
    ]
    failures = []
    for value, ref, want_hint, want_available in cases:
        h = hint_from_vision(value, 0.5, binding_ref=ref)
        if h["available"] != want_available:
            failures.append("%s/%s available=%s != %s" % (value, ref, h["available"], want_available))
        if h["vision_hint"] != want_hint:
            failures.append("%s/%s hint=%r != %r" % (value, ref, h["vision_hint"], want_hint))
        if h["reliable"] is not False:
            failures.append("%s reliable 必须恒为 false" % value)
    return {"ok": not failures, "failures": failures, "cases": len(cases)}

def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="屏幕视觉粗判 → 参考提示（不作判定依据）")
    ap.add_argument("--image", default="", help="照片路径")
    ap.add_argument("--item", default="", help="vision_bindings 的 key，如 19.7")
    ap.add_argument("--binding-ref", default="", help="屏幕项，如 course_echo")
    ap.add_argument("--selftest", action="store_true", help="纯映射自检（不读图）")
    ap.add_argument("--json", action="store_true", help="输出 JSON（默认就是 JSON）")
    args = ap.parse_args(argv)
    if args.selftest:
        report = selftest()
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 0 if report["ok"] else 1
    if not args.image:
        ap.error("需要 --image，或 --selftest")
    hint = hint_for_photo(args.image, item_key=args.item, binding_ref=args.binding_ref)
    print(json.dumps(hint, ensure_ascii=False, indent=1))
    return 0

if __name__ == "__main__":
    sys.exit(main())
