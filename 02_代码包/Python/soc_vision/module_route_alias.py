#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""二路二维码归一（module_route_alias）—— 板端唯一事实源。

用户口径（2026-10-29，权威，Lead 转述）
--------------------------------------
下面这些**不是独立模块**，而是母模块的**二路二维码**：

    z11-1                  → z11 + route II   （显示「Z11 二路」）
    z12-GL / z12-clk       → z12 + route II   （用户两种写法都算）
    z14-CLK                → z14 + route II
    z15-IF                 → z15 + route II

**保持独立**（不是二路码，原样返回）：``z11-3`` / ``z11-4`` / ``z11-5`` /
``z15-CPU``，以及 ``z4..z31``、``PS_KONG`` 这类规则 id。

为什么要这个文件
----------------
板端 ``markers_modules.json`` 的 ``part`` / ``route`` 字段**已经正确**
（Z11-1 → part=z11、route=II …），但识别链上还有多处会产生旧 id：

* engine ``/userdata/work2/engine/part_recognizer.py`` 的标记后端默认读
  ``/userdata/work2/markers_v2/markers_v2.json``（旧 18 模块表，Z11-1 的
  ``part="z11-1"``、``route=""``）⇒ 实测 2026-10-29 20:21:42 对
  ``/userdata/afh03_shots/20261029_202123/full.jpg`` 返回
  ``part="z11-1" / name="频综" / part_display="z11-1 频综" / route=""``；
* 该文件的 ``OCR_NAME_RULES`` 里「频综/GL/时钟板/接口板」同样直接指向旧 id；
* 结果进入 ``ui_kiosk._apply_route`` 后，显示成 ``z11-1 频综``，题库按
  ``z11-1`` 查找 ⇒ 20:21:43 日志
  ``[partqa] 部位 z11-1 在题库里没有 QA``；路别还可能被旧标记锁/流程步骤
  推成 ``I``（同一行日志 ``route=I``）。

本模块把「旧 id → 母模块 + II」收敛成一份表，供
``soc_vision/marker_id.py``、engine ``part_recognizer.py``、
``soc_vision/ui_kiosk.py``（路别锁定）、``soc_vision/board_infer.py`` 共用，
避免每个入口各写一份 alias 表再次漂移。

对外函数
--------
``normalize_route(route)``                      → ``"I"`` / ``"II"`` / ``""``
``normalize_part_route(part, route="")``        → ``(母模块, 归一后 route)``
``normalize_part(part)``                        → 母模块 part
``display_name(part, route="")``                → ``"Z11 二路"``；非成对部位 ``""``
``is_legacy_ii(part)``                          → 是否旧二路 id
``selfcheck()``                                 → 失败用例列表（空 = 全过）

直接自检::

    python3 soc_vision/module_route_alias.py
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

ROUTE_PAIRED = ("z11", "z12", "z14", "z15")

ROUTE_CN = {"I": "一路", "II": "二路"}

LEGACY_II_PART: Dict[str, str] = {
    "z11-1": "z11",       
    "z12-gl": "z12",      
    "z12-clk": "z12",     
    "z14-clk": "z14",     
    "z15-if": "z15",      
}

_TAIL_CASE = {"gl": "GL", "clk": "CLK", "if": "IF", "cpu": "CPU"}

_RE_PART = re.compile(r"^z(\d{1,2})(?:-?([a-z0-9]+))?$")

_ROUTE_ALIAS = {
    "I": "I", "1": "I", "1路": "I", "L1": "I", "ONE": "I", "A": "I", "一": "I", "一路": "I",
    "II": "II", "2": "II", "2路": "II", "L2": "II", "TWO": "II", "B": "II",
    "二": "II", "二路": "II", "II路": "II",
}

def _canon(part: Any) -> str:
    """小写 + 去空白 + 全角括号/下划线归一（只用于 z 编号识别）。"""
    s = str(part or "").strip().lower()
    s = s.replace("（", "(").replace("）", ")").replace("_", "-")
    s = re.sub(r"\s+", "", s)
    return s

def _parse(part: Any) -> Tuple[str, str, str]:
    """→ ``(base, tail, canonical)``。

    * z 编号：base = ``z11``、tail = ``1`` / ``gl`` / ``cpu`` …；
      canonical 用既有写法（``z15-CPU``，与 PART_INFO 一致）。
    * 非 z 编号（``PS_KONG`` 等）：base=``""``、tail=``""``、canonical=**原样**。
    """
    raw = str(part or "").strip()
    s = _canon(raw)
    if not s:
        return "", "", ""
    m = _RE_PART.match(s)
    if not m:
        return "", "", raw
    base = "z" + str(int(m.group(1)))
    tail = m.group(2) or ""
    if not tail:
        return base, "", base
    return base, tail, base + "-" + _TAIL_CASE.get(tail, tail)

def normalize_route(route: Any) -> str:
    """任意写法 → ``"I"`` / ``"II"`` / ``""``（认不出返回空，绝不猜）。"""
    if route is None or isinstance(route, bool):
        return ""
    if isinstance(route, (int, float)):
        n = int(route)
        return "I" if n == 1 else ("II" if n == 2 else "")
    s = str(route).strip().upper().replace(" ", "").replace("　", "")
    if not s:
        return ""
    if s in _ROUTE_ALIAS:
        return _ROUTE_ALIAS[s]
    if s.endswith("路") and s[:-1] in _ROUTE_ALIAS:
        return _ROUTE_ALIAS[s[:-1]]
    if s.startswith("II"):
        return "II"
    if s.startswith("I"):
        return "I"
    return ""

