#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qa_flow.py —— 民航下滑台/航向台「交互问答确认」流程引擎（60 项）。

职责
----
1. 从判据库 `判据库_SOP.csv` / `判据库_故障.csv` **生成** `qa_items.json`
   （按 SOP flow_no 顺序，只取 method 含「交互问答确认」的 60 项）。
2. 运行问答状态机：start / current / answer / next / skip / summary。
3. 输出**与多模态统一格式一致**的结构化证据（任务 6 键 + evidence/v1 的 evidence/ts）：
       {"part": "z20", "route": "I", "modality": "qa",
        "field": "(manual_action)_z20_transmit_control_power_on",
        "value": "not_done", "confidence": 1.0, "note": "操作员确认：未执行",
        "evidence": "Z20 （I）路发射控制：未执行",
        "ts": "2026-10-18T09:20:00+08:00", "source": "qa_flow.QAFlow"}
4. 给 UI（1024x600 触摸）直接渲染的题目 + 大按钮 rect / action。

设计约束
--------
* **只读判据库，绝不改写**；本文件只写 engine/ 下的 qa_items.json（--build 时）。
* 不 import cv2 / numpy / 相机 / 触摸 —— 纯标准库，PC 与板端都能跑。
* `part` 取 Z 编号（同一元件同一 z；I/II 路用 route 区分位置）。
* `value` 用判据库 abnormal_value 词表（not_done / no_move / no_reaction /
  under_voltage / over_voltage / abnormal / start_fail / done / skipped），
  这样 `F_{field}_{value}` 可直接与故障真值库的 feature_id 对齐。

用法
----
    python3 qa_flow.py --build          # 重新生成 qa_items.json（需要判据库）
    python3 qa_flow.py --selfcheck      # 自检（板端可跑，只依赖 qa_items.json）
    python3 qa_flow.py --list           # 按 flow 打印 60 项清单
    python3 qa_flow.py --demo           # 全部答"正常"并打印 summary
    python3 qa_flow.py --interactive    # 终端逐题问答（无 GUI 时人工验证）
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

__version__ = "1.0.0"
SCHEMA = "qa_items/v1"
SUMMARY_SCHEMA = "qa_summary/v1"

ENGINE_DIR = Path(__file__).resolve().parent
BASE_DIR = ENGINE_DIR.parent
SOP_CSV = BASE_DIR / "判据库_SOP.csv"
FAULT_CSV = BASE_DIR / "判据库_故障.csv"
ITEMS_JSON = ENGINE_DIR / "qa_items.json"

METHOD_QA = "交互问答确认"
CANVAS_W, CANVAS_H = 1024, 600

VALUE_VOCAB = {
    "done": "正常 / 动作完成（无异常证据）",
    "no_reaction": "按键/开关无反应",
    "not_done": "未执行 / 未动作 / 未测量（人工确认未做）",
    "no_move": "机构无动作 / 不随动",
    "start_fail": "无法启动",
    "under_voltage": "欠压（低于正常范围）",
    "over_voltage": "过压（高于正常范围）",
    "abnormal": "性能/功能异常（不细分为具体数值）",
    "skipped": "跳过（未验证，不是「正常」）",
}

_TONE = {"done": "ok", "skip": "neutral"}

def _clean(text: Any) -> str:
    """去掉换行/连续空白，保留中文标点。"""
    if text is None:
        return ""
    s = str(text).replace("\r", " ").replace("\n", " ").replace("\u3000", " ")
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()

def _flow_index(flow_no: Any) -> int:
    m = re.match(r"\s*(\d+)", str(flow_no or ""))
    return int(m.group(1)) if m else 10 ** 6

def _sub_key(sub_no: Any) -> str:
    return _clean(sub_no)

def _flow_key(flow_no: Any) -> str:
    """SOP 的 flow_no 可能是 "5(5-I)"/"16（10-II）"；引擎内部用前导数字作稳定键。"""
    idx = _flow_index(flow_no)
    return str(idx) if idx != 10 ** 6 else _clean(flow_no)

def _route(row: Dict[str, str]) -> str:
    """I/II 路（也是操显/领显两条链的位置编号）。无路别返回 ""。"""
    flow_no = _clean(row.get("flow_no"))
    if _flow_key(flow_no) == "24":             
        return "I"
    m = re.search(r"[-－]\s*(I{1,2})\s*[)）]\s*$", flow_no)
    if m:
        return m.group(1)
    text = " ".join((flow_no, _clean(row.get("flow_name")), _clean(row.get("check_item"))))
    if (re.search(r"[（(]\s*II\s*[)）]", text) or "（II）路" in text
            or "(II)路" in text or "领显" in text):
        return "II"
    if (re.search(r"[（(]\s*I\s*[)）]", text) or "（I）路" in text
            or "(I)路" in text or "操显" in text):
        return "I"
    return ""

def _position(row: Dict[str, str]) -> str:
    text = _clean(row.get("check_item")) + " " + _clean(row.get("flow_name"))
    if "操显" in text:
        return "操显"
    if "领显" in text:
        return "领显"
    return ""

def _control(row: Dict[str, str]) -> str:
    item = _clean(row.get("check_item"))
    if "内控" in item:
        return "内控"
    if "外控" in item:
        return "外控"
    if "手操控制" in item:
        return "手操"
    return ""

def _kind(row: Dict[str, str]) -> str:
    item = _clean(row.get("check_item"))
    if "电压测量" in item:
        return "voltage"
    if "测量选择" in item or "各路电压" in item:
        return "multi_voltage"
    if "手操控制" in item:
        return "switch"
    if "两路转换" in item:
        return "switch_route"
    if "中间柜" in item:
        return "switch_override"

    if any(k in item for k in ("下滑左", "下滑右", "航向俯", "航向仰")):
        return "move"
    if "外控" in item:
        return "switch_external"
    if "发射控制" in item:
        return "key_power"
    if "天线启动" in item:
        return "key_power"
    if "天线主运动" in item:
        return "motion"
    if "F7" in item or "F2" in item:
        return "key_fn"
    if "自动录取" in item:
        return "track"
    if any(k in item for k in ("发射功率", "发射频率", "噪声系数", "近程增益", "中放增益")):
        return "perf"
    if "电源" in item or "Modem" in item:
        return "key_power"
    return "key_power"

