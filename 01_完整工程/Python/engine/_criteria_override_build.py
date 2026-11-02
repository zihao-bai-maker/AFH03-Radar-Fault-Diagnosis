#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 engine/criteria_overrides.json（只读两份判据 CSV；不改 CSV/fault_grader）。

口径：
- 行号 row = 判据库_故障.csv 的 1-based 数据行（不含表头），与 csv.DictReader 顺序一致；
- line = CSV 物理行号（csv.reader.line_num，遇到 module 内换行时是“该行结束物理行”）；
- z20：故障归属里没有 Z20；只把 step_name/phenomenon 含 Z20 的 26 行作为“现象行”；
- z5：cabinet=Z5 的 63 行按子单元/模块/field 前缀收窄。
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter, OrderedDict
from datetime import datetime, timedelta, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RADAR = r"D:\xuexishengshou\雷达判据"
SOP_CSV = RADAR + r"\判据库_SOP.csv"
FAULT_CSV = RADAR + r"\判据库_故障.csv"
OUT = RADAR + r"\engine\criteria_overrides.json"

SCHEMA = "criteria_override/1.0"
TZ = timezone(timedelta(hours=8))
NOW = datetime.now(TZ).isoformat(timespec="seconds")

def load_csv(path: str):
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        for i, row in enumerate(r, 1):
            row["_row"] = i
            row["_line"] = r.line_num
            rows.append(row)
    return rows

