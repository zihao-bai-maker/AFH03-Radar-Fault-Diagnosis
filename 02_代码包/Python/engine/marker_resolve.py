#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""marker_resolve.py —— 二维码代替方案：柜级码 + 路别/显示类型 → 内部模块。

背景
----
8 个内部模块（z11-收发 / z11-1 / z12-电源 / z12-GL / z14-信处 / z14-CLK /
z15-显示电路 / z15-IF）的安装面**放不下二维码**。用户 2026-10-25 批准的代替方案：

| 柜级码（有码） | 路别 / 显示类型 | 推出的内部模块 |
|---|---|---|
| z11 | I 路 | z11-收发 |
| z11 | II 路 | z11-1 |
| z12 | I 路 | z12-电源 |
| z12 | II 路 | z12-GL |
| z14 | I 路 | z14（数据里的 z14-信处，同义归一） |
| z14 | II 路 | z14（Z14-CLK 板当 Z14 使用，同义归一） |
| z15 | 操显 | z15-显示电路 |
| z15 | 领显 | z15-IF |

★ 2026-10-25 现场（用户口述，权威）：现场有两块 Z14 板 —— Z14（信处）与
Z14-CLK（时钟板）；**Z14-CLK 这块现在当 Z14 使用**。⇒ `z14-信处` 与 `z14-CLK`
都是同一块 Z14 板的同义词，`resolve("z14", ...)` 对 I / II 两路**都返回 `z14`**
（见 `_MODULE_CANON`）。数据文件里的 `module_by_route` 仍是
`{"I": "z14-信处", "II": "z14-CLK"}`，归一在本模块做，不改数据。

★ 这是**推断**，不是直接标识！界面必须显示「（代替码推断）」，
   不能让用户以为读到的是内部模块自己的二维码。`describe()` 已带这个标记。

数据来源（按优先级）
--------------------
1. 环境变量 `AFH03_MARKERS_JSON` 指定的 JSON；
2. 与本模块同目录的 `markers_modules.json`；
3. 上一级目录的 `markers_modules.json`（板端：/home/rock/afh03_board_setup/）；
4. 上一级目录 `markers_v2/markers_v2_plus_G.json`（PC 端 `雷达判据/engine` 布局）。

只读数据里柜级码条目的 `module_by_route` / `module_by_display`（兼容旧键
`module_by_display_kind`）。数据缺失/参数缺失时**原样返回 part**，绝不猜。

用法
----
    from soc_vision.marker_resolve import resolve, describe
    resolve("z11", route="II")            # -> "z11-1"
    resolve("z15", display_kind="领显")    # -> "z15-IF"
    resolve("z14", route="II")            # -> "z14"（Z14-CLK 当 Z14 用）
    resolve("z11")                         # -> "z11"（缺参数，原样返回）
    describe("z15", display_kind="操显")   # -> "Z15（操显）→ z15-显示电路（代替码推断）"

自检（板端）：
    python3 -m soc_vision.marker_resolve --verify