_OPTION_SPECS: Dict[str, List[Tuple[str, str, str]]] = {
    "key_power": [
        ("done", "正常 ✔", "ok"),
        ("no_reaction", "无反应 ✗", "bad"),
        ("not_done", "未执行 ✗", "bad"),
    ],
    "switch": [
        ("done", "正常 ✔", "ok"),
        ("no_reaction", "无反应 ✗", "bad"),
        ("not_done", "未动作 ✗", "bad"),
    ],
    "switch_route": [
        ("done", "正常 ✔", "ok"),
        ("no_reaction", "无反应 ✗", "bad"),
        ("not_done", "未动作 ✗", "bad"),
    ],
    "switch_external": [
        ("done", "正常 ✔", "ok"),
        ("no_reaction", "无反应 ✗", "bad"),
        ("not_done", "未动作 ✗", "bad"),
    ],
    "switch_override": [
        ("done", "正常 ✔", "ok"),
        ("not_done", "外控未生效 ✗", "bad"),
        ("no_reaction", "无反应 ✗", "bad"),
    ],
    "move": [
        ("done", "正常 ✔", "ok"),
        ("no_move", "无动作 ✗", "bad"),
        ("not_done", "未测试 ✗", "bad"),
    ],
    "motion": [
        ("done", "正常 ✔", "ok"),
        ("start_fail", "无法启动 ✗", "bad"),
        ("not_done", "未执行 ✗", "bad"),
    ],
    "voltage": [
        ("done", "正常 ✔", "ok"),
        ("under_voltage", "欠压 ✗", "bad"),
        ("over_voltage", "过压 ✗", "bad"),
        ("not_done", "未测量 ✗", "bad"),
    ],
    "multi_voltage": [
        ("done", "正常 ✔", "ok"),
        ("abnormal", "异常 ✗", "bad"),
        ("not_done", "未测量 ✗", "bad"),
    ],
    "perf": [
        ("done", "正常 ✔", "ok"),
        ("abnormal", "异常 ✗", "bad"),
        ("not_done", "未测量 ✗", "bad"),
    ],
    "key_fn": [
        ("done", "正常 ✔", "ok"),
        ("no_reaction", "无反应 ✗", "bad"),
        ("not_done", "未执行 ✗", "bad"),
    ],
    "track": [
        ("done", "正常 ✔", "ok"),
        ("abnormal", "不跟踪 ✗", "bad"),
        ("not_done", "未测试 ✗", "bad"),
    ],
}

def _label_plain(label: str) -> str:
    """去掉 ✔/✗：板端 WQY 字体没有这些字形（见 ui_kiosk.py 第 565 行注释）。"""
    return label.replace("✔", "").replace("✗", "").strip()

_DIRECTION = {
    "下滑左": "glide_left",
    "下滑右": "glide_right",
    "航向俯": "course_down",
    "航向仰": "course_up",
}

_PERF_SLUG = {
    "发射功率": "transmit_power",
    "发射频率": "transmit_frequency",
    "接收机噪声系数": "receiver_noise_figure",
    "近程增益控制": "near_gain_control",
    "中放增益控制": "if_gain_control",
}

_VOLTAGE_PHASE = {"1": "a", "2": "b", "3": "c"}

_FIELD_BY_FLOW_SUB = {
    ("2", "1"): "(manual_action)_z31_control_power_on",
    ("4", "1"): "(manual_action)_z20_mains_power_on",
    ("5", "1"): "(manual_action)_route_one_z12_power_on",
    ("6", "1"): "(manual_action)_route_two_z12_power_on",
    ("6", "2"): "(manual_action)_route_two_z12_internal_supply_check",
    ("7", "1"): "(manual_action)_middle_cabinet_external_control_override",
    ("7", "2"): "(manual_action)_switch_to_route_one",
    ("9", "1"): "(manual_action)(operator_display)_z14_power_on",
    ("10", "1"): "(manual_action)(pilot_display)_z14_power_on",
    ("11", "1"): "(manual_action)(operator_display)_z15_display_power_on",
    ("12", "1"): "(manual_action)(pilot_display)_z15_display_power_on",
    ("13", "1"): "(manual_action)(operator_display)_z15_modem_power_on",
    ("14", "1"): "(manual_action)(pilot_display)_z15_modem_power_on",
    ("15", "1"): "(manual_action)(operator_display)_z16_indicator_power_on",
    ("16", "1"): "(manual_action)(pilot_display)_z16_indicator_power_on",
    ("15", "10"): "(manual_action)_z20_manual_control_switch_internal",
    ("15", "15"): "(manual_action)_z20_manual_control_switch_external",
    ("16", "9"): "(manual_action)_z20_manual_control_switch_internal",
    ("16", "15"): "(manual_action)_z20_manual_control_switch_external",
    ("17", "1"): "(manual_action)_z20_range_40km",
    ("17", "2"): "(manual_action)_z20_simulated_target_auto_track",
    ("17", "3"): "(manual_action)(operator_display)_auto_acquisition_tracking_course",
    ("17", "4"): "(manual_action)(operator_display)_auto_acquisition_tracking_glide",
    ("19", "1"): "(manual_action)_z20_antenna_start_power_on",
    ("19", "4"): "(manual_action)_antenna_main_motion",
    ("20", "1"): "(manual_action)_z11_external_control",
    ("20", "2"): "(manual_action)_switch_to_route_one",
    ("21", "1"): "(manual_action)_z20_transmit_control_power_on",
    ("24", ""): "(manual_action)_z20_transmit_control_power_off",
    ("25", "1"): "(manual_action)_switch_to_route_two",
    ("26", "1"): "(manual_action)_z20_transmit_control_power_on",
}

def _part(row: Dict[str, str], kind: str) -> Tuple[str, str]:
    """返回 (part, origin)。part 为 z 编号小写；origin=check_item/rule/fallback。"""
    item = _clean(row.get("check_item"))
    flow, sub = _flow_key(row.get("flow_no")), _sub_key(row.get("sub_no"))
    m = re.search(r"[Zz]\s*(\d{1,2})", item)
    if m:
        return "z" + m.group(1), "check_item"
    if (flow, sub) == ("7", "1"):

        return "z5", "rule"
    if kind == "move":
        return "z4", "rule"                       
    if flow in ("15", "16"):
        return "z4", "rule"                       
    if flow == "17" and sub in ("3", "4"):
        return "z15", "rule"                      
    if flow == "17":
        return "z20", "rule"                      
    if flow == "19" and sub == "4":
        return "z4", "rule"                       
    if kind == "perf":
        return "z11", "rule"                      
    m = re.search(r"[Zz]\s*(\d{1,2})", _clean(row.get("flow_name")))
    if m:
        return "z" + m.group(1), "flow_name"
    return "z0", "fallback"

def _evidence_field(row: Dict[str, str], kind: str, part: str, route: str) -> str:
    flow, sub = _flow_key(row.get("flow_no")), _sub_key(row.get("sub_no"))
    subject = _clean(row.get("subject"))
    item = _clean(row.get("check_item"))
    key = (flow, sub)
    if kind == "move":
        direction = ""
        for zh, en in _DIRECTION.items():
            if zh in item:
                direction = en
                break
        if "内控" in item:
            return "(manual_action)_internal_control_" + direction
        who = "operator_display" if "操显" in item else ("pilot_display" if "领显" in item else "operator_display")
        return "(manual_action)(%s)_external_control_%s" % (who, direction)
    if kind == "voltage":
        phase = _VOLTAGE_PHASE.get(sub, "a")
        return "(manual_action)_z18_phase_%s_voltage" % phase
    if kind == "perf":
        slug = _PERF_SLUG.get(subject, "performance")
        route_word = "one" if route == "I" else "two"
        return "(manual_action)_route_%s_z11_%s" % (route_word, slug)
    if key in _FIELD_BY_FLOW_SUB:
        return _FIELD_BY_FLOW_SUB[key]

    safe = re.sub(r"[^0-9a-zA-Z_]+", "_", subject) or ("flow_%s_sub_%s" % (flow, sub))
    return "(manual_action)_%s_%s" % (part, safe.strip("_").lower())