def one_line(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\n", " ")).strip()

def row_ref(r, field_align: str = "", topics=None):
    return {
        "row": r["_row"],
        "csv_line": r["_line"],
        "cabinet": one_line(r["cabinet"]),
        "sub_unit": one_line(r["sub_unit"]),
        "module": one_line(r["module"]),
        "step_name": one_line(r["step_name"]),
        "phenomenon": one_line(r["phenomenon"]),
        "field": r["field"].strip(),
        "abnormal_value": r["abnormal_value"].strip(),
        "feature_id": r["feature_id"].strip(),
        **({"field_align": field_align} if field_align else {}),
        **({"topics": topics} if topics else {}),
    }

def field_align(r) -> str:
    f = r["field"]
    s = r["step_name"]
    if not f:
        return "empty"
    checks = [
        ("transmitter_work" in f, "发射机工作" in s),
        ("switch_to_route_one" in f, "两路转换" in s),
        ("antenna_start" in f, "天线启动" in s),
        ("z20_transmit_control_power_on" in f, "发射控制" in s),
    ]
    for hit, ok in checks:
        if hit:
            return "ok" if ok else "mismatch"
    return "mismatch"

def topic_of(step: str) -> str:
    if "发射机工作" in step:
        return "transmitter_work"
    if "天线启动" in step:
        return "antenna_start"
    if "两路转换" in step:
        return "route_switch"
    if "发射控制" in step:
        return "transmit_control"
    return "other"

def main() -> int:
    sop = load_csv(SOP_CSV)
    faults = load_csv(FAULT_CSV)
    by_row = {r["_row"]: r for r in faults}

    sop20 = [r for r in sop if "Z20" in (r["check_item"] + r["flow_name"]).upper()]
    step20 = [r for r in faults if "Z20" in (r["step_name"] + r["phenomenon"]).upper()]
    fieldonly20 = [r for r in faults
                   if "Z20" in r["field"].upper()
                   and "Z20" not in (r["step_name"] + r["phenomenon"]).upper()]
    gradable20 = [r for r in step20 if field_align(r) == "ok"]

    def rows_where(pred):
        return [r["_row"] for r in step20 if pred(r["step_name"])]

    groups = OrderedDict()
    groups["transmitter_work_route_one"] = rows_where(lambda s: "发射机工作" in s)
    groups["antenna_start"] = rows_where(lambda s: "天线启动" in s)
    groups["route_switch"] = rows_where(lambda s: "两路转换" in s)
    groups["transmit_control_on"] = rows_where(lambda s: "发射控制" in s and "通" in s)
    assert len(groups["transmitter_work_route_one"]) == 18, groups
    assert len(groups["antenna_start"]) == 4, groups
    assert len(groups["route_switch"]) == 3, groups
    assert len(groups["transmit_control_on"]) == 1, groups
    assert sum(len(v) for v in groups.values()) == 26

    def gradable(rows):
        return [x for x in rows if field_align(by_row[x]) == "ok"]

    z20_rules = [
        {
            "id": "transmitter_work_route_one",
            "when": {"sop_flow_in": [21], "text_contains_any": ["发射机工作", "发射机工作]-[I]"]},
            "match": {"step_name_contains_any": ["发射机工作"]},
            "keep_rows": len(groups["transmitter_work_route_one"]),
            "result_rows": groups["transmitter_work_route_one"],
            "gradable_rows": gradable(groups["transmitter_work_route_one"]),
            "purpose": "Z20 面板“发射机工作 I 指示灯亮”异常时，只取 18 行现象行；其中 6 行 field 可直接判灯。",
        },
        {
            "id": "antenna_start",
            "when": {"sop_flow_in": [19]},
            "match": {"step_name_contains_any": ["天线启动"]},
            "keep_rows": len(groups["antenna_start"]),
            "result_rows": groups["antenna_start"],
            "gradable_rows": gradable(groups["antenna_start"]),
            "purpose": "天线启动指示灯/按键异常，4 行均为 Z6/Z18-1 电源或接触器故障。",
        },
        {
            "id": "route_switch",
            "when": {"sop_flow_in": [7, 20, 25]},
            "match": {"step_name_contains_any": ["两路转换"]},
            "keep_rows": len(groups["route_switch"]),
            "result_rows": groups["route_switch"],
            "gradable_rows": gradable(groups["route_switch"]),
            "purpose": "I/II 路转换无反应，3 行均指向 Z6/Z18 电源或 SA1 纽子开关。",
        },
        {
            "id": "transmit_control_on",
            "when": {"sop_flow_in": [21, 26]},
            "match": {"step_name_contains_any": ["发射控制"], "text_contains_all": ["通"]},
            "keep_rows": len(groups["transmit_control_on"]),
            "result_rows": groups["transmit_control_on"],
            "gradable_rows": gradable(groups["transmit_control_on"]),
            "purpose": "发射控制“通”按键无反应，唯一一行是 Z5/Z11 分机不到位。",
        },
        {
            "id": "all_symptom_rows",
            "when": {},
            "match": {"step_name_contains_any": ["Z20"]},
            "keep_rows": len(step20),
            "result_rows": [r["_row"] for r in step20],
            "gradable_rows": [r["_row"] for r in gradable20],
            "purpose": "兜底：只允许 step_name/phenomenon 含 Z20 的 26 行；不得扩到 Z11/Z12/Z18 的全部故障行。",
        },
    ]

    sop_refs = []
    for r in sop20:
        ci = r["check_item"]
        if "电源控制" in ci:
            topic, status, rows = "power_control", "missing", []
            why = "判据库只有 Z31（电源控制）的 Z31/配电箱行，没有 Z20 工频电源行"
        elif "手操控制" in ci:
            topic, status, rows = "manual_control", "missing", []
            why = "判据库 step_name 无“手操控制”，Z4 只有天线辅助运动 manual_action 行"
        elif "两路转换" in ci:
            topic, status, rows = "route_switch", "matched", groups["route_switch"]
            why = "3 行 Z20-[发射机控制]-[两路转换]-[I/II]"
        elif "天线启动" in ci and "按键" in ci:
            topic, status, rows = "antenna_start_button", "partial", groups["antenna_start"]
            why = "有 4 行“天线启动指示灯不亮”，没有“按键无反应”行；现象不完全等价"
        elif "天线启动" in ci and "指示灯" in ci:
            topic, status, rows = "antenna_start_lamp", "matched", groups["antenna_start"]
            why = "4 行“天线启动指示灯不亮”"
        elif "发射控制" in ci and "断" in ci:
            topic, status, rows = "transmit_control_off", "missing", []
            why = "只有“发射控制-通-按键”一行，无“断”行"
        elif "发射控制" in ci and "通" in ci:
            topic, status, rows = "transmit_control_on", "matched", groups["transmit_control_on"]
            why = "唯一“发射控制-通-按键_按键无反应”行（Z5/分机不到位）"
        elif "发射机工作" in ci and "II" in ci:
            topic, status, rows = "transmitter_work_route_two", "missing", []
            why = "判据库只有 I 路，Z5/Z6 的 sub_unit 全是 I路；全库无 II路 子单元"
        elif "发射机工作" in ci and "I" in ci:
            topic, status, rows = "transmitter_work_route_one", "matched", groups["transmitter_work_route_one"]
            why = "18 行“发射机工作-[I]-指示灯不亮”"
        else:
            topic, status, rows = "other", "missing", []
            why = "未归类"
        sop_refs.append({
            "csv_line": r["_line"], "flow_no": r["flow_no"], "check_item": ci,
            "category": r["category"], "need_qa": r["need_qa"],
            "topic": topic, "status": status, "fault_rows": rows, "why": why,
        })

    suggested = [
        {
            "for_sop_line": 12, "cabinet": "Z31(电源控制机柜）", "sub_unit": "配电箱",
            "module": "工频电源接触器", "step_name": "Z20(控制台)-[电源控制]-[工频电源]-“通”-按键",
            "phenomenon": "Z20(控制台)-[电源控制]-[工频电源]-“通”-按键_按键无反应",
            "field": "(manual_action)_z20_power_on_button", "abnormal_value": "not_done",
            "feature_id": "F_(manual_action)_z20_power_on_button_not_done",
            "why": "SOP line 12 无任何对应故障行；挂到实际执行工频上电的 Z31 配电箱",
        },
        {
            "for_sop_line": 13, "cabinet": "Z31(电源控制机柜）", "sub_unit": "配电箱",
            "module": "工频电源接触器", "step_name": "Z20(控制台)-[电源控制]-（接触器）-有吸合声",
            "phenomenon": "Z20(控制台)-[电源控制]-（接触器）-无吸合声",
            "field": "(audio)_z20_power_contactor_pull_in", "abnormal_value": "absent",
            "feature_id": "F_(audio)_z20_power_contactor_pull_in_absent",
            "why": "SOP line 13 需要声音判据；判据库现无 (audio) 字段的 Z20 行",
        },
        {
            "for_sop_line": 14, "cabinet": "Z31(电源控制机柜）", "sub_unit": "配电箱",
            "module": "工频电源指示灯", "step_name": "Z20(控制台)-[电源控制]-[工频电源]-指示灯亮",
            "phenomenon": "Z20(控制台)-[电源控制]-[工频电源]-指示灯_不亮",
            "field": "(led_indicator)_z20_power_on", "abnormal_value": "off",
            "feature_id": "F_(led_indicator)_z20_power_on_off",
            "why": "SOP line 14 无对应故障行；灯在 Z20 面板，源在 Z31",
        },
        {
            "for_sop_line": 52, "cabinet": "Z4（传动单元）", "sub_unit": "天线控制",
            "module": "手操控制开关（内）", "step_name": "Z20（控制台）-[天线控制]-[手操控制]-内",
            "phenomenon": "Z20（控制台）-[天线控制]-[手操控制]-内_开关无反应",
            "field": "(manual_action)_z20_antenna_manual_inner", "abnormal_value": "not_done",
            "feature_id": "F_(manual_action)_z20_antenna_manual_inner_not_done",
            "why": "SOP line 52 无对应故障行；手操最终驱动 Z4 传动单元",
        },
        {
            "for_sop_line": 57, "cabinet": "Z4（传动单元）", "sub_unit": "天线控制",
            "module": "手操控制开关（外）", "step_name": "Z20（控制台）-[天线控制]-[手操控制]-外",
            "phenomenon": "Z20（控制台）-[天线控制]-[手操控制]-外_开关无反应",
            "field": "(manual_action)_z20_antenna_manual_outer", "abnormal_value": "not_done",
            "feature_id": "F_(manual_action)_z20_antenna_manual_outer_not_done",
            "why": "SOP line 57 同上",
        },
        {
            "for_sop_line": 73, "cabinet": "Z4（传动单元）", "sub_unit": "天线控制",
            "module": "手操控制开关（内）", "step_name": "Z20（控制台）-[天线控制]-[手操控制]-内",
            "phenomenon": "Z20（控制台）-[天线控制]-[手操控制]-内_开关无反应",
            "field": "(manual_action)_z20_antenna_manual_inner", "abnormal_value": "not_done",
            "feature_id": "F_(manual_action)_z20_antenna_manual_inner_not_done",
            "why": "SOP line 73 与 52 同项（flow 16 领显），可复用同一行",
        },
        {
            "for_sop_line": 79, "cabinet": "Z4（传动单元）", "sub_unit": "天线控制",
            "module": "手操控制开关（外）", "step_name": "Z20（控制台）-[天线控制]-[手操控制]-外",
            "phenomenon": "Z20（控制台）-[天线控制]-[手操控制]-外_开关无反应",
            "field": "(manual_action)_z20_antenna_manual_outer", "abnormal_value": "not_done",
            "feature_id": "F_(manual_action)_z20_antenna_manual_outer_not_done",
            "why": "SOP line 79 与 57 同项（flow 16 领显）",
        },
        {
            "for_sop_line": 139, "cabinet": "Z5（收发机柜）", "sub_unit": "Z11（收发分机）（I路）",
            "module": "分机不到位", "step_name": "Z20（控制台）-[发射机控制]-[发射控制]-“断”-按键",
            "phenomenon": "Z20（控制台）-[发射机控制]-[发射控制]-“断”-按键_按键无反应",
            "field": "(manual_action)_z20_transmit_control_power_off", "abnormal_value": "not_done",
            "feature_id": "F_(manual_action)_z20_transmit_control_power_off_not_done",
            "why": "SOP line 139 只有“通”行（row50），无“断”行",
        },
        {
            "for_sop_line": 142, "cabinet": "Z5（收发机柜）", "sub_unit": "Z11（收发分机）（II路）",
            "module": "发射机 II 路", "step_name": "Z20（控制台）-[发射机控制]-[发射机工作]-[II]-指示灯亮",
            "phenomenon": "Z20（控制台）-[发射机控制]-[发射机工作]-[II]-指示灯_不亮",
            "field": "(led_indicator)_z20_transmitter_work_route_two", "abnormal_value": "off",
            "feature_id": "F_(led_indicator)_z20_transmitter_work_route_two_off",
            "why": "全库无 II路 子单元；这是整张表的结构性缺口，不只是一行",
        },
    ]

    z20 = {
        "part": "z20", "name": "控制台", "level": "cabinet", "schema": SCHEMA,
        "generated_at": NOW,
        "generated_by": "_criteria_override_build.py（只读 CSV，不改判据库/代码）",
        "source": {"sop_csv": SOP_CSV, "fault_csv": FAULT_CSV,
                   "sop_rows": len(sop), "fault_rows": len(faults)},
        "problem": "criteria_for('z20') 返回 0 行：故障真值表里没有 cabinet/sub_unit 为 Z20 的行，识别到控制台后无判据可挂。",
        "match_scope": "symptom",
        "owner_policy": "do_not_treat_as_owner",
        "diagnosis": {
            "dedicated_fault_rows": 0,
            "why_no_dedicated": "268 行的 cabinet 只有 Z6/Z5/Z4/Z31；sub_unit 无 Z20。criteria_for 对 z20 用 sub_keys=['Z20'] + 空 cab_keys（part_recognizer.py:1300-1303），因此命中 0。",
            "step_name_or_phenomenon_rows": len(step20),
            "field_only_rows": len(fieldonly20),
            "field_usable_rows": len(gradable20),
            "known_misalignment_rows": len(fieldonly20) + sum(1 for r in step20 if field_align(r) == "mismatch"),
            "sop_items": len(sop20),
            "sop_status": dict(Counter(x["status"] for x in sop_refs)),
            "owner_cabinets": ["Z5（收发机柜）", "Z6（操显机柜）"],
            "owner_parts": ["z11", "z12", "z14", "z18"],
        },
        "narrow_by": z20_rules,
        "allow_rows": [r["_row"] for r in step20],
        "excluded_rows": [
            {**row_ref(r), "why": "仅在 field 里出现 z20，step_name 是 Z11 灯或操显屏，已知列错位，不能算 Z20 面板判据"}
            for r in fieldonly20
        ],
        "row_refs": [
            row_ref(r, field_align(r), [topic_of(r["step_name"])]) for r in step20
        ],
        "sop_refs": sop_refs,
        "suggested_rows": suggested,
        "integration": {
            "semantics": "allow_rows 是绝对白名单；narrow_by 第一条 when 命中即按其 match 过滤。返回行必须带 match_scope='symptom'，并保留原 cabinet/sub_unit/module 作为故障归属。",
            "must_not": "不得把 26 行改写成 z20 自身故障；不得把 field-only 的 8 行算进 z20。",
            "gaps": "9 条 SOP 检查项在现表无对应行（power_control×3、manual_control×4、transmit_control_off×1、transmitter_work_II×1）；suggested_rows 给出建议补法。",
        },
    }

    z5rows = [r for r in faults if "Z5" in r["cabinet"].upper()]
    assert len(z5rows) == 63

    def sel(*, sub=None, mod=None, field_pref=None):
        out = []
        for r in z5rows:
            if sub and not any(k in r["sub_unit"] for k in sub):
                continue
            if mod and not any(k in r["module"] for k in mod):
                continue
            if field_pref is not None:
                f = r["field"].strip()
                if not any(f.startswith(p) for p in field_pref if p) and not ("" in field_pref and not f):
                    continue
            out.append(r["_row"])
        return out

    def box(rows):
        return {
            "keep_rows": len(rows), "result_rows": rows,
            "gradable_rows": [x for x in rows if by_row[x]["field"].strip()],
        }

    r_z11 = sel(sub=["Z11"])
    r_z12 = sel(sub=["Z12"])
    r_sw = sel(sub=["两路转换"])
    r_z111 = sel(sub=["Z11"], mod=["频综"])
    r_z113 = sel(sub=["Z11"], mod=["固态功放"])
    r_z114 = sel(sub=["Z11"], mod=["接收前端"])
    r_z115 = sel(sub=["Z11"], mod=["近程增益"])
    r_vision = sel(field_pref=["(image)", "(led_indicator)"])

    assert len(r_z11) == 38 and len(r_z12) == 22 and len(r_sw) == 3
    assert len(r_z111) == 18 and len(r_z113) == 8 and len(r_z114) == 2 and len(r_z115) == 2
    assert len(r_vision) == 34

    z5_rules = [
        {"id": "module_z11_1", "when": {"recognized_part": ["z11-1"]},
         "match": {"sub_unit_contains": ["Z11"], "module_contains": ["频综"]},
         **box(r_z111),
         "purpose": "识别到频综时只留 Z11-1 的 18 行（5 个模块：无供电/10M/400M/9000M/9400M）。"},
        {"id": "module_z11_3", "when": {"recognized_part": ["z11-3"]},
         "match": {"sub_unit_contains": ["Z11"], "module_contains": ["固态功放"]},
         **box(r_z113), "purpose": "识别到固态功放时只留 8 行。"},
        {"id": "module_z11_4", "when": {"recognized_part": ["z11-4"]},
         "match": {"sub_unit_contains": ["Z11"], "module_contains": ["接收前端"]},
         **box(r_z114), "purpose": "识别到接收前端时只留 2 行。"},
        {"id": "module_z11_5", "when": {"recognized_part": ["z11-5"]},
         "match": {"sub_unit_contains": ["Z11"], "module_contains": ["近程增益"]},
         **box(r_z115), "purpose": "识别到近程增益时只留 2 行。"},
        {"id": "sub_unit_z11", "when": {"recognized_part": ["z11"]},
         "match": {"sub_unit_contains": ["Z11"]},
         **box(r_z11), "purpose": "识别到 Z11 收发分机（未到模块）时留 38 行，仍比 63 少 25 行。"},
        {"id": "sub_unit_z12", "when": {"recognized_part": ["z12"]},
         "match": {"sub_unit_contains": ["Z12"]},
         **box(r_z12), "purpose": "识别到 Z12 电源分机时留 22 行。"},
        {"id": "route_switch", "when": {"text_contains_any": ["两路转换"]},
         "match": {"sub_unit_contains": ["两路转换"]},
         **box(r_sw), "purpose": "两路转换相关证据只留 3 行（微动开关/电机/转接件）。"},
        {"id": "vision_only", "when": {"modality": "vision"},
         "match": {"field_prefix_any": ["(image)", "(led_indicator)"]},
         **box(r_vision),
         "purpose": "纯视觉采集时只留 field 可判的 34 行（image 22 + led_indicator 12）；29 行 field 为空，视觉判不了，必须转人工/QA。"},
    ]

    z5 = {
        "part": "z5", "name": "收发机柜", "level": "cabinet", "schema": SCHEMA,
        "generated_at": NOW,
        "generated_by": "_criteria_override_build.py（只读 CSV，不改判据库/代码）",
        "source": {"sop_csv": SOP_CSV, "fault_csv": FAULT_CSV,
                   "sop_rows": len(sop), "fault_rows": len(faults)},
        "problem": "criteria_for('z5') 返回 63 行（cabinet=Z5 全柜），无法定位到具体分机/模块，现场会拿整柜判据乱套。",
        "match_scope": "cabinet",
        "diagnosis": {
            "cabinet_rows": 63,
            "row_range": [14, 76],
            "by_sub_unit": {"Z11（收发分机）(I路)": 38, "Z12（电源分机）(I路)": 22, "两路转换（两路）": 3},
            "by_field_prefix": {"(image)": 22, "(led_indicator)": 12, "EMPTY": 29},
            "by_route": {"I": 60, "unmarked": 3, "II": 0},
            "note": "Z5 的 63 行 = Z11 38 + Z12 22 + 两路转换 3；其中 60 行 sub_unit 带 (I路)，3 行两路转换不带路别；全库没有 II路 子单元。",
        },
        "narrow_by": z5_rules,
        "allow_rows": list(range(14, 77)),
        "default": {
            "keep_rows": 63,
            "need_narrow": True,
            "why": "只有“这是 Z5 柜”而没有子单元/模块/文字线索时，不能假装已定位；保留 63 行但置 need_narrow=true，让 UI 追问或补拍门牌。",
        },
        "coverage": {
            "before": 63,
            "after": {
                "module_z11_1": {"rows": 18, "pct": 28.6},
                "module_z11_3": {"rows": 8, "pct": 12.7},
                "module_z11_4": {"rows": 2, "pct": 3.2},
                "module_z11_5": {"rows": 2, "pct": 3.2},
                "sub_unit_z11": {"rows": 38, "pct": 60.3},
                "sub_unit_z12": {"rows": 22, "pct": 34.9},
                "route_switch": {"rows": 3, "pct": 4.8},
                "vision_only": {"rows": 34, "pct": 54.0},
            },
            "dropped_by_vision_only": 29,
        },
        "row_refs": [
            row_ref(r, field_align(r) if r["field"].strip() else "empty",
                    [topic_of(r["step_name"])]) for r in z5rows
        ],
        "integration": {
            "semantics": "先 allow_rows（=Z5 全部 63 行），再按 narrow_by 第一条 when 命中的 match 收窄；无规则命中时返回 63 行 + need_narrow=true。",
            "precedence": "module_* 必须先于 sub_unit_* 判断（z11-1 同时满足 z11）。",
            "must_not": "不得在只识别到 z5 时把 63 行当“z5 自身故障”；不得忽略 29 行空 field 的不可视觉判定性。",
        },
    }

    data = OrderedDict([("z20", z20), ("z5", z5)])
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("wrote", OUT)
    print("z20: step=%d fieldonly=%d allow=%d gradable=%d sop=%s" % (
        len(step20), len(fieldonly20), len(z20["allow_rows"]), len(gradable20),
        dict(Counter(x["status"] for x in sop_refs))))
    print("z5: rows=%d z11=%d z12=%d sw=%d z11-1=%d z11-3=%d vision=%d" % (
        len(z5rows), len(r_z11), len(r_z12), len(r_sw), len(r_z111), len(r_z113), len(r_vision)))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
