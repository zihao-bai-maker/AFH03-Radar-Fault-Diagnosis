#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""screen_qa.py —— 屏幕状态问答（15 项，问答为准；视觉只做参考提示）。

为什么要有这个文件
==================
`vision_rules.py` 的 `classify_screen()` 能给出 ``black_screen`` / ``yellow_screen`` /
``garbled`` / ``no_echo`` / ``no_scan`` / ``ok``，但**现场没有"底噪长什么样 / 没有底噪
长什么样"的参考样本**，屏幕识别本身很不精准。作者 2026-10-18 明确修正：

    **屏幕识别只做粗略/参考；真正的确认用「屏幕状态问答」。**

本文件只做三件事：

1. 从 `vision_bindings.json` 的 15 个 ``binding == "screen"`` 检查项生成题库
   `qa_items_screen.json`（每项一道题，选项按知识库实际存在的值裁剪）；
2. 运行问答并输出**与 `evidence/v1` 一致**的证据（``modality="qa"``）；
3. 接收视觉粗判结果（`screen_hint.py` 的产出）时，只写 ``vision_hint`` 参考字段，
   给出 ``conflict: true/false``，**最终 value 永远以问答为准**。

铁律
====
* **只新建**：`qa_items_screen.json` / `steps_screen_patch.json`；不修改
  `qa_items.json` / `vision_rules.py` / `qa_flow.py` / `steps.json` / `ui_kiosk.py`。
* 不 import cv2 / numpy / 相机；纯标准库，PC 与板端都能跑。
* 选项**不臆造**：每个选项都带 ``origin``（判据库精确命中 / 判据库同名值 /
  vision_rules 取值域 / 契约扩展 / 核心枚举 / qa_flow 词表 / 作者口述）。
  知识库里没有的（如「有底噪」「garbled」「不扫描」）一律 ``author_confirm=true``。
* 看不清 = ``skipped``，**不是正常也不是异常**；``confidence=0.0``。
* 视觉 ``reliable`` 恒为 ``false``；即使调用方传 ``reliable=true`` 也不采信。

用法
----
    python screen_qa.py --build          # 生成 qa_items_screen.json / steps_screen_patch.json
    python screen_qa.py --selfcheck      # 自检（题库 / 选项来源 / 补丁映射）
    python screen_qa.py --list           # 15 项清单
    python screen_qa.py --demo           # 全部答"正常"并打印汇总（含一个冲突示例）
    python screen_qa.py --ask SQ001 --answer 黄屏
    python screen_qa.py --ask SQ001 --answer 正常 --vision-hint yellow_screen --json
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
SCHEMA = "qa_items_screen/v1"
PATCH_SCHEMA = "steps_patch/v1"
SUMMARY_SCHEMA = "screen_qa_summary/v1"

ENGINE_DIR = Path(__file__).resolve().parent
BASE_DIR = ENGINE_DIR.parent
BINDINGS_JSON = ENGINE_DIR / "vision_bindings.json"
FAULT_CSV = BASE_DIR / "判据库_故障.csv"
STEPS_JSON = ENGINE_DIR / "steps.json"
ITEMS_JSON = ENGINE_DIR / "qa_items_screen.json"
PATCH_JSON = ENGINE_DIR / "steps_screen_patch.json"

EXPECTED_SCREEN_ITEMS = 15
SCREEN_BINDING = "screen"

VALUE_VOCAB = {
    "normal": "正常（屏幕类正常期望；不是 abnormal_value）",
    "black_screen": "黑屏（判据库 abnormal_value）",
    "yellow_screen": "黄屏（判据库 abnormal_value）",
    "garbled": "花屏（判据库只有现象，无 abnormal_value；vision_rules / 契约扩展值）",
    "no": "无回波 / 不扫描（判据库回波项 abnormal_value=no；扫描项无登记行）",
    "weak": "回波弱（判据库 abnormal_value）",
    "no_noise": "无噪声 / 无底噪（判据库 abnormal_value=no_noise）",
    "abnormal": "线条不连续/方向错误（vision_rules 取值域；判据库无本字段异常值）",
    "skipped": "看不清 / 跳过（未验证，不产生正常/异常结论）",
}

OPTION_ORIGIN_LEGEND = {
    "fault_db": "判据库_故障.csv 中该 field + abnormal_value 精确命中（db_backed=true）",
    "fault_db_value": "该 abnormal_value 在判据库其它 field 存在，但本 field 无登记行（db_backed=false）",
    "vision_state": "vision_rules.SCREEN_CHECKS 的取值域（判据库无本字段 abnormal_value 行）",
    "derived": "由判据库现象列/契约推导，无同名 abnormal_value",
    "contract_core_enum": "schema_evidence.md §5.1 核心枚举（normal）",
    "schema_ext": "schema_evidence.md §5.2 扩展枚举",
    "qa_flow_vocab": "qa_flow.py VALUE_VOCAB（skipped）",
}

LABEL_ORIGIN_LEGEND = {
    "system": "系统/题意命名（正常、跳过等）",
    "fault_db": "判据库现象列原词（黑屏、黄屏、无回波等）",
    "vision_state": "vision_rules 状态词（花屏、不扫描、线异常）",
    "user_dictated": "作者口述用词；判据库无此词或用词不同（底噪）",
}

AUTHOR_CONFIRM = [
    {
        "id": "AC1",
        "scope": "19.7 / 19.8（SQ010 / SQ011）",
        "issue": "「有底噪」不是知识库 abnormal_value，也不是判据库原词；"
                 "本文件只把它作为**正常选项**的标签（value=normal）。"
                 "判据库正常期望是 expect=ok、现象列用词「有噪声」。",
        "status": "pending",
    },
    {
        "id": "AC2",
        "scope": "19.7 / 19.8（SQ010 / SQ011）",
        "issue": "「无底噪」为作者口述；判据库 abnormal_value=no_noise 精确命中，"
                 "但判据库原词是「无噪声」。",
        "status": "pending",
    },
    {
        "id": "AC3",
        "scope": "显示画面项（SQ001 / SQ004）",
        "issue": "「花屏」在判据库只有现象（花屏 / 花屏或显示画面死机），"
                 "没有 abnormal_value；本文件用 vision_rules.SCREEN_CHECKS 的 garbled，"
                 "schema_evidence.md §5.2 也接受该值；feature_id 为合成。",
        "status": "pending",
    },
    {
        "id": "AC4",
        "scope": "19.5 / 19.6（SQ008 / SQ009）",
        "issue": "扫描项在判据库没有 field/abnormal_value 行，只有现象「不扫描」；"
                 "本文件用 core enum no（也是 vision_rules.SCREEN_CHECKS 的 scan 异常值），"
                 "feature_id 为合成。",
        "status": "pending",
    },
    {
        "id": "AC5",
        "scope": "理想线项（SQ002 / SQ003 / SQ005 / SQ006 / SQ007）",
        "issue": "理想线/方向项在判据库没有本字段异常值；"
                 "本文件用 vision_rules.SCREEN_CHECKS 的 abnormal，feature_id 为合成。",
        "status": "pending",
    },
    {
        "id": "AC6",
        "scope": "16（10-II）.*（SQ004 / SQ005 / SQ006）",
        "issue": "领显（leader_display）的显示画面/理想线字段在判据库_故障.csv 没有登记行；"
                 "异常值复用操显同名枚举，feature_id 全部为合成。",
        "status": "pending",
    },
    {
        "id": "AC7",
        "scope": "26.~3 / 26.~4（SQ014 / SQ015）",
        "issue": "视觉绑定把领显回波项绑到 (image)(operator_display)_course_echo / "
                 "_glide_echo；本文件按 vision_bindings.json 原样沿用该 field。"
                 "是否应改为 (image)(leader_display)_... 待作者确认。",
        "status": "pending",
    },
    {
        "id": "AC8",
        "scope": "全部 15 项",
        "issue": "证据 part 沿用 vision_bindings.json 的故障归属（z11 / z14），"
                 "与 steps.json 的步骤部位 z4（显示控制）不同。"
                 "集成时请以 evidence.part 为准，不要被 step.part 覆盖。",
        "status": "pending",
    },
]