_NORMAL_TEXT = {
    "voltage": "198V～242V（三相 380V 系统相电压）",
    "multi_voltage": "各档电压示数均在额定范围（+15V / +12V-II / +12V-I / +11V / +5V / -5V / -12V-II / -12V-I / -15V）",
    "switch": "切换到位、无卡滞，对应状态指示正确",
    "switch_route": "两路转换到位，对应路工作指示灯亮，收发链路随路切换",
    "switch_external": "置外控后由控制台外控接管，动作响应正确",
    "switch_override": "置外控后外控生效、内控失效，切换无回跳",
    "move": "对应方向机构正常随动（无卡滞、无反向、无限位误动作）",
    "motion": "天线正常启动并连续转动，无异常停转",
    "track": "目标自动录取并稳定跟踪（无丢失、无漂移）",
    "perf": "读数 / 现象在技术条件正常范围内（按本机自检 / 仪表判据）",
}

def _power_target(row: Dict[str, str], route: str) -> str:
    flow = _flow_key(row.get("flow_no"))
    sub = _sub_key(row.get("sub_no"))
    pos = _position(row) or ("操显" if route == "I" else ("领显" if route == "II" else ""))
    rword = "（I）路" if route == "I" else ("（II）路" if route == "II" else "")
    if flow == "2":
        return "Z31 控制电源"
    if flow == "4":
        return "Z20 工频电源"
    if flow in ("5", "6"):
        return "%s Z12 电源" % rword
    if flow in ("9", "10"):
        return "%s Z14（信处）电源" % pos
    if flow in ("11", "12"):
        return "%s Z15（显示电路）电源" % pos
    if flow in ("13", "14"):
        return "%s Z15 Modem 电源" % pos
    if flow in ("15", "16") and sub == "1":
        return "%s Z16（指示分机）电源" % pos
    if flow in ("21", "26"):
        return "%s发射控制" % rword
    if flow == "24":
        return "（I）路发射控制（断开）"
    if flow == "19":
        return "天线启动"
    return _clean(row.get("subject")) or "设备"

def _question(row: Dict[str, str], kind: str, part: str, route: str) -> str:
    item = _clean(row.get("check_item"))
    subject = _clean(row.get("subject"))
    flow = _flow_key(row.get("flow_no"))
    if kind == "voltage":
        return "测量 %s %s：读数是否在 198V～242V？" % (part.upper(), subject)
    if kind == "multi_voltage":
        return "旋转 Z12 测量选择开关逐档检查：各路电压示数是否均正常？"
    if kind == "key_power":
        target = _power_target(row, route)
        verb = "断开" if ("断" in item and "通" not in item) else "接通"
        return "按下「%s」后，%s是否正常%s？" % (item, target, verb)
    if kind == "switch":
        pos = "内" if item.endswith("内") else ("外" if item.endswith("外") else "")
        return "将 Z20 手操控制开关置「%s」：切换是否正常到位？" % pos
    if kind == "switch_route":
        return "切换两路转换开关：是否正常到位（对应路工作指示正常）？"
    if kind == "switch_override":
        return "将中间柜开关置「外控」：外控是否生效、内控是否失效？"
    if kind == "switch_external":
        return "将 Z11（收发）置「外控」：外控接管是否正常？"
    if kind == "move":
        return "%s：操作后指示 / 机构是否正常随动？" % (subject or item)
    if kind == "motion":
        return "按下天线启动后：天线主运动是否正常启动并连续转动？"
    if kind == "key_fn":
        if "F7" in item:
            return "按 F7（单击）：量程是否切换到 40KM？"
        return "按 F2（单击）：是否进入模拟目标并置自动录取与跟踪？"
    if kind == "track":
        return "%s：自动录取与跟踪是否正常？" % subject
    if kind == "perf":
        return "%s：读数 / 现象是否在正常范围内？" % subject
    return "%s：是否正常？" % (subject or item)

def _evidence_subject(row: Dict[str, str], kind: str, route: str) -> str:
    """证据里的一句人话用主语（subject 可能有判据库笔误，如天线启动写成雷达工频通）。"""
    item = _clean(row.get("check_item"))
    if kind == "key_power":
        return _power_target(row, route)
    if kind == "switch":
        pos = "内" if item.endswith("内") else ("外" if item.endswith("外") else "")
        return "手操控制开关" + (("（%s）" % pos) if pos else "")
    if kind == "switch_route":
        return "两路转换" + (("（%s 路）" % route) if route else "")
    if kind == "switch_override":
        return "中间柜外控"
    if kind == "switch_external":
        return "Z11 外控"
    if kind == "motion":
        return "天线主运动"
    if kind == "key_fn":
        return "F7 量程切换" if "F7" in item else "F2 模拟目标"
    return _clean(row.get("subject")) or item

def _normal(row: Dict[str, str], kind: str, route: str) -> str:
    if kind == "key_power":
        target = _power_target(row, route)
        flow = _flow_key(row.get("flow_no"))
        if flow == "24":
            return "%s正常断开，发射机停止工作" % target
        return "%s正常接通，动作到位（以现场指示灯 / 声响为准）" % target
    if kind == "key_fn":
        return "量程切换为 40KM 并稳定显示" if "F7" in _clean(row.get("check_item")) \
            else "进入模拟目标状态，自动录取与跟踪生效"
    return _NORMAL_TEXT.get(kind, "动作 / 指示正常，无异常现象")

