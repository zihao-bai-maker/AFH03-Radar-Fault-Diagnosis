#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cause_explainer.py —— **现象 → 故障可能原因**解释器（机柜 → 分机 → 模块 + feature_id）。

用户要求（2026-10-18 原话）
--------------------------
> 「不光底噪还是不底噪，就是**我屏幕上的所有问题**，比如**有黄线**、**有底噪**都要写出来。
>  然后你判断出这个部位是否是故障之后，**按照我知识库的内容显示出这个故障可能的原因**。」

⇒ 本文件干两件事（**只读知识库，不碰板子、不联网、不改任何现有引擎**）：

1. ``screen_options.json`` 的**生成器 + 校验器**：把雷达显示器上可能出现的问题**穷举**成
   问答选项（31 项：知识库 17 项 / 只有 SOP 检查项 1 项 / 用户口述+工程常识 13 项），
   每项标注 ``in_kb`` / ``kb_basis`` / 命中行号 / 现有视觉能否判读。
2. ``explain()``：给**部位 + 该部位看到的异常现象**（屏幕选项 / 灯状态），返回
   **全部候选原因（按置信排序，不隐藏）** + ``feature_id`` + 证据来源 + 说不清的地方。

设计口径（与作者答复 / 用户决策一致）
--------------------------------------
* 「**先统计所有可能故障，再精确**」⇒ ``causes`` 永远列**全部**候选，``primary`` 只是第一名；
  多现象时用「**覆盖度**」做第二步收敛（能同时解释 2 个现象的模块排在只解释 1 个的前面）。
* 「**宁可不判**」⇒ 知识库外现象（如「有黄线」）**绝不编原因**：
  ``in_kb:false`` + ``unknown[]`` + ``is_fault:null``（若没有别的知识库内现象支撑）。
* 「**部位 ≠ 测量点**」⇒ ``part`` 只做**先验**（同部位候选 ×1.00，跨部位 ×0.82，见
  ``PART_FACTOR_OUT``），最终**所有**跨部位候选照样列出并注明。
* 置信不是概率，是**知识库匹配强度**：``base × 覆盖度 × 现象普遍性 × 部位先验 × 路别``
  + 可机读加分，每一项都写在 ``score_detail`` 里，可复核（公式见 ``README_cause_explainer.md`` §5）。

数据来源（全部只读）
--------------------
* ``../判据库_故障.csv`` 268 行真值：``cabinet/sub_unit/module/remark/step_name/
  phenomenon/field/abnormal_value/feature_id``（本文件的**唯一**故障归属依据）；
* ``../判据库_SOP.csv`` 166 项：``显示画面`` 类 22 项（正常态检查项，用来定义「正常/有底噪」）；
* ``criteria_overrides.json`` 的 ``z20`` / ``z5`` 收窄（**只读**，用于 ``in_part_scope`` 与
  ``override`` 说明，不会因此隐藏跨柜候选）；
* ``part_recognizer.py`` 的 ``PART_INFO`` / ``criteria_for()``（**只读调用**，导入失败时用本文件
  内的等价兜底实现，见 ``_local_criteria_for``）。

不改的东西（硬约束）
--------------------
``fault_grader.py`` / ``fusion.py`` / ``part_recognizer.py`` / ``vision_rules.py`` /
``qa_flow.py`` / ``ui_kiosk.py`` / 两个判据库 CSV —— 一个字节都不改 ✗。
若 ``qa_items_screen.json`` 已存在（另一 agent 在做），本文件**只读对齐**，绝不覆写。

命令行
------
::

    python cause_explainer.py --part z11 --values yellow_screen,no_noise --route I
    python cause_explainer.py --part z15 --values black_screen --json
    python cause_explainer.py --part z15 --values no --field "(image)(operator_display)_course_scan"
    python cause_explainer.py --write-options      # 生成/刷新 screen_options.json
    python cause_explainer.py --check-options      # 校验 screen_options.json 是否过期
    python cause_explainer.py --inventory          # 打印判据库 abnormal_value 全集
    python cause_explainer.py --crosswalk          # 只读核对 qa_items_screen.json 的选项对照
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

ENGINE_DIR = Path(__file__).resolve().parent
CRITERIA_DIR = ENGINE_DIR.parent
FAULT_CSV = CRITERIA_DIR / "判据库_故障.csv"
SOP_CSV = CRITERIA_DIR / "判据库_SOP.csv"
OVERRIDES_JSON = ENGINE_DIR / "criteria_overrides.json"
OPTIONS_JSON = ENGINE_DIR / "screen_options.json"

SCHEMA = "cause_explain/1.0"
OPTIONS_SCHEMA = "screen_options/1.0"
ENGINE_VERSION = "cause_explainer/1.0.0"

ISO_TZ = timezone(timedelta(hours=8))

MIN_FAULT_CONF = 0.60        
MIN_MARGIN = 0.10            
MAX_CAUSES = 20              
MAX_TEXT_CAUSES = 10         
CONF_CAP = 0.97              

W_COVER_BASE = 0.72          
W_COVER_SPAN = 0.28
PART_FACTOR_IN = 1.00        
PART_FACTOR_OUT = 0.82       
SPEC_BASE = 0.75             
SPEC_SPAN = 0.25             
ROUTE_FACTOR_OK = 1.00
ROUTE_FACTOR_MISMATCH = 0.78  
FIELD_BONUS = 0.02           
EVIDENCE_BONUS = 0.05        
EVIDENCE_BONUS_CAP = 0.10

NORMAL_ABNORMAL_VALUES = {"normal", "ok", "good", "correct", "done", "pass", "no_fault"}

NORMAL_OPTION_IDS = {"normal", "noise_present"}

PART_SCREEN_DISPLAY = {"z15": "屏幕", "z16": "指示屏"}

def now_iso() -> str:
    return datetime.now(ISO_TZ).isoformat(timespec="seconds")

def _clean(text: Any) -> str:
    """CSV 单元格清洗：换行 / 全角空格压成单空格。"""
    s = str(text or "").replace("\u3000", " ")
    return re.sub(r"\s+", " ", s).strip()

def _key(text: Any) -> str:
    """匹配用的归一化：去所有空白（判据库里的换行/空格位置不固定）。"""
    return re.sub(r"\s+", "", _clean(text))

def _clip(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(v)))

def _norm_paren(text: str) -> str:
    return (text or "").replace("（", "(").replace("）", ")")

FALLBACK_PART_INFO: Dict[str, Dict[str, Any]] = {
    "z4": {"name": "天线控制单元", "short": "天线控制", "level": "cabinet", "cabinet": "Z4（传动单元）"},
    "z5": {"name": "收发机柜", "short": "收发机柜", "level": "cabinet", "cabinet": "Z5（收发机柜）"},
    "z11": {"name": "收发分机", "short": "收发", "level": "cabinet", "cabinet": "Z5（收发机柜）"},
    "z12": {"name": "电源分机", "short": "电源", "level": "cabinet", "cabinet": "Z5（收发机柜）"},
    "z14": {"name": "信号处理分机", "short": "信处", "level": "cabinet", "cabinet": "Z6（操显机柜）"},
    "z15": {"name": "显示电路分机", "short": "显示电路", "level": "cabinet", "cabinet": "Z6（操显机柜）"},
    "z16": {"name": "指示分机", "short": "指示", "level": "cabinet", "cabinet": "Z6（操显机柜）"},
    "z18": {"name": "控制分机", "short": "控制", "level": "cabinet", "cabinet": "Z6（操显机柜）"},
    "z20": {"name": "控制台", "short": "控制台", "level": "cabinet", "cabinet": "Z20（控制台）"},
    "z31": {"name": "配电箱", "short": "配电箱", "level": "cabinet", "cabinet": "Z31(电源控制机柜）"},
    "z11-1": {"name": "频综", "short": "频综", "level": "module", "parent": "z11"},
    "z11-3": {"name": "固态功放", "short": "功放", "level": "module", "parent": "z11"},
    "z11-4": {"name": "接收前端", "short": "接收前端", "level": "module", "parent": "z11"},
    "z11-5": {"name": "近程增益", "short": "近程增益", "level": "module", "parent": "z11"},
    "z12-GL": {"name": "GL1/GL2/GL3 电源", "short": "GL电源", "level": "module", "parent": "z12"},
    "z14-CLK": {"name": "时钟板", "short": "时钟板", "level": "module", "parent": "z14"},
    "z15-IF": {"name": "接口板", "short": "接口板", "level": "module", "parent": "z15"},
    "z15-CPU": {"name": "CPU板", "short": "CPU板", "level": "module", "parent": "z15"},
}

_PR_CACHE: Dict[str, Any] = {"loaded": False, "module": None}
PART_INFO: Dict[str, Dict[str, Any]] = dict(FALLBACK_PART_INFO)

def _load_part_recognizer():
    """只读导入 part_recognizer（成功则复用它的 PART_INFO / criteria_for）。"""
    if _PR_CACHE["loaded"]:
        return _PR_CACHE["module"]
    _PR_CACHE["loaded"] = True
    try:  
        if str(ENGINE_DIR) not in sys.path:
            sys.path.insert(0, str(ENGINE_DIR))
        import part_recognizer as pr  

        info = getattr(pr, "PART_INFO", None)
        if isinstance(info, dict) and "z11" in info:
            PART_INFO.clear()
            PART_INFO.update(FALLBACK_PART_INFO)
            for k, v in info.items():
                base = dict(FALLBACK_PART_INFO.get(k, {}))
                base.update({kk: vv for kk, vv in v.items() if kk in ("name", "short", "level", "parent")})
                PART_INFO[k] = base
        _PR_CACHE["module"] = pr
    except Exception:
        _PR_CACHE["module"] = None
    return _PR_CACHE["module"]

def part_name(part: str) -> str:
    p = normalize_part(part)
    return str(PART_INFO.get(p, {}).get("name") or "")

def part_level(part: str) -> str:
    p = normalize_part(part)
    return str(PART_INFO.get(p, {}).get("level") or "")

def part_parent(part: str) -> str:
    p = normalize_part(part)
    return str(PART_INFO.get(p, {}).get("parent") or "")

def part_display(part: str) -> str:
    p = normalize_part(part)
    if not p:
        return "该部位"
    if p in PART_SCREEN_DISPLAY:
        return PART_SCREEN_DISPLAY[p]
    nm = part_name(p)
    if not nm:
        return f"该部位（{p.upper()}）"
    if part_level(p) == "module":
        return nm
    return f"{p.upper()}（{nm}）"

def normalize_part(part: Any) -> str:
    """``Z11（收发分机）`` / ``Z11-1`` / `` z11 `` → ``z11`` / ``z11-1``。"""
    s = _clean(part).lower().replace("（", "(").replace("）", ")")
    if not s:
        return ""
    m = re.match(r"^(z\d{1,2})(?:-(\d))?", s)
    if not m:
        return ""
    base = m.group(1)
    if m.group(2):
        cand = f"{base}-{m.group(2)}"
        if cand in PART_INFO:
            return cand
    return base

def _route_of(sub_unit: str) -> str:
    """从 ``Z11（收发分机） （I路）`` 里取 ``I``；取不到返回 ``""``。"""
    marks = re.findall(r"\((I{1,2})路?\)", _norm_paren(sub_unit))
    if not marks:
        return ""

    return marks[0]

def _short_code(text: str) -> str:
    m = re.match(r"^(Z\d{1,2})", _clean(text).upper())
    return m.group(1) if m else _clean(text)

