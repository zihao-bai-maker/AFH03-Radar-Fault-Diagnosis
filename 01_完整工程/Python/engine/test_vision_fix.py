#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_vision_fix.py —— `run_photo()` 的 `ValueError('*')` 回归测试（2026-10-18）

背景（实测 traceback，09:05 版）::

    File ".../vision_rules.py", line 1496, in _eval_led
        idx = int(idx_s or 0)
    ValueError: invalid literal for int() with base 10: '*'

根因：`ANT_DIR#*` 的 `#` 后是**整排规则占位符 `'*'`**，旧代码在判断 `idx_s == "*"`
之前就把它丢给了 `int()`。修复后（当前 HEAD 已把 `*` 分支前置 + 数字解析进 try）：

* `#*` 走 `_eval_row_rule()`（复用 `led_rules.evaluate_by_litcount`），不再 `int('*')`；
* 单条判据仍抛任何异常时，`evaluate_items()` 里的防火墙只把**这一条**降级为
  `undetermined`（带原因），其余判据照常出证据；
* `analyze_photo()` 整图失败时，`run_photo()` 返回全 `undetermined` 的合法 JSON，不抛异常。

运行：``python test_vision_fix.py``
"""
from __future__ import annotations

import os
import sys
import tempfile
import traceback
from typing import Any, Dict, List, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np
from PIL import Image
import vision_rules as V
import test_vision_rules as T

PHOTO_DIR = r"D:\xuexishengshou\雷达照片_今天\拍照UI照片"
RESULTS: List[Tuple[str, bool, str]] = []

def case(name: str, fn) -> None:
    try:
        detail = fn() or ""
        RESULTS.append((name, True, str(detail)))
        print("  ✅ %-34s %s" % (name, detail))
    except Exception as exc:
        tb = traceback.format_exc()
        RESULTS.append((name, False, "%s: %s" % (type(exc).__name__, exc)))
        print("  ❌ %-34s %s: %s" % (name, type(exc).__name__, exc))
        print(tb)

def _rows2_image() -> np.ndarray:
    """合成一排 2 颗灯（一耀一灭）—— ANT_DIR 整排规则的几何前提。"""
    return T.lamp_row_image([True, False], [(0, 0, 255), (0, 0, 255)])

def t01_star_placeholder_row_rule():
    """`ANT_DIR#*` 必须走整排规则，不能 int('*')。"""
    img = _rows2_image()
    ctx = T.to_ctx(img)
    assert ctx.rows and len(ctx.rows[0].obs) == 2, "合成图没有检出 2 灯排"
    items = [it for it in V.load_catalog() if it.key == "18.2"]
    assert items and items[0].binding_ref == "ANT_DIR#*", "18.2 绑定变了"
    ev = V.evaluate_items(items, ctx, bgr=img, part_hint="z18")
    assert len(ev) == 1, "证据数异常：%d" % len(ev)
    e = ev[0]
    assert e.value in ("on", "off"), "整排规则没出结论：%r（%s）" % (e.value, e.evidence)
    assert e.rule == "led_row:ANT_DIR", "未走 led_row 规则：%s" % e.rule
    return "ANT_DIR#* → %s（%s）" % (e.value, e.rule)

def t02_item_exception_firewall():
    """单条判据抛 ValueError('*') 时，只降级这一条，其余照常判定。"""
    img = _rows2_image()
    ctx = T.to_ctx(img)
    items = V.load_catalog()
    orig = V._eval_one

    def boom(it, *a, **kw):
        if it.key == "18.2":
            raise ValueError("*")          
        return orig(it, *a, **kw)

    V._eval_one = boom
    try:
        ev = V.evaluate_items(items, ctx, bgr=img, part_hint="z18", mirror_routes=False)
    finally:
        V._eval_one = orig
    bad = [e for e in ev if e.item_no == "18.2"]
    assert bad, "18.2 证据丢了"
    assert bad[0].value == "undetermined", "异常条目没降级：%s" % bad[0].value
    assert "内部判定异常" in bad[0].evidence and "ValueError" in bad[0].evidence, \
        "降级原因不可读：%s" % bad[0].evidence
    others = [e for e in ev if e.item_no != "18.2"]
    assert others, "其它判据没出证据"
    assert not any("内部判定异常" in e.evidence for e in others), \
        "防火墙把别的判据也打成了内部异常"
    return "1 条降级、其余 %d 条照常出证据" % len(others)

def t03_run_photo_bad_image():
    """坏图不能让 run_photo 抛异常：返回全 undetermined 的合法 JSON。"""
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "broken.jpg")
        with open(p, "wb") as f:
            f.write(b"this is not a jpeg")
        r = V.run_photo(p)
    assert isinstance(r, dict) and "evidence" in r, "返回结构不对"
    assert r["evidence"], "坏图没有产出任何证据（上层会以为漏采）"
    assert all(e["value"] == "undetermined" for e in r["evidence"]), "坏图居然出了判定"
    assert any("图像分析失败" in e.get("evidence", "") for e in r["evidence"]), \
        "没写清失败原因"
    return "坏图 → %d 条全部 undetermined，未抛异常" % len(r["evidence"])

def t04_run_photo_star_path_real_file():
    """整条真实入口跑 ANT_DIR#*：合成图落盘 → run_photo(part='z18')。"""
    img = _rows2_image()
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "row2.png")
        Image.fromarray(img[:, :, ::-1]).save(p)
        r = V.run_photo(p, part="z18")
    hit = [e for e in r["evidence"] if e["item_no"] == "18.2"]
    assert hit, "run_photo 没跑出 18.2"
    assert hit[0]["value"] in ("on", "off"), "18.2 仍是 %s" % hit[0]["value"]
    return "run_photo(part=z18) → 18.2=%s" % hit[0]["value"]