def _read_csv(path: Path) -> List[Dict[str, str]]:
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def _now_iso() -> str:
    """与 fusion.py now_iso() 一致：本地时区 ISO-8601（秒级）。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")

def _feature_lookup(faults: Iterable[Dict[str, str]]) -> Dict[Tuple[str, str], str]:
    """(field, abnormal_value) -> feature_id，只收真值库中非空且以 F_ 开头的。"""
    out: Dict[Tuple[str, str], str] = {}
    for f in faults:
        field = _clean(f.get("field"))
        value = _clean(f.get("abnormal_value"))
        fid = _clean(f.get("feature_id"))
        if field and value and fid.startswith("F_"):
            out[(field, value)] = fid
    return out

_POWER_BAD = ["not_done", "no_reaction"]

def _build_dependency_specs() -> List[Tuple[Tuple[str, str], Tuple[str, str], List[str], str]]:
    deps: List[Tuple[Tuple[str, str], Tuple[str, str], List[str], str]] = []

    def add(target: Tuple[str, str], source: Tuple[str, str], values: List[str], reason: str) -> None:
        deps.append((target, source, values, reason))

    for sub in ("1", "2", "3"):
        add(("3", sub), ("2", "1"), _POWER_BAD, "上游 Z31 控制电源未通")
    add(("4", "1"), ("2", "1"), _POWER_BAD, "上游 Z31 控制电源未通")
    add(("5", "1"), ("4", "1"), _POWER_BAD, "上游 Z20 工频电源未通")
    add(("6", "1"), ("4", "1"), _POWER_BAD, "上游 Z20 工频电源未通")
    add(("6", "2"), ("6", "1"), _POWER_BAD, "（II）路 Z12 电源未通，各路电压测量无效")
    for flow in ("9", "10", "11", "12", "13", "14", "15", "16"):
        add((flow, "1"), ("4", "1"), _POWER_BAD, "上游 Z20 工频电源未通")

    add(("15", "10"), ("15", "1"), _POWER_BAD, "操显 Z16 指示分机电源未通")
    for sub in ("11", "12", "13", "14"):
        add(("15", sub), ("15", "10"), _POWER_BAD, "手操控制未切到「内」")
    add(("15", "15"), ("15", "1"), _POWER_BAD, "操显 Z16 指示分机电源未通")
    for sub in ("16", "17", "18", "19"):
        add(("15", sub), ("15", "15"), _POWER_BAD, "手操控制未切到「外」")

    add(("16", "9"), ("16", "1"), _POWER_BAD, "领显 Z16 指示分机电源未通")
    for sub in ("11", "12", "13", "14"):
        add(("16", sub), ("16", "9"), _POWER_BAD, "手操控制未切到「内」")
    add(("16", "15"), ("16", "1"), _POWER_BAD, "领显 Z16 指示分机电源未通")
    for sub in ("16", "17", "18", "19"):
        add(("16", sub), ("16", "15"), _POWER_BAD, "手操控制未切到「外」")

    add(("17", "1"), ("4", "1"), _POWER_BAD, "Z20 工频电源未通")
    add(("17", "2"), ("17", "1"), _POWER_BAD, "未切换到 40KM")
    for sub in ("3", "4"):
        add(("17", sub), ("17", "2"), _POWER_BAD, "未进入模拟目标 / 自动录取跟踪")
        add(("17", sub), ("9", "1"), _POWER_BAD, "操显 Z14（信处）电源未通")

    add(("19", "4"), ("19", "1"), _POWER_BAD, "天线启动未接通")

    add(("20", "1"), ("7", "1"), ["not_done"], "中间柜外控未生效")
    add(("20", "1"), ("7", "2"), _POWER_BAD, "两路转换未切到（I）路")
    add(("21", "1"), ("5", "1"), _POWER_BAD, "（I）路 Z12 电源未通")
    add(("21", "1"), ("7", "2"), _POWER_BAD, "两路转换未切到（I）路")
    add(("21", ""), ("21", "1"), _POWER_BAD, "发射控制未接通")   
    add(("24", ""), ("21", "1"), _POWER_BAD, "发射控制此前未接通")

    add(("25", "1"), ("24", ""), _POWER_BAD, "发射控制未断开，禁止带功率切换（II）路")
    add(("26", "1"), ("25", "1"), _POWER_BAD, "两路未转换到（II）路")
    add(("26", "1"), ("6", "1"), _POWER_BAD, "（II）路 Z12 电源未通")
    add(("26", ""), ("26", "1"), _POWER_BAD, "发射控制（II）未接通")  
    return deps

def _button_rects(n: int, x0: int = 24, y0: int = 486, x1: int = 1000, y1: int = 584,
                  gap: int = 12) -> List[List[int]]:
    n = max(1, min(4, int(n)))
    total = x1 - x0
    w = (total - gap * (n - 1)) // n
    rem = total - gap * (n - 1) - w * n
    rects, x = [], x0
    for i in range(n):
        wi = w + (1 if i < rem else 0)
        rects.append([x, y0, x + wi, y1])
        x += wi + gap
    return rects

def _attach_skip_if(items: List[Dict[str, Any]]) -> None:
    groups: Dict[Tuple[str, str], List[str]] = {}
    by_id = {it["qa_id"]: it for it in items}
    for it in items:
        groups.setdefault((_flow_key(it["flow_no"]), _sub_key(it["sub_no"])), []).append(it["qa_id"])
    deps = _build_dependency_specs()
    for it in items:
        it["skip_if"] = None
    for target, source, values, reason in deps:
        target_ids = groups.get(target)
        source_ids = groups.get(source)
        if not target_ids:
            raise ValueError("依赖目标不存在: flow=%s sub=%s" % target)
        if not source_ids:
            raise ValueError("依赖来源不存在: flow=%s sub=%s" % source)
        src = by_id[source_ids[0]]
        for qid in target_ids:
            it = by_id[qid]
            si = it.get("skip_if") or {"mode": "any", "rules": [],
                                       "reason": "上游步骤异常或未执行 → 本项无法验证（可手动继续作答）"}
            si["rules"].append({
                "qa_id": src["qa_id"],
                "flow_no": src["flow_no"],
                "check_item": src["check_item"],
                "values": list(values),
                "reason": reason,
            })
            it["skip_if"] = si

def build_items(sop_csv: Path = SOP_CSV, fault_csv: Path = FAULT_CSV,
                items_json: Path = ITEMS_JSON) -> Dict[str, Any]:
    """从判据库生成 qa_items 数据（不写盘；save_items() 负责写）。"""
    if not Path(sop_csv).is_file():
        raise FileNotFoundError("找不到 SOP 判据库: %s" % sop_csv)
    if not Path(fault_csv).is_file():
        raise FileNotFoundError("找不到故障真值库: %s" % fault_csv)

    rows = _read_csv(Path(sop_csv))
    qa_rows = [r for r in rows if METHOD_QA in _clean(r.get("method"))]

    qa_rows.sort(key=lambda r: _flow_index(r.get("flow_no")))
    faults = _read_csv(Path(fault_csv))
    lookup = _feature_lookup(faults)
    total = len(qa_rows)

    items: List[Dict[str, Any]] = []
    for seq, row in enumerate(qa_rows, 1):
        qa_id = "QA%03d" % seq
        flow_no = _clean(row.get("flow_no"))
        flow_name = _clean(row.get("flow_name"))
        sub_no = _clean(row.get("sub_no"))
        check_item = _clean(row.get("check_item"))
        category = _clean(row.get("category"))
        subject = _clean(row.get("subject"))
        route = _route(row)
        kind = _kind(row)
        part, part_origin = _part(row, kind)
        field = _evidence_field(row, kind, part, route)
        options_raw = _OPTION_SPECS.get(kind) or _OPTION_SPECS["key_power"]
        rects = _button_rects(len(options_raw))
        options: List[Dict[str, Any]] = []
        abnormalities: List[Dict[str, Any]] = []
        related: List[str] = []
        for i, (value, label, tone) in enumerate(options_raw):
            opt: Dict[str, Any] = {
                "id": value,
                "value": value,
                "label": label,
                "label_plain": _label_plain(label),
                "tone": tone,
                "style": "primary" if value == "done" else "alt",
                "rect": rects[i],
                "action": "qa:%s" % value,
            }
            if value == "done":
                opt["feature_id"] = None
                opt["feature_source"] = None
            else:
                fid = lookup.get((field, value))
                opt["abnormal_value"] = value
                opt["feature_id"] = fid or ("F_%s_%s" % (field, value))
                opt["feature_source"] = "fault_library" if fid else "synthesized"
                if opt["feature_id"] not in related:
                    related.append(opt["feature_id"])
                abnormalities.append({
                    "code": value,
                    "label": _label_plain(label),
                    "value": value,
                    "abnormal_value": value,
                    "feature_id": opt["feature_id"],
                    "source": opt["feature_source"],
                })
            options.append(opt)

        question = _question(row, kind, part, route)
        normal = _normal(row, kind, route)
        ui = {
            "screen": {"w": CANVAS_W, "h": CANVAS_H},
            "title": "问答确认",
            "progress": "%d/%d" % (seq, total),
            "flow": flow_name,
            "question": question,
            "normal": "正常判据：" + normal,
            "part_chip": part.upper(),
            "route_chip": ("%s 路" % route) if route else "",
            "category_chip": category,
            "buttons": options,
            "skip_button": {
                "id": "skip", "value": "skipped", "label": "跳过", "label_plain": "跳过",
                "tone": "neutral", "style": "alt", "rect": [856, 36, 1000, 80],
                "action": "qa:skip",
            },
            "back_button": {
                "id": "back", "label": "返回", "label_plain": "返回",
                "tone": "neutral", "style": "alt", "rect": [24, 36, 136, 80],
                "action": "qa:back",
            },
            "hint": "点击大按钮作答；异常项会作为该部件的故障证据",
        }
        item: Dict[str, Any] = {
            "qa_id": qa_id,
            "seq": seq,
            "flow_no": flow_no,
            "flow_index": _flow_index(flow_no),
            "flow_name": flow_name,
            "sub_no": sub_no,
            "check_item": check_item,
            "category": category,
            "subject": subject,
            "phenomenon": _evidence_subject(row, kind, route) or subject or category,
            "evidence_subject": _evidence_subject(row, kind, route),
            "method": METHOD_QA,
            "part": part,
            "part_origin": part_origin,
            "route": route,
            "position": _position(row),
            "control": _control(row),
            "kind": kind,
            "normal": normal,
            "question": question,
            "evidence_field": field,
            "primary_feature_id": related[0] if related else None,
            "related_feature_ids": related,
            "abnormalities": abnormalities,
            "options": options,
            "measure": {"min": 198.0, "max": 242.0, "unit": "V"} if kind == "voltage" else None,
            "skip_if": None,
            "ui": ui,
        }
        items.append(item)

    _attach_skip_if(items)

    flows: List[str] = []
    for it in items:
        if it["flow_no"] not in flows:
            flows.append(it["flow_no"])
    data: Dict[str, Any] = {
        "schema": SCHEMA,
        "engine_version": __version__,
        "generated_by": "qa_flow.py build_items()  (python3 qa_flow.py --build)",
        "source": {
            "sop": Path(sop_csv).name,
            "faults": Path(fault_csv).name,
            "filter": "method 含「%s」" % METHOD_QA,
            "count": total,
            "sop_sha256": _sha256(Path(sop_csv)),
            "faults_sha256": _sha256(Path(fault_csv)),
        },
        "flow_order": flows,
        "value_vocab": VALUE_VOCAB,
        "ui_layout": {
            "screen": {"w": CANVAS_W, "h": CANVAS_H},
            "question_rect": [24, 104, 1000, 318],
            "normal_rect": [24, 330, 1000, 432],
            "button_row": [24, 486, 1000, 584],
            "skip_rect": [856, 36, 1000, 80],
            "back_rect": [24, 36, 136, 80],
            "progress_rect": [160, 36, 840, 80],
            "min_touch_px": 44,
            "font_note": "板端按钮请用 label_plain（WQY 字体没有 ✔/✗ 字形）",
        },
        "items": items,
    }
    return data

def save_items(data: Dict[str, Any], path: Path = ITEMS_JSON) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")
    return path

def load_items(path: Optional[Path] = None) -> Dict[str, Any]:
    path = Path(path) if path else ITEMS_JSON
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if data.get("schema") != SCHEMA:
        raise ValueError("qa_items schema 不匹配: %r（期望 %s）" % (data.get("schema"), SCHEMA))
    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("qa_items.json 里没有 items")
    ids = [it.get("qa_id") for it in items]
    if len(ids) != len(set(ids)):
        raise ValueError("qa_id 重复: %r" % ids)
    return data

_ALIASES = {
    "ok": "done", "yes": "done", "y": "done", "正常": "done", "完成": "done",
    "done": "done", "pass": "done",
    "no_reaction": "no_reaction", "无反应": "no_reaction", "没反应": "no_reaction",
    "不响应": "no_reaction",
    "not_done": "not_done", "未执行": "not_done", "未动作": "not_done",
    "未测试": "not_done", "未测量": "not_done", "no": "not_done",
    "no_move": "no_move", "无动作": "no_move", "不随动": "no_move",
    "start_fail": "start_fail", "无法启动": "start_fail", "启动失败": "start_fail",
    "under_voltage": "under_voltage", "欠压": "under_voltage",
    "over_voltage": "over_voltage", "过压": "over_voltage",
    "abnormal": "abnormal", "异常": "abnormal", "不正常": "abnormal",
    "不跟踪": "abnormal", "失效": "abnormal",
    "skipped": "skipped", "skip": "skipped", "跳过": "skipped", "未验证": "skipped",
}

def _parse_voltage(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(?:v|V|伏)?\s*", str(value))
    return float(m.group(1)) if m else None

class QAFlow:
    """60 项问答状态机。

    典型用法::

        flow = QAFlow()
        flow.start()
        while flow.current():
            if flow.answer("done"):      # 只记录答案
                flow.next()             # 再前进
        print(flow.summary()["evidence"])

    语义
    ----
    * `answer()` 只记录，不自动前进；`next()` 前进。
    * `skip()` 记录"跳过"并默认前进（跳过的项**不产生正常/异常证据**）。
    * `next(auto_skip=True)` 会按 `skip_if` 自动跳过（用于"电源没通 ⇒ 后续全部
      无法验证"的级联）；默认 `auto_skip=False`，只把 `skip_suggested=True`
      交给 UI 提示，操作员仍可强行作答。
    * 结构化证据 = 任务要求的 6 键（part/route/modality/field/value/confidence/note）
      + `evidence/v1` 契约要求的 `evidence` / `ts`（另带 source/item_id/flow_no/
      check_item 审计字段）。`schema_values=True` 时 value 映射到严格枚举
      （done→normal、no_reaction→not_done、over_voltage→abnormal），原始值放 `qa_value`。
    """

    def __init__(self, items_path: Optional[Path] = None, *, confidence: float = 1.0,
                 strict: bool = False, schema_values: bool = False) -> None:
        self.path = Path(items_path) if items_path else ITEMS_JSON
        self.data = load_items(self.path)
        self.items: List[Dict[str, Any]] = self.data["items"]
        self.total = len(self.items)
        self.confidence = float(confidence)
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence 必须在 [0,1]")
        self.strict = bool(strict)

        

        self.schema_values = bool(schema_values)
        self._by_id = {it["qa_id"]: it for it in self.items}
        self._index = 0
        self._answers: Dict[str, Dict[str, Any]] = {}

    @property
    def index(self) -> int:
        return self._index

    def _index_of(self, qa_id: str) -> int:
        qid = str(qa_id).strip().upper()
        if qid not in self._by_id:
            raise KeyError("未知 qa_id: %r（应为 QA001..QA%03d）" % (qa_id, self.total))
        return self.items.index(self._by_id[qid])

    def _require_current(self) -> Dict[str, Any]:
        cur = self.current()
        if cur is None:
            raise RuntimeError("问答流程已结束（%d/%d）" % (self.total, self.total))
        return cur

    def progress(self) -> Dict[str, Any]:
        answered = len(self._answers)
        return {
            "index": min(self._index + 1, self.total),
            "total": self.total,
            "answered": answered,
            "verified": sum(1 for r in self._answers.values() if not r["skipped"]),
            "skipped": sum(1 for r in self._answers.values() if r["skipped"]),
            "pending": self.total - answered,
            "percent": round(100.0 * answered / self.total, 1) if self.total else 0.0,
        }

    def _suggestion(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        si = item.get("skip_if")
        if not si or not si.get("rules"):
            return None
        matched: List[Dict[str, Any]] = []
        for rule in si["rules"]:
            ans = self._answers.get(rule["qa_id"])
            if not ans:
                continue
            if ans["value"] in rule.get("values", []) or (ans["skipped"] and ans.get("auto")):
                matched.append(rule)
        if not matched:
            return None
        if si.get("mode") == "all" and len(matched) < len(si["rules"]):
            return None
        detail = "；".join("%s「%s」" % (r["qa_id"], r["reason"]) for r in matched)
        return {"matched": matched, "qa_ids": [r["qa_id"] for r in matched], "detail": detail}

    def current(self) -> Optional[Dict[str, Any]]:
        """当前题（含 UI/按钮/是否建议跳过/已有答案）；流程结束返回 None。"""
        if not 0 <= self._index < self.total:
            return None
        item = self.items[self._index]
        sug = self._suggestion(item)
        view = dict(item)
        view["options"] = [dict(o) for o in item.get("options", [])]
        view["answer"] = self._answers.get(item["qa_id"])
        view["answered"] = view["answer"] is not None
        view["skip_suggested"] = bool(sug)
        view["skip_reason"] = sug["detail"] if sug else ""
        view["index"] = self._index + 1
        view["progress"] = "%d/%d" % (self._index + 1, self.total)
        return view

    def start(self, qa_id: Optional[str] = None, *, auto_skip: bool = False) -> Optional[Dict[str, Any]]:
        """清空答案并从第一题（或指定 qa_id）开始。"""
        self._answers.clear()
        self._index = 0 if qa_id is None else self._index_of(qa_id)
        if auto_skip:
            self._auto_skip_chain()
        return self.current()

    def reset(self) -> Optional[Dict[str, Any]]:
        return self.start()

    def jump(self, qa_id: str, *, auto_skip: bool = False) -> Optional[Dict[str, Any]]:
        """跳题（保留已答答案；用于回看/补答）。"""
        self._index = self._index_of(qa_id)
        if auto_skip:
            self._auto_skip_chain()
        return self.current()

    def next(self, *, auto_skip: bool = False) -> Optional[Dict[str, Any]]:
        """前进一题；`auto_skip=True` 时按 skip_if 级联自动跳过。"""
        if self._index >= self.total:
            return None
        if self.strict:
            cur = self.current()
            if cur is not None and not cur["answered"]:
                raise RuntimeError("当前题 %s 尚未作答（strict=True）" % cur["qa_id"])
        self._index += 1
        if auto_skip:
            self._auto_skip_chain()
        return self.current()

    def _auto_skip_chain(self) -> None:
        while self._index < self.total:
            item = self.items[self._index]
            sug = self._suggestion(item)
            if not sug:
                break
            self._record_skip(item, reason=sug["detail"], auto=True, blocked_by=sug["qa_ids"])
            self._index += 1

    def _record_skip(self, item: Dict[str, Any], *, reason: str, auto: bool,
                     blocked_by: Optional[List[str]]) -> Dict[str, Any]:
        subject = item.get("evidence_subject") or item.get("subject") or item["check_item"]
        prefix = "" if item["part"].upper() in subject.upper() else item["part"].upper() + " "
        rec = {
            "qa_id": item["qa_id"],
            "value": "skipped",
            "label": "跳过",
            "label_plain": "跳过",
            "skipped": True,
            "auto": bool(auto),
            "abnormal": False,
            "feature_id": None,
            "feature_source": None,
            "abnormal_value": None,
            "measured": None,
            "reason": reason,
            "blocked_by": list(blocked_by or []),
            "confidence": 0.0,
            "note": ("自动跳过：" if auto else "操作员跳过：") + reason,
            "evidence_text": "%s%s：跳过（未验证）" % (prefix, subject),
            "ts": _now_iso(),
            "evidence": None,
        }
        self._answers[item["qa_id"]] = rec
        return rec

    @staticmethod
    def _schema_value(value: str, enabled: bool) -> str:
        """QA 内部词 -> evidence/v1 严格枚举（仅在 schema_values=True 时）。"""
        if not enabled:
            return value
        return {"done": "normal", "no_reaction": "not_done",
                "over_voltage": "abnormal"}.get(value, value)

    def _resolve_option(self, item: Dict[str, Any], raw: Any) -> Dict[str, Any]:
        s = str(raw).strip()
        for opt in item.get("options", []):
            if s in (opt.get("value"), opt.get("id"), opt.get("label"), opt.get("label_plain")):
                return opt
        key = _ALIASES.get(s) or _ALIASES.get(s.lower())
        if key:
            for opt in item.get("options", []):
                if opt.get("value") == key:
                    return opt
        allowed = " / ".join("%s(%s)" % (o["value"], o["label_plain"]) for o in item.get("options", []))
        raise ValueError("无效答案 %r；本题可选: %s，或 skip()" % (raw, allowed))

    def answer(self, value: Any, *, note: str = "", confidence: Optional[float] = None) -> Dict[str, Any]:
        """回答当前题并返回记录（不自动前进）。

        * `value` 可为 option value / id / label / label_plain；
        * 电压题支持直接传数值或 "185V"：自动归入 under/over/done；
        * 传 "skip"/"跳过" 等价于 `skip(advance=False)`。
        """
        item = self._require_current()
        if isinstance(value, str) and value.strip() in ("skip", "skipped", "跳过", "未验证"):
            return self._record_skip(item, reason=note or "操作员跳过（未验证）",
                                     auto=False, blocked_by=[])

        measured: Optional[float] = None
        measure = item.get("measure")
        if measure and value not in ("done", "not_done"):
            num = _parse_voltage(value)
            if num is not None:
                measured = num
                lo, hi = float(measure["min"]), float(measure["max"])
                if num < lo:
                    value = "under_voltage"
                elif num > hi:
                    value = "over_voltage"
                else:
                    value = "done"

        opt = self._resolve_option(item, value)
        conf = self.confidence if confidence is None else float(confidence)
        if not 0.0 <= conf <= 1.0:
            raise ValueError("confidence 必须在 [0,1]")

        is_done = opt["value"] == "done"
        if is_done:
            note_txt = "操作员确认"
            if note:
                note_txt += "（%s）" % note
        else:
            note_txt = "操作员确认：%s" % opt.get("label_plain", opt["value"])
            if measured is not None:
                note_txt += "（实测 %g%s）" % (measured, (measure or {}).get("unit", ""))
            if note:
                note_txt += "；%s" % note

        emitted = self._schema_value(opt["value"], self.schema_values)
        feature_id = opt.get("feature_id")
        subject = item.get("evidence_subject") or item.get("subject") or item.get("check_item")
        prefix = "" if item["part"].upper() in subject.upper() else item["part"].upper() + " "
        if is_done:
            evidence_txt = "操作员确认：%s%s 正常" % (prefix, subject)
            if note:
                evidence_txt += "（%s）" % note
        else:
            evidence_txt = "%s%s：%s" % (prefix, subject,
                                          opt.get("label_plain", opt["value"]))
            if measured is not None:
                evidence_txt += "（实测 %g%s）" % (measured, (measure or {}).get("unit", ""))
            if note:
                evidence_txt += "；%s" % note
        evidence = {
            "part": item["part"],
            "route": item["route"],
            "modality": "qa",
            "field": item["evidence_field"],
            "value": emitted,
            "confidence": round(conf, 3),
            "note": note_txt,
            "evidence": evidence_txt,
            "ts": _now_iso(),
            "source": "qa_flow.QAFlow",
            "item_id": item["qa_id"],
            "flow_no": item["flow_no"],
            "check_item": item["check_item"],
        }
        if feature_id:
            evidence["feature_id"] = feature_id
        if emitted != opt["value"]:
            evidence["qa_value"] = opt["value"]
        rec = {
            "qa_id": item["qa_id"],
            "value": opt["value"],
            "emitted_value": emitted,
            "label": opt.get("label", opt["value"]),
            "label_plain": opt.get("label_plain", opt["value"]),
            "skipped": False,
            "auto": False,
            "abnormal": not is_done,
            "feature_id": opt.get("feature_id"),
            "feature_source": opt.get("feature_source"),
            "abnormal_value": None if is_done else opt["value"],
            "measured": measured,
            "reason": "",
            "blocked_by": [],
            "confidence": round(conf, 3),
            "note": note_txt,
            "evidence_text": evidence_txt,
            "ts": evidence["ts"],
            "evidence": evidence,
        }
        self._answers[item["qa_id"]] = rec
        return rec

    def skip(self, *, note: str = "操作员跳过（未验证）", advance: bool = True) -> Optional[Dict[str, Any]]:
        """记录"跳过（未验证）"；默认前进到下一题。"""
        item = self._require_current()
        self._record_skip(item, reason=note, auto=False, blocked_by=[])
        if advance:
            return self.next(auto_skip=False)
        return self.current()

    def abort(self) -> Dict[str, Any]:
        """中止流程（保留已答），返回 summary。"""
        self._index = self.total
        return self.summary()

    def evidence(self, *, include_skipped: bool = False) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for item in self.items:
            rec = self._answers.get(item["qa_id"])
            if not rec:
                continue
            if rec["skipped"]:
                if include_skipped:
                    out.append({
                        "part": item["part"],
                        "route": item["route"],
                        "modality": "qa",
                        "field": item["evidence_field"],
                        "value": "skipped",
                        "confidence": 0.0,
                        "note": rec["note"],
                        "evidence": rec.get("evidence_text", "跳过（未验证）"),
                        "ts": rec.get("ts") or _now_iso(),
                        "source": "qa_flow.QAFlow",
                        "item_id": item["qa_id"],
                        "flow_no": item["flow_no"],
                        "check_item": item["check_item"],
                    })
                continue
            out.append(rec["evidence"])
        return out

    def summary(self, *, include_skipped_evidence: bool = False) -> Dict[str, Any]:
        """结构化汇总：证据列表 + 计数 + 按部件/路别聚合 + 跳过/待答清单。"""
        evidence = self.evidence(include_skipped=include_skipped_evidence)
        by_value: Dict[str, int] = {}
        by_part: Dict[str, Dict[str, int]] = {}
        by_route: Dict[str, Dict[str, int]] = {}
        verified = abnormal = skipped = pending = 0
        skipped_items: List[Dict[str, Any]] = []
        pending_items: List[Dict[str, Any]] = []
        flow_coverage: Dict[str, int] = {}

        for item in self.items:
            flow_coverage[item["flow_no"]] = flow_coverage.get(item["flow_no"], 0) + 1
            rec = self._answers.get(item["qa_id"])
            p = by_part.setdefault(item["part"], {"total": 0, "done": 0, "abnormal": 0,
                                                  "skipped": 0, "pending": 0})
            r = by_route.setdefault(item["route"] or "-", {"total": 0, "done": 0, "abnormal": 0,
                                                           "skipped": 0, "pending": 0})
            for bucket in (p, r):
                bucket["total"] += 1
            if not rec:
                pending += 1
                p["pending"] += 1
                r["pending"] += 1
                pending_items.append({"qa_id": item["qa_id"], "flow_no": item["flow_no"],
                                      "check_item": item["check_item"]})
                continue
            by_value[rec["value"]] = by_value.get(rec["value"], 0) + 1
            if rec["skipped"]:
                skipped += 1
                p["skipped"] += 1
                r["skipped"] += 1
                skipped_items.append({
                    "qa_id": item["qa_id"],
                    "flow_no": item["flow_no"],
                    "check_item": item["check_item"],
                    "reason": rec["reason"],
                    "auto": rec["auto"],
                    "blocked_by": rec["blocked_by"],
                })
            elif rec["value"] == "done":
                verified += 1
                p["done"] += 1
                r["done"] += 1
            else:
                verified += 1
                abnormal += 1
                p["abnormal"] += 1
                r["abnormal"] += 1

        answered = len(self._answers)
        return {
            "schema": SUMMARY_SCHEMA,
            "engine_version": __version__,
            "total": self.total,
            "finished": self._index >= self.total,
            "complete": pending == 0,
            "answered": answered,
            "verified": verified,
            "abnormal": abnormal,
            "skipped": skipped,
            "pending": pending,
            "by_value": dict(sorted(by_value.items())),
            "by_part": dict(sorted(by_part.items())),
            "by_route": dict(sorted(by_route.items())),
            "flow_coverage": flow_coverage,
            "evidence": evidence,
            "skipped_items": skipped_items,
            "pending_items": pending_items,
            "progress": self.progress(),
        }

    def evidence_jsonl(self, *, include_skipped: bool = False) -> str:
        return "\n".join(json.dumps(e, ensure_ascii=False) for e in self.evidence(include_skipped=include_skipped))

    def evidence_batch(self, *, include_skipped: bool = False) -> Dict[str, Any]:
        """evidence/v1 批量包装（可直接给 fusion.py / fault_grader.py 的 --evidence）。"""
        return {
            "schema": "evidence/v1",
            "producer": "qa_flow.py",
            "engine_version": __version__,
            "evidence": self.evidence(include_skipped=include_skipped),
        }

    def __repr__(self) -> str:  
        return "<QAFlow %d/%d answered=%d>" % (self._index, self.total, len(self._answers))

def _flow_table(data: Dict[str, Any]) -> str:
    from collections import OrderedDict
    rows: "OrderedDict[str, List[Dict[str, Any]]]" = OrderedDict()
    for it in data["items"]:
        rows.setdefault(it["flow_no"], []).append(it)
    lines = ["| flow_no | 项数 | part | route | 覆盖子项 |", "|---|---|---|---|---|"]
    for flow, items in rows.items():
        parts = ",".join(sorted({i["part"].upper() for i in items}))
        routes = ",".join(sorted({i["route"] or "-" for i in items}))
        subs = ",".join(i["sub_no"] or "-" for i in items)
        lines.append("| %s | %d | %s | %s | %s |" % (flow, len(items), parts, routes, subs))
    return "\n".join(lines)

def _cmd_build(args: argparse.Namespace) -> int:
    data = build_items(Path(args.sop), Path(args.faults), Path(args.items))
    path = save_items(data, Path(args.items))
    print("[build] %d 项 / %d 个 flow -> %s"
          % (len(data["items"]), len(data["flow_order"]), path))
    print(_flow_table(data))
    return 0

def _selfcheck_data(data: Dict[str, Any]) -> List[str]:
    errs: List[str] = []
    items = data["items"]
    if len(items) != 60:
        errs.append("项数 %d != 60" % len(items))
    ids = [it["qa_id"] for it in items]
    if len(ids) != len(set(ids)):
        errs.append("qa_id 有重复")
    if [it["seq"] for it in items] != list(range(1, len(items) + 1)):
        errs.append("seq 不连续")
    last = -1
    for it in items:
        if it["flow_index"] < last:
            errs.append("flow 顺序倒退: %s" % it["qa_id"])
        last = it["flow_index"]
        if not re.fullmatch(r"z\d{1,2}", it["part"]):
            errs.append("%s part 非法: %r" % (it["qa_id"], it["part"]))
        if it["part_origin"] == "fallback":
            errs.append("%s part 未映射（fallback）" % it["qa_id"])
        if not it["evidence_field"].startswith("(manual_action)"):
            errs.append("%s field 前缀错误" % it["qa_id"])
        if not it["question"] or not it["normal"]:
            errs.append("%s 缺 question/normal" % it["qa_id"])
        if not it.get("evidence_subject"):
            errs.append("%s 缺 evidence_subject" % it["qa_id"])
        opts = it["options"]
        if not 2 <= len(opts) <= 4:
            errs.append("%s 按钮数 %d 不在 2..4" % (it["qa_id"], len(opts)))
        if opts[0]["value"] != "done":
            errs.append("%s 首按钮不是 done" % it["qa_id"])
        if len({o["value"] for o in opts}) != len(opts):
            errs.append("%s 按钮 value 重复" % it["qa_id"])
        rects = [o["rect"] for o in opts] + [it["ui"]["skip_button"]["rect"],
                                             it["ui"]["back_button"]["rect"]]
        for rect in rects:
            x0, y0, x1, y1 = rect
            if not (0 <= x0 < x1 <= CANVAS_W and 0 <= y0 < y1 <= CANVAS_H):
                errs.append("%s rect 越界: %r" % (it["qa_id"], rect))

        for i in range(len(opts)):
            for j in range(i + 1, len(opts)):
                a, b = opts[i]["rect"], opts[j]["rect"]
                if not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]):
                    errs.append("%s 按钮 %d/%d 重叠" % (it["qa_id"], i, j))
        for ab in it["abnormalities"]:
            if not ab["feature_id"].startswith("F_"):
                errs.append("%s 异常项 feature_id 非法" % it["qa_id"])
        if it["skip_if"]:
            for rule in it["skip_if"]["rules"]:
                if rule["qa_id"] not in set(ids):
                    errs.append("%s skip_if 指向未知 %s" % (it["qa_id"], rule["qa_id"]))
    return errs

def _cmd_selfcheck(args: argparse.Namespace) -> int:
    data = load_items(Path(args.items))
    errs = _selfcheck_data(data)
    if errs:
        print("[selfcheck] FAIL (%d)" % len(errs))
        for e in errs[:40]:
            print("  -", e)
        return 1
    parts = sorted({it["part"] for it in data["items"]})
    routes = sorted({it["route"] or "-" for it in data["items"]})
    print("[selfcheck] PASS")
    print("  items=%d flows=%d parts=%s routes=%s"
          % (len(data["items"]), len(data["flow_order"]), ",".join(parts), ",".join(routes)))
    print("  abnormalities=%d (real_features=%d, synthesized=%d)"
          % (sum(len(it["abnormalities"]) for it in data["items"]),
             sum(1 for it in data["items"] for a in it["abnormalities"] if a["source"] == "fault_library"),
             sum(1 for it in data["items"] for a in it["abnormalities"] if a["source"] == "synthesized")))
    print("  skip_if=%d 项有依赖" % sum(1 for it in data["items"] if it["skip_if"]))
    return 0

def _cmd_list(args: argparse.Namespace) -> int:
    data = load_items(Path(args.items))
    print(_flow_table(data))
    print("\n共 %d 项 / %d 个 flow" % (len(data["items"]), len(data["flow_order"])))
    return 0

def _cmd_demo(args: argparse.Namespace) -> int:
    flow = QAFlow(Path(args.items))
    flow.start()
    while flow.current() is not None:
        flow.answer("done")
        flow.next()
    summary = flow.summary()
    print(json.dumps({k: summary[k] for k in
                      ("total", "answered", "verified", "abnormal", "skipped", "pending",
                       "complete", "by_value", "flow_coverage")}, ensure_ascii=False, indent=1))
    print("evidence[0] =", json.dumps(summary["evidence"][0], ensure_ascii=False))
    print("evidence[-1] =", json.dumps(summary["evidence"][-1], ensure_ascii=False))
    return 0

def _cmd_interactive(args: argparse.Namespace) -> int:
    flow = QAFlow(Path(args.items), strict=False)
    flow.start()
    print("交互问答（回车=跳过，q=退出）：")
    while True:
        cur = flow.current()
        if cur is None:
            break
        print("\n[%s] flow %s | %s | part=%s route=%s"
              % (cur["progress"], cur["flow_no"], cur["flow_name"], cur["part"], cur["route"] or "-"))
        print("题目:", cur["question"])
        print("正常:", cur["normal"])
        if cur["skip_suggested"]:
            print("提示: 建议跳过（%s）" % cur["skip_reason"])
        for i, opt in enumerate(cur["options"], 1):
            print("  %d) %s" % (i, opt["label"]))
        print("  s) 跳过")
        raw = input("选择: ").strip()
        if raw.lower() in ("q", "quit", "exit"):
            flow.abort()
            break
        if raw == "":
            flow.skip()
            continue
        try:
            if raw.lower() == "s":
                flow.skip()
            elif raw.isdigit() and 1 <= int(raw) <= len(cur["options"]):
                flow.answer(cur["options"][int(raw) - 1]["value"])
            else:
                flow.answer(raw)
        except (ValueError, RuntimeError) as e:
            print("  !", e)
            continue
        flow.next()
    summary = flow.summary()
    print("\n=== 汇总 ===")
    print(json.dumps({k: summary[k] for k in
                      ("total", "answered", "verified", "abnormal", "skipped", "pending",
                       "complete", "by_value")}, ensure_ascii=False, indent=1))
    print("证据 %d 条（跳过 %d 条不产生证据）" % (len(summary["evidence"]), summary["skipped"]))
    return 0

def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="雷达交互问答流程引擎（60 项）")
    p.add_argument("--items", default=str(ITEMS_JSON), help="qa_items.json 路径")
    p.add_argument("--sop", default=str(SOP_CSV), help="判据库_SOP.csv（--build 用）")
    p.add_argument("--faults", default=str(FAULT_CSV), help="判据库_故障.csv（--build 用）")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--build", action="store_true", help="从判据库重新生成 qa_items.json")
    g.add_argument("--selfcheck", action="store_true", help="自检 qa_items.json")
    g.add_argument("--list", action="store_true", help="按 flow 打印清单")
    g.add_argument("--demo", action="store_true", help="全部答正常并打印 summary")
    g.add_argument("--interactive", action="store_true", help="终端交互问答")
    return p

def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  
    except Exception:  
        pass
    args = _parser().parse_args(argv)
    if args.build:
        return _cmd_build(args)
    if args.selfcheck:
        return _cmd_selfcheck(args)
    if args.list:
        return _cmd_list(args)
    if args.demo:
        return _cmd_demo(args)
    if args.interactive:
        return _cmd_interactive(args)
    _parser().print_help()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