"""

from __future__ import annotations

import json
import os
import sys
import threading
from typing import Any, Dict, Optional, Tuple

__version__ = "1.1.0"
__all__ = ["resolve", "describe", "reload", "mapping_info"]

_LOG_PREFIX = "[marker_resolve]"
_HERE = os.path.dirname(os.path.abspath(__file__))
_PARENT = os.path.dirname(_HERE)

_ROUTE_KEY = "module_by_route"
_DISPLAY_KEYS = ("module_by_display", "module_by_display_kind")

_ROUTE_ALIASES = {
    "I": "I", "1": "I", "01": "I", "一": "I", "一路": "I", "1路": "I",
    "I路": "I", "Ⅰ": "I", "ONE": "I",
    "II": "II", "2": "II", "02": "II", "二": "II", "二路": "II", "2路": "II",
    "II路": "II", "Ⅱ": "II", "TWO": "II",
}

_DISPLAY_ALIASES = {
    "操显": "操显", "操显屏": "操显", "操作显": "操显", "操作显示": "操显",
    "领显": "领显", "领显屏": "领显", "领航显示": "领显",
}

_MODULE_CANON = {
    "z14-信处": "z14",
    "z14-clk": "z14",
}

_CACHE: Dict[str, Any] = {
    "path": None, "mtime": None, "by_part": {}, "n_codes": 0, "n_markers": 0,
}
_CACHE_LOCK = threading.RLock()
_WARNED: set = set()

def _warn_once(msg: str) -> None:
    if msg in _WARNED:
        return
    _WARNED.add(msg)
    print("%s [warn] %s" % (_LOG_PREFIX, msg), file=sys.stderr, flush=True)

def _candidate_paths():
    env = os.environ.get("AFH03_MARKERS_JSON", "").strip()
    if env:
        yield os.path.abspath(os.path.expanduser(env))
    yield os.path.join(_HERE, "markers_modules.json")
    yield os.path.join(_PARENT, "markers_modules.json")
    yield os.path.join(_PARENT, "markers_v2", "markers_v2_plus_G.json")
    yield os.path.join(_HERE, "markers_v2_plus_G.json")

def find_mapping_path() -> str:
    """返回实际使用的映射 JSON 绝对路径；找不到抛 FileNotFoundError。"""
    tried = []
    for path in _candidate_paths():
        path = os.path.abspath(path)
        if path in tried:
            continue
        tried.append(path)
        if os.path.isfile(path):
            return path
    raise FileNotFoundError("%s 找不到映射 JSON，已尝试: %s" % (_LOG_PREFIX, tried))

def _build_mapping(doc: Dict[str, Any]) -> Dict[str, Any]:
    modules = doc.get("modules") or {}
    by_part: Dict[str, Dict[str, Any]] = {}
    for label, mod in modules.items():
        if not isinstance(mod, dict):
            continue
        part = str(mod.get("part") or label or "").strip().lower()
        if part:
            by_part[part] = mod
        key = str(label or "").strip().lower()
        if key:
            by_part.setdefault(key, mod)          
    for mod in doc.get("markers") or []:          
        if not isinstance(mod, dict):
            continue
        part = str(mod.get("part") or "").strip().lower()
        if part:
            by_part.setdefault(part, mod)
    n_rules = 0
    n_edges = 0
    counted = set()
    for mod in modules.values():
        if not isinstance(mod, dict) or id(mod) in counted:
            continue
        counted.add(id(mod))
        routes = mod.get(_ROUTE_KEY) if isinstance(mod.get(_ROUTE_KEY), dict) else {}
        disp = {}
        for key in _DISPLAY_KEYS:
            if isinstance(mod.get(key), dict) and mod.get(key):
                disp = mod[key]
                break
        if routes or disp:
            n_rules += 1
            n_edges += len(routes) + len(disp)
    return {
        "path": None,
        "by_part": by_part,
        "n_codes": len(modules),
        "n_markers": len(doc.get("markers") or []),
        "n_rules": n_rules,
        "n_edges": n_edges,
    }

def _load_mapping(force: bool = False) -> Dict[str, Any]:
    path = find_mapping_path()
    mtime = os.path.getmtime(path)
    with _CACHE_LOCK:
        if (not force and _CACHE.get("path") == path
                and _CACHE.get("mtime") == mtime and _CACHE.get("by_part")):
            return _CACHE
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        built = _build_mapping(doc)
        built["path"] = path
        built["mtime"] = mtime
        _CACHE.clear()
        _CACHE.update(built)
        print("%s 映射载入 %d 个码（%d 个 v2 标记 + %d 个旧 G1..G6），代替映射 %d 条 / %d 个柜级码；数据=%s"
              % (_LOG_PREFIX, _CACHE["n_codes"], _CACHE["n_markers"],
                 max(0, _CACHE["n_codes"] - _CACHE["n_markers"]),
                 _CACHE["n_edges"], _CACHE["n_rules"], path),
              file=sys.stdout, flush=True)
        return _CACHE

def reload() -> Dict[str, Any]:
    """强制重新读映射（数据刚更新、不想重启 UI 时用）。"""
    return _load_mapping(force=True)

def mapping_info() -> Dict[str, Any]:
    """给 UI/自检用：映射路径、码数、代替规则条数。"""
    m = _load_mapping()
    return {
        "path": m["path"],
        "n_codes": m["n_codes"],
        "n_markers": m["n_markers"],
        "n_legacy": max(0, m["n_codes"] - m["n_markers"]),
        "n_rules": m["n_rules"],
        "n_edges": m["n_edges"],
    }

def normalize_route(route: Any) -> Optional[str]:
    """I/1/一路/Ⅰ → 'I'；II/2/二路/Ⅱ → 'II'；其它/None → None。"""
    if route is None:
        return None
    s = str(route).strip().replace(" ", "").replace("　", "").upper()
    if not s:
        return None
    return _ROUTE_ALIASES.get(s)

def normalize_display(display_kind: Any) -> Optional[str]:
    """操显/领显（容许“屏/操作显示”等写法）；其它/None → None。"""
    if display_kind is None:
        return None
    s = str(display_kind).strip().replace(" ", "").replace("　", "")
    if not s:
        return None
    return _DISPLAY_ALIASES.get(s)

def _lookup(part: Any) -> Optional[Dict[str, Any]]:
    if part is None:
        return None
    key = str(part).strip().lower()
    if not key:
        return None
    try:
        return _load_mapping()["by_part"].get(key)
    except Exception as e:                                   
        _warn_once("映射不可用（按原样返回）: %s" % e)
        return None

def _route_table(entry: Dict[str, Any]) -> Dict[str, Any]:
    table = entry.get(_ROUTE_KEY)
    return table if isinstance(table, dict) else {}

def _display_table(entry: Dict[str, Any]) -> Dict[str, Any]:
    for key in _DISPLAY_KEYS:
        table = entry.get(key)
        if isinstance(table, dict) and table:
            return table
    return {}

def _canon(module_id: Any) -> str:
    """把数据里的内部模块 id 归一到**现场实际部件 id**（只做 _MODULE_CANON 里的同义归一）。"""
    s = str(module_id)
    return _MODULE_CANON.get(s.strip().lower(), s)

def _resolve_matched(part: Any, route: Any = None,
                     display_kind: Any = None) -> Tuple[Any, bool]:
    """内部用：返回 ``(target, matched)``。

    ``matched=True`` 表示**真的命中了代替映射**（即使归一后 target 与 part 同字，
    例如 z14 + II → z14）。UI 文案要根据它决定是否打「（代替码推断）」。
    """
    entry = _lookup(part)
    if not entry:
        return part, False
    r = normalize_route(route)
    if r is not None:
        target = _route_table(entry).get(r)
        if target:
            return _canon(target), True
    d = normalize_display(display_kind)
    if d is not None:
        target = _display_table(entry).get(d)
        if target:
            return _canon(target), True
    return part, False

def resolve(part: Any, route: Any = None, display_kind: Any = None) -> Any:
    """柜级码 + 路别/显示类型 → 内部模块 id。

    * z11 + I → z11-收发；z11 + II → z11-1
    * z12 + I → z12-电源；z12 + II → z12-GL
    * z14 + I → z14；z14 + II → z14（2026-10-25 现场：Z14-CLK 板当 Z14 使用）
    * z15 + 操显 → z15-显示电路；z15 + 领显 → z15-IF
    * 其它 / 缺参数 / 参数无效 ⇒ **原样返回 part**（不猜）

    注意：z15 只按 display_kind 推断；只给 route 不会猜显示类型。
    z14 两路的原始模块 id（z14-信处 / z14-CLK）按 ``_MODULE_CANON`` 归一到 `z14`。
    """
    return _resolve_matched(part, route=route, display_kind=display_kind)[0]

def _required_param(entry: Dict[str, Any]) -> str:
    if _route_table(entry):
        return "路别 I/II"
    if _display_table(entry):
        return "操显/领显"
    return "路别或显示类型"

def _matched_qualifier(entry: Dict[str, Any], route: Any, display_kind: Any) -> str:
    """只标注真正命中的那个参数，避免 UI 显示错路别/错显示类型。"""
    r = normalize_route(route)
    if r is not None and _route_table(entry).get(r):
        return "%s路" % r
    d = normalize_display(display_kind)
    if d is not None and _display_table(entry).get(d):
        return d
    return ""

def describe(part: Any, route: Any = None, display_kind: Any = None) -> str:
    """给 UI 直接显示的字符串。

    * 推断成功：``Z11（II路）→ z11-1（代替码推断）``
    * 推断成功但归一后同名：``Z14（II路）→ z14（代替码推断）``
    * 柜级码但缺参数：``Z11（未推断：需要路别 I/II）``
    * 本来就是内部模块/未登记码：``z11-1（直接标识）``

    ★ 只要发生了代替码推断，返回值必含「（代替码推断）」。
    """
    if part is None:
        return ""
    entry = _lookup(part)
    if not entry or (not _route_table(entry) and not _display_table(entry)):
        return "%s（直接标识）" % part
    label = str(entry.get("label") or part)
    target, matched = _resolve_matched(part, route=route, display_kind=display_kind)
    if matched:
        qualifier = _matched_qualifier(entry, route, display_kind)
        return "%s（%s）→ %s（代替码推断）" % (label, qualifier, target)
    return "%s（未推断：需要%s）" % (label, _required_param(entry))

_VERIFY_CASES = [
    ("z11", "I", None, "z11-收发"),
    ("z11", "II", None, "z11-1"),
    ("z12", "I", None, "z12-电源"),
    ("z12", "II", None, "z12-GL"),
    ("z14", "I", None, "z14"),
    ("z14", "II", None, "z14"),
    ("z15", None, "操显", "z15-显示电路"),
    ("z15", None, "领显", "z15-IF"),
]

def _verify() -> int:
    print("=== marker_resolve %s 自检 ===" % __version__)
    info = mapping_info()
    print("映射: %(path)s | 码数=%(n_codes)d (v2=%(n_markers)d, 旧G=%(n_legacy)d) | 代替映射=%(n_edges)d 条 / %(n_rules)d 个柜级码" % info)
    ok = 0
    for part, route, disp, want in _VERIFY_CASES:
        got = resolve(part, route=route, display_kind=disp)
        good = got == want
        ok += int(good)
        print("%s resolve(%r, route=%r, display_kind=%r) -> %r  (期望 %r)"
              % ("[OK]" if good else "[FAIL]", part, route, disp, got, want))
        print("     describe: %s" % describe(part, route=route, display_kind=disp))
    print("结果: %d/%d %s" % (ok, len(_VERIFY_CASES), "PASS" if ok == len(_VERIFY_CASES) else "FAIL"))
    return 0 if ok == len(_VERIFY_CASES) else 1

if __name__ == "__main__":
    if "--verify" in sys.argv[1:] or not sys.argv[1:]:
        sys.exit(_verify())
    print("用法: python3 -m soc_vision.marker_resolve --verify")
    sys.exit(2)