def t06_non_numeric_placeholder():
    """`#` 后不是数字（'?' / 空）时只降级这一条，绝不进 int()。"""
    import copy
    img = _rows2_image()
    ctx = T.to_ctx(img)
    base = [it for it in V.load_catalog() if it.key == "18.2"][0]
    for ref in ("ANT_DIR#?", "ANT_DIR#"):
        it = copy.copy(base)
        it.binding_ref = ref
        ev = V.evaluate_items([it], ctx, bgr=img, part_hint="z18")
        assert len(ev) == 1, "证据数异常：%d" % len(ev)
        e = ev[0]
        assert e.value == "undetermined", "%s 没降级：%s" % (ref, e.value)
        assert "不是纯数字" in e.evidence, "%s 原因不可读：%s" % (ref, e.evidence)
    return "'ANT_DIR#?' / 'ANT_DIR#' → undetermined，未抛异常"

def t05_real_photos_no_throw(n: int = 30):
    """现场真图 ≥30 张：0 抛异常，证据 JSON 满足 8 个必填字段。"""
    if not os.path.isdir(PHOTO_DIR):
        return "跳过：本机没有真图目录 %s" % PHOTO_DIR
    photos = sorted(
        os.path.join(PHOTO_DIR, f) for f in os.listdir(PHOTO_DIR)
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
    )[:n]
    assert len(photos) >= 30, "真图不足 30 张：%d" % len(photos)
    items = V.load_catalog()
    n_ev = 0
    values: Dict[str, int] = {}
    for p in photos:
        r = V.run_photo(p, items=items)      
        assert isinstance(r, dict) and "evidence" in r, "结构不对：%s" % p
        for e in r["evidence"]:
            for k in ("part", "route", "modality", "field", "value", "confidence",
                      "evidence", "ts"):
                assert k in e, "缺字段 %s：%s" % (k, p)
            assert e["modality"] == "vision"
            assert e["value"], "value 为空：%s" % p
            values[e["value"]] = values.get(e["value"], 0) + 1
            n_ev += 1
    decided = sum(v for k, v in values.items() if k != "undetermined")
    return "%d 张 / %d 条证据 / 已判定 %d，取值 %s" % (
        len(photos), n_ev, decided,
        ", ".join("%s=%d" % kv for kv in sorted(values.items(), key=lambda x: -x[1])))

def main(argv=None) -> int:
    print("=" * 78)
    print("test_vision_fix.py —— run_photo()/ValueError('*') 回归")
    print("=" * 78)
    case("01 ANT_DIR#* 整排规则", t01_star_placeholder_row_rule)
    case("02 单条异常防火墙", t02_item_exception_firewall)
    case("03 坏图不抛异常", t03_run_photo_bad_image)
    case("04 真实入口 #* 路径", t04_run_photo_star_path_real_file)
    case("06 非数字占位符不猜", t06_non_numeric_placeholder)
    case("05 真图 30 张不抛异常", t05_real_photos_no_throw)
    ok = sum(1 for _, p, _ in RESULTS if p)
    print("-" * 78)
    print("通过 %d/%d = %.1f%%" % (ok, len(RESULTS), 100.0 * ok / max(1, len(RESULTS))))
    return 0 if ok == len(RESULTS) else 1

if __name__ == "__main__":
    raise SystemExit(main())