def _legacy_ii(part: Any) -> Optional[Tuple[str, str]]:
    """旧二路 id → ``(母模块, "II")``；不是二路码返回 ``None``。"""
    base, tail, _can = _parse(part)
    if not base or not tail:
        return None
    if tail == "ii":                              
        return (base, "II") if base in ROUTE_PAIRED else None
    mother = LEGACY_II_PART.get(base + "-" + tail)
    if mother:
        return mother, "II"
    return None

def is_legacy_ii(part: Any) -> bool:
    """是否旧「二路二维码」id（z11-1 / Z12-GL / z12-clk / Z14-CLK / Z15-IF）。"""
    return _legacy_ii(part) is not None

def normalize_part_route(part: Any, route: Any = "") -> Tuple[str, str]:
    """**核心归一**：``(part, route)`` → ``(母模块, 归一后 route)``。

    规则（按优先级）：

    1. 旧二路 id（z11-1 / z12-GL / z12-clk / z14-CLK / z15-IF）⇒
       ``("z11"/"z12"/"z14"/"z15", "II")``；
       **route 一律强制 II**：路别由二维码本身决定，旧标记锁/旧步骤给的 I 不得改判。
    2. 母模块（z11/z12/z14/z15）⇒ 原样 + 归一后的 route（认不出给 ""）。
    3. 其它（z11-3/4/5、z15-CPU、z18、PS_KONG …）⇒ part **原样**（z 编号只做大小写/
       下划线规范化）+ 归一后的 route。
    """
    r = normalize_route(route)
    lg = _legacy_ii(part)
    if lg:
        return lg[0], "II"
    base, _tail, can = _parse(part)
    if not base:
        return can, r                            
    return can, r

def normalize_part(part: Any) -> str:
    """只要母模块 part（丢弃 route）。"""
    return normalize_part_route(part, "")[0]

def display_name(part: Any, route: Any = "") -> str:
    """成对部位的显示名：``Z11 二路`` / ``Z11 一路``；非成对部位返回 ``""``。"""
    p, r = normalize_part_route(part, route)
    if p in ROUTE_PAIRED:
        cn = ROUTE_CN.get(r, "")
        return ("%s %s" % (p.upper(), cn)) if cn else p.upper()
    return ""

_VERIFY_CASES: List[Tuple[Tuple[Any, Any], Tuple[str, str, str]]] = [

    (("z11-1", ""), ("z11", "II", "Z11 二路")),
    (("Z11-1", "I"), ("z11", "II", "Z11 二路")),
    (("z11_1", "一路"), ("z11", "II", "Z11 二路")),
    (("z11ii", ""), ("z11", "II", "Z11 二路")),
    (("z12-GL", ""), ("z12", "II", "Z12 二路")),
    (("z12-clk", ""), ("z12", "II", "Z12 二路")),
    (("z12clk", "II"), ("z12", "II", "Z12 二路")),
    (("Z14-CLK", ""), ("z14", "II", "Z14 二路")),
    (("z14clk", "I"), ("z14", "II", "Z14 二路")),
    (("z15-IF", ""), ("z15", "II", "Z15 二路")),
    (("z15if", ""), ("z15", "II", "Z15 二路")),

    (("z11", "I"), ("z11", "I", "Z11 一路")),
    (("z12", "二路"), ("z12", "II", "Z12 二路")),
    (("z14", "2"), ("z14", "II", "Z14 二路")),
    (("z15", ""), ("z15", "", "Z15")),

    (("z11-3", ""), ("z11-3", "", "")),
    (("z11-4", ""), ("z11-4", "", "")),
    (("z11-5", ""), ("z11-5", "", "")),
    (("z15-CPU", ""), ("z15-CPU", "", "")),
    (("z18", ""), ("z18", "", "")),
    (("PS_KONG", ""), ("PS_KONG", "", "")),
]

def selfcheck() -> List[str]:
    """跑内置用例；返回失败描述列表（空 = 全过）。"""
    fails: List[str] = []
    for (part, route), (want_p, want_r, want_d) in _VERIFY_CASES:
        got_p, got_r = normalize_part_route(part, route)
        got_d = display_name(part, route)
        if (got_p, got_r, got_d) != (want_p, want_r, want_d):
            fails.append("normalize_part_route(%r, %r) -> (%r, %r) display=%r，期望 (%r, %r) display=%r"
                         % (part, route, got_p, got_r, got_d, want_p, want_r, want_d))
    return fails

def main() -> int:
    fails = selfcheck()
    for f in fails:
        print("[FAIL] %s" % f)
    print("%s module_route_alias selfcheck: %d/%d 通过"
          % ("[OK]" if not fails else "[FAIL]",
             len(_VERIFY_CASES) - len(fails), len(_VERIFY_CASES)))
    return 0 if not fails else 1

if __name__ == "__main__":
    raise SystemExit(main())