_FAULTS: Dict[str, Any] = {"loaded": False, "rows": [], "path": "", "error": ""}

def load_fault_rows(csv_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """读 ``判据库_故障.csv``（268 行，行号 = 数据行 1-based，与 criteria_overrides 对齐）。"""
    path = Path(csv_path) if csv_path else FAULT_CSV
    if _FAULTS["loaded"] and str(path) == _FAULTS["path"]:
        return _FAULTS["rows"]
    rows: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            for i, r in enumerate(csv.DictReader(f), 1):
                rec = {
                    "row": i,
                    "cabinet": _clean(r.get("cabinet")),
                    "sub_unit": _clean(r.get("sub_unit")),
                    "module": _clean(r.get("module")),
                    "remark": _clean(r.get("remark")),
                    "step_name": _clean(r.get("step_name")),
                    "phenomenon": _clean(r.get("phenomenon")),
                    "field": _clean(r.get("field")),
                    "abnormal_value": _clean(r.get("abnormal_value")),
                    "feature_id": _clean(r.get("feature_id")),
                }
                rec["route"] = _route_of(rec["sub_unit"])
                rows.append(rec)
    except Exception as exc:  
        _FAULTS["error"] = f"读取判据库失败：{exc}"
    _FAULTS.update({"loaded": True, "rows": rows, "path": str(path)})
    return rows

def abnormal_value_inventory(rows: Optional[Sequence[Mapping[str, Any]]] = None) -> List[Dict[str, Any]]:
    """判据库 ``abnormal_value`` 全集（每值行数 + 涉及 field + 被哪个屏幕选项覆盖）。"""
    rows = list(rows if rows is not None else load_fault_rows())
    inv: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        v = r["abnormal_value"]
        if not v:
            continue
        d = inv.setdefault(v, {"value": v, "rows": 0, "row_numbers": [], "fields": {}, "phenomena": []})
        d["rows"] += 1
        d["row_numbers"].append(r["row"])
        f = r["field"]
        if f:
            d["fields"][f] = d["fields"].get(f, 0) + 1
        if r["phenomenon"] and r["phenomenon"] not in d["phenomena"]:
            d["phenomena"].append(r["phenomenon"])
    covered = _option_ids_by_abnormal_value()
    out = []
    for v, d in sorted(inv.items(), key=lambda kv: (-kv[1]["rows"], kv[0])):
        out.append({
            "value": v,
            "rows": d["rows"],
            "row_numbers": d["row_numbers"],
            "fields": [{"field": k, "rows": n} for k, n in sorted(d["fields"].items(), key=lambda kv: -kv[1])],
            "phenomena_sample": d["phenomena"][:4],
            "screen_options": covered.get(v, []),
            "is_screen": bool(covered.get(v)),
            "meaning": ABNORMAL_VALUE_MEANING.get(v, ""),
        })
    return out

ABNORMAL_VALUE_MEANING = {
    "off": "灯灭 / 无输出",
    "on": "灯亮（**仅对 2A 保险丝报警灯是异常**；普通指示灯 on 是正常）",
    "no": "无（波形/回波）",
    "weak": "弱（回波/幅度偏小）",
    "no_noise": "无噪声 / 无底噪",
    "yellow_screen": "黄屏",
    "black_screen": "黑屏",
    "abnormal": "表头/数值异常（0.00 或离谱值）",
    "no_move": "机构不动作 / 不随动",
    "not_done": "按键/切换未完成",
    "no_sound": "无吸合声",
    "under_voltage": "欠压",
    "start_fail": "启动失败",
    "error": "方向/读数错误",
    "angle_limit": "亮线暗带处于极限或反向",
    "led_count_less_than_6_on": "板件亮灯数不足 6",
    "": "（空：该行只有现象文本，没有可机读的异常值）",
}

def load_sop_items(csv_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    path = Path(csv_path) if csv_path else SOP_CSV
    out: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                out.append({k: _clean(v) for k, v in r.items()})
    except Exception:
        pass
    return out

def load_overrides(path: Optional[Path] = None) -> Dict[str, Any]:
    p = Path(path) if path else OVERRIDES_JSON
    try:
        with p.open("r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}

MODULE_MATCH_KEYS = {
    "z11-1": ["Z11-1", "频综"],
    "z11-3": ["Z11-3", "固态功放"],
    "z11-4": ["Z11-4", "接收前端"],
    "z11-5": ["Z11-5", "近程增益"],
    "z12-GL": ["GL1", "GL2", "GL3"],
    "z14-CLK": ["Z14-1", "时钟"],
    "z15-IF": ["Z15-IF", "接口板"],
    "z15-CPU": ["Z15-CPU", "CPU板"],
}

def _local_criteria_for(part: str, route: str = "") -> List[Dict[str, Any]]:
    """与 ``part_recognizer.criteria_for`` 完全等价的兜底实现（只读 CSV）。"""
    p = normalize_part(part)
    if p not in PART_INFO:
        return []
    is_module = PART_INFO[p].get("level") == "module"
    sub_keys = {"z4": [], "z5": [], "z31": ["配电箱"], "z16": ["指示分机", "Z16"],
                "z20": ["Z20"]}.get(p, [p.upper()])
    cab_keys = {"z4": ["Z4"], "z5": ["Z5"], "z31": ["Z31"]}.get(p, [])
    mod_keys = MODULE_MATCH_KEYS.get(p, [p.upper()]) if is_module else []
    out = []
    for r in load_fault_rows():
        sub = r["sub_unit"].upper().replace(" ", "")
        cab = r["cabinet"].upper().replace(" ", "")
        mod = r["module"].upper().replace(" ", "")
        scope = ""
        if mod_keys and any(k.upper().replace(" ", "") in mod for k in mod_keys):
            scope = "module"
        elif sub_keys and any(k.upper().replace(" ", "") in sub for k in sub_keys):
            scope = "sub_unit"
        elif cab_keys and any(k.upper().replace(" ", "") in cab for k in cab_keys):
            scope = "cabinet"
        if not scope:
            continue
        rec = dict(r)
        rec["match_scope"] = scope
        out.append(rec)
    return _filter_route(out, route)

def _filter_route(rows: Sequence[Dict[str, Any]], route: str) -> List[Dict[str, Any]]:
    if not route:
        return list(rows)
    rt = str(route).strip().upper()
    keep = []
    for r in rows:
        marks = re.findall(r"\((I{1,2})\)", _norm_paren(r["sub_unit"]).upper().replace(" ", ""))
        if not marks or rt in marks:
            keep.append(r)
    return keep

def criteria_for(part: str, route: str = "") -> List[Dict[str, Any]]:
    """取该部位的判据行（**只读**；优先复用 part_recognizer.criteria_for）。"""
    pr = _load_part_recognizer()
    p = normalize_part(part)
    if pr is not None and hasattr(pr, "criteria_for"):
        try:
            got = pr.criteria_for(p, route)
            if got:
                out = []
                for r in got:
                    rec = {k: _clean(v) for k, v in r.items() if isinstance(v, str)}

                    rec["row"] = _lookup_row_number(rec)
                    rec["route"] = _route_of(rec.get("sub_unit", ""))
                    out.append(rec)
                return out
        except Exception:
            pass
    return _local_criteria_for(p, route)

def _lookup_row_number(rec: Mapping[str, Any]) -> int:
    for r in load_fault_rows():
        if (r["cabinet"] == rec.get("cabinet") and r["sub_unit"] == rec.get("sub_unit")
                and r["module"] == rec.get("module") and r["step_name"] == rec.get("step_name")
                and r["phenomenon"] == rec.get("phenomenon") and r["field"] == _clean(rec.get("field"))):
            return int(r["row"])
    return 0

def _apply_narrow_rule(rule: Mapping[str, Any], part: str, rows: List[Dict[str, Any]],
                       ctx: Mapping[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """按 ``narrow_by`` 的一条规则过滤行；``when`` 不满足返回 None（表示不适用）。"""
    when = rule.get("when") or {}
    if "recognized_part" in when:
        want = [str(x).lower() for x in (when.get("recognized_part") or [])]
        if normalize_part(part) not in want:
            return None
    if "modality" in when:
        if str(ctx.get("modality") or "") != str(when["modality"]):
            return None
    if "text_contains_any" in when:
        text = _key(ctx.get("text") or "")
        if not any(_key(k) in text for k in when["text_contains_any"]):
            return None
    if "sop_flow_in" in when:
        flows = [str(x) for x in (when.get("sop_flow_in") or [])]
        if str(ctx.get("flow_no") or "") not in flows:
            return None
    match = rule.get("match") or {}
    out = []
    for r in rows:
        ok = True
        for k, v in match.items():
            if k == "sub_unit_contains":
                if not any(_key(x) in _key(r["sub_unit"]) for x in v):
                    ok = False
            elif k == "module_contains":
                if not any(_key(x) in _key(r["module"]) for x in v):
                    ok = False
            elif k == "step_name_contains_any":
                if not any(_key(x) in _key(r["step_name"]) for x in v):
                    ok = False
            elif k == "field_prefix_any":
                if not any(_key(x) in _key(r["field"]) for x in v):
                    ok = False
            elif k == "text_contains_all":
                if not all(_key(x) in _key(r["phenomenon"] + r["step_name"] + r["module"]) for x in v):
                    ok = False
            elif k == "abnormal_value_in":
                if r["abnormal_value"] not in v:
                    ok = False
            elif k == "phenomenon_contains_any":
                if not any(_key(x) in _key(r["phenomenon"]) for x in v):
                    ok = False
        if ok:
            out.append(r)
    return out

def part_scope(part: str, ctx: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """该部位的判据行 + ``criteria_overrides.json`` 收窄（z20/z5），只读。

    返回 ``{"rows", "part", "level", "source", "override", "need_narrow", "notes"}``。
    ``rows`` 用来判断「这条候选是不是这个部位自己的判据行」（``in_part_scope``），
    **不会**因为收窄而丢掉跨部位的候选。
    """
    ctx = dict(ctx or {})
    p = normalize_part(part)
    info = {"part": p, "level": part_level(p), "rows": [], "override": {}, "need_narrow": False,
            "symptom_only": False,
            "notes": [], "source": "part_recognizer.criteria_for" if _load_part_recognizer() else "local"}
    if not p or p not in PART_INFO:
        info["notes"].append(f"部位 {part!r} 不在 18 部位清单内：部位先验不生效，只按现象枚举")
        return info
    rows = criteria_for(p, route="")  
    before = len(rows)
    ov = load_overrides().get(p)
    if ov:
        allowed = set(int(x) for x in (ov.get("allow_rows") or []))
        if allowed:
            if rows:
                rows = [r for r in rows if r["row"] in allowed]
                info["override"] = {"part": p, "allow_rows": len(allowed), "before": before,
                                    "after": len(rows),
                                    "rule": "allow_rows 白名单（只读 criteria_overrides.json）"}
            else:

                
                all_rows = load_fault_rows()
                rows = [r for r in all_rows if r["row"] in allowed]
                info["symptom_only"] = True
                info["override"] = {"part": p, "allow_rows": len(allowed), "before": 0,
                                    "after": len(rows), "rule": "allow_rows 症状白名单（不是故障归属）"}
                info["notes"].append(
                    f"{p.upper()} 在故障真值表里没有自己的行：{len(rows)} 行是**症状行**"
                    f"（owner_policy=do_not_treat_as_owner）⇒ 候选故障归属仍是 Z11/Z12/Z18 等原部位，"
                    f"不能算 {p.upper()} 自身故障")
        applied = None
        for rule in (ov.get("narrow_by") or []):
            got = _apply_narrow_rule(rule, p, rows, ctx)
            if got is None:
                continue
            if got:
                applied = (rule, got)
                break
        if applied:
            rule, got = applied
            rows = got
            info["override"].update({"rule_id": rule.get("id"), "narrow_before": before,
                                     "narrow_after": len(rows),
                                     "purpose": rule.get("purpose") or ""})
        elif not info["symptom_only"]:
            need = bool((ov.get("default") or {}).get("need_narrow")) or p in ("z5", "z20")
            info["need_narrow"] = need
            if need:
                info["notes"].append(
                    f"只识别到 {p.upper()}，没有分机/模块/文字线索："
                    f"{ov.get('default', {}).get('why') or '不能假装已定位'}")
    info["rows"] = rows
    return info

OPTION_CATALOG: List[Dict[str, Any]] = [

    {
        "id": "normal", "value": "normal", "label": "正常（有扫描、有底噪、有回波）",
        "label_plain": "正常", "category": "正常", "order": 1,
        "in_kb": True, "kb_basis": "sop_check_item", "sop_keywords": ["显示画面", "画面扫描正常", "噪声有", "回波正常"],
        "vision_hintable": True, "vision_supported": True, "vision_state": "ok",
        "vision_note": "vision_rules.screen_state 输出 ok（有扫描线 + 绿色内容 + 有底噪）",
        "aliases": ["正常", "ok", "无异常", "没有异常", "normal"],
        "note": "正常态也必须作为选项：只报「没有异常证据」≠ 正常（见 schema_evidence.md §7）",
    },
    {
        "id": "black_screen", "value": "black_screen", "label": "黑屏（整屏全黑，无光栅/无字符）",
        "label_plain": "黑屏", "category": "画面整体", "order": 2,
        "in_kb": True, "kb_basis": "abnormal_value",
        "kb_match": {"abnormal_values": ["black_screen"],
                     "field_prefixes": ["(image)(operator_display)_display_screen"],
                     "phenomenon_exact": ["黑屏"],
                     "phenomenon_contains": ["黑屏"]},
        "sop_keywords": ["显示画面"],
        "vision_hintable": True, "vision_supported": True, "vision_state": "black_screen",
        "vision_note": "vision_rules.screen_state 输出 black_screen（实心屏 + 亮度低）",
        "aliases": ["黑屏", "全黑", "不亮屏", "black_screen", "black"],
        "note": "判据库有 3 行黑屏：指示分机保险丝、Z15 显示保险丝（唯一带 feature_id 的行）、Z15 电源模块无 220V",
    },
    {
        "id": "yellow_screen", "value": "yellow_screen", "label": "黄屏（整屏发黄/土黄）",
        "label_plain": "黄屏", "category": "画面整体", "order": 3,
        "in_kb": True, "kb_basis": "abnormal_value",
        "kb_match": {"abnormal_values": ["yellow_screen"],
                     "field_prefixes": ["(image)(operator_display)_display_screen"],
                     "phenomenon_exact": ["（下滑）（航向）黄屏", "（航向）黄屏"],
                     "phenomenon_contains": ["黄屏"]},
        "sop_keywords": ["显示画面"],
        "vision_hintable": True, "vision_supported": True, "vision_state": "yellow_screen",
        "vision_note": "vision_rules.screen_state 输出 yellow_screen（实心屏 + 黄色占比高）",
        "aliases": ["黄屏", "发黄", "土黄", "yellow_screen", "yellow"],
        "note": "现象文本含「黄屏」共 10 行，但只有 5 行填了 abnormal_value ⇒ 另 5 行只能靠现象文本匹配（强度 0.80/0.88）",
    },
    {
        "id": "garbled", "value": "garbled", "label": "花屏（画面撕裂/碎块/杂色）",
        "label_plain": "花屏", "category": "画面整体", "order": 4,
        "in_kb": True, "kb_basis": "phenomenon",
        "kb_match": {"phenomenon_exact": ["花屏"], "phenomenon_contains": ["花屏"]},
        "sop_keywords": ["显示画面"],
        "vision_hintable": True, "vision_supported": True, "vision_state": "garbled",
        "vision_note": "vision_rules.screen_state 输出 garbled（高频能量 + 边缘密度双阈值）",
        "aliases": ["花屏", "碎屏", "画面撕裂", "garbled"],
        "note": "判据库**没有** garbled 这个 abnormal_value（只有现象文本「花屏」）；"
                "fusion.py 把 garbled 当扩展枚举接受 ⇒ 值为 garbled 也能判异常",
    },
    {
        "id": "screen_freeze", "value": "freeze", "label": "画面死机/冻结（卡死、不刷新）",
        "label_plain": "画面冻结", "category": "画面整体", "order": 5,
        "in_kb": True, "kb_basis": "phenomenon", "kb_quality": "merged",
        "kb_match": {"phenomenon_exact": ["花屏或显示画面死机"], "phenomenon_contains": ["死机"]},
        "sop_keywords": ["显示画面"],
        "vision_hintable": True, "vision_supported": False, "vision_state": None,
        "vision_note": "现有 vision_rules 是**单帧**判读，判不了「不刷新」；需连续 2~3 帧比对（本次不改 ✗）",
        "aliases": ["死机", "冻结", "卡死", "不刷新", "freeze", "画面不动"],
        "note": "知识库把「死机」与「花屏」写在同一现象里（Z15 图形图像板），无法单独区分 ⇒ 与花屏共用候选",
    },
    {
        "id": "no_echo", "value": "no_echo", "label": "无回波（有底噪但无目标回波）",
        "label_plain": "无回波", "category": "回波", "order": 6,
        "in_kb": True, "kb_basis": "abnormal_value",
        "kb_match": {"abnormal_values": ["no"],
                     "field_prefixes": ["(image)(operator_display)_course_echo", "(image)(operator_display)_glide_echo"],
                     "phenomenon_contains": ["无回波", "回波(无"]},
        "sop_keywords": ["回波正常"],
        "vision_hintable": True, "vision_supported": True, "vision_state": "no_echo",
        "vision_note": "vision_rules 输出 no_echo（亮像素 ≤0.12% 且有底噪）；**注意** fusion.py 的全局枚举里没有 "
                       "no_echo（只有 no），集成时需把 no_echo 归一为 no",
        "aliases": ["无回波", "没有回波", "回波没有", "no", "no_echo"],
        "note": "判据库的 abnormal_value 是 ``no``（16 行，航向/下滑回波各 8 行），不是 no_echo",
    },
    {
        "id": "weak_echo", "value": "weak", "label": "回波弱（幅度明显偏小）",
        "label_plain": "弱", "category": "回波", "order": 7,
        "in_kb": True, "kb_basis": "abnormal_value",
        "kb_match": {"abnormal_values": ["weak"],
                     "field_prefixes": ["(image)(operator_display)_course_echo", "(image)(operator_display)_glide_echo"]},
        "sop_keywords": ["回波正常"],
        "vision_hintable": True, "vision_supported": False, "vision_state": None,
        "vision_note": "vision_rules 只输出 no_echo，没有 weak 档；弱回波目前只能人工/问答确认",
        "aliases": ["弱", "回波弱", "weak", "幅度小", "信号弱"],
        "note": "判据库只有 2 行 weak，且都在 Z11-5 近程增益控制（无供电）",
    },
    {
        "id": "no_scan", "value": "no_scan", "label": "不扫描（扫描线不动/画面静止）",
        "label_plain": "不扫描", "category": "扫描", "order": 8,
        "in_kb": True, "kb_basis": "phenomenon",
        "kb_match": {"phenomenon_exact": ["（航向）_不扫描", "（下滑）_不扫描", "自检30，显示画面不扫描",
                                          "（操显）航向无扫描", "（操显）下滑无扫描"],
                     "phenomenon_contains": ["不扫描", "无扫描"]},
        "sop_keywords": ["画面扫描正常"],
        "vision_hintable": True, "vision_supported": True, "vision_state": "no_scan",
        "vision_note": "vision_rules 输出 no_scan（扫描线不动/纹理与帧差异小）；**注意** fusion.py 的全局枚举里"
                       "没有 no_scan ⇒ 会落 undetermined，集成时需补映射",
        "aliases": ["不扫描", "扫描不动", "不走", "画面静止", "no_scan", "无扫描"],
        "note": "判据库**没有** no_scan 这个 abnormal_value（只有现象文本），候选全部靠现象文本匹配",
    },
    {
        "id": "no_noise", "value": "no_noise", "label": "无底噪/无噪声（画面异常干净）",
        "label_plain": "无底噪", "category": "底噪", "order": 9,
        "in_kb": True, "kb_basis": "abnormal_value",
        "kb_match": {"abnormal_values": ["no_noise"],
                     "field_prefixes": ["(image)(operator_display)_course_noise", "(image)(operator_display)_glide_noise"],
                     "phenomenon_contains": ["无噪声"]},
        "sop_keywords": ["噪声有"],
        "vision_hintable": True, "vision_supported": True, "vision_state": "no_noise",
        "vision_note": "vision_rules 输出 no_noise（噪声场均匀度过高/亮像素极少）",
        "aliases": ["无底噪", "无噪声", "没有底噪", "底噪没有", "画面太干净", "no_noise"],
        "note": "判据库 6 行 no_noise（Z14-10 中频放大器 / Z14-3 数字脉压板 / Z19-FU1 保险丝）",
    },
    {
        "id": "noise_present", "value": "noise_present", "label": "有底噪（正常态）",
        "label_plain": "有底噪", "category": "底噪", "order": 10,
        "in_kb": True, "kb_basis": "sop_check_item", "sop_keywords": ["噪声有"],
        "vision_hintable": True, "vision_supported": True, "vision_state": "ok",
        "vision_note": "vision_rules 的噪声项输出 ok 即「有底噪」",
        "aliases": ["有底噪", "有噪声", "底噪正常", "noise_present"],
        "note": "这是**正常**态（SOP flow 19「（操显）航向噪声有」）；单给「有底噪」不能判故障",
    },
    {
        "id": "selftest_30", "value": "自检30", "label": "屏上出现「自检30」字样",
        "label_plain": "自检30", "category": "自检码", "order": 11,
        "in_kb": True, "kb_basis": "phenomenon",
        "kb_match": {"phenomenon_exact": ["自检30，显示画面不扫描"], "phenomenon_contains": ["自检30"]},
        "sop_keywords": [],
        "vision_hintable": True, "vision_supported": False, "vision_state": None,
        "vision_note": "需要 OCR 读屏上的数字；作者说现场没有样本 ⇒ 出现才报、不做强判",
        "aliases": ["自检30", "自检 30", "30"],
        "note": "作者口径：无现场样本，**不做强判**；只在屏上出现时上报（→ Z15 扫描变换板）",
    },
    {
        "id": "selftest_40", "value": "自检40", "label": "屏上出现「自检40」字样",
        "label_plain": "自检40", "category": "自检码", "order": 12,
        "in_kb": True, "kb_basis": "phenomenon",
        "kb_match": {"phenomenon_exact": ["自检40，自动录取与跟踪功能失效"], "phenomenon_contains": ["自检40"]},
        "sop_keywords": [],
        "vision_hintable": True, "vision_supported": False, "vision_state": None,
        "vision_note": "同上：需要 OCR，出现才报",
        "aliases": ["自检40", "自检 40", "40"],
        "note": "作者口径同上（→ Z15 检测获取板）",
    },
    {
        "id": "meter_zero", "value": "abnormal", "label": "表头/数值显示 0.00 或明显异常",
        "label_plain": "数值异常", "category": "表头", "order": 13,
        "in_kb": True, "kb_basis": "abnormal_value",
        "kb_match": {"abnormal_values": ["abnormal"], "field_prefixes": ["(image)z12_"],
                     "phenomenon_contains": ["0.00"]},
        "sop_keywords": ["微表区"],
        "vision_hintable": True, "vision_supported": False, "vision_state": None,
        "vision_note": "微表区读数复用 soc_vision.screen_read_v2，缺参考模板 ⇒ 未判定（当前不可用）",
        "aliases": ["0.00", "数值异常", "表头异常", "显示0", "abnormal"],
        "note": "判据库 3 行 abnormal 全是 Z12 内部电源（11V / ±15V / +5V-5V）显示 0.00",
    },
    {
        "id": "meter_dark", "value": "meter_dark", "label": "数码面板表不亮（表头无显示）",
        "label_plain": "表头不亮", "category": "表头", "order": 14,
        "in_kb": True, "kb_basis": "phenomenon",
        "kb_match": {"phenomenon_exact": ["数字面板表不亮"], "phenomenon_contains": ["数字面板表不亮"]},
        "sop_keywords": ["微表区"],
        "vision_hintable": True, "vision_supported": False, "vision_state": None,
        "vision_note": "同上：微表区需要模板读数，当前判不了「亮没亮」以外的东西",
        "aliases": ["面板表不亮", "表头不亮", "数码管不亮", "meter_dark"],
        "note": "与「表头数值异常」同一行（Z12 +5V/-5V，abnormal_value=abnormal），两者可能同时命中",
    },

    {
        "id": "meter_direction", "value": "error", "label": "天线方向显示错误（微表区数值/指针不对）",
        "label_plain": "方向显示错误", "category": "表头", "order": 15,
        "in_kb": True, "kb_basis": "abnormal_value",
        "kb_match": {"abnormal_values": ["error"], "phenomenon_contains": ["天线方向"]},
        "sop_keywords": ["微表区"],
        "vision_hintable": True, "vision_supported": False, "vision_state": None,
        "vision_note": "微表区读数复用 soc_vision.screen_read_v2，缺参考模板 ⇒ 当前未判定",
        "aliases": ["天线方向", "方向错误", "方向不对", "方向显示错误", "meter_direction", "error"],
        "note": "判据库 3 行「天线方向：错误」（Z18-1 电源 / 纽子开关SA1 / 面板保险丝FU10），"
                "只有 1 行带 field+feature_id",
    },
    {
        "id": "guidance_stuck", "value": "guidance_stuck", "label": "指向亮线/暗带不随动、反向或处于极限",
        "label_plain": "亮线暗带异常", "category": "画面内容", "order": 16,
        "in_kb": True, "kb_basis": "phenomenon",
        "kb_match": {"abnormal_values": ["angle_limit"],
                     "phenomenon_contains": ["不随动", "反向随动", "角度极限"]},
        "sop_keywords": ["指向亮线与暗带"],
        "vision_hintable": False, "vision_supported": False, "vision_state": None,
        "vision_note": "随动性是**动态**指标（亮线要跟着天线角度走），单帧判不了；SOP 也标「可能需要视频」",
        "aliases": ["不随动", "亮线暗带", "亮线与暗带", "反向随动", "角度极限", "随动异常", "guidance_stuck"],
        "note": "SOP 有「航向/下滑指向亮线与暗带正常随动」（显示画面类，可能需要视频）；"
                "故障行覆盖 Z31 相序错误、Z18 电源/继电器、Z19 电源/保险丝、Z4 极限电位器",
    },

    {
        "id": "echo_partial", "value": "echo_partial", "label": "近距/中距回波丢失（远距有回波）",
        "label_plain": "部分距离无回波", "category": "回波", "order": 17,
        "in_kb": True, "kb_basis": "phenomenon",
        "kb_match": {"phenomenon_contains": ["近距（无）", "中距（无）"]},
        "sop_keywords": ["回波正常"],
        "vision_hintable": True, "vision_supported": False, "vision_state": None,
        "vision_note": "要按距离分档统计亮像素；现有 vision_rules 只做整屏「有/无」，分不了档",
        "aliases": ["近距无回波", "中距无回波", "部分距离无回波", "远距有回波", "echo_partial"],
        "note": "判据库 6 行：Z14 时钟板 DIP 开关 0110/0100/0010 会让近距或中距回波丢失（远距仍正常）",
    },

    {
        "id": "no_guidance_line", "value": "no_guidance_line", "label": "理想线/纠偏线缺失或不连续",
        "label_plain": "理想线异常", "category": "画面内容", "order": 15,
        "in_kb": False, "in_sop": True, "kb_basis": "sop_check_item",
        "sop_keywords": ["理想下滑线及纠偏线", "理想航向线及纠偏线"],
        "vision_hintable": True, "vision_supported": False, "vision_state": None,
        "vision_note": "需要线检测/语义分割，现有 vision_rules 未覆盖（本次不改 ✗）",
        "aliases": ["理想线", "纠偏线", "十字线", "引导线", "no_guidance_line"],
        "note": "SOP 有 4 个检查项，但**故障真值表没有对应行** ⇒ 只能报现象，给不出机柜/分机/模块原因",
    },

    {
        "id": "yellow_line", "value": "yellow_line", "label": "有黄线/黄色干扰线",
        "label_plain": "有黄线", "category": "干扰", "order": 16,
        "in_kb": False, "kb_basis": "none", "user_dictated": True, "author_confirm": True,
        "vision_hintable": True, "vision_supported": False, "vision_state": None,
        "vision_note": "可用颜色阈值 + 长直线检测（Hough）实现；现有 vision_rules 没有黄线规则（本次不改 ✗）",
        "aliases": ["有黄线", "黄线", "黄色干扰线", "干扰线", "黄色线", "yellow_line"],
        "note": "**用户 2026-10-18 原话点名的现象**，但判据库/故障源表里都**没有**「黄线」记录 "
                "（全仓检索只有示波器测试图里出现过黄线）⇒ in_kb:false，explain() 会返回「无知识库依据」",
    },
    {
        "id": "flicker", "value": "flicker", "label": "闪屏/闪烁（亮度或画面整体抖动）",
        "label_plain": "闪屏", "category": "干扰", "order": 17,
        "in_kb": False, "kb_basis": "none", "user_dictated": True, "author_confirm": True,
        "vision_hintable": True, "vision_supported": False, "vision_state": None,
        "vision_note": "需要连续多帧亮度序列（≥1 s）；单帧判不了",
        "aliases": ["闪屏", "闪烁", "屏闪", "flicker"],
        "note": "知识库无记录：可能是电源纹波/行场同步/接触不良，**均属推断，不能作为判据**",
    },
    {
        "id": "too_bright", "value": "too_bright", "label": "画面过亮/发白（对比度丢失）",
        "label_plain": "过亮", "category": "亮度", "order": 18,
        "in_kb": False, "kb_basis": "none", "user_dictated": True, "author_confirm": True,
        "vision_hintable": True, "vision_supported": False, "vision_state": None,
        "vision_note": "需要亮度标定（参照正常样本）；现有阈值只判「黑/黄/花」，不判过亮",
        "aliases": ["过亮", "太亮", "发白", "白屏", "too_bright"],
        "note": "知识库无记录（亮度属连续量，判据库只记二值/枚举现象）",
    },
    {
        "id": "too_dim", "value": "too_dim", "label": "画面过暗（能看见但很暗）",
        "label_plain": "过暗", "category": "亮度", "order": 19,
        "in_kb": False, "kb_basis": "none", "user_dictated": True, "author_confirm": True,
        "vision_hintable": True, "vision_supported": False, "vision_state": None,
        "vision_note": "同「过亮」，需基准样本；与 black_screen 的边界要现场标定",
        "aliases": ["过暗", "太暗", "偏暗", "too_dim"],
        "note": "知识库无记录；注意与黑屏区分（能否看见字符/刻度）",
    },
    {
        "id": "brightness_uneven", "value": "brightness_uneven", "label": "亮度不均/暗角/局部发暗",
        "label_plain": "亮度不均", "category": "亮度", "order": 20,
        "in_kb": False, "kb_basis": "none", "user_dictated": True, "author_confirm": True,
        "vision_hintable": True, "vision_supported": False, "vision_state": None,
        "vision_note": "可用分块亮度方差；现有规则没有该阈值",
        "aliases": ["亮度不均", "暗角", "局部发暗", "uniform", "brightness_uneven"],
        "note": "知识库无记录；CRT 老化/高压不足都可能，属推断",
    },
    {
        "id": "missing_rows", "value": "missing_rows", "label": "缺行/缺列（横线或竖线缺失）",
        "label_plain": "缺行缺列", "category": "扫描", "order": 21,
        "in_kb": False, "kb_basis": "none", "user_dictated": True, "author_confirm": True,
        "vision_hintable": True, "vision_supported": False, "vision_state": None,
        "vision_note": "可用网格线投影/Hough 判；现有 vision_rules 没有「缺行」规则",
        "aliases": ["缺行", "缺列", "横线缺失", "竖线缺失", "断线", "missing_rows"],
        "note": "知识库无记录（判据库只有「不扫描」这一粒度，没有「缺行」）",
    },
    {
        "id": "image_shift", "value": "image_shift", "label": "图像偏移/跳动（画面位置不稳）",
        "label_plain": "图像偏移", "category": "同步", "order": 22,
        "in_kb": False, "kb_basis": "none", "user_dictated": True, "author_confirm": True,
        "vision_hintable": True, "vision_supported": False, "vision_state": None,
        "vision_note": "需要帧间配准/相位相关；单帧判不了",
        "aliases": ["图像偏移", "偏移", "跳动", "抖动", "image_shift"],
        "note": "知识库无记录；同步/扫描电路问题属推断",
    },
    {
        "id": "snow_excess", "value": "snow_excess", "label": "雪花噪点过多（噪声过大）",
        "label_plain": "噪点过多", "category": "底噪", "order": 23,
        "in_kb": False, "kb_basis": "none", "user_dictated": True, "author_confirm": True,
        "vision_hintable": True, "vision_supported": False, "vision_state": None,
        "vision_note": "与 no_noise 同一组特征，但「过多」缺标定基线（判据库只记「无噪声」）",
        "aliases": ["雪花", "噪点过多", "噪声过大", "底噪过大", "snow_excess"],
        "note": "⚠️ 知识库**只记录「无噪声」**，没有「噪声过大」；不能把无噪声的候选倒过来用",
    },
    {
        "id": "char_garbled", "value": "char_garbled", "label": "字符乱码/字符叠加异常",
        "label_plain": "字符乱码", "category": "字符", "order": 24,
        "in_kb": False, "kb_basis": "none", "user_dictated": True, "author_confirm": True,
        "vision_hintable": True, "vision_supported": False, "vision_state": None,
        "vision_note": "需要字符识别（RapidOCR）复核；现有规则没有字符正确性判据",
        "aliases": ["乱码", "字符乱码", "字符异常", "字重叠", "char_garbled"],
        "note": "知识库无记录；「花屏」是图像层的，不等于字符乱码 ⇒ 不要把 garbled 的候选直接套用",
    },
    {
        "id": "color_cast", "value": "color_cast", "label": "偏色（整屏发绿/发蓝/发红）",
        "label_plain": "偏色", "category": "颜色", "order": 25,
        "in_kb": False, "kb_basis": "none", "user_dictated": True, "author_confirm": True,
        "vision_hintable": True, "vision_supported": False, "vision_state": None,
        "vision_note": "整屏色相统计可判；现有规则只区分黑/黄/绿内容",
        "aliases": ["偏色", "发绿", "发蓝", "发红", "颜色不对", "color_cast"],
        "note": "知识库无记录（黄屏是唯一记录在案的颜色类故障）",
    },
    {
        "id": "black_spot", "value": "black_spot", "label": "黑斑/坏点/污渍",
        "label_plain": "黑斑", "category": "屏体", "order": 26,
        "in_kb": False, "kb_basis": "none", "user_dictated": True, "author_confirm": True,
        "vision_hintable": True, "vision_supported": False, "vision_state": None,
        "vision_note": "可用局部暗区检测；现有规则没有该判据",
        "aliases": ["黑斑", "坏点", "污渍", "亮点", "black_spot"],
        "note": "知识库无记录；多属屏体/光路问题（推断）",
    },
    {
        "id": "ghosting", "value": "ghosting", "label": "重影/拖尾",
        "label_plain": "重影", "category": "画面整体", "order": 27,
        "in_kb": False, "kb_basis": "none", "user_dictated": True, "author_confirm": True,
        "vision_hintable": True, "vision_supported": False, "vision_state": None,
        "vision_note": "需要边缘双峰/帧间残留分析；单帧不可靠",
        "aliases": ["重影", "拖尾", "残影", "ghosting"],
        "note": "知识库无记录；视频带宽/匹配问题属推断",
    },
    {
        "id": "interference", "value": "interference", "label": "横纹/条纹干扰（周期性亮暗带）",
        "label_plain": "条纹干扰", "category": "干扰", "order": 28,
        "in_kb": False, "kb_basis": "none", "user_dictated": True, "author_confirm": True,
        "vision_hintable": True, "vision_supported": False, "vision_state": None,
        "vision_note": "可用频域峰值检测；现有 vision_rules 没有该规则",
        "aliases": ["横纹", "条纹", "干扰带", "亮暗带", "interference"],
        "note": "知识库有「工频通时两个粗贯穿横线」的**注记**（在 remark 里，不是独立现象行）⇒ 未单独建判据",
    },
]

_OPTIONS_BY_ID: Dict[str, Dict[str, Any]] = {o["id"]: o for o in OPTION_CATALOG}

def _option_ids_by_abnormal_value() -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for o in OPTION_CATALOG:
        for v in ((o.get("kb_match") or {}).get("abnormal_values") or []):
            out.setdefault(v, []).append(o["id"])
    return out

_ALIAS_INDEX: Dict[str, str] = {}

def _build_alias_index() -> Dict[str, str]:
    if _ALIAS_INDEX:
        return _ALIAS_INDEX
    for o in OPTION_CATALOG:
        keys = {o["id"], o["value"], o["label_plain"], o["label"], o["id"].replace("_", " "),
                o["id"].replace("_", "")}
        keys.update(o.get("aliases") or [])
        for k in keys:
            kk = _key(k).lower()
            if kk:
                _ALIAS_INDEX.setdefault(kk, o["id"])
    return _ALIAS_INDEX

def resolve_option(text: Any) -> Optional[Dict[str, Any]]:
    """把用户输入（id / value / 中文标签 / 别名）解析成选项；失败返回 None。"""
    idx = _build_alias_index()
    k = _key(text).lower()
    if not k:
        return None
    if k in idx:
        return _OPTIONS_BY_ID[idx[k]]

    for alias, oid in sorted(idx.items(), key=lambda kv: -len(kv[0])):
        if len(alias) >= 2 and alias in k:
            return _OPTIONS_BY_ID[oid]
    return None

def _generic_option(value: str) -> Dict[str, Any]:
    """判据库其他 abnormal_value（灯/按键/声音类）→ 伪选项，让 explain() 也能吃灯状态。"""
    return {
        "id": f"kb_{value}", "value": value,
        "label": f"判据库异常值 {value}", "label_plain": value,
        "category": "判据库原始值", "order": 900,
        "in_kb": True, "kb_basis": "abnormal_value",
        "kb_match": {"abnormal_values": [value]},
        "vision_hintable": value in ("off", "on"), "vision_supported": value in ("off", "on"),
        "vision_state": value, "sop_keywords": [], "aliases": [],
        "note": ABNORMAL_VALUE_MEANING.get(value, ""),
    }

def _row_strength(opt: Mapping[str, Any], row: Mapping[str, Any]) -> Tuple[float, str]:
    """一条判据行能多强地解释这个现象（0 表示不匹配）。"""
    km = opt.get("kb_match") or {}
    avs = km.get("abnormal_values") or []
    fps = km.get("field_prefixes") or []
    exact = km.get("phenomenon_exact") or []
    contains = km.get("phenomenon_contains") or []

    if avs and row["abnormal_value"] in avs:
        if fps and any(_key(p) in _key(row["field"]) for p in fps):
            return 1.00, "abnormal_value+field"
        return 0.95, "abnormal_value"

    phn = _key(row["phenomenon"])
    if phn:
        for p in exact:
            if phn == _key(p):
                return 0.88, "phenomenon_exact"
        for p in contains:
            pk = _key(p)
            if pk and pk in phn:
                return 0.80, "phenomenon_contains"
    return 0.0, ""

def match_option(opt: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        s, by = _row_strength(opt, r)
        if s > 0:
            out.append({"row": int(r["row"]), "strength": s, "by": by})
    return out

def _split_module(module: str) -> Tuple[str, str]:
    """``（Z11-1频综）（无供电）`` → (``Z11-1频综``, ``无供电``)。"""
    s = _clean(module)
    s = re.split(r"分别拆|注意|相当于", s)[0].strip(" ，,")
    m = re.match(r"^(?:（(Z\d+[^）]*)）)\s*[（(]([^）)]+)[）)]\s*$", s)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return s, ""

def _pretty_name(name: str) -> str:
    return re.sub(r"^([A-Za-z0-9\-\+\.]+)(?=[\u4e00-\u9fff])", r"\1 ", name).strip()

def _remark_short(remark: str) -> str:
    """注记摘要：在「注意/分别拆/相当于」处截断，并去掉残留的半个/空括号。"""
    s = re.split(r"注意|分别拆|相当于|【", _clean(remark))[0]
    s = re.sub(r"[（(]\s*[）)]", "", s)          
    s = s.strip(" ，,；;：:")
    while s and s[-1] in "（(【[《":
        s = s[:-1].strip(" ，,；;：:")
    return s[:26] + ("…" if len(s) > 26 else "")

def _reason_of(mod_name: str, mod_mode: str, remark: str, step_name: str, phenomenon: str) -> Tuple[str, str]:
    """故障原因（remark/step_name 摘要）→ ``(原因, 来源)``。

    优先级：模块名第二括号里的失效模式 > remark 注记 > SOP 检查步骤。
    三者都没有就**留空**（不编原因）；JSON 里仍有 ``phenomenon`` / ``step_name`` 可追溯。
    """
    if mod_mode:
        return mod_mode, "module"
    r = _remark_short(remark)
    if r:
        return f"注记：{r}", "remark"
    if step_name:
        s = step_name if len(step_name) <= 28 else step_name[:27] + "…"
        return f"步骤：{s}", "step_name"
    return "", "none"

UNDETERMINED_INPUTS = {"skipped", "undetermined", "unknown", "uncertain", "skip",
                       "跳过", "看不清", "无法判断", "未验证"}

AMBIGUOUS_BY_FIELD: Dict[str, List[Tuple[str, Tuple[str, ...]]]] = {
    "no": [("no_scan", ("scan", "扫描")), ("no_echo", ("echo", "回波"))],
    "abnormal": [("meter_zero", ("meter", "supply", "z12", "表头", "数值")),
                 ("no_guidance_line", ("line", "guidance", "direction", "理想线", "方向"))],
}
AMBIGUOUS_DEFAULT = {"no": "no_echo", "abnormal": "kb:abnormal"}

CROSSWALK_TO_MINE: Dict[str, Dict[str, Any]] = {
    "normal": {"to": ["normal"], "note": "两边同名；正常态，不产生候选"},
    "black_screen": {"to": ["black_screen"], "note": "两边同名；判据库 abnormal_value"},
    "yellow_screen": {"to": ["yellow_screen"], "note": "两边同名；判据库 abnormal_value"},
    "garbled": {"to": ["garbled"], "note": "两边同名；判据库只有现象文本"},
    "no": {"to": ["no_echo", "no_scan"], "note": "有歧义：回波题 → no_echo，扫描题 → no_scan；"
                                                "带 field 或直接传我的 id 才准"},
    "weak": {"to": ["weak_echo"], "note": "值相同、id 不同（我的是 weak_echo）"},
    "no_noise": {"to": ["no_noise"], "note": "两边同名"},
    "abnormal": {"to": ["meter_zero", "no_guidance_line"], "note": "有歧义：表头/数值题 → meter_zero，"
                                                                  "理想线/方向题 → no_guidance_line（无候选）"},
    "skipped": {"to": [], "note": "跳过/看不清：不算异常，也不给原因（UNDETERMINED_INPUTS）"},
}

def crosswalk_qa_items_screen(path: Optional[Path] = None) -> Dict[str, Any]:
    """**只读**核对 ``qa_items_screen.json``（另一 agent 的产出）与本清单的选项对照。"""
    p = Path(path) if path else (ENGINE_DIR / "qa_items_screen.json")
    out: Dict[str, Any] = {"path": str(p), "exists": p.exists(), "ok": False, "items": 0,
                           "their_option_ids": [], "mapping": CROSSWALK_TO_MINE,
                           "unmapped_theirs": [], "mine_not_in_theirs": [],
                           "ambiguous": sorted(AMBIGUOUS_BY_FIELD), "warnings": []}
    if not p.exists():
        out["warnings"].append("qa_items_screen.json 不存在（另一 agent 未产出）：本文件不新建、只读对齐")
        return out
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        out["warnings"].append(f"读取失败：{exc}")
        return out
    items = d.get("items") or []
    out["items"] = len(items)
    out["their_schema"] = d.get("schema")
    ids: List[str] = []
    for it in items:
        for o in (it.get("options") or []):
            if o.get("id") and o["id"] not in ids:
                ids.append(o["id"])
    out["their_option_ids"] = ids
    out["unmapped_theirs"] = [i for i in ids if i not in CROSSWALK_TO_MINE]
    mine = {o["id"] for o in OPTION_CATALOG}
    mapped = {x for v in CROSSWALK_TO_MINE.values() for x in v["to"]}
    out["mine_not_in_theirs"] = sorted(mine - mapped)
    out["ok"] = not out["unmapped_theirs"]
    for i in ids:
        if i in AMBIGUOUS_BY_FIELD:
            out["warnings"].append(f"选项值 {i!r} 有歧义：调用 explain() 时必须带 field（如该题的 "
                                   f"evidence_field），否则按默认 {AMBIGUOUS_DEFAULT.get(i)} 处理")
    return out

def _disambiguate(value: str, fields: Sequence[str]) -> Optional[str]:
    """用 evidence field 消歧 ``no`` / ``abnormal``；返回选项 id 或 ``None``（不消歧）。"""
    key = _key(value).lower()
    rules = AMBIGUOUS_BY_FIELD.get(key)
    if not rules:
        return None
    joined = _key(" ".join(fields)).lower()
    if not joined:
        return AMBIGUOUS_DEFAULT.get(key)
    for opt_id, keys in rules:
        if any(_key(k).lower() in joined for k in keys):
            return opt_id
    return None

def _classify_values(values: Sequence[Any],
                     fields: Sequence[str] = ()) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """把输入值分成（知识库内选项, 知识库外/未识别项）。"""
    known: List[Dict[str, Any]] = []
    unknown: List[Dict[str, Any]] = []
    seen = set()
    kb_av_values = {d["value"] for d in abnormal_value_inventory()}
    for raw in values:
        if raw is None or str(raw).strip() == "":
            continue
        opt = resolve_option(raw)

        forced = _disambiguate(str(raw), fields)
        if forced:
            if forced.startswith("kb:"):
                opt = _generic_option(forced[3:])
            elif forced in _OPTIONS_BY_ID:
                opt = _OPTIONS_BY_ID[forced]
        if opt is None:
            k = _key(raw).lower()
            if k in kb_av_values:  
                opt = _generic_option(k)
            else:
                unknown.append({"value": _clean(raw), "option_id": None, "in_kb": False,
                                "reason": "知识库和屏幕选项清单里都没有这个现象（需人工确认；本文件不编原因）"})
                continue
        if opt["id"] in seen:
            continue
        seen.add(opt["id"])
        opt = dict(opt)                      
        opt["_raw"] = _clean(raw)
        known.append(opt)
    return known, unknown

def explain(part: str = "", values: Optional[Sequence[Any]] = None, route: str = "",
            evidence: Optional[Sequence[Mapping[str, Any]]] = None,
            ctx: Optional[Mapping[str, Any]] = None,
            rows: Optional[Sequence[Mapping[str, Any]]] = None,
            field: str = "", fields: Sequence[str] = ()) -> Dict[str, Any]:
    """**现象 → 该部位是否故障 + 全部候选原因**。

    参数
    ----
    part : 部位 token（``z11`` / ``z11-1`` / ``Z11（收发分机）`` 都行；空串 = 只按现象枚举）
    values : 现象列表（屏幕选项 id / 中文标签 / 判据库 abnormal_value，如
             ``["yellow_screen","no_noise"]``、``["黄屏","无底噪"]``、``["off"]``）
    route : ``"I"`` / ``"II"`` / ``""``
    evidence : 可选证据（evidence/v1 片段：``{"field","value","confidence"}``），
               命中同一候选取时**加**置信（多模态交叉印证）
    ctx : 可选上下文（``text`` / ``flow_no`` / ``modality``），用于 criteria_overrides 的收窄规则
    field / fields : 可选 **evidence field**，只用于消歧 ``no``（回波？扫描？）和
             ``abnormal``（表头？理想线？）—— ``qa_items_screen.json`` 的选项值
             ``no`` / ``abnormal`` 在不同题目下含义不同，带上 field 才不会串味

    返回
    ----
    dict（``schema=cause_explain/1.0``）：``is_fault`` / ``primary`` / ``causes``（全部）/
    ``evidence_used`` / ``unknown`` / ``uncertain_reason`` / ``text`` 等。
    """
    values = list(values or [])
    field_list = [f for f in ([field] if field else []) + list(fields or []) if _clean(f)]
    skipped = [v for v in values if _key(v).lower() in UNDETERMINED_INPUTS]
    values = [v for v in values if _key(v).lower() not in UNDETERMINED_INPUTS]
    all_rows = list(rows if rows is not None else load_fault_rows())
    part_norm = normalize_part(part)
    scope = part_scope(part, dict(ctx or {}, route=route)) if part else {
        "part": "", "level": "", "rows": [], "override": {}, "need_narrow": False,
        "notes": [], "source": ""}
    scope_keys = {_row_key(r) for r in scope["rows"]}
    symptom_only = bool(scope.get("symptom_only"))

    known, unknown = _classify_values(values, field_list)

    evidence_used: List[Dict[str, Any]] = []
    hits: List[Dict[str, Any]] = []            
    matched_opts: List[Dict[str, Any]] = []
    for opt in known:
        if opt["id"] in NORMAL_OPTION_IDS or opt["value"] in ("normal", "noise_present"):
            evidence_used.append({"value": opt["value"], "option_id": opt["id"], "label": opt["label_plain"],
                                  "kb_value": "", "match_by": "normal_state", "strength": 0.0,
                                  "rows": [], "count": 0,
                                  "note": "正常态：不产生候选原因，只用于「没有异常证据」"})
            continue
        got = match_option(opt, all_rows)
        if not got:
            unknown.append({"value": opt.get("_raw") or opt["value"], "option_id": opt["id"],
                            "label": opt["label_plain"], "in_kb": bool(opt.get("in_kb")),
                            "reason": "选项在清单里，但判据库 268 行没有任何一行能对应"
                                      "（in_kb 标注可能有误，需作者确认）"})
            continue
        matched_opts.append(opt)
        rows_by_no = {int(r["row"]): r for r in all_rows}
        evidence_used.append({
            "value": opt["value"], "raw": opt.get("_raw") or opt["value"],
            "option_id": opt["id"], "label": opt["label_plain"],
            "kb_value": ",".join((opt.get("kb_match") or {}).get("abnormal_values") or []) or "",
            "in_kb": bool(opt.get("in_kb")), "kb_basis": opt.get("kb_basis"),
            "match_by": got[0]["by"], "strength": max(g["strength"] for g in got),
            "count": len(got),
            "rows": [{"row": g["row"], "cabinet": rows_by_no[g["row"]]["cabinet"],
                      "sub_unit": rows_by_no[g["row"]]["sub_unit"],
                      "module": rows_by_no[g["row"]]["module"],
                      "feature_id": rows_by_no[g["row"]]["feature_id"]} for g in got],
        })
        for g in got:
            hits.append({"opt": opt, "row": rows_by_no[g["row"]], "strength": g["strength"], "by": g["by"]})

    ev_rows: Dict[int, List[str]] = {}
    ev_used: List[Dict[str, Any]] = []
    for ev in (evidence or []):
        if not isinstance(ev, Mapping):
            continue
        field = _clean(ev.get("field"))
        value = _clean(ev.get("value"))
        if not field or not value:
            continue
        conf = ev.get("confidence")
        try:
            conf = float(conf) if conf is not None else 0.6
        except (TypeError, ValueError):
            conf = 0.6
        hit = [r for r in all_rows if r["field"] == field and r["abnormal_value"] == value]
        for r in hit:
            ev_rows.setdefault(int(r["row"]), []).append(field)
        ev_used.append({"field": field, "value": value, "confidence": _clip(conf),
                        "matched_rows": [int(r["row"]) for r in hit],
                        "note": "" if hit else "该 field+value 组合在判据库里不存在（不能当依据）"})

    groups: Dict[str, Dict[str, Any]] = {}
    for h in hits:
        r = h["row"]
        g = groups.setdefault(_row_key(r), {
            "cabinet": r["cabinet"], "sub_unit": r["sub_unit"], "module": r["module"],
            "remark": r["remark"], "step_name": r["step_name"], "phenomenon": r["phenomenon"],
            "row": int(r["row"]), "rows": [], "per_value": {},
        })
        g["rows"].append(int(r["row"]))
        cur = g["per_value"].get(h["opt"]["id"])
        if cur is None or h["strength"] > cur["strength"]:
            g["per_value"][h["opt"]["id"]] = {
                "value": h["opt"]["value"], "option_id": h["opt"]["id"],
                "label": h["opt"]["label_plain"], "strength": h["strength"], "by": h["by"],
                "row": int(r["row"]), "feature_id": r["feature_id"], "field": r["field"],
                "phenomenon": r["phenomenon"], "step_name": r["step_name"],
            }

    n_vals = max(1, len(matched_opts))

    opt_groups: Dict[str, set] = {}
    for h in hits:
        opt_groups.setdefault(h["opt"]["id"], set()).add(_row_key(h["row"]))
    causes: List[Dict[str, Any]] = []
    for key, g in groups.items():
        per = g["per_value"]
        best = max(per.values(), key=lambda d: d["strength"])
        coverage = len(per) / n_vals
        own = key in scope_keys and not symptom_only
        part_factor = PART_FACTOR_IN if own else PART_FACTOR_OUT
        route_mismatch = bool(route) and bool(_route_of(g["sub_unit"])) and \
            _route_of(g["sub_unit"]).upper() != str(route).strip().upper()
        route_factor = ROUTE_FACTOR_MISMATCH if route_mismatch else ROUTE_FACTOR_OK
        best_row = next((r for r in all_rows if int(r["row"]) == best["row"]), None) or {}
        field_bonus = FIELD_BONUS if (best_row.get("feature_id") and best_row.get("field")) else 0.0
        ev_hit = [f for rn, fs in ev_rows.items() if rn in g["rows"] for f in fs]
        ev_bonus = min(EVIDENCE_BONUS_CAP, EVIDENCE_BONUS * (1 if ev_hit else 0))
        n_spec = max(1, len(opt_groups.get(best["option_id"], {key})))
        spec_factor = SPEC_BASE + SPEC_SPAN / n_spec
        cover_factor = W_COVER_BASE + W_COVER_SPAN * coverage
        conf = (best["strength"] * cover_factor * spec_factor
                * part_factor * route_factor + field_bonus + ev_bonus)
        conf = _clip(conf, 0.0, CONF_CAP)

        mod_name, mod_mode = _split_module(g["module"])
        reason, reason_src = _reason_of(mod_name, mod_mode, g["remark"], g["step_name"], g["phenomenon"])
        gid = next((d.get("feature_id") for d in per.values() if d.get("feature_id")), "")
        causes.append({
            "rank": 0,
            "cabinet": g["cabinet"],
            "cabinet_code": _short_code(g["cabinet"]),
            "sub_unit": g["sub_unit"],
            "sub_unit_code": _short_code(g["sub_unit"]),
            "module": mod_name,
            "module_raw": g["module"],
            "reason": reason,
            "reason_source": reason_src,
            "feature_id": gid or "",
            "feature_ids": sorted({d["feature_id"] for d in per.values() if d.get("feature_id")}),
            "confidence": round(conf, 3),
            "in_part_scope": own,
            "in_symptom_scope": bool(key in scope_keys and symptom_only),
            "route_mismatch": route_mismatch,
            "explains": [{"value": d["value"], "option_id": d["option_id"], "label": d["label"],
                          "strength": d["strength"], "by": d["by"], "row": d["row"],
                          "field": d["field"], "feature_id": d["feature_id"]}
                         for d in sorted(per.values(), key=lambda x: -x["strength"])],
            "coverage": {"matched": len(per), "total": n_vals, "ratio": round(coverage, 3)},
            "phenomenon": g["phenomenon"],
            "step_name": g["step_name"],
            "kb_rows": sorted(set(g["rows"])),
            "score_detail": {
                "base": round(best["strength"], 3), "base_by": best["by"],
                "coverage_factor": round(cover_factor, 3),
                "specificity": round(spec_factor, 3), "specificity_n": n_spec,
                "part_factor": part_factor, "route_factor": route_factor,
                "field_bonus": field_bonus, "evidence_bonus": round(ev_bonus, 3),
                "formula": "base × (0.72+0.28×coverage) × (0.75+0.25/N) × part_factor × route_factor"
                           " + field_bonus + evidence_bonus",
            },
            "evidence_matched": sorted(set(ev_hit)),
        })

    causes.sort(key=lambda c: (-c["confidence"], not c["in_part_scope"], c["kb_rows"][0]))
    for i, c in enumerate(causes, 1):
        c["rank"] = i
    causes = causes[:MAX_CAUSES]

    normal_given = [o for o in known if o["id"] in NORMAL_OPTION_IDS]
    top_conf = causes[0]["confidence"] if causes else 0.0
    second_conf = causes[1]["confidence"] if len(causes) > 1 else 0.0
    is_fault: Optional[bool]
    uncertain_reason = ""
    if not values:
        is_fault = None
        if skipped:
            uncertain_reason = ("选择了「跳过/看不清」：该现象未验证，不产生正常/异常结论"
                                "（与 qa_items_screen.json 的 skipped 口径一致）")
        else:
            uncertain_reason = "没有提供任何现象：不知道屏幕现在是什么样，不能判（宁可不判）"
    elif not matched_opts:
        if normal_given and not unknown:
            is_fault = False
            uncertain_reason = ""
        elif unknown:
            names = "、".join(u.get("label") or u["value"] for u in unknown[:6])
            uncertain_reason = (f"这些现象在知识库里没有对应记录：{names} ⇒ 无法给出可能原因。"
                                "请人工确认，或补充其它现象（如有没有回波/底噪/扫描）")
            is_fault = None
        else:
            is_fault = None
            uncertain_reason = "没有可判的异常现象 ⇒ 不判故障"
    elif top_conf < MIN_FAULT_CONF:
        is_fault = None
        uncertain_reason = (f"现象在知识库里能对上，但最高候选置信只有 {top_conf:.2f} < "
                            f"{MIN_FAULT_CONF:.2f} ⇒ 证据太弱，宁可不判")
    else:
        is_fault = True
    if is_fault is True and normal_given:
        uncertain_reason = (uncertain_reason + "；" if uncertain_reason else "") + \
            "同时给了「正常」和异常现象（互相矛盾），请复核现场"

    need_confirm = bool(is_fault is None or (is_fault and top_conf - second_conf < MIN_MARGIN)
                        or (is_fault and not causes[0]["in_part_scope"]))

    notes: List[str] = list(scope.get("notes") or [])
    if scope.get("override"):
        ov = scope["override"]
        if ov.get("rule_id"):
            notes.append(f"部位收窄：{scope['part'].upper()} 命中 criteria_overrides.json 规则 "
                         f"{ov['rule_id']}（{ov.get('narrow_before')} → {ov.get('narrow_after')} 行）")
        elif ov.get("allow_rows") and int(ov.get("after") or 0) < int(ov.get("before") or 0):
            notes.append(f"部位白名单：{scope['part'].upper()} 只允许 allow_rows 里的 "
                         f"{ov.get('allow_rows')} 行（criteria_overrides.json，只读）")
    if is_fault and causes and not causes[0]["in_part_scope"]:
        notes.append(f"⚠️ 主因**不在** {part_display(part)}："
                     f"知识库里能解释这些现象的是 {causes[0]['cabinet_code']}/"
                     f"{causes[0]['sub_unit_code']} {causes[0]['module']}")
    if is_fault and len(causes) > 1 and top_conf - second_conf < MIN_MARGIN:
        notes.append(f"前两名置信接近（{top_conf:.2f} / {second_conf:.2f}）："
                     "知识库无法只凭这些现象定论，需结合灯状态/示波器/声音继续收敛")
    better = [c for c in causes[1:] if c["coverage"]["matched"] > causes[0]["coverage"]["matched"]]
    if is_fault and better:
        b = better[0]
        notes.append(f"交叉印证：{b['cabinet_code']}/{b['sub_unit_code']} {b['module']} 能同时解释 "
                     f"{b['coverage']['matched']}/{b['coverage']['total']} 个现象"
                     f"（第一名只解释 {causes[0]['coverage']['matched']}/{causes[0]['coverage']['total']}）"
                     "⇒ 若现场能确认屏幕归属，可优先查它")
    if route and causes:
        if any(c["route_mismatch"] for c in causes):
            notes.append(f"路别提示：判据库只有 I 路子单元记录，route={route} 时相关候选按 ×"
                         f"{ROUTE_FACTOR_MISMATCH} 降权（**未丢弃**，需人工确认知识库缺口）")
        elif not any(_route_of(r["sub_unit"]) for r in all_rows if int(r["row"]) in
                     {rn for c in causes for rn in c["kb_rows"]}):
            notes.append(f"route={route}：命中的判据行都没有路别标记，按通用处理")
    if not scope["rows"] and part and not any("不在 18 部位清单内" in n for n in notes):
        notes.append(f"部位 {part!r} 在判据库里没有判据行（或 token 不认识）：部位先验未生效")
    if not field_list and any(_key(v).lower() in AMBIGUOUS_BY_FIELD for v in values):
        notes.append("提示：值 no / abnormal 有歧义（在不同 field 下含义不同：回波 vs 扫描、表头 vs 理想线）；"
                     "建议带上 field（或直接传选项 id no_echo/no_scan/meter_zero/no_guidance_line）")

    result: Dict[str, Any] = {
        "schema": SCHEMA,
        "engine": ENGINE_VERSION,
        "generated_at": now_iso(),
        "part": part_norm,
        "part_name": part_name(part_norm) if part_norm else "",
        "part_level": part_level(part_norm) if part_norm else "",
        "part_display": part_display(part_norm) if part_norm else "该部位",
        "route": str(route or ""),
        "values": [_clean(v) for v in values if _clean(v)],
        "skipped_values": [_clean(v) for v in skipped if _clean(v)],
        "field_context": field_list,
        "options_used": [{"option_id": o["id"], "value": o["value"], "label": o["label_plain"],
                          "in_kb": bool(o.get("in_kb")), "kb_basis": o.get("kb_basis"),
                          "category": o.get("category")} for o in known],
        "is_fault": is_fault,
        "primary": causes[0] if causes else None,
        "causes": causes,
        "causes_total": len(causes),
        "evidence_used": evidence_used,
        "extra_evidence": ev_used,
        "unknown": unknown,
        "uncertain_reason": uncertain_reason,
        "need_confirm": need_confirm,
        "part_scope": {
            "criteria_rows": len(scope["rows"]),
            "source": scope.get("source", ""),
            "override": scope.get("override") or {},
            "need_narrow": bool(scope.get("need_narrow")),
        },
        "notes": notes,
        "meta": {
            "fault_csv": str(FAULT_CSV),
            "fault_rows": len(all_rows),
            "options_source": str(OPTIONS_JSON),
            "thresholds": {"min_fault_conf": MIN_FAULT_CONF, "min_margin": MIN_MARGIN,
                           "part_factor_in": PART_FACTOR_IN, "part_factor_out": PART_FACTOR_OUT,
                           "route_factor_mismatch": ROUTE_FACTOR_MISMATCH},
        },
    }
    result["text"] = format_text(result)
    return result

def _row_key(r: Mapping[str, Any]) -> str:
    return f"{_key(r['cabinet'])}|{_key(r['sub_unit'])}|{_key(r['module'])}"

_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"

def format_text(res: Mapping[str, Any]) -> str:
    """人看的显示格式（UI 可照抄；JSON 里另有完整字段）。"""
    disp = res.get("part_display") or "该部位"
    labels = [o["label"] for o in (res.get("options_used") or [])]
    val_txt = " + ".join(labels)
    head_tail = f"（{val_txt}）" if val_txt else ""
    lines: List[str] = []
    if res.get("is_fault") is True:
        lines.append(f"❌ {disp}存在故障{head_tail}")
    elif res.get("is_fault") is False:
        lines.append(f"✅ {disp}未发现知识库内的异常现象{head_tail}")
    else:
        lines.append(f"⚠️ 无法判定{head_tail}")

    if res.get("uncertain_reason"):
        lines.append(f"原因：{res['uncertain_reason']}")

    causes = res.get("causes") or []
    if causes:
        lines.append("可能原因（按可能性排序）：")
        for c in causes[:MAX_TEXT_CAUSES]:
            i = c["rank"]
            num = _CIRCLED[i - 1] if i <= len(_CIRCLED) else f"({i})"
            loc = f"{c['cabinet_code']}/{c['sub_unit_code']}"
            flag = "" if c["in_part_scope"] else "（跨部位）"
            reason = f" —— {c['reason']}" if c.get("reason") else ""
            lines.append(f" {num} {_pretty_name(c['module'])}{reason}"
                         f"（置信 {c['confidence']:.2f}）｜{loc}{flag}")
        if len(causes) > MAX_TEXT_CAUSES:
            lines.append(f" …共 {len(causes)} 条候选，其余见 JSON")
        lines.append("注：以上为知识库中的候选，需结合其它现象进一步确认")
    else:
        lines.append("可能原因：（知识库没有能对应这些现象的行）")

    if res.get("unknown"):
        bits = []
        for u in res["unknown"][:6]:
            name = u.get("label") or u["value"]
            r = str(u.get("reason") or "")
            if "没有对应记录" in r or "知识库和屏幕选项" in r or "没有任何一行" in r:
                r = "知识库无此现象，需人工确认"
            bits.append(f"{name}（{r}）")
        lines.append("未纳入：" + "；".join(bits))
    for n in (res.get("notes") or [])[:4]:
        lines.append(f"· {n}")
    return "\n".join(lines)

def build_screen_options(fault_rows: Optional[Sequence[Mapping[str, Any]]] = None,
                         sop_items: Optional[Sequence[Mapping[str, Any]]] = None,
                         generated_at: Optional[str] = None) -> Dict[str, Any]:
    """由目录 + 判据库现算，生成 ``screen_options.json`` 的内容（确定性，可 diff）。"""
    rows = list(fault_rows if fault_rows is not None else load_fault_rows())
    sops = list(sop_items if sop_items is not None else load_sop_items())
    inv = abnormal_value_inventory(rows)
    inv_by_value = {d["value"]: d for d in inv}

    options: List[Dict[str, Any]] = []

    ordered = sorted(OPTION_CATALOG,
                     key=lambda o: (0 if o.get("in_kb") else (1 if o.get("in_sop") else 2),
                                    int(o.get("order") or 900)))
    for idx, o in enumerate(ordered, 1):
        got = match_option(o, rows)
        avs = (o.get("kb_match") or {}).get("abnormal_values") or []
        av_rows = [int(r["row"]) for r in rows if r["abnormal_value"] in avs] if avs else []
        causes = []
        if got:
            sub = explain(values=[o["id"]], rows=rows)  
            for c in sub["causes"][:8]:
                causes.append({k: c[k] for k in ("rank", "cabinet", "sub_unit", "module", "reason",
                                                 "reason_source", "phenomenon", "feature_id",
                                                 "confidence", "in_part_scope", "kb_rows", "coverage")})
            total = len(sub["causes"])
        else:
            total = 0
        sop_refs = []
        for s in sops:
            item = _clean(s.get("check_item"))
            if any(_key(k) and _key(k) in _key(item) for k in (o.get("sop_keywords") or [])):
                sop_refs.append({"flow_no": s.get("flow_no"), "check_item": item,
                                 "subject": s.get("subject"), "method": s.get("method"),
                                 "need_qa": s.get("need_qa"), "fault_refs": s.get("fault_refs")})
        rec: Dict[str, Any] = {
            "id": o["id"], "value": o["value"], "label": o["label"], "label_plain": o["label_plain"],
            "category": o["category"], "order": idx,
            "in_kb": bool(o.get("in_kb")), "in_sop": bool(o.get("in_sop") or sop_refs),
            "kb_basis": o.get("kb_basis"), "user_dictated": bool(o.get("user_dictated")),
            "author_confirm": bool(o.get("author_confirm")),
            "abnormal_value": ",".join(avs),
            "abnormal_value_in_kb": bool(avs and any(a in inv_by_value for a in avs)),
            "kb_rows": [int(g["row"]) for g in got],
            "kb_row_count": len(got),
            "kb_row_count_by_abnormal_value": len(av_rows),
            "kb_strength_max": max((g["strength"] for g in got), default=0.0),
            "kb_strength_by": sorted({g["by"] for g in got}),
            "sop_refs": sop_refs[:6],
            "vision_hintable": bool(o.get("vision_hintable")),
            "vision_supported": bool(o.get("vision_supported")),
            "vision_state": o.get("vision_state"),
            "vision_note": o.get("vision_note") or "",
            "possible_causes": causes,
            "possible_causes_total": total,
            "possible_causes_truncated": total > len(causes),
            "nearest_kb_hint": "",
            "note": o.get("note") or "",
        }
        if not got and o.get("in_kb"):
            rec["note"] = (rec["note"] + " ⚠️ 标注 in_kb 但判据库 0 行命中（需复核）").strip()
        if not got and not o.get("in_kb"):
            if o.get("in_sop"):
                rec["nearest_kb_hint"] = ("SOP 有该检查项，但故障真值表无对应行 ⇒ 给不出机柜/分机/模块，"
                                          "需作者补判据")
            else:
                rec["nearest_kb_hint"] = ("知识库无此现象 ⇒ 不提供候选原因（本文件不编）。"
                                          "若现场确实出现，请作者补一条真值行后再启用")
        options.append(rec)

    data: Dict[str, Any] = {
        "schema": OPTIONS_SCHEMA,
        "engine": ENGINE_VERSION,
        "generated_at": generated_at or now_iso(),
        "user_request": "「屏幕上的所有问题，比如有黄线、有底噪都要写出来；判出故障后按知识库显示可能原因」",
        "source": {
            "fault_csv": str(FAULT_CSV), "fault_rows": len(rows),
            "sop_csv": str(SOP_CSV), "sop_rows": len(sops),
            "overrides_json": str(OVERRIDES_JSON),
            "fault_columns": ["cabinet", "sub_unit", "module", "remark", "step_name", "phenomenon",
                              "field", "abnormal_value", "feature_id"],
        },
        "stats": {
            "options_total": len(options),
            "in_kb_true": sum(1 for o in options if o["in_kb"]),
            "in_kb_false": sum(1 for o in options if not o["in_kb"]),
            "user_dictated": sum(1 for o in options if o["user_dictated"]),
            "sop_only": sum(1 for o in options if not o["in_kb"] and o["in_sop"]),
            "vision_supported": sum(1 for o in options if o["vision_supported"]),
            "with_kb_causes": sum(1 for o in options if o["possible_causes_total"] > 0),
        },
        "options": options,
        "abnormal_value_inventory": inv,
        "abnormal_value_uncovered": [d for d in inv if not d["screen_options"]],
        "align_with_qa_items_screen": {
            "how": "qa_items_screen.json（另一 agent 产出）的选项值与本清单对齐；本文件只读对齐、"
                   "绝不写别人的文件。传值时建议带上该题的 evidence_field（见 crosswalk）",
            "ui_option_shape": {"id": "<options[].id>", "value": "<options[].value>",
                                "label": "<label>", "label_plain": "<label_plain>",
                                "tone": "ok|bad|warn", "in_kb": "<in_kb>"},
            "rule": "in_kb=false 的选项必须带「知识库未收录，需人工确认」提示；不得给它编候选原因",
            "crosswalk": CROSSWALK_TO_MINE,
            "ambiguous_values": sorted(AMBIGUOUS_BY_FIELD),
            "cli": "python cause_explainer.py --crosswalk   # 实时核对对方的 qa_items_screen.json",
        },
    }
    return data

def _strip_dynamic(data: Mapping[str, Any]) -> Dict[str, Any]:
    d = json.loads(json.dumps(data, ensure_ascii=False))
    d.pop("generated_at", None)
    return d

def check_screen_options(path: Optional[Path] = None) -> Dict[str, Any]:
    """校验磁盘上的 ``screen_options.json`` 是否与当前判据库同源（防止过期）。"""
    p = Path(path) if path else OPTIONS_JSON
    if not p.exists():
        return {"ok": False, "reason": f"{p} 不存在"}
    try:
        disk = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "reason": f"读取失败：{exc}"}
    fresh = build_screen_options()
    a, b = _strip_dynamic(disk), _strip_dynamic(fresh)
    if a == b:
        return {"ok": True, "reason": "与判据库/目录一致", "options": fresh["stats"]["options_total"]}
    diffs = []
    da = {o["id"]: o for o in a.get("options", [])}
    db = {o["id"]: o for o in b.get("options", [])}
    for k in sorted(set(da) | set(db)):
        if da.get(k) != db.get(k):
            diffs.append(k)
    return {"ok": False, "reason": "screen_options.json 已过期（判据库或目录变了）",
            "diff_option_ids": diffs[:20], "diff_count": len(diffs)}

def write_screen_options(path: Optional[Path] = None) -> Path:
    p = Path(path) if path else OPTIONS_JSON
    data = build_screen_options()
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return p

_SUBUNIT_TO_PART = {"Z11": "z11", "Z12": "z12", "Z14": "z14", "Z15": "z15", "Z16": "z16",
                    "Z18": "z18", "Z19": "z19", "Z31": "z31", "Z4": "z4", "指示分机": "z16",
                    "转接分机": "z19", "配电箱": "z31"}

def to_evidence(result: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """把解释结果转成 ``evidence/v1``（可直接喂 fusion.py / fault_grader.py，只读不改它们）。"""
    out: List[Dict[str, Any]] = []
    rows = {int(r["row"]): r for r in load_fault_rows()}
    route = str(result.get("route") or "")
    for c in result.get("causes") or []:
        for ex in c.get("explains") or []:
            r = rows.get(int(ex["row"]))
            if not r or not r["field"] or not r["abnormal_value"]:
                continue
            part = next((v for k, v in _SUBUNIT_TO_PART.items() if k in r["sub_unit"]), "")
            out.append({
                "part": part or (result.get("part") or ""),
                "route": route,
                "modality": "vision",
                "field": r["field"],
                "value": r["abnormal_value"],
                "confidence": round(min(0.95, c["confidence"]), 3),
                "evidence": f"{_clean(r['cabinet'])}/{_clean(r['sub_unit'])} {_clean(r['module'])}"
                            f" → {_clean(r['phenomenon'])}（判据库第 {r['row']} 行）",
                "ts": now_iso(),
                "source": "cause_explainer.explain",
                "feature_id": r["feature_id"],
                "meta": {"kb_row": r["row"], "cause_rank": c["rank"]},
            })
    return out

def _print_inventory() -> None:
    inv = abnormal_value_inventory()
    print(f"判据库 abnormal_value 全集：{len(inv)} 个值（268 行里 {sum(d['rows'] for d in inv)} 行有值，"
          f"{268 - sum(d['rows'] for d in inv)} 行是纯现象行）")
    for d in inv:
        screen = "、".join(d["screen_options"]) or "—"
        print(f"  {d['rows']:3d} 行  {d['value']:24s} 屏幕选项: {screen:28s} {d['meaning']}")

def _parse_values(raw: Optional[str], file: Optional[str]) -> List[str]:
    if file:
        txt = Path(file).read_text(encoding="utf-8")
        return [x.strip() for x in re.split(r"[,\n;，、]+", txt) if x.strip()]
    if not raw:
        return []
    return [x.strip() for x in re.split(r"[,;，、]+", raw) if x.strip()]

def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="现象 → 故障可能原因（只读知识库）")
    ap.add_argument("--part", default="", help="部位 token，如 z11 / z11-1 / Z11（收发分机）")
    ap.add_argument("--values", default="", help="现象，逗号分隔，如 yellow_screen,no_noise")
    ap.add_argument("--values-file", default="", help="从文件读现象（每行/逗号分隔）")
    ap.add_argument("--route", default="", help="I / II / 空")
    ap.add_argument("--field", default="", help="该题的 evidence field（用于消歧 no / abnormal）")
    ap.add_argument("--json", action="store_true", help="输出完整 JSON")
    ap.add_argument("--evidence", default="", help="可选证据 JSON 文件（evidence/v1 片段数组）")
    ap.add_argument("--write-options", action="store_true", help="生成/刷新 screen_options.json")
    ap.add_argument("--check-options", action="store_true", help="校验 screen_options.json 是否过期")
    ap.add_argument("--inventory", action="store_true", help="打印判据库 abnormal_value 全集")
    ap.add_argument("--list-options", action="store_true", help="打印屏幕现象穷举清单")
    ap.add_argument("--crosswalk", action="store_true", help="只读核对 qa_items_screen.json 的选项对照")
    args = ap.parse_args(argv)

    if args.crosswalk:
        r = crosswalk_qa_items_screen()
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0 if r.get("ok") or not r.get("exists") else 2

    if args.write_options:
        p = write_screen_options()
        d = json.loads(p.read_text(encoding="utf-8"))
        print(f"已写入 {p}：{d['stats']['options_total']} 项 "
              f"（in_kb {d['stats']['in_kb_true']} / 知识库外 {d['stats']['in_kb_false']}）")
        return 0
    if args.check_options:
        r = check_screen_options()
        print(("OK  " if r["ok"] else "FAIL ") + str(r.get("reason")))
        if not r["ok"] and r.get("diff_option_ids"):
            print("差异选项：" + "、".join(r["diff_option_ids"]))
        return 0 if r["ok"] else 2
    if args.inventory:
        _print_inventory()
        return 0
    if args.list_options:
        data = build_screen_options()
        for o in data["options"]:
            tag = "KB " if o["in_kb"] else ("SOP" if o["in_sop"] else "口述")
            print(f"{o['order']:2d} [{tag}] {o['id']:18s} {o['label']:38s} 行{o['kb_row_count']:2d} "
                  f"候选{o['possible_causes_total']:2d} 视觉{'✔' if o['vision_supported'] else '✗'}")
        print(f"共 {data['stats']['options_total']} 项：in_kb {data['stats']['in_kb_true']} / "
              f"知识库外 {data['stats']['in_kb_false']}（其中仅 SOP {data['stats']['sop_only']}、"
              f"用户口述 {data['stats']['user_dictated']}）")
        return 0

    evidence = None
    if args.evidence:
        evidence = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
    res = explain(part=args.part, values=_parse_values(args.values, args.values_file),
                  route=args.route, evidence=evidence, field=args.field)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        print(res["text"])
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