PHENOMENON_KEYWORDS = {
    "garbled": "花屏",
    "no_scan": "不扫描",
}

def _clean(text: Any) -> str:
    """去掉换行/连续空白，保留中文标点。"""
    if text is None:
        return ""
    s = str(text).replace("\r", " ").replace("\n", " ").replace("\u3000", " ")
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()

def _now_iso() -> str:
    """与 qa_flow / fusion 一致：本地时区 ISO-8601（秒级）。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def _read_csv(path: Path) -> List[Dict[str, str]]:
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def _load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _step_id(binding: Dict[str, Any]) -> str:
    """与 steps.json 的 step_id 口径一致：flow_no-sub_no；sub_no 空则 flow_no。"""
    flow = _clean(binding.get("flow_no"))
    sub = _clean(binding.get("sub_no"))
    return "%s-%s" % (flow, sub) if sub else flow

def _kind_of(binding_ref: str) -> str:
    ref = _clean(binding_ref)
    if ref == "display_screen":
        return "screen"
    if ref.endswith("_line"):
        return "line"
    if ref.endswith("_scan"):
        return "scan"
    if ref.endswith("_noise"):
        return "noise"
    if ref.endswith("_echo"):
        return "echo"
    raise ValueError("未知屏幕 binding_ref: %r" % binding_ref)

def _position(binding: Dict[str, Any]) -> str:
    text = " ".join((
        _clean(binding.get("item")),
        _clean(binding.get("subject")),
        _clean(binding.get("display")),
        _clean(binding.get("field")),
    ))
    if "操显" in text or "operator_display" in text:
        return "操显"
    if "领显" in text or "leader_display" in text:
        return "领显"
    return ""

def _subject_label(binding: Dict[str, Any], kind: str) -> str:
    """证据/题干里的人话主语。"""
    subject = _clean(binding.get("subject"))
    item = _clean(binding.get("item"))
    pos = _position(binding)
    if kind == "line" and "方向" in item:
        subject = "（%s）理想航向线" % (pos or "操显")
    if not subject:
        subject = item
    if pos and not subject.startswith("（"):
        subject = "（%s）%s" % (pos, subject)
    return subject

def _question(binding: Dict[str, Any], kind: str) -> str:
    label = _subject_label(binding, kind)
    item = _clean(binding.get("item"))
    if kind == "screen":
        short = label
        if short.startswith("（") and "）" in short:
            short = short[1:].replace("）", "-", 1)
        return "现在屏幕显示是什么状态？（%s）" % short
    if kind == "line":
        if "方向" in item:
            return "现在屏幕上「%s」的方向是否正确？" % label
        return "现在屏幕上「%s」是否连续且正常？" % label
    if kind == "scan":
        return "现在屏幕上「%s」是否在正常扫描？" % label
    if kind == "noise":
        return "现在屏幕上「%s」有底噪吗？" % label
    if kind == "echo":
        return "现在屏幕上「%s」有回波吗？" % label
    raise ValueError(kind)

def _normal_text(binding: Dict[str, Any], kind: str) -> str:
    item = _clean(binding.get("item"))
    if kind == "screen":
        return "有显示画面，无黑屏 / 黄屏 / 花屏"
    if kind == "line":
        if "方向" in item:
            return "航向线方向正确，无反向 / 不连续"
        return "理想线连续、方向正确，无中断 / 缺失"
    if kind == "scan":
        return "画面正常扫描，无静止 / 不扫描"
    if kind == "noise":
        return "屏面有底噪 / 噪声（判据库正常期望：有噪声）"
    if kind == "echo":
        return "屏面有正常回波（判据库正常期望：有回波）"
    raise ValueError(kind)

def _normal_option(screen_state: str, label: str = "正常 ✔", plain: str = "正常",
                   note: str = "", *, label_origin: str = "system",
                   author_confirm: bool = False) -> Dict[str, Any]:
    return {
        "id": "normal", "value": "normal", "label": label, "label_plain": plain,
        "tone": "ok", "abnormal": False, "screen_state": screen_state,
        "origin": "contract_core_enum", "label_origin": label_origin,
        "author_confirm": author_confirm, "note": note,
    }

def _skip_option() -> Dict[str, Any]:
    return {
        "id": "skipped", "value": "skipped", "label": "看不清（跳过）",
        "label_plain": "看不清（跳过）", "tone": "neutral", "abnormal": None,
        "screen_state": "skipped", "origin": "qa_flow_vocab", "label_origin": "system",
        "author_confirm": False,
        "note": "看不清/跳过 = 未验证；不产生正常/异常结论，confidence=0.0",
    }

def _option_specs(binding: Dict[str, Any], kind: str) -> List[Dict[str, Any]]:
    item = _clean(binding.get("item"))
    if kind == "screen":
        return [
            _normal_option("screen_ok", note="屏幕正常；判据库 display_screen expect=ok"),
            {
                "id": "black_screen", "value": "black_screen", "label": "黑屏",
                "label_plain": "黑屏", "tone": "bad", "abnormal": True,
                "screen_state": "black_screen", "origin": "fault_db",
                "label_origin": "fault_db",
                "note": "判据库 abnormal_value=black_screen 精确命中",
            },
            {
                "id": "yellow_screen", "value": "yellow_screen", "label": "黄屏",
                "label_plain": "黄屏", "tone": "bad", "abnormal": True,
                "screen_state": "yellow_screen", "origin": "fault_db",
                "label_origin": "fault_db",
                "note": "判据库 abnormal_value=yellow_screen 精确命中",
            },
            {
                "id": "garbled", "value": "garbled", "label": "花屏",
                "label_plain": "花屏", "tone": "bad", "abnormal": True,
                "screen_state": "garbled", "origin": "vision_state",
                "label_origin": "vision_state", "author_confirm": True,
                "note": "判据库只有现象「花屏 / 花屏或显示画面死机」，无 abnormal_value；"
                        "garbled 取自 vision_rules.SCREEN_CHECKS 与 schema_evidence §5.2",
            },
            _skip_option(),
        ]
    if kind == "line":
        label = "方向错误" if "方向" in item else "线条不连续或缺失"
        return [
            _normal_option("line_ok"),
            {
                "id": "abnormal", "value": "abnormal", "label": label,
                "label_plain": label, "tone": "bad", "abnormal": True,
                "screen_state": "line_abnormal", "origin": "vision_state",
                "label_origin": "vision_state", "author_confirm": True,
                "note": "判据库无本字段异常值行；abnormal 取自 vision_rules.SCREEN_CHECKS "
                        "的 line 取值域（ok / abnormal）",
            },
            _skip_option(),
        ]
    if kind == "scan":
        return [
            _normal_option("scan_ok", label="正常（扫描正常）✔",
                           plain="正常（扫描正常）",
                           note="判据库 check_item 用词「画面扫描正常」"),
            {
                "id": "no", "value": "no", "label": "不扫描", "label_plain": "不扫描",
                "tone": "bad", "abnormal": True, "screen_state": "no_scan",
                "origin": "vision_state", "label_origin": "vision_state",
                "author_confirm": True,
                "note": "判据库无 scan 字段异常值行，只有现象「（航向）_不扫描」/「（下滑）_不扫描」；"
                        "no 取自 vision_rules.SCREEN_CHECKS 的 scan 取值域（ok / no）",
            },
            _skip_option(),
        ]
    if kind == "noise":
        return [
            _normal_option(
                "noise_ok", label="有底噪（正常）✔", plain="有底噪（正常）",
                label_origin="user_dictated", author_confirm=True,
                note="「有底噪」是作者口述用词，不是判据库 abnormal_value；"
                     "判据库正常期望是 expect=ok、现象列用词「有噪声」。本选项 value=normal。",
            ),
            {
                "id": "no_noise", "value": "no_noise", "label": "无底噪（无噪声）",
                "label_plain": "无底噪（无噪声）", "tone": "bad", "abnormal": True,
                "screen_state": "no_noise", "origin": "fault_db",
                "label_origin": "user_dictated", "author_confirm": True, "note":
                "abnormal_value=no_noise 精确命中；「底噪」是作者口述，"
                "判据库原词是「无噪声」，db_label 保留原文",
            },
            _skip_option(),
        ]
    if kind == "echo":
        return [
            _normal_option("echo_ok", label="有回波（正常）✔", plain="有回波（正常）",
                           note="判据库正常期望 expect=ok；现象列用词「航向回波 / 下滑回波」"),
            {
                "id": "no", "value": "no", "label": "无回波", "label_plain": "无回波",
                "tone": "bad", "abnormal": True, "screen_state": "no_echo",
                "origin": "fault_db", "label_origin": "fault_db",
                "note": "判据库 abnormal_value=no 精确命中",
            },
            {
                "id": "weak", "value": "weak", "label": "回波弱", "label_plain": "回波弱",
                "tone": "bad", "abnormal": True, "screen_state": "no_echo_weak",
                "origin": "fault_db", "label_origin": "fault_db",
                "note": "判据库 abnormal_value=weak 精确命中",
            },
            _skip_option(),
        ]
    raise ValueError(kind)

def _make_option(binding: Dict[str, Any], spec: Dict[str, Any], rows: List[Dict[str, str]],
                 lookup: Dict[Tuple[str, str], str],
                 lookup_rows: Dict[Tuple[str, str], Dict[str, str]],
                 value_index: Dict[str, List[Dict[str, str]]]) -> Dict[str, Any]:
    field = _clean(binding.get("field"))
    value = spec["value"]
    exact = lookup.get((field, value))
    seen = value_index.get(value, [])
    origin = spec["origin"]
    if origin == "fault_db" and not exact:
        origin = "fault_db_value" if seen else "derived"

    opt: Dict[str, Any] = {
        "id": spec["id"],
        "value": value,
        "label": spec["label"],
        "label_plain": spec["label_plain"],
        "tone": spec["tone"],
        "abnormal": spec["abnormal"],
        "screen_state": spec["screen_state"],
        "origin": origin,
        "label_origin": spec.get("label_origin", "system"),
        "db_backed": bool(exact),
    }
    if exact:
        row = lookup_rows[(field, value)]
        opt["feature_id"] = exact
        opt["feature_source"] = "fault_library"
        opt["db_feature_id"] = exact
        opt["db_label"] = _clean(row.get("phenomenon"))
        opt["db_sub_unit"] = _clean(row.get("sub_unit"))
    else:
        if spec["abnormal"]:
            opt["feature_id"] = "F_%s_%s" % (field, value)
            opt["feature_source"] = "synthesized"
        else:
            opt["feature_id"] = None
            opt["feature_source"] = None
        if seen:
            opt["db_value_seen"] = True
            opt["db_value_fields"] = sorted({_clean(r.get("field")) for r in seen if r.get("field")})[:5]
        kw = PHENOMENON_KEYWORDS.get(spec["screen_state"], "")
        hits = [r for r in rows if kw and kw in _clean(r.get("phenomenon"))]
        if hits:
            opt["db_phenomenon_seen"] = True
            opt["db_phenomenon"] = _clean(hits[0].get("phenomenon"))
            opt["db_phenomenon_sub_unit"] = _clean(hits[0].get("sub_unit"))

    opt["author_confirm"] = bool(
        spec.get("author_confirm")
        or (spec["abnormal"] and not exact)
    )

    notes: List[str] = []
    if spec.get("note"):
        notes.append(spec["note"])
    if origin == "fault_db_value":
        notes.append("该异常值在判据库其它 field 存在（%s），本 field 无登记行；feature_id 合成"
                     % "、".join(opt.get("db_value_fields", [])[:3]))
    if origin == "derived" and spec["abnormal"]:
        notes.append("判据库无本字段同名异常值；feature_id 合成，待作者确认")
    if opt.get("db_phenomenon_seen") and not exact:
        notes.append("判据库现象列有「%s」，但没有 field/abnormal_value 行"
                     % opt["db_phenomenon"])
    if opt["author_confirm"] and not any("待作者确认" in n for n in notes):
        notes.append("知识库无精确对应，待作者确认")
    opt["note"] = "；".join(dict.fromkeys(notes))
    return opt

def _build_item(binding: Dict[str, Any], seq: int, rows: List[Dict[str, str]],
                lookup: Dict[Tuple[str, str], str],
                lookup_rows: Dict[Tuple[str, str], Dict[str, str]],
                value_index: Dict[str, List[Dict[str, str]]]) -> Dict[str, Any]:
    ref = _clean(binding.get("binding_ref"))
    kind = _kind_of(ref)
    options = [
        _make_option(binding, spec, rows, lookup, lookup_rows, value_index)
        for spec in _option_specs(binding, kind)
    ]
    label = _subject_label(binding, kind)
    question = _question(binding, kind)
    normal = _normal_text(binding, kind)
    qa_id = "SQ%03d" % seq
    notes: List[str] = []
    field_src = _clean(binding.get("field_src"))
    if field_src.startswith("fault_db"):
        notes.append("field / part / route 沿用 vision_bindings.json（判据库字段名）")
    elif field_src:
        notes.append("本项 field 在判据库无登记行（vision_bindings field_src=%s）；"
                     "field 按 vision_rules 命名沿用" % field_src)
    if "leader_display" in _clean(binding.get("field")):
        notes.append("领显字段在判据库_故障.csv 无登记行；feature_id 为合成")
    if _clean(binding.get("flow_no")) in ("21", "26") and ref.endswith("_echo"):
        notes.append("该领显/操显回波项的 field 在 vision_bindings 里是 operator_display；"
                     "本文件原样沿用，是否改 leader_display 待作者确认")
    if ref.endswith("_noise"):
        notes.append("「底噪」为作者口述；判据库原词「无噪声」（no_noise）")
    if ref.endswith("_scan"):
        notes.append("判据库无 scan 字段异常值行；no 来自 vision_rules.SCREEN_CHECKS")
    if ref.endswith("_line"):
        notes.append("判据库无 line 字段异常值行；abnormal 来自 vision_rules.SCREEN_CHECKS")
    if binding.get("part") == "":
        notes.append("vision_bindings 的 part 为空（契约违规）；本文件继承空值并标出")

    ui_buttons = [
        {"id": o["id"], "value": o["value"], "label": o["label"],
         "label_plain": o["label_plain"], "tone": o["tone"],
         "style": "primary" if o["value"] == "normal" else "alt"}
        for o in options
    ]
    item: Dict[str, Any] = {
        "qa_id": qa_id,
        "seq": seq,
        "step_id": _step_id(binding),
        "screen_key": _clean(binding.get("key")),
        "flow_no": _clean(binding.get("flow_no")),
        "sub_no": _clean(binding.get("sub_no")),
        "check_item": _clean(binding.get("item")),
        "category": _clean(binding.get("category")),
        "subject": _clean(binding.get("subject")),
        "display": _clean(binding.get("display")),
        "position": _position(binding),
        "part": _clean(binding.get("part")),
        "route": _clean(binding.get("route")),
        "part_source": "vision_bindings.json",
        "screen_kind": kind,
        "binding_ref": ref,
        "evidence_field": _clean(binding.get("field")),
        "question": question,
        "normal": normal,
        "options": options,
        "ui": {
            "screen": {"w": 1024, "h": 600},
            "title": "屏幕状态确认",
            "progress": "%d/%d" % (seq, EXPECTED_SCREEN_ITEMS),
            "question": question,
            "normal": "正常判据：" + normal,
            "part_chip": _clean(binding.get("part")).upper(),
            "route_chip": ("%s 路" % _clean(binding.get("route"))) if _clean(binding.get("route")) else "",
            "buttons": ui_buttons,
            "hint": "点击大按钮作答；选项来源见 option.origin（判据库 / 契约 / 口述）",
            "min_touch_px": 44,
            "layout_note": "只给语义与建议样式；具体矩形由流程页统一布局，本文件不绑定",
        },
        "vision_policy": "hint_only",
        "author_confirm": any(o.get("author_confirm") for o in options),
        "notes": notes,
    }
    return item

def build_items(bindings_path: Path = BINDINGS_JSON, fault_path: Path = FAULT_CSV) -> Dict[str, Any]:
    """从 vision_bindings + 判据库_故障.csv 生成题库数据（不写盘）。"""
    if not Path(bindings_path).is_file():
        raise FileNotFoundError("找不到 vision_bindings.json: %s" % bindings_path)
    if not Path(fault_path).is_file():
        raise FileNotFoundError("找不到判据库_故障.csv: %s" % fault_path)

    data = _load_json(Path(bindings_path))
    bindings = [it for it in (data.get("items") or []) if _clean(it.get("binding")) == SCREEN_BINDING]
    if len(bindings) != EXPECTED_SCREEN_ITEMS:
        raise ValueError("vision_bindings 中 binding=screen 的项应为 %d，实际 %d"
                         % (EXPECTED_SCREEN_ITEMS, len(bindings)))

    rows = _read_csv(Path(fault_path))
    lookup: Dict[Tuple[str, str], str] = {}
    lookup_rows: Dict[Tuple[str, str], Dict[str, str]] = {}
    value_index: Dict[str, List[Dict[str, str]]] = {}
    for r in rows:
        field = _clean(r.get("field"))
        value = _clean(r.get("abnormal_value"))
        fid = _clean(r.get("feature_id"))
        if field and value:
            value_index.setdefault(value, []).append(r)
            if field and value and fid.startswith("F_") and (field, value) not in lookup:
                lookup[(field, value)] = fid
                lookup_rows[(field, value)] = r

    items = [
        _build_item(b, seq, rows, lookup, lookup_rows, value_index)
        for seq, b in enumerate(bindings, 1)
    ]
    out: Dict[str, Any] = {
        "schema": SCHEMA,
        "engine_version": __version__,
        "generated_by": "screen_qa.py build_items()  (python screen_qa.py --build)",
        "source": {
            "vision_bindings": Path(bindings_path).name,
            "fault_db": Path(fault_path).name,
            "binding_filter": "binding == 'screen'（与 vision_rules.py --kind screen 同一批 15 项）",
            "count": len(items),
            "vision_bindings_sha256": _sha256(Path(bindings_path)),
            "faults_sha256": _sha256(Path(fault_path)),
            "qa_items_base": "qa_items.json（60 题；本文件不改它，qa_id 用 SQxxx 避免冲突）",
            "schema_contract": "schema_evidence.md（evidence/v1）",
            "note": "选项按 field 实际存在的知识库值裁剪；没有的值不臆造，"
                    "一律标 origin + author_confirm，见 author_confirm 列表。",
        },
        "value_vocab": VALUE_VOCAB,
        "option_origin_legend": OPTION_ORIGIN_LEGEND,
        "label_origin_legend": LABEL_ORIGIN_LEGEND,
        "author_confirm": AUTHOR_CONFIRM,
        "items": items,
    }
    return out

def build_patch(items_data: Dict[str, Any], steps_path: Path = STEPS_JSON) -> Dict[str, Any]:
    """生成 steps.json 的增量补丁（只读 steps.json，不修改它）。"""
    steps_doc = _load_json(Path(steps_path))
    steps = { _clean(s.get("step_id")): s for s in (steps_doc.get("steps") or []) }
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for item in items_data.get("items") or []:
        sid = _clean(item.get("step_id"))
        if sid not in steps:
            raise ValueError("steps.json 中找不到 step_id=%r（screen_key=%s）"
                             % (sid, item.get("screen_key")))
        groups.setdefault(sid, []).append(item)

    patches: List[Dict[str, Any]] = []
    for sid in sorted(groups, key=lambda s: (steps[s].get("seq", 10 ** 6), s)):
        step = steps[sid]
        items = groups[sid]
        append = []
        for it in items:
            append.append({
                "qa_id": it["qa_id"],
                "seq": it["seq"],
                "check_item": it["check_item"],
                "question": it["question"],
                "normal": it["normal"],
                "part": it["part"],
                "route": it["route"],
                "evidence_field": it["evidence_field"],
                "category": it["category"],
                "subject": it["subject"],
                "options": [
                    {"value": o["value"], "label_plain": o["label_plain"],
                     "tone": o["tone"], "origin": o["origin"]}
                    for o in it["options"]
                ],
                "source": "qa_items_screen.json",
            })
        patch: Dict[str, Any] = {
            "step_id": sid,
            "flow_no": _clean(step.get("flow_no")),
            "sub_no": _clean(step.get("sub_no")),
            "step_name": _clean(step.get("step_name")),
            "step_part": _clean(step.get("part")),
            "step_route": _clean(step.get("route")),
            "existing_qa_ids": [q.get("qa_id") for q in (step.get("qa_items") or [])],
            "append_to": "step.qa_items",
            "qa_items_append": append,
        }
        mism = [it for it in items if _clean(it.get("part")) != _clean(step.get("part"))]
        if mism:
            patch["part_mismatch"] = {
                "step_part": _clean(step.get("part")),
                "qa_parts": sorted({_clean(it.get("part")) for it in mism}),
                "note": "steps.json 步骤部位与 evidence.part 不同；集成时 evidence.part 优先",
            }
        patches.append(patch)

    all_ids = [it["qa_id"] for it in items_data.get("items") or []]
    return {
        "schema": PATCH_SCHEMA,
        "generated_by": "screen_qa.py build_patch()  (python screen_qa.py --build)",
        "base": "steps.json",
        "apply": "把 patches[].qa_items_append 追加到 steps.json 对应 step_id 的 qa_items；"
                 "不要改 steps.json 其它字段（本文件只是增量补丁）",
        "source": {
            "steps": Path(steps_path).name,
            "steps_sha256": _sha256(Path(steps_path)),
            "qa_items_screen": "qa_items_screen.json",
        },
        "counts": {
            "screen_items": len(all_ids),
            "steps_patched": len(patches),
            "qa_items_appended": len(all_ids),
            "steps_with_two_screen_items": [sid for sid, g in groups.items() if len(g) > 1],
        },
        "result_row": {
            "template": "视觉提示：{vision_hint}（参考） + 人工确认：{qa_label} ✔",
            "example": "视觉提示：偏黄（参考） + 人工确认：黄屏 ✔",
            "rule": "视觉提示只展示、不参与结论；人工确认缺失时显示「待问答」，不得用视觉值代替",
        },
        "notes": [
            "15 个屏幕检查项落在 steps.json 的 13 个步骤里：flow 21 / 26 各含 2 个屏幕项，"
            "其余 11 个步骤各 1 项。",
            "步骤 18-3 在 steps.json 里 part 为空；screen_qa 证据 part 用 vision_bindings 的 z11。",
            "步骤 15/16/19 的 step.part=z4（显示控制），而 evidence.part=z11/z14（故障归属）；"
            "集成时 display 用 step.part，证据落库用 evidence.part。",
            "patch 只追加，不删除/覆盖 steps.json 里已有的 QA048..QA060 等问答项。",
        ],
        "patches": patches,
    }

def save_json(data: Any, path: Path = ITEMS_JSON) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")
    return path

def load_items(path: Optional[Path] = None) -> Dict[str, Any]:
    p = Path(path) if path else ITEMS_JSON
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    if data.get("schema") != SCHEMA:
        raise ValueError("qa_items_screen schema 不匹配: %r（期望 %s）" % (data.get("schema"), SCHEMA))
    items = data.get("items")
    if not isinstance(items, list) or len(items) != EXPECTED_SCREEN_ITEMS:
        raise ValueError("qa_items_screen 应有 %d 项，实际 %r"
                         % (EXPECTED_SCREEN_ITEMS, len(items or [])))
    ids = [it.get("qa_id") for it in items]
    if len(ids) != len(set(ids)):
        raise ValueError("qa_id 重复: %r" % ids)
    expected = ["SQ%03d" % i for i in range(1, EXPECTED_SCREEN_ITEMS + 1)]
    if ids != expected:
        raise ValueError("qa_id 应为 %r，实际 %r" % (expected, ids))
    return data

_HINT_VALUE_ALIASES = {
    "ok": "ok", "normal": "ok", "正常": "ok", "画面正常": "ok", "有底噪": "ok", "有噪声": "ok",
    "black_screen": "black_screen", "黑屏": "black_screen", "画面全黑": "black_screen",
    "yellow_screen": "yellow_screen", "黄屏": "yellow_screen", "画面偏黄": "yellow_screen",
    "garbled": "garbled", "花屏": "garbled", "画面花屏": "garbled",
    "no_echo": "no_echo", "无回波": "no_echo", "看不到明显回波": "no_echo",
    "no_scan": "no_scan", "不扫描": "no_scan", "画面像静止": "no_scan",
    "no": "no", "no_noise": "no_noise", "无噪声": "no_noise", "无底噪": "no_noise",
    "weak": "weak", "回波弱": "weak",
    "abnormal": "abnormal", "异常": "abnormal", "线条不连续": "abnormal", "方向错误": "abnormal",
    "undetermined": "undetermined", "看不清": "undetermined", "无法判断": "undetermined",
}

_HINT_TEXT_ORDER = [
    ("黑", "black_screen"),
    ("黄", "yellow_screen"),
    ("花", "garbled"),
    ("无回波", "no_echo"),
    ("没有回波", "no_echo"),
    ("不扫描", "no_scan"),
    ("静止", "no_scan"),
    ("无噪声", "no_noise"),
    ("无底噪", "no_noise"),
    ("回波弱", "weak"),
    ("正常", "ok"),
    ("看不清", "undetermined"),
]

def _canonical_hint_value(value: Any = "", text: str = "") -> str:
    v = _clean(value)
    if v in _HINT_VALUE_ALIASES:
        return _HINT_VALUE_ALIASES[v]
    t = _clean(text)
    if t in _HINT_VALUE_ALIASES:
        return _HINT_VALUE_ALIASES[t]
    for kw, canon in _HINT_TEXT_ORDER:
        if kw in t:
            return canon
    return "undetermined"

def _normalize_hint(hint: Any) -> Dict[str, Any]:
    """把 str / screen_hint.py dict 统一成比较用的内部结构。"""
    if hint is None or hint == "":
        return {"available": False, "value": "", "text": "", "field": "",
                "binding_ref": "", "confidence": None, "reason": "未提供视觉提示",
                "raw": None}
    if isinstance(hint, str):
        value = _canonical_hint_value(text=hint)
        return {"available": value != "undetermined", "value": value, "text": _clean(hint),
                "field": "", "binding_ref": "", "confidence": None,
                "reason": "" if value != "undetermined" else "视觉提示无法解析",
                "raw": hint}
    if not isinstance(hint, dict):
        return {"available": False, "value": "", "text": "", "field": "",
                "binding_ref": "", "confidence": None,
                "reason": "视觉提示类型不支持（%s）" % type(hint).__name__, "raw": hint}

    available = bool(hint.get("available", True)) and not bool(hint.get("suppressed"))
    text = _clean(hint.get("vision_hint") or hint.get("hint") or "")
    raw_value = hint.get("vision_value") or hint.get("value") or hint.get("state") or ""
    value = _canonical_hint_value(raw_value, text)
    if value == "undetermined":
        available = False
    return {
        "available": available,
        "value": value,
        "text": text or (_HINT_VALUE_ALIASES.get(value, "") if value else ""),
        "field": _clean(hint.get("field") or hint.get("evidence_field")),
        "binding_ref": _clean(hint.get("binding_ref") or hint.get("screen_binding_ref")),
        "confidence": hint.get("confidence"),
        "reason": _clean(hint.get("reason") or hint.get("note")),
        "raw": hint,
    }

_KIND_STATES = {
    "screen": {"screen_ok", "black_screen", "yellow_screen", "garbled"},
    "line": {"line_ok", "line_abnormal"},
    "scan": {"scan_ok", "no_scan"},
    "noise": {"noise_ok", "no_noise"},
    "echo": {"echo_ok", "no_echo", "no_echo_weak"},
}

_HINT_TO_STATE = {
    "ok": {"screen": "screen_ok", "line": "line_ok", "scan": "scan_ok",
           "noise": "noise_ok", "echo": "echo_ok"},
    "black_screen": {"screen": "black_screen"},
    "yellow_screen": {"screen": "yellow_screen"},
    "garbled": {"screen": "garbled"},
    "no": {"echo": "no_echo", "scan": "no_scan"},
    "no_echo": {"echo": "no_echo"},
    "weak": {"echo": "no_echo_weak"},
    "no_scan": {"scan": "no_scan"},
    "no_noise": {"noise": "no_noise"},
    "abnormal": {"line": "line_abnormal"},
}

def _hint_state(value: str, kind: str) -> Optional[str]:
    return (_HINT_TO_STATE.get(value) or {}).get(kind)

def _compare_hint(item: Dict[str, Any], option: Dict[str, Any],
                  hint: Dict[str, Any]) -> Dict[str, Any]:
    """返回 {conflict, hint_match, reason, vision_state}。"""
    qa_state = option["screen_state"]
    base = {"conflict": False, "hint_match": "none", "reason": "", "vision_state": None}
    if option["value"] == "skipped":
        base["hint_match"] = "not_comparable" if hint["available"] else "none"
        base["reason"] = "问答选择看不清/跳过，未形成结论，冲突不成立"
        return base
    if not hint["available"]:
        base["hint_match"] = "unknown" if hint.get("value") else "none"
        base["reason"] = hint.get("reason") or "无可用视觉提示"
        return base
    if hint.get("field") and hint["field"] != _clean(item.get("evidence_field")):
        base["hint_match"] = "not_comparable"
        base["reason"] = "视觉提示来自另一个 field（%s），不可比" % hint["field"]
        return base
    if hint.get("binding_ref") and hint["binding_ref"] != _clean(item.get("binding_ref")):
        base["hint_match"] = "not_comparable"
        base["reason"] = "视觉提示来自另一个屏幕项（%s），不可比" % hint["binding_ref"]
        return base
    kind = _clean(item.get("screen_kind"))
    vstate = _hint_state(hint["value"], kind)
    base["vision_state"] = vstate
    if vstate is None:
        base["hint_match"] = "not_comparable"
        base["reason"] = "视觉提示「%s」与本题（%s）不是同一类状态，不能直接比较" % (
            hint["value"], kind)
        return base
    if vstate == qa_state:
        base["hint_match"] = "agree"
        base["reason"] = "视觉提示与人工确认一致（视觉仍只作参考）"
        return base
    base["conflict"] = True
    base["hint_match"] = "disagree"
    base["reason"] = "视觉提示「%s」与人工确认「%s」不一致，以人工确认为准" % (
        hint["text"] or hint["value"], option["label_plain"])
    return base

_GLOBAL_ALIASES = {
    "normal": ["normal"], "正常": ["normal"], "ok": ["normal"], "done": ["normal"],
    "black_screen": ["black_screen"], "黑屏": ["black_screen"],
    "yellow_screen": ["yellow_screen"], "黄屏": ["yellow_screen"],
    "garbled": ["garbled"], "花屏": ["garbled"],
    "weak": ["weak"], "回波弱": ["weak"],
    "skipped": ["skipped"], "skip": ["skipped"], "看不清": ["skipped"],
    "跳过": ["skipped"], "未验证": ["skipped"],
}

_KIND_ALIASES = {
    "line": {"abnormal": ["abnormal"], "异常": ["abnormal"],
             "线条不连续": ["abnormal"], "方向错误": ["abnormal"]},
    "scan": {"no": ["no"], "不扫描": ["no"], "无扫描": ["no"]},
    "noise": {"no_noise": ["no_noise"], "无底噪": ["no_noise"], "无噪声": ["no_noise"],
              "有底噪": ["normal"], "有噪声": ["normal"]},
    "echo": {"no": ["no"], "无回波": ["no"], "有回波": ["normal"]},
}

def _resolve_option(item: Dict[str, Any], raw: Any) -> Dict[str, Any]:
    s = _clean(raw)
    options = item.get("options") or []
    for opt in options:
        if s in (_clean(opt.get("value")), _clean(opt.get("id")),
                 _clean(opt.get("label")), _clean(opt.get("label_plain"))):
            return opt
    candidates: List[str] = []
    kind = _clean(item.get("screen_kind"))
    candidates.extend(_KIND_ALIASES.get(kind, {}).get(s, []))
    candidates.extend(_GLOBAL_ALIASES.get(s) or _GLOBAL_ALIASES.get(s.lower()) or [])
    for value in dict.fromkeys(candidates):
        for opt in options:
            if _clean(opt.get("value")) == value:
                return opt
    allowed = " / ".join("%s(%s)" % (o["value"], o["label_plain"]) for o in options)
    raise ValueError("无效答案 %r；本题可选: %s，或 skip/看不清" % (raw, allowed))

class ScreenQA:
    """15 项屏幕状态问答（每项独立作答；不是顺序流程）。"""

    def __init__(self, items_path: Optional[Path] = None, *, confidence: float = 1.0) -> None:
        self.path = Path(items_path) if items_path else ITEMS_JSON
        self.data = load_items(self.path)
        self.items: List[Dict[str, Any]] = self.data["items"]
        self.by_id = {it["qa_id"]: it for it in self.items}
        self.confidence = float(confidence)
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence 必须在 [0,1]")
        self._answers: Dict[str, Dict[str, Any]] = {}

    def get(self, qa_id: str) -> Dict[str, Any]:
        qid = _clean(qa_id).upper()
        if qid not in self.by_id:
            raise KeyError("未知 qa_id: %r（应为 SQ001..SQ015）" % qa_id)
        return self.by_id[qid]

    def question(self, qa_id: str) -> Dict[str, Any]:
        item = dict(self.get(qa_id))
        item["answer"] = self._answers.get(item["qa_id"])
        item["answered"] = item["answer"] is not None
        return item

    def answer(self, qa_id: str, option: Any, *, vision_hint: Any = None,
               note: str = "", confidence: Optional[float] = None,
               ts: Optional[str] = None) -> Dict[str, Any]:
        item = self.get(qa_id)
        opt = _resolve_option(item, option)
        hint = _normalize_hint(vision_hint)
        hint_ignored = False

        if _clean(item.get("screen_kind")) == "noise" and hint["available"]:
            hint_ignored = True
            hint = {"available": False, "value": "", "text": "", "field": "",
                    "binding_ref": "", "confidence": None,
                    "reason": "底噪类视觉无参考样本，视觉提示被忽略（以问答为准）",
                    "raw": hint.get("raw")}
        cmp = _compare_hint(item, opt, hint)

        skipped = opt["value"] == "skipped"
        conf = 0.0 if skipped else (self.confidence if confidence is None else float(confidence))
        if not 0.0 <= conf <= 1.0:
            raise ValueError("confidence 必须在 [0,1]")
        ts = ts or _now_iso()
        label = _clean(opt.get("label_plain") or opt["value"])
        subject = _clean(item.get("subject")) or _clean(item.get("check_item"))
        field = _clean(item.get("evidence_field"))
        qa_value = opt["value"]
        abnormal = opt.get("abnormal")

        if skipped:
            note_txt = "人工未确认：看不清/跳过（未验证，不是正常也不是异常）"
            evidence_txt = "%s：看不清/跳过（未验证）" % subject
        else:
            note_txt = "人工确认：%s" % label
            evidence_txt = "%s：人工确认%s" % (subject, label)
        if hint["available"] and not skipped:
            if cmp["conflict"]:
                note_txt += "；视觉粗判：%s（参考）⇒ 不一致，以人工确认为准" % (
                    hint["text"] or hint["value"])
                evidence_txt += "；视觉粗判「%s」不予采信（仅参考），存在冲突，以问答为准" % (
                    hint["text"] or hint["value"])
            elif cmp["hint_match"] == "agree":
                note_txt += "；视觉提示：%s（参考，一致）" % (hint["text"] or hint["value"])
                evidence_txt += "（视觉提示：%s，仅参考）" % (hint["text"] or hint["value"])
            else:
                note_txt += "；视觉提示：%s（参考，%s）" % (
                    hint["text"] or hint["value"], cmp["reason"])
                evidence_txt += "（视觉提示：%s，仅参考；%s）" % (
                    hint["text"] or hint["value"], cmp["reason"])
        elif skipped and hint["available"]:
            note_txt += "；视觉提示：%s（参考，不作判定依据）" % (hint["text"] or hint["value"])
        if note:
            note_txt += "；%s" % _clean(note)
            evidence_txt += "；%s" % _clean(note)

        evidence: Dict[str, Any] = {
            "part": _clean(item.get("part")),
            "route": _clean(item.get("route")),
            "modality": "qa",
            "field": field,
            "value": qa_value,
            "confidence": round(conf, 3),
            "note": note_txt,
            "evidence": evidence_txt,
            "ts": ts,
            "source": "screen_qa.ScreenQA",
            "item_id": item["qa_id"],
            "flow_no": _clean(item.get("flow_no")),
            "check_item": _clean(item.get("check_item")),
            "screen_item_key": _clean(item.get("screen_key")),
            "step_id": _clean(item.get("step_id")),
            "screen_kind": _clean(item.get("screen_kind")),
            "screen_state": opt["screen_state"],
            "qa_value": qa_value,
            "value_source": "qa",
            "decided_by": "qa",
            "option_origin": opt.get("origin"),
            "vision_hint": (hint["text"] or hint["value"]) if hint["available"] else "",
            "vision_value": hint["value"] if hint["available"] else None,
            "vision_reliable": False,
            "conflict": bool(cmp["conflict"]),
            "hint_match": cmp["hint_match"],
            "hint_note": cmp["reason"],
            "hint_ignored": hint_ignored,
            "skipped": skipped,
        }
        if opt.get("feature_id"):
            evidence["feature_id"] = opt["feature_id"]
            evidence["feature_source"] = opt.get("feature_source")
        if opt.get("db_backed"):
            evidence["db_backed"] = True

        rec: Dict[str, Any] = {
            "qa_id": item["qa_id"],
            "value": qa_value,
            "label": _clean(opt.get("label")),
            "label_plain": label,
            "skipped": skipped,
            "abnormal": abnormal,
            "feature_id": opt.get("feature_id"),
            "feature_source": opt.get("feature_source"),
            "abnormal_value": qa_value if abnormal else None,
            "option_origin": opt.get("origin"),
            "confidence": round(conf, 3),
            "note": note_txt,
            "evidence_text": evidence_txt,
            "ts": ts,
            "conflict": bool(cmp["conflict"]),
            "hint_match": cmp["hint_match"],
            "vision_hint": evidence["vision_hint"],
            "vision_value": evidence["vision_value"],
            "evidence": evidence,
        }
        self._answers[item["qa_id"]] = rec
        return rec

    def evidence(self, *, include_skipped: bool = True) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for item in self.items:
            rec = self._answers.get(item["qa_id"])
            if not rec:
                continue
            if rec["skipped"] and not include_skipped:
                continue
            out.append(rec["evidence"])
        return out

    def summary(self) -> Dict[str, Any]:
        answers = [self._answers[it["qa_id"]] for it in self.items if it["qa_id"] in self._answers]
        by_value: Dict[str, int] = {}
        by_part: Dict[str, int] = {}
        for rec in answers:
            by_value[rec["value"]] = by_value.get(rec["value"], 0) + 1
        for rec in answers:
            item = self.by_id[rec["qa_id"]]
            by_part[item["part"]] = by_part.get(item["part"], 0) + 1
        return {
            "schema": SUMMARY_SCHEMA,
            "total": len(self.items),
            "answered": len(answers),
            "normal": sum(1 for r in answers if r["abnormal"] is False),
            "abnormal": sum(1 for r in answers if r["abnormal"] is True),
            "skipped": sum(1 for r in answers if r["skipped"]),
            "conflict": sum(1 for r in answers if r["conflict"]),
            "by_value": by_value,
            "by_part": by_part,
            "pending": [it["qa_id"] for it in self.items if it["qa_id"] not in self._answers],
            "evidence": self.evidence(include_skipped=True),
        }

def selfcheck() -> Tuple[bool, Dict[str, Any]]:
    errors: List[str] = []
    warnings: List[str] = []
    data = load_items()
    items = data["items"]
    if len(items) != EXPECTED_SCREEN_ITEMS:
        errors.append("items != 15")
    origin_legend = data.get("option_origin_legend") or {}
    label_legend = data.get("label_origin_legend") or {}
    for it in items:
        qid = it.get("qa_id")
        for key in ("part", "route", "evidence_field", "question",
                    "normal", "screen_kind", "binding_ref", "step_id"):
            if it.get(key) in (None, "") and key != "route":   
                errors.append("%s.%s 为空" % (qid, key))
        options = it.get("options") or []
        if not any(o.get("value") == "normal" for o in options):
            errors.append("%s 没有正常选项" % qid)
        if not any(o.get("value") == "skipped" for o in options):
            errors.append("%s 没有看不清/跳过选项" % qid)
        for o in options:
            if o.get("origin") not in origin_legend:
                errors.append("%s.%s origin=%r 不在 legend" % (qid, o.get("value"), o.get("origin")))
            if o.get("label_origin") not in label_legend:
                errors.append("%s.%s label_origin=%r 不在 legend"
                              % (qid, o.get("value"), o.get("label_origin")))
            if o.get("abnormal") and not o.get("feature_id"):
                errors.append("%s.%s 异常选项缺 feature_id" % (qid, o.get("value")))
            if o.get("db_backed") and not o.get("db_feature_id"):
                errors.append("%s.%s db_backed 但缺 db_feature_id" % (qid, o.get("value")))
    patch = build_patch(data)
    if patch["counts"]["screen_items"] != EXPECTED_SCREEN_ITEMS:
        errors.append("patch screen_items != 15")
    if len(patch["patches"]) != 13:
        warnings.append("steps_patched=%d（预期 13；21/26 各含 2 项）" % len(patch["patches"]))
    patch_ids = [q["qa_id"] for p in patch["patches"] for q in p["qa_items_append"]]
    if sorted(patch_ids) != sorted(it["qa_id"] for it in items):
        errors.append("patch 的 qa_id 与题库不一致")
    return (not errors), {"ok": not errors, "errors": errors, "warnings": warnings,
                          "items": len(items), "steps_patched": len(patch["patches"]),
                          "qa_ids": patch_ids}

def _print_list(data: Dict[str, Any]) -> None:
    for it in data["items"]:
        opts = "/".join(o["label_plain"] for o in it["options"])
        print("%s  %-12s %-22s part=%-3s route=%-2s  %s"
              % (it["qa_id"], it["step_id"], it["check_item"][:22], it["part"],
                 it["route"] or "-", opts))

def _print_evidence(rec: Dict[str, Any]) -> None:
    print(json.dumps(rec["evidence"], ensure_ascii=False, indent=1))

def _demo() -> Dict[str, Any]:
    qa = ScreenQA()
    hints = {
        "SQ001": "yellow_screen",   
    }
    for it in qa.items:
        qa.answer(it["qa_id"], "正常", vision_hint=hints.get(it["qa_id"]))
    return qa.summary()

def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="屏幕状态问答（15 项）")
    ap.add_argument("--build", action="store_true", help="生成 qa_items_screen.json / steps_screen_patch.json")
    ap.add_argument("--selfcheck", action="store_true", help="自检题库与补丁")
    ap.add_argument("--list", action="store_true", help="列出 15 项")
    ap.add_argument("--demo", action="store_true", help="全部答正常并打印汇总（含冲突示例）")
    ap.add_argument("--ask", metavar="QA_ID", default="", help="作答一道题，如 SQ001")
    ap.add_argument("--answer", metavar="VALUE", default="", help="答案：value / label / 中文别名")
    ap.add_argument("--vision-hint", metavar="HINT", default="",
                    help="视觉粗判提示（字符串，如 yellow_screen / 画面偏黄）；仅参考")
    ap.add_argument("--note", default="", help="附加备注")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args(argv)

    if args.build:
        data = build_items()
        save_json(data, ITEMS_JSON)
        patch = build_patch(data)
        save_json(patch, PATCH_JSON)
        print("wrote %s (%d items)" % (ITEMS_JSON, len(data["items"])))
        print("wrote %s (%d steps)" % (PATCH_JSON, len(patch["patches"])))
        return 0
    if args.selfcheck:
        ok, report = selfcheck()
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 0 if ok else 1
    if args.list:
        _print_list(load_items())
        return 0
    if args.demo:
        print(json.dumps(_demo(), ensure_ascii=False, indent=1))
        return 0
    if args.ask:
        if not args.answer:
            ap.error("--ask 需要同时给 --answer")
        qa = ScreenQA()
        rec = qa.answer(args.ask, args.answer, vision_hint=args.vision_hint or None,
                        note=args.note)
        if args.json:
            print(json.dumps(rec["evidence"], ensure_ascii=False, indent=1))
        else:
            _print_evidence(rec)
        return 0
    ap.print_help()
    return 0

if __name__ == "__main__":
    sys.exit(main())
